#!/usr/bin/env python3
"""Carry the Claude Code CLI's TCC grants forward across auto-updates.

THE PROBLEM. macOS identifies the `claude` CLI to TCC by **path**, because the
binary is a bare Mach-O with no bundle (`identifier_type=Path` in tccd's log).
The native installer puts each release at its own versioned path:

    ~/.local/share/claude/versions/2.1.233
    ~/.local/share/claude/versions/2.1.234   <- new path = new TCC identity
    ~/.local/share/claude/versions/2.1.235

The CLI auto-updates roughly daily, so roughly daily every grant it has
silently evaporates and Alex re-approves Documents, Desktop, "data from other
apps", Google Drive, and Things 3 automation from scratch.

WHY THIS IS SAFE, AND NOT A TCC BYPASS. Every grant stores a code requirement
alongside it, and the one macOS writes for this binary is version-independent:

    identifier "com.anthropic.claude-code" and anchor apple generic
      and certificate leaf[subject.OU] = Q6L2SF6YDW

Any Anthropic-signed `claude` satisfies it; only the *path* changed. So the
user's consent was never withdrawn or scoped to a version -- macOS just lost
track of who it was talking to. This re-points the existing grant at the new
path and copies the csreq with it, and it refuses to move a grant onto a
binary that does not satisfy that very requirement (see `verify_binary`).
That gate is the whole security argument: a grant can only ever land on the
genuine, Apple-notarized Anthropic CLI.

INVARIANTS
  - NEVER carry a grant to a binary failing `codesign --verify --strict -R`
    against the csreq being copied. No signature, no grant. No exceptions.
  - NEVER invent a grant. Every row written is copied from a row the user
    approved by hand for an older version of this same binary.
  - NEVER pin the CLI's path. It has moved install locations before
    (npm-global -> ~/.local); always resolve it live.
  - Back up TCC.db before the first write of a run.
  - Idempotent: a run with nothing to do writes nothing and exits 0.

Full Disk Access (kTCCServiceSystemPolicyAllFiles) lives in the SYSTEM
database at /Library/..., which needs root, so it cannot be carried here.
`--check` reports when it looks stale so the session-start hook can say so.

Usage:
    tcc_carry_forward.py            # carry grants forward, print what changed
    tcc_carry_forward.py --check    # report only, touch nothing (exit 1 = work pending)
    tcc_carry_forward.py --prune    # also drop rows for versions no longer on disk
"""

from __future__ import annotations

import argparse
import os
import re
import shutil
import sqlite3
import subprocess
import sys
import tempfile
import time
from pathlib import Path

USER_TCC_DB = Path.home() / "Library/Application Support/com.apple.TCC/TCC.db"
BACKUP_DIR = Path.home() / "Library/Logs/exobrain/tcc-backups"

# A client path we are willing to treat as "the Claude CLI, some version".
# Anchored on the versions directory the native installer owns, so a stray
# row for an unrelated binary can never be picked up as a donor.
CLAUDE_VERSION_RE = re.compile(r"/claude/versions/[^/]+$")

# Services we deliberately do not touch. AllFiles lives in the system DB and
# needs root; listing it here keeps it out of the "missing" noise and into the
# explicit warning instead.
SYSTEM_DB_SERVICES = {"kTCCServiceSystemPolicyAllFiles"}


class Grant:
    """One row of TCC's `access` table, keyed the way TCC keys it."""

    __slots__ = ("service", "client", "ioi", "row", "last_modified")

    def __init__(self, service: str, client: str, ioi: str, row: tuple, last_modified: int):
        self.service = service
        self.client = client
        self.ioi = ioi
        self.row = row
        self.last_modified = last_modified

    @property
    def key(self) -> tuple[str, str]:
        return (self.service, self.ioi)

    def __str__(self) -> str:
        short = self.service.replace("kTCCServiceSystemPolicy", "").replace("kTCCService", "")
        return f"{short}" + (f" -> {self.ioi}" if self.ioi and self.ioi != "UNUSED" else "")


