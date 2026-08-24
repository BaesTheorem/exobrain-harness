#!/usr/bin/env python3
"""Pre-draft divergence sign-off: no counter-consensus pick without a signature.

Alex's standard (2026-08-24): deviating from consensus is fine only behind an
explicit thesis. The board's player-level divergences were emerging from its
sources (Ringer ordering, ESPN+Sleeper tail noise), not from anyone's
conviction, so this makes every material divergence a deliberate decision:

    report            list divergences vs FantasyPros ECR, with dispositions
    keep NAME --thesis "..." [--vs NAME]
                      sign the divergence as a deliberate bet; registers a
                      ledger entry so the bet settles against real points
    correct NAME      re-slot the player at his consensus positional rank
                      when the board is next built (vor.py applies it)
    unsign NAME       remove a disposition
    status            dispositions + any UNSIGNED divergences (draft-morning
                      gate: rebuild the board, then this must come back clean)

Divergence is measured in POSITIONAL ranks, ours vs ECR's, which deliberately
ignores structural cross-position choices (early QB in a 1-QB league is
policy, signed globally; Josh Allen at QB1 vs ECR QB1 is no divergence).

Overrides live in board-overrides.json (gitignored: it is Alex's signed draft
strategy). Firewall note: corrections pull ECR, the examiner's audit source,
into the board for SIGNED players only; the independent judge
(consensus.json, CBS+FFT points) stays out of the board entirely.
"""

import argparse
import json
import pathlib
import re
import subprocess
import sys
import unicodedata

HERE = pathlib.Path(__file__).resolve().parent
VOR = HERE / "draftbot" / "vor.json"
ECR = HERE / "draftbot" / "ecr.json"
OVERRIDES = HERE / "board-overrides.json"

# A divergence is material when our slot and consensus's slot for the same
# player differ by at least this many positional ranks, inside the range that
# can actually reach a draft board (replacement + a bench's worth). RB is 4
# because the motivating case (Barkley, ours RB4 vs ECR RB8) sits exactly
# there; K/D/ST are 6 because both sources are near-dartboards at those
# positions and the picks are round-11+ streamer seeds anyway.
GAP = {"QB": 3, "RB": 4, "WR": 5, "TE": 3, "K": 6, "D/ST": 6}
RANGE = {"QB": 14, "RB": 40, "WR": 48, "TE": 20, "K": 12, "D/ST": 12}


def norm(s):
    s = unicodedata.normalize("NFKD", s).replace("’", "").replace("'", "").lower()
    s = re.sub(r"\b(jr|sr|ii|iii|iv)\b", "", s)
    return re.sub(r"[^a-z]", "", s)


def load_overrides():
    if OVERRIDES.exists():
        return json.loads(OVERRIDES.read_text())
    return {}


def save_overrides(data):
    OVERRIDES.write_text(json.dumps(data, indent=1))


def ecr_pos_ranks():
    """{norm_name: (pos, ecr_positional_rank)} from the cached ECR pull."""
    if not ECR.exists():
        sys.exit("no draftbot/ecr.json; run examiner.py --refresh first")
    ecr = json.loads(ECR.read_text())
    bypos = {}
    for k, v in ecr.items():
        bypos.setdefault(v["pos"], []).append((v["ecr"], k))
    out = {}
    for pos, lst in bypos.items():
        for i, (_, k) in enumerate(sorted(lst), 1):
            out[k] = (pos, i)
    return out


def divergences():
    """Material board-vs-ECR gaps, most divergent first."""
    board = json.loads(VOR.read_text())["players"]
    ecr = ecr_pos_ranks()
    rows = []
    for key, v in board.items():
        pos = v["pos"]
        got = ecr.get(key)
        ours = v["posRank"]
        theirs = got[1] if got and got[0] in (pos, "DST") else None
        if theirs is None:
            continue
        gap = theirs - ours  # positive: we are HIGHER on him than consensus
        if abs(gap) < GAP.get(pos, 5):
            continue
        if min(ours, theirs) > RANGE.get(pos, 40):
            continue
        rows.append(
            {
                "key": key,
                "name": v["name"],
                "pos": pos,
                "ours": ours,
                "ecr": theirs,
                "gap": gap,
                "adp": v["adp"],
            }
        )
    rows.sort(key=lambda r: -abs(r["gap"]))
    return rows


