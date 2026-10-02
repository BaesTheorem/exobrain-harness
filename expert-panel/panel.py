#!/usr/bin/env python3
"""Run an isolated expert panel that works through a shared message board.

Every panelist is its own headless `claude -p` process that knows nothing
about this machine: no settings, CLAUDE.md, hooks, memory or MCP servers
(--setting-sources "" and --strict-mcp-config), a system prompt built only
from the run's panel.json and brief, a neutral cwd under /tmp, and three kinds of tool:
WebSearch, WebFetch and the board server (board_server.py). The panel works
in the rounds listed in the run's panel.json. The operator plays the client
liaison: `watch` streams the panel's questions and `answer` replies to them.

A run directory holds panel.json and brief.md (see example/). The run writes
everything else next to them: board.jsonl, state.json, events.log,
notebooks/, mcp/, logs/ (one stream-json log per panelist per round).

Usage:
  panel.py check RUN [--control] [--model M]   one cheap call that proves the sandbox
  panel.py run RUN                 run the rounds, or resume an interrupted run
  panel.py watch RUN [--tail]      event stream for a monitor: questions, rounds, errors
  panel.py pending RUN             unanswered questions
  panel.py answer RUN ID TEXT      answer question ID as the liaison ("-" reads stdin)
  panel.py say RUN TEXT            liaison note to the whole panel
  panel.py status RUN              rounds, posts, cost so far
  panel.py render RUN OUT_DIR      the board, notebooks and research trail as markdown

INVARIANTS
- A panelist's environment carries no CLAUDE*/MIST_* variable except
  MIST_UNATTENDED=1, so nothing about the parent session leaks into it.
- Resume never reruns a (round, panelist) pair that finished: state.json
  records each pair as it completes.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import shutil
import subprocess
import sys
import time
import uuid
from dataclasses import dataclass, field
from pathlib import Path
from string import Template
from typing import IO, Any

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import board

SERVER = HERE / "board_server.py"
PROMPT_TEMPLATE = HERE / "system-prompt.md"
BOARD_TOOLS = ["read_board", "post", "ask_client", "submit_scores", "score_table",
               "notebook_read", "notebook_write"]
ALLOWED_TOOLS = ["WebSearch", "WebFetch"] + [f"mcp__board__{t}" for t in BOARD_TOOLS]
SANDBOX_ROOT = Path("/private/tmp/expert-panel")
WATCH_TAGS = ("START", "ROUND", "RETRY", "ERROR", "LIMIT", "WAITING", "ANSWERS", "FATAL", "DONE")
Agent = dict[str, Any]


# ---- config -----------------------------------------------------------------

def load(run: Path) -> dict[str, Any]:
    cfg = json.loads((run / "panel.json").read_text(encoding="utf-8"))
    cfg["brief"] = (run / cfg.get("brief_file", "brief.md")).read_text(encoding="utf-8").strip()
    return cfg


def everyone(cfg: dict[str, Any]) -> list[Agent]:
    return cfg["panelists"] + [cfg["chair"]]


def members(cfg: dict[str, Any], who: str | list[str]) -> list[Agent]:
    if who == "panel":
        return cfg["panelists"]
    if who == "chair":
        return [cfg["chair"]]
    if who == "all":
        return everyone(cfg)
    return [a for a in everyone(cfg) if a["handle"] in who]


def names(cfg: dict[str, Any]) -> dict[str, str]:
    out = {a["handle"]: a["name"] for a in everyone(cfg)}
    out.update({board.LIAISON: "Client liaison", board.MODERATOR: "Moderator"})
    return out


def system_prompt(cfg: dict[str, Any], agent: Agent) -> str:
    roster = "\n".join(f"- `{a['handle']}`: {a['name']}. {a['summary']}" for a in everyone(cfg))
    return Template(PROMPT_TEMPLATE.read_text(encoding="utf-8")).substitute(
        name=agent["name"], handle=agent["handle"], persona=agent["persona"],
        brief=cfg["brief"], roster=roster, today=time.strftime("%A, %B %-d, %Y"))


# ---- the sandboxed claude process -------------------------------------------

def agent_env() -> dict[str, str]:
    env = {k: v for k, v in os.environ.items() if not k.startswith(("CLAUDE", "MIST_"))}
    env["MIST_UNATTENDED"] = "1"
    env["MCP_TOOL_TIMEOUT"] = str(35 * 60 * 1000)  # ask_client may wait up to 30 min
    return env


def mcp_config(run: Path, cfg: dict[str, Any], agent: Agent) -> Path:
    path = run / "mcp" / f"{agent['handle']}.json"
    path.parent.mkdir(exist_ok=True)
    server = {"command": sys.executable, "args": [str(SERVER)],
              "env": {"PANEL_RUN": str(run), "PANEL_AGENT": agent["handle"],
                      "PANEL_CHAIR": cfg["chair"]["handle"], "PANEL_NAMES": json.dumps(names(cfg))}}
    path.write_text(json.dumps({"mcpServers": {"board": server}}, indent=2), encoding="utf-8")
    return path


def claude_cmd(run: Path, cfg: dict[str, Any], agent: Agent, model: str,
               effort: str | None, isolated: bool = True) -> list[str]:
    exe = shutil.which("claude")
    if not exe:
        sys.exit("claude CLI not found on PATH")
    cmd = [exe, "-p", "--model", model,
           "--strict-mcp-config", "--mcp-config", str(mcp_config(run, cfg, agent)),
           "--tools", "WebSearch,WebFetch",
           "--allowedTools", ",".join(ALLOWED_TOOLS),
           "--permission-mode", "dontAsk", "--permission-prompts", "none",
           "--output-format", "stream-json", "--verbose"]
    if isolated:
        cmd += ["--setting-sources", "", "--system-prompt", system_prompt(cfg, agent)]
    if effort:
        cmd += ["--effort", effort]
    return cmd


def sandbox(run: Path) -> Path:
    path = SANDBOX_ROOT / run.name
    path.mkdir(parents=True, exist_ok=True)
    return path


def read_log(log: Path) -> tuple[dict[str, Any], dict[str, Any] | None, list[dict[str, Any]]]:
    """(init event, result event, tool calls) from a stream-json log."""
    init: dict[str, Any] = {}
    result: dict[str, Any] | None = None
    calls: list[dict[str, Any]] = []
    if not log.exists():
        return init, result, calls
    for line in log.read_text(encoding="utf-8", errors="replace").splitlines():
        try:
            ev = json.loads(line)
        except json.JSONDecodeError:
            continue
        if ev.get("type") == "system" and ev.get("subtype") == "init":
            init = ev
        elif ev.get("type") == "result":
            result = ev
        elif ev.get("type") == "assistant":
            for block in (ev.get("message") or {}).get("content") or []:
                if isinstance(block, dict) and block.get("type") == "tool_use":
                    calls.append({"name": block.get("name"), "input": block.get("input") or {}})
    return init, result, calls


# ---- running rounds ---------------------------------------------------------

@dataclass
class Job:
    agent: Agent
    proc: subprocess.Popen[bytes]
    log: Path
    err: Path
    started: float
    attempt: int
    sid: str
    files: list[IO[bytes]] = field(default_factory=list)

    @property
    def handle(self) -> str:
        return self.agent["handle"]

    def close(self) -> None:
        for f in self.files:
            f.close()


def event(run: Path, text: str) -> None:
    line = f"{time.strftime('%H:%M:%S')} {text}"
    with open(run / "events.log", "a", encoding="utf-8") as f:
        f.write(line + "\n")
    print(line, flush=True)


def progress(action: str, run: Path, pct: float | None = None, detail: str = "") -> None:
    exe = shutil.which("mist-progress")
    if not exe:
        return
    cmd = [exe, action, "--id", f"panel-{run.name}", "--label", "Expert panel"]
    if pct is not None:
        cmd += ["--pct", f"{pct:.0f}"]
    if detail:
        cmd += ["--detail", detail]
    try:
        subprocess.run(cmd, capture_output=True, timeout=15, check=False)
    except subprocess.TimeoutExpired:
        pass


def start_job(run: Path, cfg: dict[str, Any], agent: Agent, rnd: dict[str, Any], attempt: int) -> Job:
    logs = run / "logs"
    logs.mkdir(exist_ok=True)
    stem = f"{rnd['id']}-{agent['handle']}" + (f"-try{attempt}" if attempt > 1 else "")
    sid = str(uuid.uuid4())
    cmd = claude_cmd(run, cfg, agent, cfg["model"], cfg.get("effort")) + ["--session-id", sid]
    out, err = open(logs / f"{stem}.jsonl", "wb"), open(logs / f"{stem}.err", "wb")
    proc = subprocess.Popen(cmd, stdin=subprocess.PIPE, stdout=out, stderr=err,
                            cwd=sandbox(run), env=agent_env())
    assert proc.stdin is not None
    proc.stdin.write(f"{rnd['id']}: {rnd['label']}\n\n{rnd['prompt']}".encode())
    proc.stdin.close()
    return Job(agent, proc, logs / f"{stem}.jsonl", logs / f"{stem}.err", time.time(), attempt, sid, [out, err])


def failure(job: Job, result: dict[str, Any] | None) -> str:
    err = job.err.read_text(encoding="utf-8", errors="replace").strip() if job.err.exists() else ""
    text = (result or {}).get("result") or ""
    why = f"exit {job.proc.returncode}, " + (str((result or {}).get("subtype")) if result else "no result event")
    detail = " ".join((text or err).split())[:300]
    if re.search(r"session limit|usage limit|rate.?limit|\b429\b", f"{text} {err}", re.I):
        why = "LIMIT " + why
    return f"{why}: {detail}" if detail else why


def autopost_if_silent(run: Path, rnd: dict[str, Any], handle: str, result: dict[str, Any]) -> None:
    """If a panelist finished without posting, its final message goes on the board in its name."""
    if any(p["author"] == handle and p.get("round") == rnd["id"] for p in board.read_posts(run)):
        return
    text = str(result.get("result") or "").strip()
    if text:
        board.append_post(run, handle, "note", text, "Final message (posted by the moderator: no post this round)")


def run_round(run: Path, cfg: dict[str, Any], rnd: dict[str, Any], finished: int, total: int) -> int:
    state = board.read_state(run)
    state.update(round=rnd["id"], label=rnd["label"], gated=bool(rnd.get("gated")))
    board.write_state(run, state)
    done: list[str] = state["done"].setdefault(rnd["id"], [])
    todo = [a for a in members(cfg, rnd["who"]) if a["handle"] not in done]
    finished += len(members(cfg, rnd["who"])) - len(todo)
    event(run, f"ROUND {rnd['id']} {rnd['label']}: started, {len(todo)} running"
               + (" (gated)" if rnd.get("gated") else ""))
    timeout = float(rnd.get("timeout_min", 45)) * 60
    jobs = [start_job(run, cfg, a, rnd, 1) for a in todo]
    ok = 0
    while jobs:
        time.sleep(5)
        for job in list(jobs):
            if job.proc.poll() is None:
                if time.time() - job.started > timeout:
                    job.proc.kill()
                    job.proc.wait()
                    job.close()
                    jobs.remove(job)
                    finished += 1
                    event(run, f"ERROR {rnd['id']} {job.handle}: timed out after {timeout / 60:.0f} min")
                continue
            job.close()
            jobs.remove(job)
            _, result, _ = read_log(job.log)
            if result and result.get("subtype") == "success" and not result.get("is_error"):
                ok += 1
                finished += 1
                autopost_if_silent(run, rnd, job.handle, result)
                state = board.read_state(run)
                state["done"].setdefault(rnd["id"], []).append(job.handle)
                state.setdefault("sessions", {})[f"{rnd['id']}-{job.handle}"] = job.sid
                board.write_state(run, state)
                print(f"  {rnd['id']} {job.handle} finished: {result.get('num_turns')} turns, "
                      f"${result.get('total_cost_usd') or 0:.2f}", flush=True)
                continue
            why = failure(job, result)
            if job.attempt < 2 and not why.startswith("LIMIT"):
                event(run, f"RETRY {rnd['id']} {job.handle}: {why}")
                jobs.append(start_job(run, cfg, job.agent, rnd, job.attempt + 1))
            else:
                finished += 1
                event(run, f"{'LIMIT' if why.startswith('LIMIT') else 'ERROR'} {rnd['id']} {job.handle}: {why}")
        running = ", ".join(j.handle for j in jobs)
        progress("set", run, 100 * finished / total,
                 f"{rnd['id']} {rnd['label']}: " + (f"waiting on {running}" if running else "wrapping up"))
    if todo and ok == 0:
        event(run, f"FATAL {rnd['id']}: no panelist finished; fix the cause, then run again to resume")
        progress("fail", run, 100 * finished / total, f"{rnd['id']} failed; resumable")
        sys.exit(2)
    if rnd.get("await_answers"):
        await_answers(run, float(rnd.get("await_minutes", 30)))
    state = board.read_state(run)
    state["completed"].append(rnd["id"])
    board.write_state(run, state)
    event(run, f"ROUND {rnd['id']} done: {ok}/{len(todo)} finished")
    return finished


def await_answers(run: Path, minutes: float) -> None:
    deadline, announced = time.time() + minutes * 60, False
    while time.time() < deadline:
        n = len(board.unanswered(board.read_posts(run)))
        if n == 0:
            if announced:
                event(run, "ANSWERS all questions answered")
            return
        if not announced:
            event(run, f"WAITING for {n} answers before the next round")
            progress("set", run, None, f"waiting for the liaison: {n} questions")
            announced = True
        time.sleep(5)
    event(run, "WAITING timed out; the next round starts with questions unanswered")


def cmd_run(run: Path) -> None:
    cfg = load(run)
    state = board.read_state(run)
    for key, empty in (("done", {}), ("completed", []), ("sessions", {})):
        state.setdefault(key, empty)
    state.setdefault("started", board.now_iso())
    board.write_state(run, state)
    total = sum(len(members(cfg, r["who"])) for r in cfg["rounds"])
    finished = 0
    progress("start", run, 0, "starting")
    event(run, f"START {cfg['title']}: {len(cfg['rounds'])} rounds, model {cfg['model']}")
    for rnd in cfg["rounds"]:
        if rnd["id"] in state["completed"]:
            finished += len(members(cfg, rnd["who"]))
            continue
        finished = run_round(run, cfg, rnd, finished, total)
    state = board.read_state(run)
    state.update(round="done", label="finished", gated=False, finished=board.now_iso())
    board.write_state(run, state)
    progress("done", run, 100, "finished")
    event(run, f"DONE {len(board.read_posts(run))} posts")


# ---- the liaison's side -----------------------------------------------------

def cmd_watch(run: Path, tail: bool) -> None:
    evp = run / "events.log"
    offset = evp.stat().st_size if tail and evp.exists() else 0
    seen: set[int] = set()
    while True:
        if evp.exists():
            with open(evp, encoding="utf-8") as f:
                f.seek(offset)
                chunk = f.read()
                offset = f.tell()
            for line in chunk.splitlines():
                if any(f" {tag} " in f" {line} " for tag in WATCH_TAGS):
                    print(line, flush=True)
                if " DONE " in f"{line} " or " FATAL " in line:
                    return
        for q in board.unanswered(board.read_posts(run)):
            if q["id"] not in seen:
                seen.add(q["id"])
                print(f"QUESTION #{q['id']} from {q['author']}: {' '.join(q['body'].split())}", flush=True)
        time.sleep(2)


def cmd_pending(run: Path) -> None:
    qs = board.unanswered(board.read_posts(run))
    for q in qs:
        print(f"#{q['id']} {q['author']}: {' '.join(q['body'].split())}\n")
    print(f"{len(qs)} unanswered")


def _text(arg: str) -> str:
    text = sys.stdin.read() if arg == "-" else arg
    if not text.strip():
        sys.exit("empty text")
    return text


def cmd_answer(run: Path, qid: int, text: str) -> None:
    q = next((p for p in board.read_posts(run) if p["id"] == qid), None)
    if not q or q["kind"] != "question":
        sys.exit(f"#{qid} is not a question")
    p = board.append_post(run, board.LIAISON, "answer", _text(text), reply_to=qid)
    print(f"answered #{qid} as #{p['id']}")


def cmd_say(run: Path, text: str) -> None:
    p = board.append_post(run, board.LIAISON, "liaison-note", _text(text))
    print(f"posted #{p['id']}")


def costs(run: Path) -> dict[str, float]:
    out: dict[str, float] = {}
    for log in sorted((run / "logs").glob("*.jsonl")):
        _, result, _ = read_log(log)
        if result:
            out[log.stem] = float(result.get("total_cost_usd") or 0)
    return out


def cmd_status(run: Path) -> None:
    state, posts = board.read_state(run), board.read_posts(run)
    spent = costs(run)
    print(f"round: {state.get('round')} ({state.get('label')}), gated={state.get('gated')}")
    print(f"completed: {', '.join(state.get('completed', [])) or '-'}")
    print(f"posts: {len(posts)}, unanswered questions: {len(board.unanswered(posts))}")
    print(f"API-equivalent cost so far: ${sum(spent.values()):.2f} over {len(spent)} sessions")


def cmd_check(run: Path, control: bool, model: str | None) -> None:
    """Prove the sandbox: the tool list, the board server, and no trace of this machine's context."""
    cfg = load(run)
    prompt = ("This is a configuration test. Do not call any tools. Reply with exactly three lines. "
              "CONTEXT: YES or NO. Does anything in your context (system prompt, messages, reminders, "
              "attachments) mention MIST, Exobrain, Obsidian, Things 3 or Kansas City? If YES, quote it. "
              "ROLE: your role on the panel, your board handle, and the client's target, from your "
              "instructions, or NONE. PROMPT: the first ten words of your system prompt.")
    cmd = claude_cmd(run, cfg, cfg["panelists"][0], model or cfg.get("check_model", cfg["model"]), None,
                     isolated=not control) + ["--no-session-persistence"]
    proc = subprocess.run(cmd, input=prompt.encode(), capture_output=True, cwd=sandbox(run),
                          env=agent_env(), timeout=300, check=False)
    log = run / "check.jsonl"
    log.write_bytes(proc.stdout)
    init, result, _ = read_log(log)
    tools = sorted(init.get("tools") or [])
    servers = {s.get("name"): s.get("status") for s in init.get("mcp_servers") or []}
    answer = str((result or {}).get("result") or proc.stderr.decode(errors="replace")).strip()
    print(f"mode: {'CONTROL (settings and default prompt loaded)' if control else 'isolated'}")
    print(f"model: {init.get('model')}")
    print(f"tools: {', '.join(tools)}")
    print(f"mcp servers: {servers}")
    print(f"answer:\n{answer}")
    extra = [t for t in tools if t not in ALLOWED_TOOLS]
    leaked = re.search(r"CONTEXT:\s*\**\s*YES", answer, re.I) is not None
    ok = not extra and servers.get("board") == "connected" and not leaked and result is not None
    print(f"\nverdict: {'PASS' if ok else 'FAIL'}"
          + (f" (extra tools: {extra})" if extra else "") + (" (context leaked)" if leaked else ""))


