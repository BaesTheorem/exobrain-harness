#!/usr/bin/env python3
"""Stdio MCP server that connects one panelist to the shared message board.

Claude Code starts one copy per panelist. The run directory and the
panelist's handle come from the environment (PANEL_RUN, PANEL_AGENT), so a
panelist cannot post under another name. No dependencies: JSON-RPC 2.0, one
message per line, as the MCP stdio transport specifies. Tool calls run on
threads, so a blocking ask_client never stalls a read.

panel.py also sets, per panelist: PANEL_TOOLS (the board tools it gets),
PANEL_KINDS (the post kinds it may use), PANEL_DRAFT_KIND, and
PANEL_DRAFT_HOOK (a checker command: it reads a text on stdin and prints a
report, which the moderator posts after every draft and scan_text returns).
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
import threading
import time
from collections.abc import Callable
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parent))
import board

RUN = Path(os.environ["PANEL_RUN"])
ME = os.environ["PANEL_AGENT"]
CHAIR = os.environ.get("PANEL_CHAIR", "chair")
NAMES: dict[str, str] = json.loads(os.environ.get("PANEL_NAMES", "{}"))
NAMES.setdefault(board.LIAISON, "Client liaison")
NAMES.setdefault(board.MODERATOR, "Moderator")

PANEL_KINDS = ["candidate", "critique", "evidence", "deep-dive", "position", "note"]
CHAIR_KINDS = ["synthesis", "report"]
KINDS: list[str] = (json.loads(os.environ["PANEL_KINDS"]) if os.environ.get("PANEL_KINDS")
                    else PANEL_KINDS + (CHAIR_KINDS if ME == CHAIR else []))
DRAFT_KIND = os.environ.get("PANEL_DRAFT_KIND", "draft")
HOOK: list[str] = json.loads(os.environ.get("PANEL_DRAFT_HOOK") or "[]")
HOOK_LABEL = os.environ.get("PANEL_HOOK_LABEL", "Checker report")
Args = dict[str, Any]
_out = threading.Lock()


def _state() -> dict[str, Any]:
    return board.read_state(RUN)


def read_board(args: Args) -> str:
    since = int(args.get("since") or 0)
    author = str(args.get("author") or "").strip()
    kinds = {k.strip() for k in str(args.get("kind") or "").split(",") if k.strip()}
    last = int(args.get("last") or 0)
    state = _state()
    gated = bool(state.get("gated"))
    only: list[str] | None = state.get("visible_kinds")
    posts = [p for p in board.visible(board.read_posts(RUN), ME, gated, only)
             if p["id"] > since and (not author or p["author"] == author)
             and (not kinds or p["kind"] in kinds)]
    if last > 0:
        posts = posts[-last:]
    head = f"Board as seen by {ME}. Current round: {state.get('round', '?')} ({state.get('label', '')})."
    if only:
        head += f" This round shows you your own posts and posts of kind {', '.join(only)} only."
    elif gated:
        head += " This round is gated: you see the liaison Q&A and your own posts only."
    if not posts:
        return head + "\n\nNo posts match."
    return f"{head} {len(posts)} posts.\n\n" + "\n\n-----\n\n".join(
        board.format_post(p, NAMES) for p in posts)


def _run_hook(text: str) -> str:
    try:
        proc = subprocess.run(HOOK, input=text, capture_output=True, text=True, timeout=90, check=False)
    except (OSError, subprocess.TimeoutExpired) as e:
        return f"(the checker failed: {e})"
    return proc.stdout.strip() or proc.stderr.strip() or "(the checker returned nothing)"


def post(args: Args) -> str:
    kind = str(args.get("kind") or "note")
    if kind not in KINDS:
        raise ValueError(f"kind must be one of {KINDS}")
    if kind == DRAFT_KIND and _state().get("no_drafts"):
        raise ValueError("this round does not accept drafts: post your critique and vote with submit_verdict")
    body = str(args.get("body") or "").strip()
    if not body:
        raise ValueError("body is empty")
    reply_to = args.get("reply_to")
    p = board.append_post(RUN, ME, kind, body, str(args.get("title") or ""),
                          int(reply_to) if reply_to else None)
    out = f"Posted as #{p['id']}."
    if kind == DRAFT_KIND and HOOK:
        report = _run_hook(body)
        r = board.append_post(RUN, board.MODERATOR, "scan", report, f"{HOOK_LABEL} for draft #{p['id']}", p["id"])
        out += f"\n\n{HOOK_LABEL} (posted as #{r['id']}):\n{report}"
    return out


def scan_text(args: Args) -> str:
    text = str(args.get("text") or "").strip()
    if not text:
        raise ValueError("text is empty")
    return _run_hook(text)


def submit_verdict(args: Args) -> str:
    satisfied = args.get("satisfied")
    if isinstance(satisfied, str) and satisfied.strip().lower() in ("true", "false"):
        satisfied = satisfied.strip().lower() == "true"
    if not isinstance(satisfied, bool):
        raise ValueError("satisfied must be true or false")
    must = str(args.get("must_change") or "").strip()
    if not satisfied and not must:
        raise ValueError("must_change is required when you are not satisfied: list the specific changes you need")
    draft = board.latest(board.read_posts(RUN), DRAFT_KIND)
    if draft is None:
        raise ValueError("there is no draft to vote on yet")
    if satisfied:
        body = f"SATISFIED with draft #{draft['id']}: I would sign it as finished work." + (
            f"\n\nNotes, not conditions: {must}" if must else "")
    else:
        body = f"NOT SATISFIED with draft #{draft['id']}. Before I sign, these must change:\n\n{must}"
    p = board.append_post(RUN, ME, "verdict", body, "Verdict", draft["id"],
                          data={"draft": draft["id"], "satisfied": satisfied, "must_change": must})
    return (f"Recorded as #{p['id']}: {'satisfied' if satisfied else 'not satisfied'} with draft "
            f"#{draft['id']}. A later vote in this round replaces it.")


def ask_client(args: Args) -> str:
    question = str(args.get("question") or "").strip()
    if not question:
        raise ValueError("question is empty")
    p = board.append_post(RUN, ME, "question", question)
    later = f"The answer will appear on the board as a reply to #{p['id']}."
    if args.get("wait") is False:
        return f"Question posted as #{p['id']}. {later}"
    deadline = time.time() + min(float(args.get("wait_minutes") or 15), 30) * 60
    while time.time() < deadline:
        answer = board.answer_for(board.read_posts(RUN), p["id"])
        if answer:
            return f"Answer to #{p['id']} (post #{answer['id']}):\n{answer['body']}"
        time.sleep(3)
    return f"No answer yet to #{p['id']}. Continue on an explicit assumption. {later}"


def submit_scores(args: Args) -> str:
    clean: list[dict[str, Any]] = []
    for r in args.get("scores") or []:
        item = str(r.get("item") or "").strip().upper()
        if not item:
            raise ValueError("every score row needs an item id")
        row: dict[str, Any] = {"item": item, "note": str(r.get("note") or "").strip()}
        for c in board.CRITERIA:
            v = int(r.get(c) or 0)
            if not 1 <= v <= 5:
                raise ValueError(f"{item}: {c} must be an integer from 1 to 5")
            row[c] = v
        clean.append(row)
    if not clean:
        raise ValueError("no score rows")
    body = "\n".join(
        f"- {r['item']}: " + ", ".join(f"{c} {r[c]}" for c in board.CRITERIA)
        + (f". {r['note']}" if r["note"] else "") for r in clean)
    p = board.append_post(RUN, ME, "scores", body, "Scores", data=clean)
    return f"Recorded {len(clean)} score rows as #{p['id']}. A later row for the same item replaces it."


def score_table(_: Args) -> str:
    return board.score_table(board.read_posts(RUN))


def _notebook() -> Path:
    return RUN / "notebooks" / f"{ME}.md"


def notebook_read(_: Args) -> str:
    path = _notebook()
    return path.read_text(encoding="utf-8") if path.exists() else "Your notebook is empty."


def notebook_write(args: Args) -> str:
    text = str(args.get("text") or "").strip()
    if not text:
        raise ValueError("text is empty")
    path = _notebook()
    path.parent.mkdir(parents=True, exist_ok=True)
    if args.get("mode") == "replace":
        path.write_text(text + "\n", encoding="utf-8")
    else:
        with open(path, "a", encoding="utf-8") as f:
            f.write(f"\n## {_state().get('round', '')} {time.strftime('%H:%M')}\n{text}\n")
    return f"Notebook saved ({path.stat().st_size} bytes)."


def _obj(props: dict[str, Any], required: list[str] | None = None) -> dict[str, Any]:
    return {"type": "object", "properties": props, "required": required or []}


SCORE_ROW = _obj({"item": {"type": "string", "description": "Longlist id, for example L3."},
                  **{c: {"type": "integer", "minimum": 1, "maximum": 5} for c in board.CRITERIA},
                  "note": {"type": "string", "description": "One-line rationale."}},
                 ["item", *board.CRITERIA])

TOOLS: list[dict[str, Any]] = [
    {"name": "read_board",
     "description": "Read the shared message board, oldest post first. Filters: `since` (only posts "
                    "numbered above it), `author` (one member's posts), `kind` (one kind, or several "
                    "separated by commas), `last` (only the last N posts that match).",
     "inputSchema": _obj({"since": {"type": "integer"}, "author": {"type": "string"},
                          "kind": {"type": "string"}, "last": {"type": "integer"}})},
    {"name": "post",
     "description": "Publish a post to the board. The whole panel and the client read it. "
                    "Use reply_to to answer or critique a specific post."
                    + (f" After a post of kind {DRAFT_KIND}, the moderator posts the "
                       f"{HOOK_LABEL.lower()} for it, and you get the report back." if HOOK else ""),
     "inputSchema": _obj({"kind": {"type": "string", "enum": KINDS},
                          "title": {"type": "string"},
                          "body": {"type": "string", "description": "Markdown."},
                          "reply_to": {"type": "integer"}}, ["kind", "title", "body"])},
    {"name": "submit_verdict",
     "description": f"Vote on the latest {DRAFT_KIND}. satisfied=true means you would sign it as "
                    "finished work as it stands. When false, must_change lists the specific changes "
                    "you need before you would sign, each one possible in one revision pass. Your "
                    "latest vote in a round replaces an earlier one.",
     "inputSchema": _obj({"satisfied": {"type": "boolean"},
                          "must_change": {"type": "string",
                                          "description": "Required when satisfied is false."}},
                         ["satisfied"])},
    {"name": "scan_text",
     "description": f"Run the room's checker ({HOOK_LABEL.lower()}) on any text you give it, a stanza "
                    "or a whole draft, and return the report. Nothing is posted.",
     "inputSchema": _obj({"text": {"type": "string"}}, ["text"])},
    {"name": "ask_client",
     "description": "Ask the client liaison one question about the client: skills, time, money, "
                    "location, constraints, preferences. The whole panel sees the question and the "
                    "answer. By default it waits for the answer, which usually takes a few minutes.",
     "inputSchema": _obj({"question": {"type": "string"},
                          "wait": {"type": "boolean", "description": "Wait for the answer (default true)."},
                          "wait_minutes": {"type": "number", "description": "Default 15, maximum 30."}},
                         ["question"])},
    {"name": "submit_scores",
     "description": "Score longlist items from 1 (bad) to 5 (good). demand: evidence that money "
                    "already changes hands for this. reach: how cheaply and fast the first customers "
                    "can be reached. build: how feasible it is for this client to build and run. "
                    "speed: how fast it reaches the client's target. durability: survives competitors, "
                    "platforms and AI commoditization, with low churn. fit: fits the client's answers.",
     "inputSchema": _obj({"scores": {"type": "array", "items": SCORE_ROW}}, ["scores"])},
    {"name": "score_table",
     "description": "The panel's aggregated scores: the mean per criterion per item, and the spread "
                    "between scorers.",
     "inputSchema": _obj({})},
    {"name": "notebook_read",
     "description": "Read your private notebook. Only you see it, and it persists between rounds.",
     "inputSchema": _obj({})},
    {"name": "notebook_write",
     "description": "Write to your private notebook: sources, leads, rejected ideas, open questions. "
                    "mode append (default) adds a dated section; replace rewrites it.",
     "inputSchema": _obj({"text": {"type": "string"},
                          "mode": {"type": "string", "enum": ["append", "replace"]}}, ["text"])},
]

_ENABLED: list[str] | None = json.loads(os.environ["PANEL_TOOLS"]) if os.environ.get("PANEL_TOOLS") else None
TOOLS = [t for t in TOOLS if (_ENABLED is None or t["name"] in _ENABLED)
         and (HOOK or t["name"] != "scan_text")
         and (_ENABLED is not None or t["name"] not in ("submit_verdict", "scan_text"))]

DISPATCH: dict[str, Callable[[Args], str]] = {
    name: fn for name, fn in {
        "read_board": read_board, "post": post, "ask_client": ask_client,
        "submit_scores": submit_scores, "score_table": score_table,
        "notebook_read": notebook_read, "notebook_write": notebook_write,
        "submit_verdict": submit_verdict, "scan_text": scan_text,
    }.items() if name in {t["name"] for t in TOOLS}}


def _send(msg: dict[str, Any]) -> None:
    with _out:
        sys.stdout.write(json.dumps(msg) + "\n")
        sys.stdout.flush()


def _call(mid: Any, name: str, args: Args) -> None:
    try:
        fn = DISPATCH.get(name)
        if fn is None:
            raise ValueError(f"unknown tool {name}")
        text, is_error = fn(args), False
    except Exception as e:  # every failure goes back to the model as a tool error
        text, is_error = f"Error: {e}", True
    _send({"jsonrpc": "2.0", "id": mid,
           "result": {"content": [{"type": "text", "text": text}], "isError": is_error}})


def main() -> None:
    calls: list[threading.Thread] = []
    for line in sys.stdin:
        try:
            msg = json.loads(line)
        except json.JSONDecodeError:
            continue
        mid, method, params = msg.get("id"), msg.get("method"), msg.get("params") or {}
        if method == "initialize":
            _send({"jsonrpc": "2.0", "id": mid, "result": {
                "protocolVersion": params.get("protocolVersion", "2025-06-18"),
                "capabilities": {"tools": {}},
                "serverInfo": {"name": "board", "version": "1.0.0"}}})
        elif method == "tools/list":
            _send({"jsonrpc": "2.0", "id": mid, "result": {"tools": TOOLS}})
        elif method == "tools/call":
            t = threading.Thread(target=_call, daemon=True,
                                 args=(mid, params.get("name"), params.get("arguments") or {}))
            t.start()
            calls.append(t)
        elif method == "ping":
            _send({"jsonrpc": "2.0", "id": mid, "result": {}})
        elif mid is not None:
            _send({"jsonrpc": "2.0", "id": mid,
                   "error": {"code": -32601, "message": f"method not found: {method}"}})
    # stdin closed: let quick calls land on the board; a waiting ask_client is abandoned.
    for t in calls:
        t.join(timeout=5)


if __name__ == "__main__":
    main()
