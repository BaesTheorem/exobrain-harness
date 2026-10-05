"""Daily: ask the city for an update on each 311 report that has not moved.

A report is due when it is open and has had no movement and no update
request for 7 days (civicapi.due_for_update). The rule reads the city's own
records, where filed update requests also appear, so this job and the KC 311
iPhone app never ask twice. One banner and one Discord DM per run, and only
when something was filed or failed.

INVARIANTS:
- Files only reports that due_for_update returns; never an update request
  for an update request.
"""

from __future__ import annotations

import os
import subprocess
from pathlib import Path

HERE = Path(__file__).resolve().parent
ENV = HERE.parent / ".env"


def load_env() -> None:
    if not ENV.exists():
        return
    for line in ENV.read_text().splitlines():
        if "=" in line and not line.lstrip().startswith("#"):
            k, v = line.split("=", 1)
            os.environ.setdefault(k.strip().removeprefix("export "), v.strip().strip('"').strip("'"))


def main() -> int:
    load_env()
    import server

    result = server.request_311_updates(confirm=True, only_due=True)
    rows = result.get("results", [])
    if not rows and result.get("ok"):
        print("nothing due")
        return 0
    ok = [r for r in rows if r.get("ok")]
    bad = [r for r in rows if not r.get("ok")]
    lines = [f"Asked KC 311 for updates on {len(ok)} report(s) with no movement in 7 days."] if ok else []
    lines += [f"- {r['sub_type']} ({r['reference']})" for r in ok]
    if bad or not result.get("ok", True):
        lines.append(f"Failed: {len(bad) or 'all'}. {result.get('error') or '; '.join(str(r.get('error')) for r in bad)}")
    msg = "\n".join(lines)
    print(msg)
    subprocess.run([str(HERE.parent / "mist-voice" / "bin" / "mist-notify"), msg, "KC 311 updates", "Glass",
                    "--discord", "--context", "mykcmo/auto_updates.py daily run"], check=False)
    return 0 if not bad else 1


if __name__ == "__main__":
    raise SystemExit(main())
