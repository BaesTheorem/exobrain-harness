#!/usr/bin/env python3
"""PreToolUse guard for sessions nobody is watching.

Every headless runner in this harness (launchd routines, the transcript and
Supernote watchers, the job scan, the ESPN chat watcher, the Zulip listener,
the Discord bot, the voice line) exports MIST_UNATTENDED=1 before it starts
`claude`. This hook reads that variable and, when it is set, refuses the
tool calls that would let a fooled or a weaker model change what MIST is or
reach past the task:

  - writing any instruction-bearing file: CLAUDE.md, anything under .claude/
    (hooks, skills, settings, scheduled tasks, memory), MCP configs, launchd
    plists, shell rc files, PATH directories, and source code in this repo;
  - reading a secret file (.env, .zuliprc, token and credential JSON, the
    user-level .claude.json);
  - shell commands with a persistence or exfiltration shape: pipe-to-shell,
    launchctl, crontab, Keychain access, sudo, defaults write, force pushes,
    remote changes, and any write verb or redirect whose target is a protected
    path (a protected path merely mentioned elsewhere in the command is not).

Attended sessions (the Console, a terminal) are untouched: the variable is
absent, the hook exits immediately, and Alex keeps bypassPermissions as he
chose. MIST_GUARD=off disables it for debugging a runner. MIST_GUARD_NOTIFY=off
keeps the denial and the log line but skips the banner; the test suite sets
it, because a fake HOME redirects the log but mist-notify still reaches the
real screen.

The point is that the model's judgment is not the last line. A routine can
be convinced of anything by a good enough message; this hook cannot.

Every denial is appended to ~/Library/Logs/exobrain/guard-unattended.log and
raised once per session as a clickable banner, because a denial in an
unattended run is exactly the event Alex wants to hear about.

INVARIANTS
  - Fail open on malformed input. A broken hook that blocks every tool would
    kill every routine; a logged parse failure is the lesser harm.
  - Never deny on the basis of the model's stated intent, only on the
    concrete tool input. Reasons are matched against paths and command text.
  - Anything the guard denies must be reachable from an interactive session,
    so the fix for a legitimate need is the runner or the rule, never a
    loophole in the pattern list.
  - The canary string __MIST_GUARD_CANARY__ is always denied under the guard.
    It is the zero-side-effect positive control for a live end-to-end test.
"""

from __future__ import annotations

import datetime
import json
import os
import re
import shlex
import subprocess
import sys
from pathlib import Path

HARNESS = Path(__file__).resolve().parent.parent.parent
HOME = Path.home()
LOG_DIR = HOME / "Library" / "Logs" / "exobrain"
LOG = LOG_DIR / "guard-unattended.log"
NOTIFIED_DIR = LOG_DIR / "guard-notified"
NOTIFY = HARNESS / "mist-voice" / "bin" / "mist-notify"

CANARY = "__MIST_GUARD_CANARY__"

WRITE_TOOLS = {"Write", "Edit", "MultiEdit", "NotebookEdit"}
READ_TOOLS = {"Read"}

# Paths an unattended session may never write. Matched against the absolute,
# ~-expanded path. Order does not matter; the first match names the reason.
PROTECTED_WRITE: list[tuple[str, str]] = [
    (r"/CLAUDE\.md$", "CLAUDE.md is the rule file"),
    (r"/mist-global\.md$", "mist-global.md is the rule file"),
    (r"/\.claude(/|$)", "the .claude directory holds hooks, skills, settings, scheduled tasks and memory"),
    (r"/\.claude\.json$", "user-level Claude config"),
    (r"/\.mcp\.json$", "MCP server config"),
    (r"/Library/LaunchAgents/", "launchd agents are persistence"),
    (r"/Library/LaunchDaemons/", "launchd daemons are persistence"),
    (r"\.plist$", "a plist is a launchd job or app config"),
    (r"/\.env(\.[^/]+)?$", "environment files hold secrets"),
    (r"/\.zuliprc$", "Zulip bot credentials"),
    (r"[^/]*token[^/]*\.json$", "token file"),
    (r"/credentials[^/]*\.json$", "credentials file"),
    (r"/\.(zshrc|zprofile|zshenv|bashrc|bash_profile|profile)$", "shell rc files are persistence"),
    (r"/\.ssh/", "SSH keys and config"),
    (r"^/etc/", "system config"),
    (r"^/Library/", "system-wide library"),
    (r"/\.local/bin/", "a PATH directory"),
    (r"^/opt/homebrew/bin/", "a PATH directory"),
    (r"^/usr/local/bin/", "a PATH directory"),
    (r"/Documents/mist-console/", "the Console runs every chat"),
    (r"/scheduled-tasks/", "routine prompts"),
    (r"/Applications/[^/]+\.app/", "an app bundle"),
]

