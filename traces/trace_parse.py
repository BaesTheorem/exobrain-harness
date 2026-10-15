"""Turn the lines of one Claude Code transcript into flat rows for the trace database.

One file in, five row lists out: "sessions" (one row), "api_calls",
"tool_calls", "prompts" and "events". README.md documents every column.

INVARIANTS
- Pure: no I/O and no third-party imports. Runs on Python 3.11+ (the tests
  use 3.13, the venv 3.14).
- A bad line never raises. It is counted in the session's bad_lines.
- Claude Code logs an assistant message once per content block. api_calls has
  one row per (message id, request id), with the max of each usage field,
  because the usage on the earlier lines of a split message can be partial.
- Prompt text is kept verbatim up to TEXT_CHARS (the database is private and
  gitignored). Tool inputs are cut to INPUT_CHARS. The archive keeps both in full.
"""

from __future__ import annotations

import json
import re
from collections.abc import Iterable
from datetime import datetime

INPUT_CHARS = 400
TEXT_CHARS = 100_000
USAGE_FIELDS = ("input_tokens", "cache_creation_input_tokens", "cache_read_input_tokens", "output_tokens")

# Heuristic intent of a human prompt. Crude on purpose: the labels from reading
# traces are the real measure, these only make a baseline cheap to recompute.
INTENTS = (
    ("status_poll", re.compile(r"^(status|any update|update\??$|how'?s it (going|coming)|still (working|going)"
                               r"|progress|where are we|eta)\b", re.I)),
    ("approval", re.compile(r"^(y|yes|yep|yeah|ok|okay|sure|do it|go|go ahead|approved?|sounds good|lgtm|proceed)"
                            r"\b[\s\w!.,]{0,14}$", re.I)),
    ("resume", re.compile(r"^(resume|continue|keep going|go on|carry on|pick up)\b", re.I)),
)


def file_identity(file_id: str) -> dict:
    """project / session / agent identity from the archive-relative path."""
    parts = file_id.split("/")
    stem = parts[-1].removesuffix(".jsonl")
    if "subagents" in parts:
        i = parts.index("subagents")
        return {"project": parts[0], "session_id": parts[i - 1], "agent_id": stem, "is_subagent": True}
    return {"project": parts[0], "session_id": stem, "agent_id": None, "is_subagent": False}


def classify(text: str, *, is_subagent: bool, is_meta: bool, is_compact: bool) -> str:
    if is_subagent:
        return "agent_prompt"
    if is_compact:
        return "compact_summary"
    if is_meta:
        return "meta"
    if text.startswith("[Request interrupted by user"):
        return "interrupt"
    if text.startswith("<task-notification>"):
        return "task_notification"
    if "<command-name>" in text[:300]:
        return "slash_command"
    if text.startswith("<local-command"):
        return "local_command"
    if text.startswith("<") or text.startswith("Caveat:"):
        return "system_injected"
    return "human"


def intent(text: str) -> str | None:
    for name, rx in INTENTS:
        if rx.match(text):
            return name
    return None


def _seconds(a: str | None, b: str | None) -> float | None:
    if not a or not b:
        return None
    try:
        return round((datetime.fromisoformat(b) - datetime.fromisoformat(a)).total_seconds(), 3)
    except ValueError:
        return None


def _num(value: object) -> int | float | None:
    return value if isinstance(value, (int, float)) and not isinstance(value, bool) else None


def _event(o: dict, base: dict) -> dict:
    sub = o.get("subtype")
    row = {**base, "ts": o.get("timestamp"), "subtype": sub, "level": o.get("level"),
           "duration_ms": None, "pre_tokens": None, "post_tokens": None, "compact_trigger": None,
           "retry_attempt": _num(o.get("retryAttempt")), "detail": None}
    if sub == "compact_boundary":
        meta = o.get("compactMetadata") or {}
        row.update(compact_trigger=meta.get("trigger"), pre_tokens=_num(meta.get("preTokens")),
                   post_tokens=_num(meta.get("postTokens")), duration_ms=_num(meta.get("durationMs")))
    elif sub == "turn_duration":
        row["duration_ms"] = _num(o.get("durationMs"))
    elif sub == "api_error":
        err = o.get("error")
        if isinstance(err, dict):
            err = err.get("formatted") or err.get("message") or json.dumps(err)
        row["detail"] = str(err)[:INPUT_CHARS] if err is not None else None
    else:
        content = o.get("content")
        row["detail"] = str(content)[:INPUT_CHARS] if content is not None else None
    return row


