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
  - shell commands with a persistence or exfiltration shape: pipe-to-shell
    (and network output fed to a script that executes it), launchctl, crontab,
    Keychain access, sudo, defaults write, any git push (bin/harness-commit is
    the sanctioned path), remote changes, AppleScript that runs a shell or
    types keystrokes, and any write verb, in-place editor (sed/perl/ruby -i)
    or redirect whose target is a protected path (a protected path merely
    mentioned elsewhere in the command is not).

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
  - Fail closed on a crash in the guard's own logic. An exception while
    judging a well-formed call denies that call, logs the traceback, and
    raises one banner per session. Exiting non-zero without a decision would
    let Claude Code run the call, which turns the guard off with no signal.
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
import traceback
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

# A session's own tool-result dumps under ~/.claude/projects are its scratch:
# routines cd there to parse an MCP result and delete it after. The memory
# directory and the transcripts beside them stay protected.
SESSION_SCRATCH = re.compile(r"/\.claude/projects/[^/]+/[0-9a-f-]{36}/tool-results/.+$")

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

# The start of a command: after a chain operator, a subshell, a substitution,
# or a word that runs its argument (`xargs`, `env`, `eval`, `do shell script "`).
# An escaped `\|` is regex alternation inside a grep pattern, not a pipe.
CMD_START = (r"(?:^|[;&(`\n]|(?<!\\)\||\$\(|\b(?:xargs|env|exec|command|nohup|time|eval|then|do|else|script)\s+[\"']?)"
             r"\s*(?:\S*/)?")

# Shell commands with a persistence, escalation or exfiltration shape.
BASH_DENY: list[tuple[str, str]] = [
    (re.escape(CANARY), "guard canary"),
    # `curl | python3 -c '<parse>'` is an API read with the script inline in the
    # command; only a bare interpreter (or `python3 -`) executes the download.
    (r"\b(curl|wget)\b[^|\n]{0,200}\|\s*(sudo\s+)?(sh|bash|zsh|python3?|perl|ruby|node)\b(?!\s+-[cme]\b)", "pipe from the network into an interpreter"),
    (r"\bbase64\s+(-d|--decode)\b[^|\n]{0,80}\|\s*(sh|bash|zsh|python3?)\b", "decode into an interpreter"),
    (r"\beval\s+[\"']?\$\(", "eval of a command substitution"),
    # Code fetched by a substitution and handed to an interpreter as its
    # program. Downloaded data passed as an ordinary argument is not code.
    (r"\b(?:python3?|node|ruby|perl|sh|bash|zsh)\s+(?:-\S+\s+)*?-[ce]\s+[\"']?(?:\$\(|`)\s*(?:curl|wget)\b",
     "runs code fetched by a command substitution"),
    (r"(?:\b(?:python3?|node|ruby|perl|sh|bash|zsh|source)|(?:^|(?<=[\s;&|(]))\.)\s+[\"']?<\(\s*(?:curl|wget)\b",
     "runs code fetched by a process substitution"),
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
    # Only as a command, and not the read-only forms: `pmset -g log` is how a
    # routine checks whether the laptop slept, and `grep "pmset\|caffeinate"`
    # merely searches for the word (both denied 2026-09-27).
    (CMD_START + r"(?:pmset(?!\s+-g\b)|systemsetup(?!\s+-(?:get|list|print)\w*)|"
     r"networksetup(?!\s+-(?:list|get|print|show)\w*)|scutil(?!\s+(?:--get|--dns|--proxy|--nwi|-r)\b))\b",
     "changes system state"),
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
# Verbs that read every operand but the destination. `mv` is not here: it
# removes its source.
DEST_ONLY = {"cp", "ln", "install", "rsync"}
SED_INPLACE = re.compile(r"^-[a-zA-Z]*i")
# perl and ruby switches that can be clustered ahead of -i (`-pi`, `-0pi`,
# `-i.bak`). Not a bare letter class: `-MList::Util` must not read as -i.
PERL_INPLACE = re.compile(r"^-(?:[aclnpswTtWX]|0[0-7]*)*i")
INPLACE_EDITORS = {"sed", "perl", "ruby"}
# Flags whose next word is the editing program, not a file it edits.
INPLACE_SCRIPT_FLAGS = {"sed": {"-e", "--expression", "-f", "--file"}, "perl": {"-e", "-E"}, "ruby": {"-e"}}
INTERPRETERS = {"python", "python3", "perl", "ruby", "node", "sh", "bash", "zsh"}
SHELLS = {"sh", "bash", "zsh"}
NET_FETCHERS = {"curl", "wget"}
# Words that run the command after them, so that command is still in command
# position (`curl x | env python3 -c ...`).
RUNNERS = {"env", "sudo", "exec", "command", "nohup", "time", "nice", "xargs"}
# Code that runs text as code. Fed from curl, any of these executes the
# download; `json.load(sys.stdin)` and `re.compile` do not.
EXEC_CODE = re.compile(r"(?<![\w.$])(?:exec|eval|compile|execfile|Function)\s*\(|\brunpy\b|\bvm\.run")
EXEC_ANY = re.compile(
    EXEC_CODE.pattern
    + r"|\bos\.(?:system|popen|exec\w*|spawn\w*)\b|\bsubprocess\b|\bchild_process\b|\bpty\.spawn\b|\b__import__\b"
    # perl and ruby: `eval $x`, `system "..."`, `exec(...)`.
    + r"|(?<![\w.$'\"])(?:eval|system|exec)\s*[(\"'$`{]"
)
# A script that fetches over the network by itself.
NET_IN_SCRIPT = re.compile(
    r"\burllib\b|\burlopen\b|\brequests\.\w+\(|\bhttpx\b|\bhttp\.client\b|\bsocket\b|\bfetch\(|"
    r"https?://|\bLWP::|\bNet::HTTP\b|\bopen-uri\b"
)
OSASCRIPT = re.compile(r"\bosascript\b")
OSASCRIPT_DENY: list[tuple[str, str]] = [
    (r"\bdo\s+shell\s+script\b", "AppleScript that runs a shell command"),
    (r"\bSystem Events\b[\s\S]*\b(?:keystroke|key\s+code)\b", "AppleScript that types keystrokes through System Events"),
]
# Any push, whatever the flags. The sanctioned path is bin/harness-commit,
# which scans before it pushes; a bare push from a routine skips that scan.
GIT_PUSH = re.compile(CMD_START + r"git\s+(?:-[cC]\s+(?:\"[^\"]*\"|'[^']*'|\S+)\s+|--[\w-]+(?:=\S+)?\s+)*push\b",
                      re.IGNORECASE)
HARNESS_COMMIT = HARNESS / "bin" / "harness-commit"
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
    # A redirect only inside a literal (perl `open(F, ">x")`): a bare `>` in a
    # script is a comparison or a regex, never a write.
    r"\bsubprocess\b|['\"]\+?>{1,2}"
)