# Source code inside the harness repo. Data files (json, md, txt, csv, jsonl,
# cache) are deliberately not here: routines write logs, state and notes.
CODE_EXT = re.compile(r"\.(sh|bash|zsh|py|js|mjs|cjs|ts|swift|rb|pl|php|lua|go|rs|c|h|m|scpt|applescript|command)$", re.IGNORECASE)

# Paths an unattended session may never read through the Read tool, and may
# not name in a shell command. Example templates are fine.
PROTECTED_READ: list[tuple[str, str]] = [
    (r"/\.env(\.(local|production|secret|private))?$", "environment file"),
    (r"/\.zuliprc$", "Zulip bot credentials"),
    (r"[^/]*token[^/]*\.json$", "token file"),
    (r"/credentials[^/]*\.json$", "credentials file"),
    (r"/\.claude\.json$", "user-level Claude config carries MCP secrets"),
    (r"/\.claude/channels/[^/]+/\.env$", "channel token"),
    (r"/\.ssh/", "SSH keys"),
    (r"/Library/Keychains/", "Keychain"),
]

# Shell commands with a persistence, escalation or exfiltration shape.
BASH_DENY: list[tuple[str, str]] = [
    (re.escape(CANARY), "guard canary"),
    # `curl | python3 -c '<parse>'` is an API read with the script inline in the
    # command; only a bare interpreter (or `python3 -`) executes the download.
    (r"\b(curl|wget)\b[^|\n]{0,200}\|\s*(sudo\s+)?(sh|bash|zsh|python3?|perl|ruby|node)\b(?!\s+-[cme]\b)", "pipe from the network into an interpreter"),
    (r"\bbase64\s+(-d|--decode)\b[^|\n]{0,80}\|\s*(sh|bash|zsh|python3?)\b", "decode into an interpreter"),
    (r"\beval\s+[\"']?\$\(", "eval of a command substitution"),
    (r"\bsudo\b", "privilege escalation"),
    (r"\blaunchctl\s+(bootstrap|bootout|load|unload|kickstart|enable|disable|submit)\b", "launchd is persistence"),
    (r"\bcrontab\b", "cron is persistence"),
    (r"\bsecurity\s+(find-|dump-|delete-|add-|export|import|set-)", "Keychain access"),
    (r"\bdefaults\s+write\b", "changes system preferences"),
    (r"\btccutil\b", "changes privacy grants"),
    (r"\bxattr\s+(-d|-c)\b", "strips quarantine"),
    (r"\bchmod\s+(\+x|[0-7]*[1357][0-7]{0,2}\b)", "makes something executable"),
    # Recursive delete of root, home, anything one level under home (the vault,
    # Documents, Library), any user directory, or a system directory. Deeper
    # paths are a routine's own scratch and stay allowed.
    (r"\brm\s+(-[a-zA-Z]*[rR][a-zA-Z]*\s+)+(?:(?:/|~|\$HOME)(?:/[^/\s]+)?|/Users(?:/[^/\s]+){0,2}|"
     r"/(?:Applications|Library|System|private|etc|opt|usr|var|bin)\b\S*)/?(?:\s|$)",
     "recursive delete of a home, vault, user or system directory"),
    (r"\bgit\s+push\b[^\n]*(\s-f\b|--force)", "force push"),
    (r"\bgit\s+remote\s+(add|set-url|remove)\b", "changes where code is pushed"),
    (r"\bgit\s+config\b[^\n]*(user\.|credential|url\.)", "rewrites git identity or credentials"),
    (r"\bssh-(keygen|add|copy-id)\b", "SSH key changes"),
    (r"\b(nc|ncat|netcat)\s+(-l|-e)\b", "listener or reverse shell"),
    (r"\bosascript\b[^\n]*administrator privileges", "elevated AppleScript"),
    (r"\b(pmset|systemsetup|networksetup|scutil)\b", "changes system state"),
    (r"\bopen\s+-a\s+[\"']?(Terminal|iTerm|Script Editor|System Settings|System Preferences)\b", "opens a control surface"),
    (r"\bkill(all)?\s+(-9\s+)?(-[0-9]+\s+)?(claude|MIST|launchd|loginwindow)\b", "kills the harness"),
    (r"\bclaude\b[^\n]*\s(-p|--print)(\s|$)", "spawning a second headless session escapes this guard's scope"),
]

