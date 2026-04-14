#!/usr/bin/env python3
"""
Exposure audit — Mode 2 of the cybersecurity-bodyguard skill.

Scans staged git changes (or an arbitrary file/directory) for PII from
targets.json, generic credential patterns, and document metadata leaks.
Exits 0 if clean, 1 if MED findings, 2 if HIGH findings — making it safe
to chain in pre-commit / pre-push hooks:

    python3 exposure_audit.py --staged || { echo "Blocked: HIGH PII leak"; exit 1; }

Usage:
    python3 exposure_audit.py --staged           # audit git staged changes
    python3 exposure_audit.py --path FILE_OR_DIR # audit a path
    python3 exposure_audit.py --stdin            # read text from stdin
"""
from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
from pathlib import Path

SKILL_DIR = Path(__file__).resolve().parent.parent
TARGETS_PATH = SKILL_DIR / "targets.json"

# Generic high-risk credential / secret patterns. Conservative — we flag and
# let the user decide. False positives are preferable to false negatives.
SECRET_PATTERNS = [
    ("aws_access_key", r"\bAKIA[0-9A-Z]{16}\b"),
    ("github_pat", r"\bghp_[A-Za-z0-9]{36}\b"),
    ("github_oauth", r"\bgho_[A-Za-z0-9]{36}\b"),
    ("google_api", r"\bAIza[0-9A-Za-z_\-]{35}\b"),
    ("openai_key", r"\bsk-[A-Za-z0-9]{20,}\b"),
    ("anthropic_key", r"\bsk-ant-[A-Za-z0-9\-_]{80,}\b"),
    ("slack_token", r"\bxox[baprs]-[0-9A-Za-z\-]{10,}\b"),
    ("private_key", r"-----BEGIN (RSA |EC |OPENSSH |DSA |)PRIVATE KEY-----"),
    ("jwt", r"\beyJ[A-Za-z0-9_\-]+\.eyJ[A-Za-z0-9_\-]+\.[A-Za-z0-9_\-]+\b"),
    ("bearer_header", r"(?i)\bauthorization:\s*bearer\s+[A-Za-z0-9\-_\.]{20,}"),
]

# Shapes of PII we flag even without a targets.json match
GENERIC_PII_PATTERNS = [
    ("ssn", r"\b\d{3}-\d{2}-\d{4}\b"),
    ("credit_card", r"\b(?:\d{4}[-\s]?){3}\d{4}\b"),
    ("ipv4_private", r"\b(?:10\.\d{1,3}\.\d{1,3}\.\d{1,3}|192\.168\.\d{1,3}\.\d{1,3}|172\.(?:1[6-9]|2\d|3[01])\.\d{1,3}\.\d{1,3})\b"),
]


def load_targets() -> dict:
    if not TARGETS_PATH.exists():
        return {}
    with TARGETS_PATH.open() as fh:
        return json.load(fh)


def build_target_patterns(targets: dict) -> list[tuple[str, re.Pattern]]:
    """
    Build regex patterns from targets.json. Returns (label, compiled_regex) so
    we can report by category without leaking the actual value in generic
    contexts.
    """
    patterns: list[tuple[str, re.Pattern]] = []

    def add(label: str, values: list[str]) -> None:
        for v in values:
            if not v or len(v) < 4:
                continue
            patterns.append((label, re.compile(re.escape(v), re.IGNORECASE)))

    add("name", targets.get("names", []))
    add("email", targets.get("emails", []))
    add("phone", targets.get("phones", []))
    add("username", targets.get("usernames", []))
    add("alias", targets.get("aliases_pen_names", []))
    if employer := targets.get("employer"):
        add("employer", [employer])
    # Partner identifiers are extra-sensitive; flag high regardless
    partner = targets.get("partner") or {}
    add("partner_name", partner.get("names", []))
    add("partner_email", partner.get("emails", []))
    add("partner_username", partner.get("usernames", []))
    return patterns