# A literal argument list handed to subprocess.
SUBPROCESS_ARGV = re.compile(r"\bsubprocess\.\w+\(\s*\[([^\]]*)\]")

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
    if SESSION_SCRATCH.search(path):
        return None
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


def _quote_open(text: str) -> bool:
    """Whether `text` ends inside an unclosed shell quote. A `#` comment
    (`# don't`) is skipped so its apostrophe does not open one."""
    quote = ""
    i = 0
    while i < len(text):
        ch = text[i]
        if quote == "'":
            quote = "" if ch == "'" else quote
        elif ch == "\\":
            i += 1
        elif quote == '"':
            quote = "" if ch == '"' else quote
        elif ch in "'\"":
            quote = ch
        elif ch == "#" and (i == 0 or text[i - 1] in " \t\n;&|("):
            nl = text.find("\n", i)
            i = len(text) if nl < 0 else nl
            continue
        i += 1
    return bool(quote)


def _split_heredocs(command: str) -> tuple[list[tuple[str, str | None, bool]], list[str]]:
    """Command lines (each with the interpreter script body it opens, if any,
    and whether that interpreter is a shell), and expanding data bodies.

    A command line runs to the next newline outside quotes, so a multi-line
    `python3 -c "..."` stays one line and its code is never read as shell:
    `re.sub(r'<[^>]+>', ...)` on a line of its own was a redirect into the
    working directory (2026-09-26). A quote that never closes falls back to
    one physical line.

    A heredoc fed to cat or tee is data: prose in a note can contain `>`,
    a path, or the words `curl x | sh` without running anything. With a
    quoted marker (<<'EOF') the body is inert and dropped. With a bare marker
    the shell expands `$(...)` inside it, so that body is still scanned as
    command text.
    """
    lines = command.split("\n")
    cmd_lines: list[tuple[str, str | None, bool]] = []
    expanding: list[str] = []
    i = 0
    while i < len(lines):
        line = lines[i]
        j = i
        while _quote_open(line) and j + 1 < len(lines):
            j += 1
            line += "\n" + lines[j]
        if _quote_open(line):
            line, j = lines[i], i
        i = j
        m = HEREDOC.search(line)
        if not m:
            cmd_lines.append((line, None, False))
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
        interp = [Path(t).name for t in head if Path(t).name in INTERPRETERS or Path(t).name == "osascript"]
        if interp:
            cmd_lines.append((line, "\n".join(body), interp[0] in SHELLS))
            if interp[0] == "osascript" and not m.group(1):
                expanding.append("\n".join(body))
            continue
        cmd_lines.append((line, None, False))
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
    """A script body that writes and names a protected path.

    A literal argv handed to subprocess is judged as the command line it is,
    so running `fantasy/bin/roster-news` from a script that also writes a note
    is not a write to the tool (2026-09-28), while `["cp", x, "fantasy/bin/y"]`
    still is.
    """
    if not SCRIPT_WRITES.search(script):
        return None
    for m in SUBPROCESS_ARGV.finditer(script):
        argv = [lit[1:-1] for lit in STRING_LITERAL.findall(m.group(1)) if lit[:3] not in ('"""', "'''")]
        # The whole shell check, not only the write test: `["git", "push"]`
        # is the same push as the command line.
        why = check_bash(shlex.join(argv), cwd or str(HARNESS)) if argv else None
        if why:
            return why
    script = SUBPROCESS_ARGV.sub("[]", script)
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
    # A join is only a candidate while no later word starts a new rooted path:
    # `cp /a/src /tmp/dst` is two paths, never one called "/a/src /tmp/dst".
    return ops + [" ".join(ops[k:]) for k in range(len(ops)) if len(ops) - k > 1
                  and not any(w.startswith(("/", "~", "$HOME")) for w in ops[k + 1:])]