# Verbs whose operands are written, moved, deleted or made executable. The
# write test pairs each verb with the operands it actually takes (and each
# redirect with its target) instead of asking "is there a write verb anywhere
# and a protected path anywhere", which read `python3 weather/get-weather.py
# 2>&1` as an overwrite of get-weather.py and blocked most routines.
WRITE_VERBS = {"tee", "cp", "mv", "rm", "ln", "chmod", "chown", "touch", "truncate",
               "install", "patch", "dd", "rsync", "unzip", "tar"}
SED_INPLACE = re.compile(r"^-[a-zA-Z]*i")
INTERPRETERS = {"python", "python3", "perl", "ruby", "node", "sh", "bash", "zsh"}
SHELLS = {"sh", "bash", "zsh"}
# The tokenizer splits shell operators into their own tokens, so `x.md;` is
# the path and a `;`, never one run-on operand that swallows the next command.
OPERATOR = re.compile(r"[;&|<>()]+")
REDIRECTS = {">", ">>", ">|", "&>", "&>>", ">&"}
# Segments that read a file's metadata, never its contents, may name a secret:
# `stat -f %Sm fitbit-mcp/.fitbit-token.json` is how the health routine checks
# token freshness. Not when piped on (`ls x | xargs cat`), redirected, or
# carrying a substitution.
METADATA_SEGMENT = re.compile(r"(?:^|(?<=[;&\n]))[ \t]*(?:stat|ls|test|\[\[?)[ \t][^;&|\n<>`$]*(?=[;&\n]|$)")
HEREDOC = re.compile(r"(?<!<)<<(?!<)-?\s*(['\"]?)(\w+)\1")
# A script body (python -c, a python heredoc) only counts as a write when it
# contains something that writes; a read-only script naming a protected path
# is how routines read tool results and session files.
SCRIPT_WRITES = re.compile(
    r"open\([^)]*['\"][wax]|['\"](?:w|a|x|r\+|wb|ab)['\"]\s*\)|write_text|write_bytes|json\.dump\(|"
    r"\bshutil\.|\bos\.(?:remove|unlink|rename|replace|symlink|chmod|system)|\.(?:unlink|rename|touch|mkdir)\(|"
    r"\bsubprocess\b|>{1,2}"
)

# Anything in a command that names a file: absolute, home-relative, dot-relative,
# a relative path with a slash, or a bare secret/rule filename. Relative forms
# resolve against the harness (the cwd of every unattended session), so
# `cat .env` and `echo x >> CLAUDE.md` are caught as well as their absolute twins.
PATH_TOKEN = re.compile(
    r"(?:~|\$HOME|/|\.{1,2}/|"
    r"(?<![\w/.@-])(?:CLAUDE\.md|\.env|\.zuliprc|\.claude(?:\.json|/)|\.mcp\.json|"
    r"[\w.-]*token[\w.-]*\.json|credentials[\w.-]*\.json|[\w.-]+/))"
    r"[^\s\"'`;|&<>)]*"
)