def parse_lines(lines: Iterable[str], file_id: str) -> dict[str, list[dict]]:
    ident = file_identity(file_id)
    base = {"file_id": file_id, "session_id": ident["session_id"]}
    s: dict = {**base, "project": ident["project"], "agent_id": ident["agent_id"],
               "is_subagent": ident["is_subagent"], "cwd": None, "entrypoint": None, "version": None,
               "git_branch": None, "first_ts": None, "last_ts": None, "title": None, "ai_title": None,
               "permission_mode": None, "cost_usd": None, "api_duration_ms": None, "tool_duration_ms": None,
               "lines_added": None, "lines_removed": None, "lines": 0, "bad_lines": 0, "n_queued": 0}
    calls: dict[tuple, dict] = {}
    uses: dict[str, dict] = {}
    results: dict[str, dict] = {}
    prompts: list[dict] = []
    events: list[dict] = []

    for line in lines:
        s["lines"] += 1
        try:
            o = json.loads(line)
        except ValueError:
            s["bad_lines"] += 1
            continue
        if not isinstance(o, dict):
            s["bad_lines"] += 1
            continue
        ts = o.get("timestamp")
        if isinstance(ts, str) and ts:
            s["first_ts"] = ts if s["first_ts"] is None else min(s["first_ts"], ts)
            s["last_ts"] = ts if s["last_ts"] is None else max(s["last_ts"], ts)
        for key, field in (("cwd", "cwd"), ("entrypoint", "entrypoint"), ("version", "version"),
                           ("git_branch", "gitBranch")):
            if s[key] is None and o.get(field):
                s[key] = o[field]
        t = o.get("type")
        raw_msg = o.get("message")
        msg: dict = raw_msg if isinstance(raw_msg, dict) else {}

        if t == "assistant":
            key = (msg.get("id"), o.get("requestId"))
            usage = msg.get("usage") or {}
            cache = usage.get("cache_creation") or {}
            row = calls.get(key)
            if row is None:
                row = calls[key] = {**base, "message_id": key[0], "request_id": key[1], "ts": ts,
                                    "model": msg.get("model"), "requested_model": o.get("requestedModel"),
                                    "effort": o.get("effort"), "skill": o.get("attributionSkill"),
                                    "stop_reason": None, "is_api_error": bool(o.get("isApiErrorMessage")),
                                    "input_tokens": 0, "cache_write_tokens": 0, "cache_read_tokens": 0,
                                    "output_tokens": 0, "cache_write_5m": 0, "cache_write_1h": 0}
            for src, dst in zip(USAGE_FIELDS, ("input_tokens", "cache_write_tokens", "cache_read_tokens",
                                               "output_tokens"), strict=True):
                row[dst] = max(row[dst], _num(usage.get(src)) or 0)
            row["cache_write_5m"] = max(row["cache_write_5m"], _num(cache.get("ephemeral_5m_input_tokens")) or 0)
            row["cache_write_1h"] = max(row["cache_write_1h"], _num(cache.get("ephemeral_1h_input_tokens")) or 0)
            if msg.get("stop_reason"):
                row["stop_reason"] = msg["stop_reason"]
            for block in msg.get("content") or []:
                if isinstance(block, dict) and block.get("type") == "tool_use" and block.get("id") not in uses:
                    uses[block["id"]] = {**base, "tool_use_id": block["id"], "ts": ts, "tool": block.get("name"),
                                         "skill": o.get("attributionSkill"), "model": msg.get("model"),
                                         "input": json.dumps(block.get("input"), ensure_ascii=False)[:INPUT_CHARS]}

        elif t == "user":
            content = msg.get("content")
            texts: list[str] = []
            has_image = False
            if isinstance(content, str):
                texts.append(content)
            elif isinstance(content, list):
                for block in content:
                    if not isinstance(block, dict):
                        continue
                    kind = block.get("type")
                    if kind == "tool_result":
                        body = block.get("content")
                        if isinstance(body, list):
                            chars = sum(len(b.get("text", "")) for b in body if isinstance(b, dict))
                        else:
                            chars = len(str(body or ""))
                        results[block.get("tool_use_id") or ""] = {"is_error": bool(block.get("is_error")),
                                                                   "chars": chars, "ts": ts}
                    elif kind == "text":
                        texts.append(block.get("text", ""))
                    elif kind == "image":
                        has_image = True
            text = "\n".join(x for x in texts if x).strip()
            if text:
                category = classify(text, is_subagent=ident["is_subagent"], is_meta=bool(o.get("isMeta")),
                                    is_compact=bool(o.get("isCompactSummary")))
                prompts.append({**base, "uuid": o.get("uuid"), "ts": ts, "category": category,
                                "intent": intent(text) if category == "human" else None,
                                "chars": len(text), "has_image": has_image, "text": text[:TEXT_CHARS]})

        elif t == "system":
            events.append(_event(o, base))
        elif t == "cost-state":
            s.update(cost_usd=_num(o.get("totalCostUSD")), api_duration_ms=_num(o.get("totalAPIDuration")),
                     tool_duration_ms=_num(o.get("totalToolDuration")), lines_added=_num(o.get("totalLinesAdded")),
                     lines_removed=_num(o.get("totalLinesRemoved")))
        elif t == "custom-title" and o.get("customTitle"):
            s["title"] = o["customTitle"]
        elif t == "ai-title" and o.get("aiTitle"):
            s["ai_title"] = o["aiTitle"]
        elif t == "permission-mode" and o.get("permissionMode"):
            s["permission_mode"] = o["permissionMode"]
        elif t == "queue-operation" and o.get("operation") == "enqueue":
            s["n_queued"] += 1

    tool_calls = []
    for use_id, use in uses.items():
        res = results.get(use_id)
        tool_calls.append({**use, "has_result": res is not None, "is_error": bool(res and res["is_error"]),
                           "result_chars": res["chars"] if res else None,
                           "latency_s": _seconds(use["ts"], res["ts"]) if res else None})
    api_calls = sorted(calls.values(), key=lambda r: r["ts"] or "")
    first = next((c for c in api_calls if c["model"] != "<synthetic>"), None)
    humans = [p for p in prompts if p["category"] == "human"]

    def count(category: str, by: str = "category") -> int:
        return sum(1 for p in prompts if p[by] == category)

    s.update(
        title=s["title"] or s["ai_title"],
        models=sorted({c["model"] for c in api_calls if c["model"] and c["model"] != "<synthetic>"}),
        n_api_calls=len(api_calls), n_tool_calls=len(tool_calls),
        n_tool_errors=sum(1 for c in tool_calls if c["is_error"]),
        n_human_prompts=len(humans), n_interrupts=count("interrupt"),
        n_status_polls=count("status_poll", "intent"), n_approvals=count("approval", "intent"),
        n_resumes=count("resume", "intent"), n_task_notifications=count("task_notification"),
        n_slash_commands=count("slash_command"),
        n_compactions=sum(1 for e in events if e["subtype"] == "compact_boundary"),
        n_api_errors=sum(1 for e in events if e["subtype"] == "api_error"),
        first_context_tokens=(first["input_tokens"] + first["cache_write_tokens"] + first["cache_read_tokens"])
        if first else None,
        input_tokens=sum(c["input_tokens"] for c in api_calls),
        cache_write_tokens=sum(c["cache_write_tokens"] for c in api_calls),
        cache_read_tokens=sum(c["cache_read_tokens"] for c in api_calls),
        output_tokens=sum(c["output_tokens"] for c in api_calls),
        first_prompt=humans[0]["text"][:500] if humans else None,
        kind="subagent" if ident["is_subagent"] else ("multi_turn" if len(humans) >= 2 else "single_turn"),
    )
    del s["ai_title"]
    return {"sessions": [s], "api_calls": api_calls, "tool_calls": tool_calls, "prompts": prompts, "events": events}