def _dest_operands(toks: list[str], start: int) -> list[str]:
    """Write candidates for a copy-shaped verb: the destination (the `-t`
    directory if given, else the last operand, with the space-joined runs
    ending in it), and each source's name inside it, since `cp x fantasy/bin`
    writes fantasy/bin/x. Copying a tool result out of ~/.claude to /tmp was
    denied as a write to ~/.claude (2026-09-28)."""
    words: list[str] = []
    j = start
    while j < len(toks) and not _is_op(toks[j]):
        words.append(toks[j])
        j += 1
    if "--remove-source-files" in words:
        return _operands(toks, start)
    plain = [w for w in words if not w.startswith("-")]
    dest = None
    for k, w in enumerate(words):
        if w in ("-t", "--target-directory") and k + 1 < len(words):
            dest = words[k + 1]
            plain.remove(dest)
        elif w.startswith("--target-directory="):
            dest = w.split("=", 1)[1]
    if dest is None:
        if not plain:
            return []
        if len(plain) == 1:  # `ln -s /x/y` makes ./y
            return [os.path.basename(plain[0].rstrip("/"))]
        dest = plain.pop()
        out = [c for c in _operands(toks, start) if c == dest or (" " in c and c.endswith(dest))]
    else:
        out = [dest]
    return out + [os.path.join(d, os.path.basename(src.rstrip("/"))) for d in out for src in plain]


def _inplace_operands(name: str, toks: list[str], start: int) -> list[str] | None:
    """Files an in-place editor (`sed -i`, `perl -pi`, `ruby -i`) rewrites, or
    None when this invocation does not edit in place. The flag may sit
    anywhere in the segment (`sed -e 's/a/b/' -i f`), and the program after
    -e is not a file."""
    words: list[str] = []
    j = start
    while j < len(toks) and not _is_op(toks[j]):
        words.append(toks[j])
        j += 1
    flag = SED_INPLACE if name == "sed" else PERL_INPLACE
    if not any(flag.match(w) or w.startswith("--in-place") for w in words):
        return None
    script_flags = INPLACE_SCRIPT_FLAGS[name]
    kept: list[str] = []
    skip = False
    for w in words:
        if skip:
            skip = False
        elif w in script_flags:
            skip = True
        else:
            kept.append(w)
    return _operands(kept, 0)


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
        if name in INPLACE_EDITORS:
            inplace = _inplace_operands(name, toks, i + 1)
            if inplace is not None:
                targets.extend((t, cwd) for t in inplace)
        if name in INTERPRETERS and i + 2 < len(toks) and toks[i + 1] in ("-c", "-e"):
            script = toks[i + 2]
            why = check_bash(script, cwd) if name in SHELLS else _script_reason(script, cwd)
            if why:
                return why, cwd
            i += 3
            continue
        if name in DEST_ONLY:
            targets.extend((t, cwd) for t in _dest_operands(toks, i + 1))
        elif name in WRITE_VERBS:
            targets.extend((t, cwd) for t in _operands(toks, i + 1))
        i += 1
    for t, at in targets:
        why = check_write_path(t, at)
        if why:
            return why, cwd
    return None, cwd


