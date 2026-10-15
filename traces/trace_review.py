"""Pick a labeling sample, and turn one archived transcript into a readable trace.

sample() takes a seeded, stratified random set of top-level sessions from one
window and writes it to data/labels/<name>.json, so the same set shows again
after a restart. condense_lines() turns the lines of one transcript into turns:
the prompt, the steps (tool calls, interim text, events) and the final reply.

INVARIANTS
- Read-only on the archive and the database. Labels go to
  <labels dir>/labels.jsonl, append-only; the newest line for a session wins.
- All transcript text is data. Nothing here turns it into markup, and the
  labeling page must insert it as text, never as HTML.
- No duckdb or compression.zstd import at module level: the tests load this
  file on an interpreter that has neither.
"""

from __future__ import annotations

import io
import json
import threading
from collections.abc import Iterable
from datetime import UTC, datetime
from pathlib import Path

from trace_parse import classify

HERE = Path(__file__).resolve().parent
LABELS = HERE / "data" / "labels"
MEMORY_WRITER = "<!-- session-memory-writer -->"
TEXT_CAP = 60_000     # one prompt or reply; the page folds anything past a screen
RESULT_CAP = 1_200    # one tool result
STRATA = {"chat": 50, "task": 40, "memory": 10}
_append_lock = threading.Lock()


def sample(name: str, start: datetime, end: datetime, seed: str, strata: dict[str, int] | None = None,
           labels_dir: Path = LABELS) -> dict:
    import trace_db

    strata = strata or STRATA
    out = labels_dir / f"{name}.json"
    if out.exists():
        raise FileExistsError(f"{out} exists; a sample is frozen once made")
    con = trace_db.connect(read_only=True)
    rows = con.execute("""
        WITH writer AS (SELECT DISTINCT file_id FROM prompts WHERE category = 'system_injected' AND starts_with(text, ?)),
        s AS (
          SELECT s.*, CASE WHEN kind = 'multi_turn' THEN 'chat'
                           WHEN w.file_id IS NOT NULL THEN 'memory' ELSE 'task' END AS stratum
          FROM sessions s LEFT JOIN writer w USING (file_id)
          WHERE NOT is_subagent AND n_api_calls > 0 AND first_ts >= ? AND first_ts < ?)
        SELECT file_id, stratum, first_ts::VARCHAR, title, first_prompt, n_human_prompts, n_tool_calls, n_tool_errors,
               n_interrupts, cost_usd, md5(file_id || ?) AS draw
        FROM s ORDER BY stratum, draw""", [MEMORY_WRITER, start, end, seed]).fetchall()
    con.close()
    cols = ["file_id", "stratum", "first_ts", "title", "first_prompt", "n_human_prompts", "n_tool_calls",
            "n_tool_errors", "n_interrupts", "cost_usd", "draw"]
    pools: dict[str, list[dict]] = {}
    for r in rows:
        item = dict(zip(cols, r, strict=True))
        item["first_prompt"] = (item["first_prompt"] or "")[:200]
        pools.setdefault(item["stratum"], []).append(item)
    items = [i for k, n in strata.items() for i in pools.get(k, [])[:n]]
    items.sort(key=lambda i: i["draw"])  # mix the strata, so the order says nothing about the kind
    doc = {"name": name, "created": datetime.now(UTC).isoformat(timespec="seconds"),
           "window": [start.isoformat(), end.isoformat()], "seed": seed, "strata": strata,
           "population": {k: len(v) for k, v in pools.items()}, "items": items}
    labels_dir.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(doc, indent=1, default=str) + "\n")
    return doc


def short_label(title: str | None, first_prompt: str | None, first_any: str | None) -> str:
    """A short name for a session: its title, else what started it."""
    text = " ".join((title or first_prompt or first_any or "").split())
    if text.startswith(MEMORY_WRITER):
        return "Session memory writer"
    if text.startswith("<scheduled-task name="):
        return "Scheduled task: " + text.split('"')[1]
    if "<command-name>" in text:
        return text.split("<command-name>")[1].split("<")[0]
    return text[:120] or "(no prompt)"


def item_meta(file_ids: list[str]) -> dict[str, dict]:
    """Name and UTC start/end for each session, from the trace database."""
    import trace_db

    con = trace_db.connect(read_only=True)
    rows = con.execute("""
        SELECT s.file_id, s.title, s.first_prompt,
               (SELECT text FROM prompts p WHERE p.file_id = s.file_id AND p.category NOT IN ('meta', 'interrupt')
                ORDER BY ts LIMIT 1),
               strftime(timezone('UTC', s.first_ts), '%Y-%m-%dT%H:%M:%SZ'),
               strftime(timezone('UTC', s.last_ts), '%Y-%m-%dT%H:%M:%SZ'), s.entrypoint, s.project
        FROM sessions s WHERE s.file_id IN (SELECT unnest(?::VARCHAR[]))""", [file_ids]).fetchall()
    con.close()
    return {r[0]: {"label": short_label(r[1], r[2], r[3]), "first_ts": r[4], "last_ts": r[5], "entrypoint": r[6],
                   "project": r[7]} for r in rows}


def _summary(name: str, args: object) -> str:
    """One line for a tool call: the argument a person scans for first."""
    if not isinstance(args, dict):
        return str(args)[:300]
    for key in ("command", "file_path", "path", "pattern", "url", "query", "skill", "description", "prompt"):
        if args.get(key):
            text = str(args[key])
            if name in ("Agent", "Task") and key == "description" and args.get("prompt"):
                text += " :: " + str(args["prompt"])
            return " ".join(text.split())[:300]
    return json.dumps(args, ensure_ascii=False)[:300]