def resolve_claude() -> Path | None:
    """Find the live CLI the way TCC sees it: fully resolved, no symlinks.

    Never pin a path here. `~/.local/bin/claude` is a symlink into the
    versioned tree, and TCC records the *target*, so realpath is the identity
    that matters.
    """
    found = shutil.which("claude")
    candidates = [found] if found else []
    candidates += [
        str(Path.home() / ".local/bin/claude"),
        str(Path.home() / ".npm-global/bin/claude"),
        "/opt/homebrew/bin/claude",
        "/usr/local/bin/claude",
    ]
    for cand in candidates:
        if cand and os.path.exists(cand):
            real = Path(os.path.realpath(cand))
            if real.exists():
                return real
    return None


def verify_binary(binary: Path, csreq: bytes | None, _cache: dict = {}) -> tuple[bool, str]:  # noqa: B006 -- deliberate memo across calls
    """Gate: does `binary` satisfy the code requirement this grant was issued under?

    Returns (ok, detail). A missing csreq is NOT a pass -- some rows (AppData)
    store none, so those fall back to the canonical Anthropic requirement
    rather than to trusting the path.

    Memoized on (binary, requirement): codesign hashes a 300MB Mach-O on every
    call, and a run carries several grants that all share one requirement.
    """
    ck = (str(binary), csreq)
    if ck in _cache:
        return _cache[ck]

    if not binary.exists():
        return False, "binary does not exist"

    if csreq:
        with tempfile.NamedTemporaryFile(suffix=".csreq", delete=False) as fh:
            fh.write(csreq)
            req_path = fh.name
        try:
            proc = subprocess.run(
                ["codesign", "--verify", "--strict", "-R", req_path, str(binary)],
                capture_output=True,
                text=True,
                timeout=120,
            )
        finally:
            os.unlink(req_path)
    else:
        proc = subprocess.run(
            [
                "codesign",
                "--verify",
                "--strict",
                "-R=identifier \"com.anthropic.claude-code\" and anchor apple generic "
                "and certificate leaf[subject.OU] = Q6L2SF6YDW",
                str(binary),
            ],
            capture_output=True,
            text=True,
            timeout=120,
        )

    if proc.returncode == 0:
        result = (True, "signature and requirement satisfied")
    else:
        detail = (proc.stderr or proc.stdout).strip().splitlines()
        result = (False, detail[-1] if detail else "requirement not satisfied")
    _cache[ck] = result
    return result


def read_grants(conn: sqlite3.Connection) -> list[Grant]:
    """Every grant currently held by any version of the Claude CLI."""
    cur = conn.execute(
        "SELECT service, client, client_type, auth_value, auth_reason, auth_version,"
        "       csreq, policy_id, indirect_object_identifier_type,"
        "       indirect_object_identifier, indirect_object_code_identity, flags,"
        "       last_modified"
        "  FROM access"
    )
    grants: list[Grant] = []
    for row in cur.fetchall():
        service, client = row[0], row[1]
        if not CLAUDE_VERSION_RE.search(client or ""):
            continue
        if service in SYSTEM_DB_SERVICES:
            continue
        grants.append(Grant(service, client, row[9] or "UNUSED", row, row[12]))
    return grants


def pick_donors(grants: list[Grant], live: str) -> dict[tuple[str, str], Grant]:
    """For each (service, target) the CLI ever had, the newest grant NOT on the live path.

    Newest wins because it reflects the user's most recent decision -- if they
    revoked something two versions ago, we must not resurrect the older allow.
    """
    donors: dict[tuple[str, str], Grant] = {}
    for g in sorted(grants, key=lambda g: g.last_modified):
        if g.client == live:
            continue
        donors[g.key] = g  # later (newer) rows overwrite earlier ones
    return donors