def _pipe_reason(line: str) -> str | None:
    """Network output that ends up executed, judged per pipeline.

    `curl x | python3 -c "import json,sys; print(json.load(sys.stdin))"` is an
    API read and stays allowed (2026-09-21). The same pipe into a shell in any
    form, or into an inline script that execs, evals or spawns, runs the
    download. So does an inline script that fetches and execs by itself.
    """
    toks = _tokens(line)
    net_pipe = seg_net = False
    seg_start = True
    prev = ""
    i = 0
    while i < len(toks):
        tok = toks[i]
        if _is_op(tok):
            if tok in REDIRECTS:
                i += 2
                continue
            # `|` carries the pipeline on; `;`, `&&`, `||` and newlines end it.
            net_pipe = (net_pipe or seg_net) if ("|" in tok and "||" not in tok) else False
            seg_net = False
            seg_start = True
            prev = ""
            i += 1
            continue
        name = Path(tok).name
        if seg_start and re.match(r"^\w+=", tok):  # `FOO=1 python3 ...`
            i += 1
            continue
        at_cmd = seg_start or prev in RUNNERS
        seg_start = False
        prev = name
        if name in NET_FETCHERS:
            seg_net = True
        if at_cmd and name in INTERPRETERS:
            if net_pipe and name in SHELLS:
                return "network output piped into a shell"
            if i + 2 < len(toks) and toks[i + 1] in ("-c", "-e"):
                script = toks[i + 2]
                if net_pipe and EXEC_ANY.search(script):
                    return "network output piped into an inline script that executes it"
                if EXEC_CODE.search(script) and NET_IN_SCRIPT.search(script):
                    return "inline script that fetches code over the network and executes it"
        i += 1
    return None


def _net_exec_reason(script: str) -> str | None:
    """A script body (heredoc) that fetches code over the network and runs it."""
    if EXEC_CODE.search(script) and NET_IN_SCRIPT.search(script):
        return "script body that fetches code over the network and executes it"
    return None


def _osascript_reason(text: str) -> str | None:
    for rx, why in OSASCRIPT_DENY:
        if re.search(rx, text, re.IGNORECASE):
            return why
    return None


def _is_harness_commit(command: str, cwd: str) -> bool:
    """One plain invocation of bin/harness-commit: no chain, no substitution,
    so its commit message may mention `git push` without being one."""
    if "\n" in command.strip() or "$(" in command or "`" in command:
        return False
    toks = _tokens(command)
    if not toks or any(_is_op(t) for t in toks):
        return False
    return _expand(toks[0], cwd) == str(HARNESS_COMMIT)


def _deny_pattern(text: str) -> str | None:
    for rx, why in BASH_DENY:
        if re.search(rx, text, re.IGNORECASE):
            return why
    return None


