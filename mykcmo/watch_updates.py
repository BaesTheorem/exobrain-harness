"""Every 5 minutes: tell Alex at once when the city touches one of his 311 reports.

Polls myissues (one call). A report is checked again only when its status or
updated_on moved, or the status or updated_on of an update request that names
it moved. For those, it reads the merged timeline (civicapi.merged_timeline)
and sends each entry it has not seen: one Mac banner and one Discord DM per
run, never one per entry. The first run records what exists and sends nothing.

INVARIANTS:
- Update requests are never reported on their own; their activity goes out
  under the report they name.
- State in watch-state.json (gitignored) is written only after the
  notification is sent, so a failed send is retried on the next run.
"""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
STATE = HERE / "watch-state.json"

sys.path.insert(0, str(HERE))
import auto_updates  # noqa: E402  (load_env)
import civicapi  # noqa: E402


def signature(r: dict) -> str:
    return f"{r.get('status')}|{r.get('updated_on')}"


def entry_key(e: dict) -> str:
    return f"{int(e['at'])}|{e['title']}"


def main() -> int:
    auto_updates.load_env()
    mine = civicapi.my_reports().get("my_issues", [])
    first = not STATE.exists()
    state = {} if first else json.loads(STATE.read_text())
    sigs, seen = state.get("sigs", {}), state.get("seen", {})
    new_sigs = {str(r.get("id")): signature(r) for r in mine}
    lines: list[str] = []
    for r in mine:
        if civicapi.is_update_request(r):
            continue
        rid = str(r.get("id"))
        group = [r, *civicapi.update_requests_for(r, mine)]
        if not first and rid in seen and all(sigs.get(str(g.get("id"))) == new_sigs[str(g.get("id"))] for g in group):
            continue
        try:
            timeline = civicapi.merged_timeline(rid, civicapi.report_detail(rid), mine)
        except civicapi.CivicError as exc:
            print(f"{rid}: {exc}")
            new_sigs.pop(rid, None)   # check this one again next run
            continue
        known = set(seen.get(rid, []))
        fresh = [e for e in timeline if entry_key(e) not in known]
        if fresh and not first and rid in seen:
            label = r.get("subcategory") or r.get("sub_type") or r.get("name")
            lines.append(f"{label} (report {rid}), now {r.get('status')}:")
            lines += [f"- {e['when']}: {e['title']}. {str(e.get('details') or '').strip()}" for e in fresh]
        seen[rid] = sorted(known | {entry_key(e) for e in timeline})
    if lines:
        msg = "\n".join(lines)
        print(msg)
        sent = subprocess.run([str(HERE.parent / "mist-voice" / "bin" / "mist-notify"), msg, "KC 311 ticket update",
                               "Glass", "--discord", "--context", "mykcmo/watch_updates.py"], check=False)
        if sent.returncode != 0:
            return 1
    STATE.write_text(json.dumps({"sigs": new_sigs, "seen": seen}, indent=1))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