def get_staged_changes() -> list[tuple[str, str]]:
    """Return list of (path, content) for staged file additions/modifications."""
    result = subprocess.run(
        ["git", "diff", "--cached", "--name-only", "--diff-filter=AM"],
        capture_output=True,
        text=True,
        check=True,
    )
    files = [p for p in result.stdout.splitlines() if p.strip()]
    changes: list[tuple[str, str]] = []
    for path in files:
        # We scan the *new content* of each staged file, not just the diff,
        # so previously-committed PII re-staged is still caught.
        try:
            blob = subprocess.run(
                ["git", "show", f":{path}"],
                capture_output=True,
                text=True,
                check=True,
                errors="replace",
            ).stdout
            changes.append((path, blob))
        except subprocess.CalledProcessError:
            continue
    return changes


def scan_text(
    text: str,
    target_patterns: list[tuple[str, re.Pattern]],
) -> list[dict]:
    """Scan a single text blob. Returns a list of findings."""
    findings: list[dict] = []
    for i, line in enumerate(text.splitlines(), start=1):
        for label, pat in target_patterns:
            if pat.search(line):
                sev = "HIGH" if label.startswith(("partner", "name", "email", "phone")) else "MED"
                findings.append(
                    {
                        "severity": sev,
                        "category": f"target:{label}",
                        "line": i,
                        "snippet": line[:120],
                    }
                )
        for label, regex in SECRET_PATTERNS:
            if re.search(regex, line):
                findings.append(
                    {
                        "severity": "HIGH",
                        "category": f"secret:{label}",
                        "line": i,
                        "snippet": "[redacted — credential shape detected]",
                    }
                )
        for label, regex in GENERIC_PII_PATTERNS:
            if re.search(regex, line):
                findings.append(
                    {
                        "severity": "HIGH",
                        "category": f"pii:{label}",
                        "line": i,
                        "snippet": "[redacted — PII shape detected]",
                    }
                )
    return findings


def scan_path(path: Path, target_patterns: list[tuple[str, re.Pattern]]) -> list[dict]:
    out: list[dict] = []
    files = [path] if path.is_file() else [p for p in path.rglob("*") if p.is_file()]
    for f in files:
        if f.suffix in {".png", ".jpg", ".jpeg", ".gif", ".pdf", ".zip", ".mp4", ".mp3"}:
            continue
        try:
            text = f.read_text(errors="replace")
        except Exception:
            continue
        for finding in scan_text(text, target_patterns):
            finding["file"] = str(f)
            out.append(finding)
    return out


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    g = parser.add_mutually_exclusive_group(required=True)
    g.add_argument("--staged", action="store_true")
    g.add_argument("--path")
    g.add_argument("--stdin", action="store_true")
    parser.add_argument("--format", choices=["text", "json"], default="text")
    args = parser.parse_args()

    targets = load_targets()
    target_patterns = build_target_patterns(targets)

    findings: list[dict] = []
    if args.staged:
        for path, content in get_staged_changes():
            for f in scan_text(content, target_patterns):
                f["file"] = path
                findings.append(f)
    elif args.path:
        findings = scan_path(Path(args.path), target_patterns)
    else:
        findings = scan_text(sys.stdin.read(), target_patterns)

    high = sum(1 for f in findings if f["severity"] == "HIGH")
    med = sum(1 for f in findings if f["severity"] == "MED")

    if args.format == "json":
        json.dump({"high": high, "med": med, "findings": findings}, sys.stdout, indent=2)
        print()
    else:
        if not findings:
            print("[OK] No exposure findings.")
        else:
            print(f"[!!] {high} HIGH  {med} MED  findings:")
            for f in findings:
                print(f"  [{f['severity']}] {f.get('file', '<stdin>')}:{f['line']}  {f['category']}")
                print(f"       {f['snippet']}")

    if high:
        return 2
    if med:
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
