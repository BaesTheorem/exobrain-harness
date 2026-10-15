# research

Reproducible tests behind the fantasy rules. Each script reads raw data
(nflverse box scores through `ffmodel.nflraw`, archived projections, public
leagues), tests one rule on seasons the rule was not fitted on, and writes
its numbers to `out/`. The playbook's *Corrections ledger* and the vault
notes in `~/Exobrain/Research/` cite these files. Built 2026-10-15.

| Script | Question | Output |
|---|---|---|
| `rule_backtests.py` | Do the in-season constants hold? `ros_rate` blend, player spread, D/ST and K streaming gaps, BUY/SELL gap, waiver gate, backup QB/TE allowance, one- against two-week role reads, the own-ratio blend, the review alarms | `out/rule_backtests.json` |
| `role_eval.py` | Does a Bayesian opportunity model (`ffmodel/role.py`) add to Sleeper and the market? | `out/role_eval.json` |
| `fp_eval.py` | Do MIST's ranks beat FantasyPros' consensus on FantasyPros' own accuracy method? | `out/fp_eval.json` |
| `sleeper_crawl.py` | Crawls public Sleeper leagues (2024-2025) for the two scripts below | raw files in `/tmp/ffvoi`, never in the repo |
| `standings_decomp.py` | Where do final standings come from: draft, acquisitions, lineups or schedule luck, and which parts persist for a manager? | `out/standings_decomp.json` |
| `sleeper_validation.py` | Is `espn check`'s win probability calibrated on real matchups, and is `season_sim.py` calibrated on real seasons? | `out/sleeper_validation.json` |

## Rules

- Hold a season out. A number fitted on a season is never scored on it.
- Every test carries a positive control (a planted effect it must find) and,
  where it fits, a shuffled or null control (an effect it must not find).
- Public league data is other people's data: the crawl stays in `/tmp`, and
  only aggregates (no league ids, user ids or names) enter `out/`.
- One Python process at a time on the 8 GB Mac; load one season of
  play-by-play or participation at a time.

## Running

From `fantasy/`:

```sh
python3 research/rule_backtests.py ros|spread|dst|k|flags|gate|backup|role|ownratio|alarms
python3 research/role_eval.py
python3 research/fp_eval.py
python3 research/sleeper_crawl.py --seed-league <id> --target 1000   # slow: hundreds of leagues, 2024-2025
python3 research/standings_decomp.py
python3 research/sleeper_validation.py winprob|byes|all
```
