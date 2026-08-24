#!/usr/bin/env python3
"""One-shot command to the running driver. Shares the channel with arm.py.

Kept as a file rather than a heredoc because every draft-day diagnostic needs it
and retyping the poll loop is how typos reach a live clock.
"""
import json
import pathlib
import sys
import time

HERE = pathlib.Path(__file__).resolve().parent
CMD = HERE / "cmd.json"
RESULT = HERE / "result.json"


def send(op, arg, wait=60):
    RESULT.unlink(missing_ok=True)
    CMD.write_text(json.dumps({"id": int(time.time() * 1000) % 100000, "op": op, "arg": arg}))
    deadline = time.time() + wait
    while time.time() < deadline:
        if RESULT.exists():
            try:
                return json.loads(RESULT.read_text())
            except json.JSONDecodeError:
                pass
        time.sleep(0.3)
    return {"ok": False, "error": f"timeout after {wait}s"}


if __name__ == "__main__":
    op = sys.argv[1]
    arg = sys.stdin.read() if len(sys.argv) < 3 else sys.argv[2]
    res = send(op, arg)
    print(json.dumps(res.get("data") if res.get("ok") else res, indent=1, default=str)[:4000])
