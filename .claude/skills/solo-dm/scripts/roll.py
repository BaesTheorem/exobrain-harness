#!/usr/bin/env python3
"""Solo DM dice roller.

Uses secrets.SystemRandom so numbers come from the OS entropy pool, not from
the LLM's sampler. Results can be atomically linked to a committed turn row
in SQLite, guaranteeing the DC was written down before the roll landed.

    roll.py "1d20+5"
    roll.py "1d20+5" --adv --dc 15
    roll.py "2d6+3" --dmg                # damage: no dc
    roll.py "1d20" --crit                # doubles dice
    roll.py "1d20+5" --slug <slug> --turn-id 42   # writes rolls row + jsonl
    roll.py --selftest
"""
from __future__ import annotations

import argparse
import json
import re
import secrets
import sqlite3
import sys
from datetime import datetime, timezone
from pathlib import Path

HARNESS_ROOT = Path("/Users/alexhedtke/Documents/Exobrain harness")
DATA_ROOT = HARNESS_ROOT / "data/solo-dm"

_rng = secrets.SystemRandom()

SPEC_RE = re.compile(r"\s*(\d+)d(\d+)\s*([+-]\s*\d+)?\s*$")


def parse_spec(spec: str) -> tuple[int, int, int]:
    m = SPEC_RE.match(spec)
    if not m:
        raise ValueError(f"bad dice spec: {spec!r}")
    n, d = int(m[1]), int(m[2])
    mod = int(m[3].replace(" ", "")) if m[3] else 0
    if n < 1 or d < 2:
        raise ValueError(f"bad dice spec: {spec!r}")
    return n, d, mod


def roll(spec: str, adv: str | None = None, crit: bool = False) -> dict:
    n, d, mod = parse_spec(spec)
    if crit:
        n *= 2
    rolls = [_rng.randint(1, d) for _ in range(n)]
    used = rolls
    note = None
    if adv in ("adv", "dis") and n == 1 and not crit:
        second = _rng.randint(1, d)
        pair = [rolls[0], second]
        used = [max(pair)] if adv == "adv" else [min(pair)]
        note = {"pair": pair, "kept": used[0], "kind": adv}
    total = sum(used) + mod
    return {
        "spec": spec,
        "rolls": rolls,
        "used": used,
        "mod": mod,
        "total": total,
        "adv_note": note,
        "crit_dice": crit,
    }


def classify_outcome(res: dict, dc: int | None, is_d20_check: bool, dmg: bool) -> str | None:
    if dmg or dc is None:
        return None
    if is_d20_check:
        natural = res["used"][0]
        if natural == 20:
            return "crit"
        if natural == 1:
            return "crit_fail"
    return "pass" if res["total"] >= dc else "fail"


def write_to_db(slug: str, turn_id: int, res: dict, outcome: str | None) -> int:
    db = DATA_ROOT / slug / "state.sqlite"
    if not db.exists():
        sys.exit(f"db not found: {db}")
    conn = sqlite3.connect(db)
    try:
        conn.execute("PRAGMA foreign_keys = ON")
        cur = conn.execute(
            "INSERT INTO rolls (turn_id, spec, rolls_json, total, outcome) "
            "VALUES (?,?,?,?,?)",
            (turn_id, res["spec"], json.dumps(res["rolls"]), res["total"], outcome),
        )
        conn.commit()
        return cur.lastrowid
    finally:
        conn.close()


def mirror_jsonl(slug: str, session_number: int, record: dict) -> None:
    path = DATA_ROOT / slug / "sessions" / f"Session-{session_number}.jsonl"
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a") as f:
        f.write(json.dumps(record) + "\n")


def resolve_session_number(slug: str, turn_id: int) -> int | None:
    db = DATA_ROOT / slug / "state.sqlite"
    conn = sqlite3.connect(db)
    try:
        row = conn.execute(
            "SELECT s.number FROM turns t JOIN sessions s ON s.id=t.session_id "
            "WHERE t.id=?",
            (turn_id,),
        ).fetchone()
        return row[0] if row else None
    finally:
        conn.close()


