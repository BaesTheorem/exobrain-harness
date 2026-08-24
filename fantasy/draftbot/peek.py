#!/usr/bin/env python3
"""Race-free look at Alex's roster in the draft room, straight off the page.

Separate from arm.py on purpose: arm.py and watch.py share the command channel,
and the roster panel is the one thing worth reading while a pick is in flight.
"""

import json
import pathlib
import sys
import time

HERE = pathlib.Path(__file__).resolve().parent
CMD = HERE / "cmd.json"
RESULT = HERE / "result.json"

JS = """() => {
  const b = document.body.innerText;
  const end = b.indexOf('Roster Limits');
  const start = b.lastIndexOf('POS', end);
  const rows = [];
  const lines = b.slice(start, end).split('\\n').map(s => s.trim()).filter(Boolean);
  for (let i = 0; i < lines.length - 2; i++) {
    if (!/^(QB|RB|WR|TE|FLEX|D\\/ST|K|BE|IR)$/.test(lines[i])) continue;
    rows.push({ slot: lines[i], player: lines[i + 1], bye: lines[i + 2] });
  }
  const limits = (b.match(/QB\\d+\\/\\d+RB[^\\n]*/) || [''])[0];
  const rnd = (b.match(/RND (\\d+) OF (\\d+)/) || []);
  return { rows, limits, round: rnd[1] + '/' + rnd[2],
           onClock: /You are on the clock/i.test(b) };
}"""


def main():
    RESULT.unlink(missing_ok=True)
    CMD.write_text(
        json.dumps({"id": int(time.time() * 1000) % 100000, "op": "eval", "arg": JS})
    )
    deadline = time.time() + 25
    while time.time() < deadline:
        if RESULT.exists():
            try:
                res = json.loads(RESULT.read_text())
                break
            except json.JSONDecodeError:
                pass
        time.sleep(0.3)
    else:
        sys.exit("timeout talking to driver.py")

    if not res.get("ok"):
        sys.exit(f"error: {res.get('error')}")
    d = res["data"]
    print(f"round {d['round']}   {d['limits']}   on the clock: {d['onClock']}")
    byes = {}
    for r in d["rows"]:
        if r["player"] == "Empty":
            print(f"  {r['slot']:<5} --")
            continue
        byes[r["bye"]] = byes.get(r["bye"], 0) + 1
        print(f"  {r['slot']:<5} {r['player']:<22} bye {r['bye']}")
    stacked = {w: n for w, n in byes.items() if n > 1}
    print("bye stacks:", stacked or "none")


if __name__ == "__main__":
    main()
