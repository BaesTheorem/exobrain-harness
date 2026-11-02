#!/usr/bin/env python3
"""Hold a command until the current Console turn ends, then run it.

mist-ask uses this so that a decision banner reaches Alex only after the final
message of the turn is complete. Before, the banner fired while the reply was
still to come, and the click opened a chat that showed tool calls and thinking
but not the question.

Usage:
    ask_after_turn.py --detach LOG -- CMD [ARGS...]   (returns at once)
    ask_after_turn.py LOG -- CMD [ARGS...]            (waits in the foreground)

LOG is the chat's stream log, ``~/Documents/mist-console/data/<sid>.jsonl``.
The turn has ended when a line appended after the start is a JSON object with
``"type": "result"``. The wait stops after MAX_WAIT_SEC in any case, so a hung
turn still delivers the ask.

INVARIANTS:
- Only lines appended after the start count; a result row from an earlier
  turn never releases the command.
- A line counts only when it is complete (ends in a newline) and parses as a
  JSON object whose top-level "type" is "result". Text that only contains the
  string "result" never matches.
- With --detach the waiter runs in its own session (setsid), so the cleanup
  of the shell that started it cannot stop it.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
import time

MAX_WAIT_SEC = 1800
POLL_SEC = 1.0


def _is_result(line: str) -> bool:
    try:
        obj = json.loads(line)
    except ValueError:
        return False
    return isinstance(obj, dict) and obj.get("type") == "result"


def wait_for_turn_end(log: str, max_wait: float = MAX_WAIT_SEC) -> bool:
    """Return True when a result row appears after the start, False on timeout."""
    deadline = time.monotonic() + max_wait
    pending = ""
    with open(log, encoding="utf-8", errors="replace") as fh:
        fh.seek(0, os.SEEK_END)
        while time.monotonic() < deadline:
            chunk = fh.read()
            if chunk:
                pending += chunk
                *complete, pending = pending.split("\n")
                if any(_is_result(line) for line in complete):
                    return True
            else:
                time.sleep(POLL_SEC)
    return False


def main(argv: list[str]) -> int:
    args = argv[1:]
    detach = bool(args) and args[0] == "--detach"
    if detach:
        args = args[1:]
    if "--" not in args or args.index("--") != 1 or len(args) < 3:
        print(__doc__, file=sys.stderr)
        return 2
    log, cmd = args[0], args[2:]
    if detach:
        subprocess.Popen(  # noqa: S603 - argv comes from mist-ask, not from data
            [sys.executable, os.path.abspath(__file__), log, "--", *cmd],
            start_new_session=True,
            stdin=subprocess.DEVNULL,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
        return 0
    if os.path.isfile(log):
        wait_for_turn_end(log)
    os.execvp(cmd[0], cmd)  # noqa: S606 - same argv mist-ask would have run
    return 0  # not reached


if __name__ == "__main__":
    sys.exit(main(sys.argv))