def format_human(res: dict, outcome: str | None, dc: int | None) -> str:
    rolls_str = f"[{', '.join(str(r) for r in res['rolls'])}]"
    used_str = ""
    if res["adv_note"]:
        n = res["adv_note"]
        used_str = f" -> kept {n['kept']} ({n['kind']})"
    mod_str = f" + {res['mod']}" if res["mod"] > 0 else (f" - {-res['mod']}" if res["mod"] < 0 else "")
    line = f"{res['spec']}: {rolls_str}{used_str}{mod_str} = {res['total']}"
    if dc is not None and outcome is not None:
        line += f"  [DC {dc} -> {outcome.upper()}]"
    elif outcome:
        line += f"  [{outcome.upper()}]"
    return line


def selftest() -> None:
    # Chi-squared-ish: 10k d20 rolls, expected 500 per face.
    counts = [0] * 21
    for _ in range(10_000):
        r = roll("1d20")
        counts[r["used"][0]] += 1
    chi2 = sum((counts[i] - 500) ** 2 / 500 for i in range(1, 21))
    # For 19 dof at p=0.001, critical value ~ 43.8. We expect < that comfortably.
    assert chi2 < 50, f"chi^2={chi2:.2f} suggests non-uniform d20"

    # Advantage: keeps the max of two d20.
    adv_totals = [roll("1d20", adv="adv")["total"] for _ in range(5000)]
    avg_adv = sum(adv_totals) / len(adv_totals)
    assert 13 < avg_adv < 14.5, f"adv avg {avg_adv:.2f} outside expected band"

    dis_totals = [roll("1d20", adv="dis")["total"] for _ in range(5000)]
    avg_dis = sum(dis_totals) / len(dis_totals)
    assert 6.5 < avg_dis < 8, f"dis avg {avg_dis:.2f} outside expected band"

    # Crit doubles dice count.
    r = roll("2d6+3", crit=True)
    assert len(r["rolls"]) == 4, f"crit did not double dice: {r['rolls']}"

    # Outcome classification.
    assert classify_outcome({"used": [20], "total": 25}, 15, True, False) == "crit"
    assert classify_outcome({"used": [1], "total": 6}, 15, True, False) == "crit_fail"
    assert classify_outcome({"used": [10], "total": 15}, 15, True, False) == "pass"
    assert classify_outcome({"used": [5], "total": 10}, 15, True, False) == "fail"
    assert classify_outcome({"used": [10], "total": 10}, None, False, True) is None

    print("roll.py selftest: OK (chi^2={:.2f}, adv={:.2f}, dis={:.2f})".format(chi2, avg_adv, avg_dis))


def main() -> None:
    p = argparse.ArgumentParser()
    p.add_argument("spec", nargs="?")
    p.add_argument("--adv", action="store_const", const="adv", dest="adv")
    p.add_argument("--dis", action="store_const", const="dis", dest="adv")
    p.add_argument("--crit", action="store_true")
    p.add_argument("--dc", type=int)
    p.add_argument("--dmg", action="store_true", help="damage roll; no DC comparison")
    p.add_argument("--slug")
    p.add_argument("--turn-id", type=int)
    p.add_argument("--quiet", action="store_true")
    p.add_argument("--selftest", action="store_true")
    args = p.parse_args()

    if args.selftest:
        selftest()
        return
    if not args.spec:
        p.error("spec required")

    res = roll(args.spec, adv=args.adv, crit=args.crit)
    is_d20_check = args.spec.strip().startswith("1d20") and not args.dmg and not args.crit
    outcome = classify_outcome(res, args.dc, is_d20_check, args.dmg)

    if args.slug and args.turn_id:
        roll_id = write_to_db(args.slug, args.turn_id, res, outcome)
        session_n = resolve_session_number(args.slug, args.turn_id)
        if session_n is not None:
            mirror_jsonl(
                args.slug,
                session_n,
                {
                    "ts": datetime.now(timezone.utc).isoformat(),
                    "kind": "roll",
                    "turn_id": args.turn_id,
                    "roll_id": roll_id,
                    "spec": res["spec"],
                    "rolls": res["rolls"],
                    "used": res["used"],
                    "mod": res["mod"],
                    "total": res["total"],
                    "adv": res["adv_note"],
                    "dc": args.dc,
                    "outcome": outcome,
                },
            )

    out = {
        "spec": res["spec"],
        "rolls": res["rolls"],
        "used": res["used"],
        "mod": res["mod"],
        "total": res["total"],
        "adv": res["adv_note"],
        "dc": args.dc,
        "outcome": outcome,
    }
    if args.quiet:
        print(json.dumps(out))
    else:
        print(format_human(res, outcome, args.dc))
        print(json.dumps(out))


if __name__ == "__main__":
    main()