# String literals in a script body. Triple-quoted first so their inner quotes
# are not read as short literals.
STRING_LITERAL = re.compile(
    r"\"\"\"[\s\S]*?\"\"\"|'''[\s\S]*?'''|\"(?:[^\"\\\n]|\\.)*\"|'(?:[^'\\\n]|\\.)*'"
)
# A literal whose whole content is an absolute or home-relative path. These may
# contain spaces (this repo's own directory has one); relative paths may not.
ROOTED_PATH = re.compile(r"(?:~|\$HOME|\.{1,2})?/[^\n\"'`]*")


def _log(line: str) -> None:
    try:
        LOG_DIR.mkdir(parents=True, exist_ok=True)
        with LOG.open("a") as fh:
            fh.write(f"{datetime.datetime.now():%Y-%m-%d %H:%M:%S} {line}\n")
    except OSError:
        pass


def _expand(path: str, cwd: str | None = None) -> str:
    p = path.strip().strip("\"'")
    if p.startswith("~"):
        p = str(HOME) + p[1:]
    elif p.startswith("$HOME"):
        p = str(HOME) + p[len("$HOME"):]
    if not p.startswith("/"):
        p = os.path.join(cwd or str(HARNESS), p)
    return os.path.normpath(p)


def _matches(path: str, rules: list[tuple[str, str]]) -> str | None:
    for rx, why in rules:
        if re.search(rx, path):
            return why
    return None


def check_write_path(raw: str, cwd: str | None = None) -> str | None:
    """Reason this path may not be written unattended, or None.

    Relative paths resolve against `cwd`: the session's working directory, as
    moved by any `cd` earlier in the command. Resolving them against the
    harness regardless turned `cd /tmp && cat > gen.py` into a write of
    harness source (2026-09-24 and 09-25).
    """
    path = _expand(raw, cwd)
    why = _matches(path, PROTECTED_WRITE)
    if why:
        return why
    if path.startswith(str(HARNESS) + "/") and CODE_EXT.search(path):
        return "source code in the harness"
    if path.startswith(str(HARNESS) + "/") and "/bin/" in path:
        return "an executable in a bin directory"
    return None


def check_read_path(raw: str) -> str | None:
    path = _expand(raw)
    if path.endswith(".example") or path.endswith(".sample"):
        return None
    return _matches(path, PROTECTED_READ)


def _unquote(tok: str) -> str:
    """Shell-unquote one token. A quoted token made only of operator characters
    (`';'`) keeps its quotes, so it is never mistaken for the operator."""
    try:
        out = "".join(shlex.split(tok, posix=True))
    except ValueError:
        out = tok.replace("\\", "").strip("\"'")
    return tok if OPERATOR.fullmatch(out) and not OPERATOR.fullmatch(tok) else out


def _tokens(line: str) -> list[str]:
    """Words and operators. Operators are bare runs of `;&|<>()`."""
    try:
        lex = shlex.shlex(line, posix=False, punctuation_chars=True)
        lex.whitespace_split = True
        raw = list(lex)
    except ValueError:
        # Unbalanced quotes (an apostrophe in prose): fall back to a plain split
        # that still keeps quoted runs together where they are balanced.
        raw = re.findall(r"\"[^\"]*\"|'[^']*'|[;&|<>()]+|[^\s\"';&|<>()]+", line)
    return [t if OPERATOR.fullmatch(t) else _unquote(t) for t in raw]


def _is_op(tok: str) -> bool:
    return bool(OPERATOR.fullmatch(tok))


def _split_heredocs(command: str) -> tuple[list[tuple[str, str | None]], list[str]]:
    """Command lines (each with the interpreter script body it opens, if any),
    and expanding data bodies.

    A heredoc fed to cat or tee is data: prose in a note can contain `>`,
    a path, or the words `curl x | sh` without running anything. With a
    quoted marker (<<'EOF') the body is inert and dropped. With a bare marker
    the shell expands `$(...)` inside it, so that body is still scanned as
    command text.
    """
    lines = command.split("\n")
    cmd_lines: list[tuple[str, str | None]] = []
    expanding: list[str] = []
    i = 0
    while i < len(lines):
        line = lines[i]
        m = HEREDOC.search(line)
        if not m:
            cmd_lines.append((line, None))
            i += 1
            continue
        marker = m.group(2)
        head = _tokens(line[:m.start()])
        body: list[str] = []
        i += 1
        while i < len(lines) and lines[i].strip() != marker:
            body.append(lines[i])
            i += 1
        i += 1
        if any(Path(t).name in INTERPRETERS for t in head):
            cmd_lines.append((line, "\n".join(body)))
            continue
        cmd_lines.append((line, None))
        if not m.group(1):
            expanding.append("\n".join(body))
    return cmd_lines, expanding