def cmd_report(_args):
    ov = load_overrides()
    rows = divergences()
    if not rows:
        print("no material divergences")
        return
    print(f"{'player':<24} {'pos':<5} {'ours':>4} {'ecr':>4} {'gap':>5}  {'adp':>5}  disposition")
    for r in rows:
        d = ov.get(r["key"], {})
        disp = d.get("action", "UNSIGNED")
        if disp == "keep":
            disp = f"kept: {d.get('thesis', '')[:40]}"
        side = "we reach" if r["gap"] > 0 else "we pass"
        print(
            f"{r['name']:<24} {r['pos']:<5} {r['ours']:>4} {r['ecr']:>4} "
            f"{r['gap']:>+5}  {r['adp']:>5.0f}  [{side}] {disp}"
        )
    unsigned = [r for r in rows if r["key"] not in ov]
    print(f"\n{len(rows)} divergences, {len(unsigned)} UNSIGNED")


def find_board_player(name):
    board = json.loads(VOR.read_text())["players"]
    key = norm(name)
    if key not in board:
        sys.exit(f"{name!r} not on the board")
    return key, board[key]


def cmd_keep(args):
    key, p = find_board_player(args.name)
    ov = load_overrides()
    ov[key] = {
        "name": p["name"],
        "action": "keep",
        "thesis": args.thesis,
        "signed": args.date,
    }
    save_overrides(ov)
    print(f"signed keep: {p['name']} -- {args.thesis}")
    # The bet must pay rent: register it in the ledger against the player
    # consensus would put in our slot (or an explicit --vs).
    rival = args.vs
    if not rival:
        ecr = ecr_pos_ranks()
        best = None
        for k, (pos, rk) in ecr.items():
            if pos != p["pos"] or k == key:
                continue
            d = abs(rk - p["posRank"])
            if best is None or d < best[0]:
                board = json.loads(VOR.read_text())["players"]
                if k in board:
                    best = (d, board[k]["name"])
        rival = best[1] if best else None
    if rival:
        subprocess.run(
            [sys.executable, str(HERE / "ledger.py"), "add",
             "--a", p["name"], "--b", rival,
             "--claim", f"signed divergence: {args.thesis}",
             "--basis", "pre-draft sign-off", "--date", args.date],
            check=False,
        )


def cmd_correct(args):
    key, p = find_board_player(args.name)
    ov = load_overrides()
    ov[key] = {"name": p["name"], "action": "consensus", "signed": args.date}
    save_overrides(ov)
    print(f"signed correct-to-consensus: {p['name']} (applies on next board build)")


def cmd_unsign(args):
    key, _ = find_board_player(args.name)
    ov = load_overrides()
    if ov.pop(key, None):
        save_overrides(ov)
        print("removed")
    else:
        print("no disposition to remove")


def cmd_status(_args):
    ov = load_overrides()
    for d in ov.values():
        line = f"{d['name']:<24} {d['action']}"
        if d.get("thesis"):
            line += f"  -- {d['thesis']}"
        print(line)
    unsigned = [r for r in divergences() if r["key"] not in ov]
    if unsigned:
        print(f"\nUNSIGNED divergences ({len(unsigned)}) -- sign before drafting:")
        for r in unsigned:
            print(f"  {r['name']:<24} {r['pos']} ours {r['ours']} vs ecr {r['ecr']}")
        sys.exit(1)
    print("\nall material divergences signed")


def main():
    ap = argparse.ArgumentParser()
    sub = ap.add_subparsers(dest="cmd", required=True)
    sub.add_parser("report")
    k = sub.add_parser("keep")
    k.add_argument("name")
    k.add_argument("--thesis", required=True)
    k.add_argument("--vs", default=None)
    k.add_argument("--date", default="")
    c = sub.add_parser("correct")
    c.add_argument("name")
    c.add_argument("--date", default="")
    u = sub.add_parser("unsign")
    u.add_argument("name")
    sub.add_parser("status")
    args = ap.parse_args()
    {
        "report": cmd_report,
        "keep": cmd_keep,
        "correct": cmd_correct,
        "unsign": cmd_unsign,
        "status": cmd_status,
    }[args.cmd](args)


if __name__ == "__main__":
    main()
