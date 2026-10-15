# ffmodel

Statistical models for the fantasy tools. They start from raw data: box
scores, betting lines, and the archived projections that the models score
against. Built 2026-10-15, when Alex asked for a deeper version of the system
rather than a bigger one. Each module answers one question, and its number
has been tested on seasons that the fit did not see.

| Module | Question | Raw input | Used by |
|---|---|---|---|
| `nflraw.py` | What did each player score in this league? | nflverse box scores, schedules with closing lines, the cross-site id table, Sleeper's archived weekly projections | all modules here |
| `props.py` | What did the betting market forecast for each box score? | ESPN's core API player props (ESPN BET to late 2025, DraftKings from 2026) | `market.py` |
| `market.py` | How many points do those lines give? | `props.py` + `nflraw.py` | `forecast dossier` (the `market` vote), `forecast settle` and `history` (closing line value) |
| `corr.py` | Which starters' weekly surprises move together? | `nflraw.py` residuals against Sleeper's projections | `espncli.value.win_prob`, so `espn check` and `espn matchup` |
| `score.py` | Is a forecast good, and not only sufficiently wide? | the filed `forecasts/*.json` | `forecast history` |

## What each one measured

**Scoring (`nflraw`).** Compared with ESPN's weekly totals for all players
rostered in the league, 2026 weeks 1-5. QB, RB, WR, TE and K agree with
ESPN to the decimal on 854 of 854 player-weeks. D/ST agrees on 66 of 72,
with a mean error of -0.15. The differences are a sack or a return
touchdown that nflverse does not record. ESPN's yards allowed is the opponent's net yards (sack
yardage subtracted), and its points allowed leaves out the opponent's
defensive and return touchdowns.

**Correlations (`corr`).** Residual correlations, 2022-2025, stable in each
season. The largest correlations are these:

| Pair | rho |
|---|---|
| A D/ST and the quarterback it faces | -0.48 |
| A quarterback and his own WR1 | +0.38 |
| A quarterback and his own TE1 | +0.30 |
| A D/ST and the RB1 it faces | -0.30 |
| A D/ST and the kicker it faces | -0.27 |
| A quarterback and his own WR2 | +0.26 |
| A D/ST and its own kicker | +0.22 |
| The two quarterbacks in one game | +0.16 |

`python3 -m ffmodel.corr validate` estimates on 2022-2024 and scores
synthetic 2025 matchups. Random lineups: the 90% interval of the margin
contained 88.4% of results with no correlation and 88.3% with
correlations, thus no change. Stacked lineups (QB with his WR1, D/ST against
the other QB): 83.3% with no correlation and 87.4% with correlations.

**Market (`market`).** One linear model for each position, on the core
lines of the position plus the implied team total. Out of sample, the market
model and Sleeper have the same error on all players with lines (MAE 5.13
against 5.13 on 2024, 5.09 against 5.06 on 2025, 5.16 against 5.16 on
2026). The mean of the two is better than each source alone. On players rostered in the league in
2026, weeks 1-5 (n = 833), the market's MAE is 5.70, Sleeper's is 5.78 and
ESPN's is 5.86. The market beats ESPN by 0.162 (95% CI 0.065 to 0.261) with
closing lines and by 0.135 (0.032 to 0.237) with opening lines. The model
reads only core lines, because books post different menus. A model that
read "this line is missing" as information gave 2024 quarterbacks an error
of 8.4, against 6.0 for Sleeper.

**Proper scores (`score`).** The weighted interval score (WIS), and the
position of each result in the forecast distribution. On the 59 settled player lines of weeks
2-5, MIST's WIS is 3.11 and the baseline's is 3.25 (difference -0.14, se
0.12). 36% of results occurred between MIST's 75th and 95th percentiles,
against 20% for a calibrated forecaster. Thus MIST's medians and the top of
the 50% band are too low.

**Closing line value (`market.clv`).** On weeks 2-5, with the opening line
standing in for the market at forecast time (n = 47, 21 lines that moved),
MIST's lean against the market had a correlation of +0.16 with the
subsequent move, and the lean had the direction of the move 9 times in 21.
This gives no indication of an edge above the market. On the same rows the closing market
had an MAE of 5.54. MIST's MAE was 6.10, the consensus 5.70 and ESPN 5.63.
From 2026-10-15, `forecast record` keeps the market value at forecast
time, thus subsequent weeks measure the actual lean.

## Commands

```sh
python3 -m ffmodel.nflraw 2025            # build the parquet caches for a season
python3 -m ffmodel.props 2026 --weeks 6-6 # crawl a finished week's props (settle does this)
python3 -m ffmodel.market fit --seasons 2024,2025
python3 -m ffmodel.market evaluate        # leave-one-season-out + 2026 three-way
python3 -m ffmodel.market week 7          # this week's market projections
python3 -m ffmodel.corr                   # rebuild corr_table.json
python3 -m ffmodel.corr validate          # the out-of-sample coverage check
```

Start the commands in `fantasy/`. Caches go to `fantasy/.cache/nflraw/` and
`fantasy/.cache/props/` (gitignored). `corr_table.json` and
`market_model.json` are fitted coefficients and are tracked, thus a new
clone computes the same numbers.

## Limits

- The 2026 DraftKings data has no prices. A line is read as the market
  median, and touchdown odds are not available. Thus the touchdown part of
  the market projection comes from the implied total and the yardage lines.
- ESPN BET props stop after 2025 week 13. ESPN then moved to DraftKings, and
  the late-2025 DraftKings games have no props in the data.
- A prop is void when the player does not play. Thus a market projection is
  conditional on playing. The injury status gives the risk that the player
  does not play.