def _script_paths(script: str) -> list[str]:
    """Paths a script body could open: string literals that are wholly a path,
    plus path tokens in the code outside any literal.

    A path mentioned inside a sentence ("ran fantasy/bin/espn check") is prose
    headed for a note, not a file the script touches. Counting it denied every
    routine that logged which tool it ran (2026-09-22 and 09-23). A path built
    by concatenation slips past this, as one held in a variable already did.
    """
    paths: list[str] = []
    for m in STRING_LITERAL.finditer(script):
        body = m.group(0)
        body = body[3:-3] if body[:3] in ('"""', "'''") else body[1:-1]
        if ROOTED_PATH.fullmatch(body) or PATH_TOKEN.fullmatch(body):
            paths.append(body)
    code = STRING_LITERAL.sub('""', script)
    paths.extend(m.group(0) for m in PATH_TOKEN.finditer(code))
    return paths


def _script_reason(script: str, cwd: str | None = None) -> str | None:
    """A script body that writes and names a protected path."""
    if not SCRIPT_WRITES.search(script):
        return None
    for path in _script_paths(script):
        why = check_write_path(path, cwd)
        if why:
            return why
    return None


def _operands(toks: list[str], start: int) -> list[str]:
    """Operand tokens from `start` to the next chain operator or heredoc.

    Each token is a candidate on its own, and so is every run of tokens
    joined by a space, so an unquoted path with a space in it (this repo's
    own directory has one) still names the file it would hit.
    """
    ops: list[str] = []
    j = start
    while j < len(toks) and not _is_op(toks[j]):
        if not toks[j].startswith("-"):
            ops.append(toks[j])
        j += 1
    return ops + [" ".join(ops[k:]) for k in range(len(ops)) if len(ops) - k > 1]


def _line_reason(line: str, cwd: str) -> tuple[str | None, str]:
    """Reason this command line writes a protected path, and the working
    directory after it runs (`cd` moves it; a subshell's `cd` does not leak)."""
    toks = _tokens(line)
    targets: list[tuple[str, str]] = []
    stack: list[str] = []
    seg_start = True
    i = 0
    while i < len(toks):
        tok = toks[i]
        if _is_op(tok):
            if tok in REDIRECTS:
                nxt = toks[i + 1] if i + 1 < len(toks) else ""
                if not (tok == ">&" and (nxt.isdigit() or nxt == "-")):  # `2>&1` duplicates a descriptor
                    targets.extend((t, cwd) for t in _operands(toks, i + 1))
                i += 2
                continue
            for ch in tok:
                if ch == "(":
                    stack.append(cwd)
                elif ch == ")" and stack:
                    cwd = stack.pop()
            seg_start = any(c in tok for c in ";&|()")
            i += 1
            continue
        name = Path(tok).name
        if seg_start and tok in ("cd", "pushd"):
            args = [t for t in _operands(toks, i + 1)[:1] if t != "-"]
            cwd = _expand(args[0], cwd) if args else str(HOME)
            seg_start = False
            i += 1
            continue
        seg_start = False
        if name in INTERPRETERS and i + 2 < len(toks) and toks[i + 1] in ("-c", "-e"):
            script = toks[i + 2]
            why = check_bash(script, cwd) if name in SHELLS else _script_reason(script, cwd)
            if why:
                return why, cwd
            i += 3
            continue
        if name in WRITE_VERBS or (name == "sed" and i + 1 < len(toks) and SED_INPLACE.match(toks[i + 1])):
            targets.extend((t, cwd) for t in _operands(toks, i + 1))
        i += 1
    for t, at in targets:
        why = check_write_path(t, at)
        if why:
            return why, cwd
    return None, cwd


