#!/usr/bin/env python3
"""Tripwire for instruction-shaped text in files that get loaded as context.

Session memories, daily digests, the vault snapshot, People notes, Job
Listings with an archived JD, and CLAUDE.md pulled back from iCloud are all
read by a model that trusts them more than a chat message. Each of them was
written, at one remove, from something a third party said. This scanner is
the deterministic check that runs before such a file is loaded, committed,
or installed as instructions.

It is a tripwire, not a wall. A hit means "a human or the loading session
should look at this line", never "this file is malicious". The signatures
are deliberately specific, because a scanner that fires on every session
memory gets ignored within a week.

    scan_injection.py PATH...            scan files; exit 1 on any hit
    scan_injection.py --stdin            scan stdin
    scan_injection.py --added-lines      stdin is a unified diff; scan '+' lines only
    scan_injection.py --count PATH       print just the hit count for one file
    scan_injection.py --json PATH...     machine-readable hits

Exit status: 0 clean, 1 hits, 2 usage or unreadable input.

INVARIANTS
  - Every signature has a name and a one-line reason (SIGNATURES). A hit is
    reported with its name so the reader knows what fired without opening
    this file.
  - The scanner never modifies a file. Quarantine or annotation is the
    caller's decision.
  - Binary files and files over MAX_BYTES are skipped and reported as
    skipped, never silently passed.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from dataclasses import dataclass
from pathlib import Path

MAX_BYTES = 5 * 1024 * 1024

# name -> (regex, why it is here). Compiled once below.
SIGNATURES: dict[str, tuple[str, str]] = {
    "ignore_previous": (
        r"\b(ignore|disregard|forget|override)\b[^.\n]{0,40}\b(previous|prior|above|earlier|all|"
        r"any|existing)\b[^.\n]{0,25}\b(instructions?|rules?|prompts?|guidelines?|directives?|"
        r"constraints?|guardrails?)\b",
        "the canonical phrasing of a prompt-override attempt",
    ),
    "new_instructions": (
        r"\byour (new|real|actual|updated|true|revised) (system )?(instructions?|rules?|prompt|"
        r"directives?|orders?)\b",
        "asserts a replacement rule set",
    ),
    "fake_role_tag": (
        r"(?<![/`\w])</?\s*(system|assistant|developer|instructions?|tool_result|function_results?)\s*>|"
        r"\[\s*/?\s*(SYSTEM|INST)\s*\]|<<\s*SYS\s*>>|<\|(im_start|system|user|assistant)\|>|"
        r"^\s*#{1,4}\s*system\s*(prompt|message)?\s*$",
        "markup that mimics a chat template's role boundary",
    ),
    "role_line": (
        r"^\s*(system|developer)\s*:\s*\S",
        "a line that opens like a system turn",
    ),
    "role_override": (
        r"\byou are now (a|an|the|my|no longer|free|unrestricted|in \w+ mode|DAN)\b|"
        r"\bfrom now on,? you (are|will|must|should)\b|"
        r"\bact as (the |an? )?(system|developer|admin|root|operator)\b|"
        r"\bpretend (you are|to be|that you)\b[^.\n]{0,40}\b(alex|system|admin|owner|unrestricted)\b|"
        r"\benter (developer|debug|god|admin|unrestricted) mode\b|\bjailbreak\b|\bDAN mode\b",
        "tries to reassign who the model is",
    ),
    "impersonation": (
        r"\b(urgent|official|direct|secret|special|priority)\s+(message|instruction|order|"
        r"request|directive)s?\s+from\s+(alex|the (owner|admin|administrator|system|developer)|"
        r"your (owner|creator|human|operator))\b|"
        r"\b(message|instruction|order|directive)s? from (the )?(system|administrator|"
        r"developer|operator)\s*:|"
        r"\b(this is|i am|i'm) (alex|your (owner|creator|admin))\b[^.\n]{0,30}"
        r"\b(you must|you need to|now do|please (run|send|give|show|change))\b",
        "claims to speak as Alex or the system from a channel that is not his",
    ),
    "secrecy": (
        r"\b(do not|don't|never)\s+(tell|inform|notify|alert|mention (this|it|that) to)\s+"
        r"(alex|the (user|owner|human|operator)|your (owner|user|human|operator))\b|"
        r"\bwithout (telling|informing|alerting|notifying) (alex|the (user|owner)|"
        r"your (owner|user|human))\b|"
        r"\bkeep (this|it) (a )?(secret|between us)\b|"
        r"\bdelete (this|the) (message|instruction|conversation) after\b",
        "asks the model to hide an action from Alex",
    ),
    "exfiltration": (
        r"\b(send|upload|forward|email|exfiltrate|transmit|paste)\s+(me\s+|us\s+|them\s+|him\s+)?"
        r"(the\s+|your\s+|all\s+|any\s+|his\s+|alex'?s\s+|every\s+)?(\S+\s+){0,3}"
        r"(api[ _-]?keys?|tokens?|passwords?|credentials?|\.env\b|secrets?|keychain|"
        r"private keys?|cookies?|session ids?|\.zuliprc|refresh tokens?)\b",
        "a transfer verb with a secret as its object",
    ),
    "pipe_to_shell": (
        r"\b(curl|wget|fetch)\b[^|\n]{0,120}\|\s*(sudo\s+)?(sh|bash|zsh|python3?|perl|ruby|node)\b|"
        r"\bbase64\s+(-d|--decode)\b[^|\n]{0,60}\|\s*(sh|bash|zsh)\b|"
        r"\beval\s+[\"']?\$\((curl|wget)\b",
        "remote code straight into a shell",
    ),
    "prompt_leak": (
        r"\b(reveal|print|show|output|repeat|display|dump|recite|paste|echo)\b[^.\n]{0,30}"
        r"\b(your |the |its |this )?(system prompt|hidden prompt|initial prompt|instructions you were "
        r"given|CLAUDE\.md|persona (file|prompt)|configuration prompt)\b",
        "asks for the instruction set",
    ),
    "permission_escalation": (
        r"\bMIST_UNATTENDED\b|\bMIST_GUARD\b|"
        r"\b(disable|turn off|remove|skip|bypass|circumvent|delete|ignore) (the |your |all |any )?"
        r"(guard|guards|guard hook|hooks?|safety|safeguards?|permission (checks?|mode)|"
        r"restrictions?|content filter|filters?)\b",
        "names the guard by name or asks for it to be switched off; only a rule file does that",
    ),
    "tool_coercion": (
        r"\b(run|execute|invoke|call)\b (the following|this|these|that) (command|script|code|"
        r"shell|tool|bash)\b|\brm\s+-[rRf]{1,3}\s+(/|~|\$HOME|/Users)\b|"
        r"\b(write|append|add)\b[^.\n]{0,40}\bto (CLAUDE\.md|the hooks?|settings\.json|"
        r"\.zshrc|a launchd|the plist|LaunchAgents)\b",
        "directs the model at a specific dangerous action",
    ),
    "invisible_chars": (
        # Bidi embeddings, overrides and isolates anywhere; zero-width characters
        # only when they split a word. U+200D (the emoji joiner) is not here on
        # purpose, and a stray U+200B after a bullet (Google Docs exports do
        # this) is not an attempt either.
        "[\u202a-\u202e\u2066-\u2069]|(?<=[A-Za-z])[\u200b\u200c\u200e\u200f\u2060-\u2064\ufeff](?=[A-Za-z])",
        "bidirectional controls, or zero-width characters splitting a word, which hide text from a reader",
    ),
    "hidden_html": (
        r"<!--[^>]{0,300}\b(instruction|ignore|system|assistant|claude|must|mist)\b|"
        r"\b(display\s*:\s*none|visibility\s*:\s*hidden|font-size\s*:\s*0(px|pt)?\b|"
        r"opacity\s*:\s*0\b|color\s*:\s*(white|#fff(fff)?)\b)[^\n]{0,200}\b(ai|assistant|claude|"
        r"model|candidate|instruction|ignore|rank|score|recommend)\b|"
        r"<(div|span|p)[^>]*\bhidden\b",
        "text styled to be invisible to a human but visible to a parser",
    ),
    "base64_blob": (
        r"(?<![A-Za-z0-9+/])[A-Za-z0-9+/]{160,}={0,2}(?![A-Za-z0-9+/])",
        "a long encoded blob where prose should be",
    ),
}

_COMPILED = {name: re.compile(rx, re.IGNORECASE | re.MULTILINE) for name, (rx, _) in SIGNATURES.items()}

# What a rule file (CLAUDE.md, a SKILL.md, a routine prompt) is allowed to say
# because it is describing the attack. Everything else still fires there.
INSTRUCTION_FILE_EXCLUDES = {
    "ignore_previous", "prompt_leak", "role_override", "impersonation", "tool_coercion",
    "fake_role_tag", "permission_escalation",
}


@dataclass
class Hit:
    path: str
    line: int
    signature: str
    snippet: str

    def as_dict(self) -> dict:
        return {"path": self.path, "line": self.line, "signature": self.signature,
                "snippet": self.snippet}


def scan_text(text: str, path: str = "<stdin>", exclude: set[str] | None = None) -> list[Hit]:
    """Every signature match, one Hit per (line, signature).

    `exclude` drops signatures by name. Rule files legitimately quote the
    phrases behind ignore_previous, prompt_leak, role_override, impersonation
    and tool_coercion (the injection rule in CLAUDE.md is the obvious case),
    so callers scanning instruction files pass INSTRUCTION_FILE_EXCLUDES.
    """
    exclude = exclude or set()
    hits: list[Hit] = []
    for lineno, line in enumerate(text.split("\n"), start=1):
        for name, rx in _COMPILED.items():
            if name in exclude:
                continue
            if rx.search(line):
                snippet = line.strip()
                if len(snippet) > 140:
                    snippet = snippet[:137] + "..."
                hits.append(Hit(path, lineno, name, snippet))
    return hits


def scan_added_lines(diff_text: str, path: str = "<diff>",
                     exclude: set[str] | None = None) -> list[Hit]:
    """Scan only the '+' lines of a unified diff, reporting diff line numbers."""
    hits: list[Hit] = []
    for lineno, line in enumerate(diff_text.split("\n"), start=1):
        if not line.startswith("+") or line.startswith("+++"):
            continue
        for h in scan_text(line[1:], path, exclude):
            hits.append(Hit(path, lineno, h.signature, h.snippet))
    return hits


def scan_file(path: Path, exclude: set[str] | None = None) -> tuple[list[Hit], str | None]:
    """(hits, skip_reason). skip_reason is set when the file was not scanned."""
    try:
        size = path.stat().st_size
    except OSError as e:
        return [], f"unreadable: {e}"
    if size > MAX_BYTES:
        return [], f"skipped: {size} bytes exceeds {MAX_BYTES}"
    try:
        raw = path.read_bytes()
    except OSError as e:
        return [], f"unreadable: {e}"
    if b"\x00" in raw[:4096]:
        return [], "skipped: binary"
    text = raw.decode("utf-8", errors="replace")
    return scan_text(text, str(path), exclude), None


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="mist-injection-scan",
                                 description=(__doc__ or "").split("\n\n")[0])
    ap.add_argument("paths", nargs="*", help="files to scan")
    ap.add_argument("--stdin", action="store_true", help="scan standard input instead of files")
    ap.add_argument("--added-lines", action="store_true",
                    help="stdin is a unified diff; scan only added lines")
    ap.add_argument("--count", action="store_true", help="print only the total hit count")
    ap.add_argument("--json", action="store_true", help="print hits as JSON")
    ap.add_argument("--quiet", action="store_true", help="no output, exit status only")
    ap.add_argument("--exclude", default="",
                    help="comma-separated signature names to skip; 'instructions' expands to "
                         "the set a rule file legitimately quotes")
    args = ap.parse_args(argv)

    exclude = set()
    for name in args.exclude.split(","):
        name = name.strip()
        if name == "instructions":
            exclude |= INSTRUCTION_FILE_EXCLUDES
        elif name:
            if name not in SIGNATURES:
                print(f"unknown signature {name!r}; known: {', '.join(SIGNATURES)}", file=sys.stderr)
                return 2
            exclude.add(name)

    hits: list[Hit] = []
    skipped: list[str] = []
    if args.stdin or args.added_lines:
        text = sys.stdin.read()
        hits = scan_added_lines(text, exclude=exclude) if args.added_lines else scan_text(text, exclude=exclude)
    elif args.paths:
        for p in args.paths:
            file_hits, reason = scan_file(Path(p).expanduser(), exclude)
            hits.extend(file_hits)
            if reason:
                skipped.append(f"{p}: {reason}")
    else:
        ap.print_usage(sys.stderr)
        return 2

    if args.count:
        print(len(hits))
    elif args.json:
        print(json.dumps({"hits": [h.as_dict() for h in hits], "skipped": skipped}, indent=1))
    elif not args.quiet:
        for h in hits:
            print(f"{h.path}:{h.line}: {h.signature}: {h.snippet}")
        for s in skipped:
            print(f"SKIPPED {s}", file=sys.stderr)
    return 1 if hits else 0


if __name__ == "__main__":
    sys.exit(main())