# ---- rendering --------------------------------------------------------------

def _demote(body: str) -> str:
    return re.sub(r"^(#{1,4}) ", lambda m: "#" * (len(m.group(1)) + 2) + " ", body, flags=re.M)


def cmd_render(run: Path, out: Path) -> None:
    cfg, state, posts = load(run), board.read_state(run), board.read_posts(run)
    nm, spent = names(cfg), costs(run)
    out.mkdir(parents=True, exist_ok=True)
    by_id = {p["id"]: p for p in posts}
    md = [f"# {cfg['title']}: full message board", "",
          f"- Run `{run.name}`, started {state.get('started', '?')}, finished {state.get('finished', 'not yet')}",
          f"- Model `{cfg['model']}`, effort {cfg.get('effort') or 'default'}; every panelist ran isolated "
          "(no settings, memory or MCP servers; tools: WebSearch, WebFetch, the board)",
          f"- {len(posts)} posts; API-equivalent cost ${sum(spent.values()):.2f} over {len(spent)} sessions",
          "", "## Panel", ""]
    md += [f"- **{a['name']}** (`{a['handle']}`): {a['summary']}" for a in everyone(cfg)]
    md += ["", "## Brief given to every panelist", ""] + [f"> {ln}" for ln in cfg["brief"].splitlines()]
    md += ["", "## Rounds", ""] + [f"- **{r['id']} {r['label']}** ({r['who'] if isinstance(r['who'], str) else ', '.join(r['who'])})"
                                   for r in cfg["rounds"]]
    qa = [p for p in posts if p["kind"] == "question"]
    if qa:
        md += ["", "## Questions to the liaison", ""]
        for q in qa:
            a = board.answer_for(posts, q["id"])
            md += [f"**#{q['id']} {nm.get(q['author'], q['author'])}:** {q['body']}", "",
                   f"> **#{a['id']} liaison:** " + a["body"].replace("\n", "\n> ") if a else "> (no answer)", ""]
    md += ["", "## Board (chronological)", ""]
    for p in posts:
        head = f"### #{p['id']} · {nm.get(p['author'], p['author'])} · {p['kind']} · {p.get('round') or '-'} · {p['ts'][11:16]}"
        md.append(head)
        if p.get("title"):
            md.append(f"**{p['title']}**")
        if p.get("reply_to"):
            parent = by_id.get(p["reply_to"])
            md.append(f"*Reply to #{p['reply_to']}" + (f" ({nm.get(parent['author'], parent['author'])})" if parent else "") + "*")
        md += ["", _demote(p["body"]), ""]
    (out / "Message Board.md").write_text("\n".join(md) + "\n", encoding="utf-8")

    notes = [f"# {cfg['title']}: panelist notebooks", "",
             "Each panelist's private notebook. Nobody else on the panel could read these.", ""]
    for a in everyone(cfg):
        path = run / "notebooks" / f"{a['handle']}.md"
        notes += [f"## {a['name']} (`{a['handle']}`)", "",
                  _demote(path.read_text(encoding="utf-8")) if path.exists() else "(empty)", ""]
    (out / "Panelist Notebooks.md").write_text("\n".join(notes) + "\n", encoding="utf-8")

    trail = [f"# {cfg['title']}: research trail", "",
             "Every web search and page fetch, per panelist per round, from the session logs.", "",
             "| session | turns | cost |", "|---|---|---|"]
    sections: list[str] = []
    for log in sorted((run / "logs").glob("*.jsonl")):
        _, result, calls = read_log(log)
        trail.append(f"| {log.stem} | {(result or {}).get('num_turns', '?')} | ${spent.get(log.stem, 0):.2f} |")
        lines = [f"- search: {c['input'].get('query')}" if c["name"] == "WebSearch"
                 else f"- fetch: {c['input'].get('url')}" for c in calls
                 if c["name"] in ("WebSearch", "WebFetch")]
        board_calls = sum(1 for c in calls if str(c["name"]).startswith("mcp__board__"))
        sections += [f"## {log.stem}", "", f"{len(lines)} web calls, {board_calls} board calls.", ""] + lines + [""]
    (out / "Research Trail.md").write_text("\n".join(trail + [""] + sections) + "\n", encoding="utf-8")
    print(f"wrote {out}")


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)
    for name in ("check", "run", "watch", "pending", "answer", "say", "status", "render"):
        sp = sub.add_parser(name)
        sp.add_argument("run", type=Path)
        if name == "check":
            sp.add_argument("--control", action="store_true", help="load settings and the default prompt (positive control)")
            sp.add_argument("--model", help="model for the check (default: check_model, else model)")
        if name == "watch":
            sp.add_argument("--tail", action="store_true", help="skip events already in the log")
        if name == "answer":
            sp.add_argument("qid", type=int)
        if name in ("answer", "say"):
            sp.add_argument("text")
        if name == "render":
            sp.add_argument("out", type=Path)
    a = ap.parse_args()
    run = a.run.resolve()
    if not (run / "panel.json").exists():
        sys.exit(f"{run} has no panel.json")
    if a.cmd == "check":
        cmd_check(run, a.control, a.model)
    elif a.cmd == "run":
        cmd_run(run)
    elif a.cmd == "watch":
        cmd_watch(run, a.tail)
    elif a.cmd == "pending":
        cmd_pending(run)
    elif a.cmd == "answer":
        cmd_answer(run, a.qid, a.text)
    elif a.cmd == "say":
        cmd_say(run, a.text)
    elif a.cmd == "status":
        cmd_status(run)
    elif a.cmd == "render":
        cmd_render(run, a.out)


if __name__ == "__main__":
    main()