def carry_forward(
    conn: sqlite3.Connection, live: Path, donors: dict[tuple[str, str], Grant], held: set[tuple[str, str]]
) -> tuple[list[Grant], list[tuple[Grant, str]]]:
    """Write the missing grants. Returns (carried, refused)."""
    carried: list[Grant] = []
    refused: list[tuple[Grant, str]] = []
    now = int(time.time())

    for key, donor in sorted(donors.items()):
        if key in held:
            continue
        ok, detail = verify_binary(live, donor.row[6])
        if not ok:
            refused.append((donor, detail))
            continue
        r = donor.row
        conn.execute(
            "INSERT OR REPLACE INTO access"
            "  (service, client, client_type, auth_value, auth_reason, auth_version,"
            "   csreq, policy_id, indirect_object_identifier_type,"
            "   indirect_object_identifier, indirect_object_code_identity, flags,"
            "   last_modified, last_reminded)"
            " VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
            (r[0], str(live), r[2], r[3], r[4], r[5], r[6], r[7], r[8], r[9], r[10], r[11], now, now),
        )
        carried.append(donor)
    return carried, refused


def prune_dead(conn: sqlite3.Connection, live: Path) -> list[str]:
    """Drop rows for version paths that no longer exist on disk."""
    cur = conn.execute("SELECT DISTINCT client FROM access")
    dead = [
        c
        for (c,) in cur.fetchall()
        if CLAUDE_VERSION_RE.search(c or "") and c != str(live) and not os.path.exists(c)
    ]
    for client in dead:
        conn.execute("DELETE FROM access WHERE client = ?", (client,))
    return dead


def backup_db() -> Path:
    BACKUP_DIR.mkdir(parents=True, exist_ok=True)
    dest = BACKUP_DIR / f"TCC.db.{time.strftime('%Y%m%d-%H%M%S')}"
    shutil.copy2(USER_TCC_DB, dest)
    # One week of backups is plenty; this file is small but not free.
    for old in sorted(BACKUP_DIR.glob("TCC.db.*"))[:-7]:
        old.unlink()
    return dest


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--check", action="store_true", help="report only; exit 1 if grants are pending")
    ap.add_argument("--prune", action="store_true", help="also drop rows for versions no longer installed")
    args = ap.parse_args()

    live = resolve_claude()
    if live is None:
        print("FAIL: could not resolve the claude CLI", file=sys.stderr)
        return 2
    if not USER_TCC_DB.exists():
        print(f"FAIL: no user TCC database at {USER_TCC_DB}", file=sys.stderr)
        return 2

    try:
        conn = sqlite3.connect(f"file:{USER_TCC_DB}?mode=rw", uri=True)
    except sqlite3.OperationalError as exc:
        # Reading this DB at all requires Full Disk Access for the RESPONSIBLE
        # process, which after an upgrade is exactly what is missing.
        print(f"FAIL: cannot open TCC.db ({exc}).", file=sys.stderr)
        print(f"  Grant Full Disk Access to {live} and re-run.", file=sys.stderr)
        return 2

    with conn:
        grants = read_grants(conn)
        held = {g.key for g in grants if g.client == str(live)}
        donors = pick_donors(grants, str(live))
        pending = {k: g for k, g in donors.items() if k not in held}

        if args.check:
            if pending:
                print(f"WARN: {len(pending)} TCC grant(s) lost to the CLI upgrade at {live.name}")
                for g in sorted(pending.values(), key=str):
                    print(f"  missing: {g}")
                print("  Fix: maintenance/bin/mist-tcc-carry")
                return 1
            print(f"OK: TCC grants intact for claude {live.name}")
            return 0

        if not pending and not args.prune:
            print(f"OK: nothing to carry forward; claude {live.name} holds all {len(held)} grant(s)")
            return 0

        backup = backup_db()
        carried, refused = carry_forward(conn, live, donors, held)
        dead = prune_dead(conn, live) if args.prune else []

    if carried:
        print(f"Carried {len(carried)} grant(s) forward to claude {live.name}:")
        for g in sorted(carried, key=str):
            print(f"  + {g}")
    if refused:
        print(f"REFUSED {len(refused)} grant(s) -- binary failed its own code requirement:", file=sys.stderr)
        for g, why in refused:
            print(f"  ! {g}: {why}", file=sys.stderr)
    if dead:
        print(f"Pruned {len(dead)} row-set(s) for uninstalled versions:")
        for c in dead:
            print(f"  - {Path(c).name}")
    if not carried and not refused and not dead:
        print(f"OK: nothing to do for claude {live.name}")
    else:
        print(f"Backup: {backup}")

    return 1 if refused else 0


if __name__ == "__main__":
    sys.exit(main())