def _result_text(body: object) -> str:
    if isinstance(body, list):
        parts = [b.get("text", "") if b.get("type") == "text" else f"[{b.get('type')}]"
                 for b in body if isinstance(b, dict)]
        return "\n".join(parts)
    return "" if body is None else str(body)


def condense_lines(lines: Iterable[str], file_id: str) -> dict:
    turns: list[dict] = []
    tools: dict[str, dict] = {}
    meta: dict = {"file_id": file_id, "title": None, "first_ts": None, "last_ts": None, "entrypoint": None,
                  "models": [], "cost_usd": None}

    def turn() -> dict:
        if not turns:
            turns.append({"prompt": None, "steps": []})
        return turns[-1]

    for line in lines:
        try:
            o = json.loads(line)
        except ValueError:
            continue
        if not isinstance(o, dict):
            continue
        ts = o.get("timestamp")
        if isinstance(ts, str) and ts:  # lines are not always in time order
            meta["first_ts"] = min(meta["first_ts"] or ts, ts)
            meta["last_ts"] = max(meta["last_ts"] or ts, ts)
        meta["entrypoint"] = meta["entrypoint"] or o.get("entrypoint")
        t = o.get("type")
        raw_msg = o.get("message")
        msg: dict = raw_msg if isinstance(raw_msg, dict) else {}
        content = msg.get("content")
        if t == "user":
            blocks = [{"type": "text", "text": content}] if isinstance(content, str) else (content or [])
            texts = []
            for b in blocks:
                if not isinstance(b, dict):
                    continue
                if b.get("type") == "tool_result" and b.get("tool_use_id") in tools:
                    text = _result_text(b.get("content"))
                    tools[b["tool_use_id"]].update(is_error=bool(b.get("is_error")), result=text[:RESULT_CAP],
                                                   result_chars=len(text))
                elif b.get("type") == "text":
                    texts.append(b.get("text", ""))
                elif b.get("type") == "image":
                    texts.append("[image]")
            text = "\n".join(x for x in texts if x).strip()
            if not text:
                continue
            category = classify(text, is_subagent=False, is_meta=bool(o.get("isMeta")),
                                is_compact=bool(o.get("isCompactSummary")))
            if category in ("meta", "compact_summary", "interrupt", "local_command"):
                turn()["steps"].append({"type": "note", "category": category, "ts": ts, "text": text[:400]})
            else:
                turns.append({"prompt": {"category": category, "ts": ts, "text": text[:TEXT_CAP],
                                         "chars": len(text)}, "steps": []})
        elif t == "assistant":
            model = msg.get("model")
            if model and model != "<synthetic>" and model not in meta["models"]:
                meta["models"].append(model)
            for b in content or []:
                if not isinstance(b, dict):
                    continue
                if b.get("type") == "text" and b.get("text", "").strip():
                    turn()["steps"].append({"type": "text", "ts": ts, "text": b["text"][:TEXT_CAP]})
                elif b.get("type") == "tool_use" and b.get("id") not in tools:
                    step = {"type": "tool", "ts": ts, "tool": b.get("name"),
                            "summary": _summary(b.get("name") or "", b.get("input")),
                            "skill": o.get("attributionSkill"), "is_error": False, "result": None}
                    tools[b["id"]] = step
                    turn()["steps"].append(step)
        elif t == "system" and o.get("subtype") in ("api_error", "compact_boundary", "model_refusal_fallback"):
            turn()["steps"].append({"type": "event", "subtype": o.get("subtype"), "ts": ts})
        elif t == "custom-title" and o.get("customTitle"):
            meta["title"] = o["customTitle"]
        elif t == "ai-title" and o.get("aiTitle") and not meta["title"]:
            meta["title"] = o["aiTitle"]
        elif t == "cost-state":
            meta["cost_usd"] = o.get("totalCostUSD")

    for tr in turns:  # the last text step of a turn is its reply; the page shows it open
        texts = [s for s in tr["steps"] if s["type"] == "text"]
        tr["reply"] = texts[-1]["text"] if texts else None
        if texts:
            tr["steps"].remove(texts[-1])
        tr["n_tools"] = sum(1 for s in tr["steps"] if s["type"] == "tool")
        tr["n_errors"] = sum(1 for s in tr["steps"] if s["type"] == "tool" and s["is_error"])
    meta["turns"] = turns
    return meta


def condense(file_id: str, archive: Path | None = None) -> dict:
    from compression import zstd

    import trace_archive

    path = (archive or trace_archive.DEFAULT_DEST) / (file_id + ".zst")
    with zstd.ZstdFile(path) as raw, io.TextIOWrapper(raw, encoding="utf-8", errors="replace") as fh:
        return condense_lines(fh, file_id)


def labels(labels_dir: Path = LABELS) -> dict[str, dict]:
    """Newest label for each file_id."""
    path = labels_dir / "labels.jsonl"
    out: dict[str, dict] = {}
    if path.exists():
        for line in path.read_text().splitlines():
            try:
                row = json.loads(line)
            except ValueError:
                continue
            out[row["file_id"]] = row
    return out


def add_label(sample_name: str, file_id: str, verdict: str, note: str, labels_dir: Path = LABELS) -> dict:
    if verdict not in ("pass", "fail", "skip"):
        raise ValueError(f"verdict must be pass, fail or skip, not {verdict!r}")
    row = {"ts": datetime.now(UTC).isoformat(timespec="seconds"), "sample": sample_name, "file_id": file_id,
           "verdict": verdict, "note": note.strip()[:2000], "labeler": "alex"}
    labels_dir.mkdir(parents=True, exist_ok=True)
    with _append_lock, open(labels_dir / "labels.jsonl", "a") as fh:
        fh.write(json.dumps(row, ensure_ascii=False) + "\n")
    return row