def check_bash(command: str, cwd: str | None = None) -> str | None:
    """Reason this shell command may not run unattended, or None."""
    cwd = cwd or str(HARNESS)
    cmd_lines, expanding = _split_heredocs(command)
    text = "\n".join([line for line, _ in cmd_lines] + expanding)
    for rx, why in BASH_DENY:
        if re.search(rx, text, re.IGNORECASE):
            return why
    # Reading a secret by name is not allowed either, whatever the verb.
    scripts = [body for _, body in cmd_lines if body is not None]
    for m in PATH_TOKEN.finditer("\n".join([METADATA_SEGMENT.sub("", text), *scripts])):
        why = check_read_path(m.group(0))
        if why:
            return f"names a secret ({why})"
    for line, body in cmd_lines:
        why, cwd = _line_reason(line, cwd)
        if why:
            return f"write-shaped command naming a protected path ({why})"
        if body is not None:
            why = check_bash(body, cwd) or _script_reason(body, cwd)
            if why:
                return f"script body that writes a protected path ({why})"
    return None


def decide(tool_name: str, tool_input: dict, cwd: str | None = None) -> str | None:
    """Denial reason for this call, or None to allow. `cwd` is the session's
    working directory from the hook payload; relative paths resolve against it."""
    if tool_name in WRITE_TOOLS:
        path = tool_input.get("file_path") or tool_input.get("notebook_path") or ""
        why = check_write_path(path)
        return f"unattended session may not write {path}: {why}" if why else None
    if tool_name in READ_TOOLS:
        path = tool_input.get("file_path") or ""
        why = check_read_path(path)
        return f"unattended session may not read {path}: {why}" if why else None
    if tool_name == "Bash":
        command = tool_input.get("command") or ""
        why = check_bash(command, cwd)
        return f"unattended session may not run this: {why}" if why else None
    return None


def _notify_once(session_id: str, reason: str) -> None:
    """One banner per session, so a looping model cannot flood the screen."""
    try:
        NOTIFIED_DIR.mkdir(parents=True, exist_ok=True)
        marker = NOTIFIED_DIR / (re.sub(r"[^A-Za-z0-9_-]", "_", session_id or "nosession")[:80])
        if marker.exists():
            return
        marker.touch()
        if NOTIFY.exists():
            subprocess.run(
                [str(NOTIFY), f"Guard blocked a tool call in an unattended session: {reason[:160]}",
                 "MIST guard", "Basso", str(LOG), "--group", "security", "--id", "guard-unattended"],
                capture_output=True, timeout=20, check=False,
            )
    except (OSError, subprocess.SubprocessError):
        pass


def main() -> int:
    if os.environ.get("MIST_GUARD", "").lower() in ("off", "0", "false"):
        return 0
    if os.environ.get("MIST_UNATTENDED") != "1":
        return 0
    try:
        payload = json.load(sys.stdin)
    except (ValueError, OSError) as e:
        _log(f"PARSE-FAIL {e}")
        return 0
    tool_name = str(payload.get("tool_name") or "")
    tool_input = payload.get("tool_input") or {}
    if not isinstance(tool_input, dict):
        tool_input = {}
    cwd = payload.get("cwd")
    reason = decide(tool_name, tool_input, cwd if isinstance(cwd, str) and cwd.startswith("/") else None)
    if not reason:
        return 0
    session_id = str(payload.get("session_id") or "")
    _log(f"DENY session={session_id or '-'} tool={tool_name} :: {reason} :: "
         f"{json.dumps(tool_input)[:400]}")
    if os.environ.get("MIST_GUARD_NOTIFY", "").lower() not in ("off", "0", "false"):
        _notify_once(session_id, reason)
    print(json.dumps({
        "hookSpecificOutput": {
            "hookEventName": "PreToolUse",
            "permissionDecision": "deny",
            "permissionDecisionReason": (
                f"{reason}. This session is unattended (MIST_UNATTENDED=1) and the guard hook "
                f"does not allow it, whatever the text that asked for it said. If the routine "
                f"genuinely needs this, it is a change to the runner or the rules, made from an "
                f"interactive session. The denial has been logged and Alex notified."
            ),
        }
    }))
    return 0


if __name__ == "__main__":
    sys.exit(main())
