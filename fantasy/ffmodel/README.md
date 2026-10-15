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
| `injury.py` | How often does a player on the injury report play, and how many points does he get? | nflverse injury reports and snap counts, 2016-2025 | `espn check` (`p_play`, `practice`, `injury_ratio`) |
| `fpranks.py` | Do MIST's weekly ranks beat the FantasyPros consensus on FantasyPros' own method? | the four FantasyPros weekly ranking pages, the projections above, box scores | `fpranks snapshot` (Sunday lineup run), `fpranks score` (Tuesday review) |
| `role.py` | Can a projection built from opportunity shares alone add to Sleeper and the market? | nflverse box scores, snap counts, participation (routes, 2016-2025) | nothing: it did not earn a vote (research artifact) |

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
| A quarterback and his own WR1 | +0.39 |
| A quarterback and his own TE1 | +0.31 |
| A D/ST and the RB1 it faces | -0.29 |
| A D/ST and the kicker it faces | -0.27 |
| A quarterback and his own WR2 | +0.26 |
| A D/ST and its own kicker | +0.22 |
| The two quarterbacks in one game | +0.17 |

`python3 -m ffmodel.corr validate` estimates on 2022-2024 and scores
synthetic 2025 matchups, with the spread table `espncli/value.py` uses
(CV_TABLE, variance-matched on 2026-10-15). Random lineups: the 90% interval
of the margin contained 91.2% of results with no correlation and 91.3% with
correlations, thus no change. Stacked lineups (QB with his WR1, D/ST against
the other QB): 86.6% with no correlation and 90.5% with correlations.

**Market (`market`).** One linear model for each position, on the core
lines of the position plus the implied team total. Out of sample, the market
model and Sleeper have the same error on all players with lines (MAE 5.13
against 5.13 on 2024, 5.09 against 5.06 on 2025, 5.16 against 5.16 on
2026). The mean of the two is better than each source alone. In `espn
check` the lineup mean weights the market 0.75: on 842 rostered 2026
player-weeks the error fell as the market's weight rose (ESPN alone 5.885,
even 5.777, market alone 5.721). On players rostered in the league in
2026, weeks 1-5 (n = 833), the market's MAE is 5.70, Sleeper's is 5.78 and
ESPN's is 5.86. The market beats ESPN by 0.162 (95% CI 0.065 to 0.261) with
closing lines and by 0.135 (0.032 to 0.237) with opening lines. The model
reads only core lines, because books post different menus. A model that
read "this line is missing" as information gave 2024 quarterbacks an error
of 8.4, against 6.0 for Sleeper.

**Injury report (`injury`).** Regular contributors (40% or more of the
snaps in a recent game) listed questionable played 0.71 of the time: 0.45
after a missed practice, 0.73 after a limited one, 0.88 after a full one,
and 0.53 for a quarterback. Doubtful played 0.01, out 0.001. When a
questionable player played, he got 0.91 of his projection against
players not on the report. `espn check` reads this week's practice line,
scales ESPN's part of the mean by the ratio (the market already prices the
report), and treats a questionable starter as a mixture with the bench
cover that kicks off no earlier than he does. Our side gets the cover at
rate 1, because `lineup-watch --fix` makes the swap. A rival gets it at his
manager's measured fix rate (bye holes fixed over faced, shrunk as
(fixed + 1) / (faced + 2)), and his bye and OUT holes are priced the same
way. Until 2026-10-15 a rival's questionable starter counted as certain to
play, which put the week 6 opponent 12.1 points too high.

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

**FantasyPros method (`fpranks`).** On 31 past weeks (2024-2026) scored by
FantasyPros' published accuracy method, MIST's ranks (the mean of Sleeper,
ESPN and the market, on half PPR) had a mean gap of 6.581 points a scored
player-week against 6.707 for FantasyPros' consensus (difference -0.126,
95% CI -0.182 to -0.071), 6.623 for Sleeper and 6.646 for the market. The
archived consensus is a Friday snapshot in PPR order, so part of the lead
can be timing. From week 6 the Sunday lineup run saves both lists at the
same moment before the 1 p.m. ET games (`forecasts/fp/`), and the Tuesday
review scores them.

**Role model (`role`).** Team volume from the spread and the total, player
shares from a discounted Beta-Binomial filter with partial pooling, and
points per opportunity shrunk to the position. Walk-forward on 2022-2025
(16,596 player-games) it is worse than Sleeper alone (MAE 4.51 against
4.35) and adds nothing to the Sleeper and market blend (+0.002, 95% CI
-0.009 to +0.014): its errors correlate 0.96 with both. Routes from the
participation data beat snap share by 0.004, all of it at tight end. A
planted source with the same error and a small amount of new information
moves the blend by -0.099, so the test can see a gain. It stays out of the
lineup and the forecast.

## Outside checks on actual leagues

`fantasy/research/sleeper_validation.py` tests the models on hundreds of
public Sleeper leagues (2024-2025) that played no part in fitting them.

- **Win probability:** on 58,779 regular-season matchups in 754 leagues,
  the `espn check` model (Sleeper projections scored on each league's own
  rules, the CV_TABLE spreads) is calibrated to about one point in every
  decile (Brier 0.202). Correlations change nothing there, because real
  lineups seldom stack.
- **Bye odds:** from the week-5 standings of 857 leagues, a fixed-strength
  season model was overconfident about the leaders (0.55 predicted, 0.47
  observed; 0.65 against 0.55). A 6-point weekly drift in team strength
  brings those to 0.54 and 0.64 with the best Brier score, and
  `season_sim.py` now uses it.

## Commands

```sh
python3 -m ffmodel.nflraw 2025            # build the parquet caches for a season
python3 -m ffmodel.props 2026 --weeks 6-6 # crawl a finished week's props (settle does this)
python3 -m ffmodel.market fit --seasons 2024,2025
python3 -m ffmodel.market evaluate        # leave-one-season-out + 2026 three-way
python3 -m ffmodel.market week 7          # this week's market projections
python3 -m ffmodel.corr                   # rebuild corr_table.json
python3 -m ffmodel.corr validate          # the out-of-sample coverage check
python3 -m ffmodel.injury                 # rebuild injury_table.json
python3 -m ffmodel.fpranks week 7         # MIST's half-PPR ranks at contest depth
python3 -m ffmodel.fpranks snapshot 7     # save MIST and FantasyPros side by side (Sunday)
python3 -m ffmodel.fpranks score          # score every saved week
python3 -m ffmodel.role 7                 # the role model's projection (research)
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
- The injury table is fitted on the final report of each week (Friday for a
  Sunday game). Before that report, `current()` reads the practice line so
  far, often Wednesday's. A Wednesday DNP that becomes a Friday LP thus
  reads as a final DNP (0.45 against 0.73). nflverse's injury file keeps
  one row per player-week (6,068 of 6,068 in 2025), so this is not
  measured; read a Thursday price as provisional.