def check_bash(command: str, cwd: str | None = None) -> str | None:
    """Reason this shell command may not run unattended, or None."""
    cwd = cwd or str(HARNESS)
    cmd_lines, expanding = _split_heredocs(command)
    text = "\n".join([line for line, _, _ in cmd_lines] + expanding)
    why = _deny_pattern(text)
    if why:
        return why
    if GIT_PUSH.search(text) and not _is_harness_commit(command, cwd):
        return "git push from an unattended session (bin/harness-commit is the sanctioned path)"
    # Reading a secret by name is not allowed either, whatever the verb.
    scripts = [body for _, body, _ in cmd_lines if body is not None]
    for m in PATH_TOKEN.finditer("\n".join([METADATA_SEGMENT.sub("", text), *scripts])):
        why = check_read_path(m.group(0))
        if why:
            return f"names a secret ({why})"
    for line, body, shell in cmd_lines:
        why = _pipe_reason(line)
        if why:
            return why
        applescript = bool(OSASCRIPT.search(line))
        if applescript:
            why = _osascript_reason(line + "\n" + (body or ""))
            if why:
                return why
        why, cwd = _line_reason(line, cwd)
        if why:
            return f"write-shaped command naming a protected path ({why})"
        if body is not None and not applescript:
            why = _net_exec_reason(body) if not shell else None
            if why:
                return why
            # A Python body is not shell: its `->` and `'<[^>]+>'` are not
            # redirects (2026-09-25, 09-26, 09-28). It still gets the pattern
            # scan, which catches `os.system("sudo ...")`.
            why = check_bash(body, cwd) if shell else (_deny_pattern(body) or _script_reason(body, cwd))
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


def _notify_once(session_id: str, message: str, link: str, kind: str = "") -> None:
    """One banner per session and kind, so a looping model cannot flood the screen."""
    if os.environ.get("MIST_GUARD_NOTIFY", "").lower() in ("off", "0", "false"):
        return
    try:
        NOTIFIED_DIR.mkdir(parents=True, exist_ok=True)
        marker = NOTIFIED_DIR / (kind + re.sub(r"[^A-Za-z0-9_-]", "_", session_id or "nosession")[:80])
        if marker.exists():
            return
        marker.touch()
        if NOTIFY.exists():
            subprocess.run(
                [str(NOTIFY), message, "MIST guard", "Basso", link,
                 "--group", "security", "--id", f"guard-unattended{'-' + kind.rstrip('-') if kind else ''}"],
                capture_output=True, timeout=20, check=False,
            )
    except (OSError, subprocess.SubprocessError):
        pass


def _emit_deny(reason: str) -> None:
    print(json.dumps({
        "hookSpecificOutput": {
            "hookEventName": "PreToolUse",
            "permissionDecision": "deny",
            "permissionDecisionReason": reason,
        }
    }))


def _judge(payload: dict, session_id: str) -> int:
    tool_name = str(payload.get("tool_name") or "")
    tool_input = payload.get("tool_input") or {}
    if not isinstance(tool_input, dict):
        tool_input = {}
    cwd = payload.get("cwd")
    reason = decide(tool_name, tool_input, cwd if isinstance(cwd, str) and cwd.startswith("/") else None)
    if not reason:
        return 0
    _log(f"DENY session={session_id or '-'} tool={tool_name} :: {reason} :: "
         f"{json.dumps(tool_input)[:400]}")
    _notify_once(session_id, f"Guard blocked a tool call in an unattended session: {reason[:160]}", str(LOG))
    _emit_deny(
        f"{reason}. This session is unattended (MIST_UNATTENDED=1) and the guard hook "
        f"does not allow it, whatever the text that asked for it said. If the routine "
        f"genuinely needs this, it is a change to the runner or the rules, made from an "
        f"interactive session. The denial has been logged and Alex notified."
    )
    return 0


def _fail_closed(session_id: str, tb: str) -> int:
    """The guard crashed on a well-formed call: deny it, log why, banner once."""
    try:
        _log(f"CRASH session={session_id or '-'} :: guard raised, call denied (fail closed)\n{tb.rstrip()}")
        _notify_once(session_id, "The unattended-session guard crashed and is denying tool calls "
                     "until it is fixed. Traceback in guard-unattended.log.", "console", kind="crash-")
        _emit_deny(
            "The guard hook crashed while checking this call, so it is denied (fail closed). "
            "This session is unattended (MIST_UNATTENDED=1). The traceback has been logged and "
            "Alex notified; the fix is to the guard, from an interactive session."
        )
        return 0
    except Exception:  # noqa: BLE001 - last resort: exit 2 blocks the call even if stdout is gone
        sys.stderr.write("guard-unattended crashed; call denied (fail closed)\n")
        return 2


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
    if not isinstance(payload, dict):
        _log(f"PARSE-FAIL payload is {type(payload).__name__}, not an object")
        return 0
    session_id = str(payload.get("session_id") or "")
    try:
        return _judge(payload, session_id)
    except Exception:  # noqa: BLE001 - any crash must deny, not switch the guard off
        return _fail_closed(session_id, traceback.format_exc())


if __name__ == "__main__":
    sys.exit(main())
