---
name: fantasy-football
description: Evidence-based fantasy football partner for Alex's season-long redraft league. Draft prep and live draft support, weekly lineup and waiver decisions, trade evaluation, and league analysis grounded in what the data actually shows predicts winning. Use when Alex mentions fantasy football, his league, a draft or mock draft, ADP, waivers or FAAB, start/sit, a trade offer, a player's value, "who should I start", "should I take X or Y", "is this trade fair", or wants help preparing for or running his fantasy season.
---

# Fantasy Football

Alex's partner for a **season-long head-to-head redraft league**. Everything here is
scoped to that format. Best-ball and DFS findings do not transfer cleanly (see
§8), and importing them is the most common way smart people optimize the wrong
objective.

This skill is built from a multi-agent research pass on 2026-08-16. Every number
below traces to a source in `references/evidence.md`. Claims marked UNVERIFIED
were not confirmable against a primary source. Do not launder them into
confident advice.

---

## 0. Alex's league (confirmed 2026-08-16)

Run by a friend of Alex Hedtke. **Snake draft, not yet scheduled. Head-to-head points,
FULL PPR.**

| Setting | Value |
|---|---|
| Roster | 16 total (9 starters, 7 bench, 1 IR) |
| Offense starters | 7: QB, RB, RB, WR, WR, TE, FLEX (ESPN default shape) |
| Required | 1 D/ST, 1 K |
| League size | **UNKNOWN — ask before building a draft board** |

**What this format implies, using §2-§4:**

- **Full PPR is the WR-friendly end of the spectrum.** Sharp's data: RB12 produces
  56.4% of RB1's output and lands **below WR24**, while WR12 is at 71.7%. WR
  value catches RB at the RB4 spot and never looks back. Lean receiver, and treat
  pass-catching backs as materially more valuable than their rushing volume alone
  suggests.
- **One QB slot, so wait.** Not superflex. QB scoring declines near-linearly by
  rank (Lee & Liu), QB6 historically returns ~72% of QB1's output, and Rounds 2-7
  NFL draft capital produced 4 QB1 seasons in 90 tries. Late QB is well supported
  here.
- **Both K and D/ST are required starters, which is where the herding edge is.**
  Draft them in the final two rounds and stream. When the room starts its K/DST
  run, do not follow: take the skill player they skipped. This is a documented,
  reproducible behavioral inefficiency and this format guarantees it fires.
- **The IR slot is free value most managers waste.** It lets Alex stash a
  high-upside injured player without paying a bench spot. Check league rules for
  which designations qualify (ESPN typically requires OUT/IR status, not
  questionable).
- **7 bench spots is generous**, which supports constant bottom-of-roster churn
  on small FAAB/waiver bids (§4) rather than hoarding handcuffs (§4, handcuffing).
- **Only 2 RB + 1 FLEX starting.** Combined with full PPR, this weakens the case
  for early RB volume beyond the genuinely elite tier.

**Still needed before a draft board:** league size (8/10/12/14 changes
replacement level and scarcity), draft slot once known, and whether the FLEX
allows TE. Ask for these rather than assuming.

---

## 1. The prior: set expectations before doing anything else

**A normal home league is mostly luck, and Alex should know that going in.**

Applying MIT's R\* skill metric to 4,115 teams across 1,252 repeated public ESPN
leagues (2019 to 2020, managers who missed a lineup filtered out), Alex Cates
measured **R\* = 0.19, roughly 20% skill and 80% luck**, comparable to stock
picking. Year-over-year correlation of a manager's z-scored points was **R² =
0.01**. Essentially no persistence.

This is *not* the same as MIT's widely-cited finding. Getty et al. (SIAM Review
2018, partially funded by FanDuel) studied **daily** fantasy on FanDuel, where you
are pooled against thousands of strangers of wildly varying skill. Even there,
NFL was the second most luck-driven of the four major sports (behind hockey),
needing roughly **25 contests** before skill dominates chance. A home league
compresses skill variance further, because ten friends self-select into similar
competence, then a 13-week head-to-head schedule adds noise on top.

Corroborating the ceiling:
- A genuinely above-average team (53% single-week win probability) wins a
  standard 3-round bracket only about **28%** of the time.
- Schedule luck: about **20% of teams finish "lucky," 20% "unlucky."** Applying a
  different random schedule to identical scores swung one team by **4 wins**.
- Each extra ~1 point per week of scoring edge is worth roughly **+0.7%**
  championship probability.

**How to use this.** Do not promise Alex a title. Frame the goal as *maximizing
his edge per decision*, then accept the variance. When he loses on a 150-point
opponent explosion, that is the format working as designed, not a process
failure. Equally, do not let a championship retroactively validate every choice
he made. Judge process, not outcome. This is the single most important thing
this skill does, because the entire fantasy content industry is built on
survivorship bias.

---

## 2. What actually predicts production, ranked by evidence strength

### Volume is sticky. Efficiency is not. This is the whole game.

Year-over-year self-correlation for WRs (4for4, 2017-2023, ≥30 targets in
consecutive seasons):

| Metric | YoY r | Predicts next-year PPG (r) |
|---|---|---|
| Slot rate | 0.75 | (role, not value) |
| Targets/game | 0.70 | 0.62 |
| Fantasy PPG | 0.68 | — |
| Yards/game | 0.67 | 0.67 |
| aDOT | 0.65 | (role, not value) |
| Targets per route run | 0.64 | 0.53 |
| Yards per route run | 0.56 | 0.59 |
| **TD rate** | **0.19** | — |
| Drop rate | 0.14 | — |
| Contested catch rate | 0.02 | — |

Football Perspective's regressions (2007-2012 PFF, 344 WR seasons) say the same
thing in R² terms: **TPRR R² = 0.41, YPRR R² = 0.21, yards per target R² = 0.08.**
Opportunity repeats. Catch efficiency barely does.

Rushing is worse. SumerSports found EPA per rush attempt has "virtually
negligible" year-over-year correlation, and the stickiest RB stat they located
was tackled-for-loss rate at ~0.40. Their verdict: rushing stats are excellent
*descriptive* statistics with "little predictive value in the long term."

**Operating rule: rank by projected opportunity, not by last year's results.**
When Alex asks about a player, lead with target share, routes run, snap share,
and touch share. Treat a great yards-per-carry season as noise about to
disappear.

### Touchdowns are close to pure noise

RotoViz, 2008-2017, 530 WR seasons with ≥50 targets in both years:

- Total receiving TDs → next-season TDs: **R² = 0.079**
- Red-zone TDs → next-season TDs: **R² = 0.029**
- 10-zone TDs → next-season TDs: **R² = 0.018**

Verbatim: "The R-squared values are all close to zero." A player coming off 12
TDs on modest volume is a sell. A player with heavy volume and bad TD luck is a
buy. This is the most reliable single edge available in a casual league, because
leaguemates price players almost entirely on last year's fantasy points, and
touchdowns are the loudest, least repeatable component of that total.

*Contested:* expected-TD (xTD) models are claimed to be both stickier and more
predictive than raw TDs, but two sourced figure sets disagree on whether xTD
actually out-predicts raw TDs for next season, and neither traced to an open
primary source. Treat xTD as directionally useful, not settled.

### Draft capital predicts, and it predicts by round

DynastyNerds, 11 draft classes:
- **QB:** Round 1 → 59.5% produce at least one QB1 season. Rounds 3-7 combined
  produced **4 QB1 seasons out of 90 quarterbacks (4.4%)**.
- **RB:** Round 1 (n=15) → 66.7% RB1, 80.0% RB2+. Round 2 (n=24) → 33.3% RB1.
  Round 4 → **6.3%** RB1.

PFF (1993-2016, all drafted skill players) found round-level R² of **0.85 to
0.95** for round vs. career fantasy PPG at RB/WR/TE, dropping to ~0.30 at the
individual-pick level. Round matters; exact pick much less.

### Age curves

Northwestern Sports Analytics (2007-2016, half PPR): top-20 RB finishes hold
steady through 28 (22 at age 27, 23 at age 28) then collapse (11 at age 29, 8 at
age 30). Over half of elite RBs posted a top-10 season at 28 and fell out of the
top 10 the very next year. A competing source puts the break at 27→28 instead.
The shape is real; the exact inflection is not settled, so do not quote a precise
cliff age.

WR breakout age (LevelUpFantasy, nflverse + CollegeFootballData): WRs who broke
out in college before age 20 posted top-24 PPR seasons at **38.6%** vs. **9.2%**
for late breakouts, and **10.4%** for those who never broke out.

### Environment

- **Offensive line matters far less than the broadcast narrative.** Adjusted Line
  Yards explains **28.9%** of RB half-PPR production (rushing only, essentially
  zero for receiving). For QBs, adjusted sack rate explains just **13.9%**. Use
  O-line as an RB tiebreaker, not a QB input.
- **PROE** (pass rate over expectation, from nflfastR's xpass model) isolates
  coaching intent from game script better than raw pass rate.

### Preseason strength of schedule is dead

Footballguys, six seasons of fantasy points allowed: "there is little predictive
quality for strength of schedule from one season to the next," and **exactly one
team repeated as stingiest against any position in six years.** 4for4 confirms
with 2015-2025 data: QB defense YoY r = 0.27 (the *highest*), RB 0.22, WR
essentially noise (23% top-5-to-top-5 repeat rate).

If Alex is choosing between two similar players based on schedule, tell him it is
a coin flip and pick on volume instead. Playoff-weeks (15-17) SOS is plausibly
more useful but is UNVERIFIED.

---

## 3. Draft protocol

### The uncomfortable headline: strategy choice barely matters

An independent open-source simulation (dlm1223, half-PPR 12-team, 2008-2018
projections, 2,000 simulated seasons per variant) tested Zero RB, Zero WR, Zero
QB, and backup-position strategies across every draft slot. Conclusion, verbatim:
"Zero RB does seem to perform better than zero WR, but in general, strategy seems
to have only a small effect for most of the draft slots... most strategies did
similarly, **finishing within 10-20 points**." What mattered more was handling of
backup QB and TE.

So do not let Alex agonize over a named strategy. The leverage is in *player
selection within a tier* and *in-season management*, not in the sequencing
doctrine.

### Zero RB specifically: the edge has been arbitraged away

Shawn Siegele's 2013 RotoViz piece founded it. The mechanism was real: mine
league-winning RBs off the wire while others paid up. FTN documented 13 sub-RB40
ADP backs finishing RB15+ from 2017 to 2024, then showed that through Week 8 of
2025 only one sub-RB40 back was inside the top 15 while **14 of the top 16 ADP
backs were hitting as RB2 or better**. Establish The Run separately documented the
"RB dead zone" (rounds 3-6) eroding as ADP corrected.

Note the format dependency that gets lost: a 500,000-run Monte Carlo found RB-heavy
early builds optimal in **best ball**, where there is no waiver wire, which is
exactly the mechanism Zero RB depends on. Zero RB is a *redraft* strategy.

### Positional value depends entirely on scoring

Sharp Football Analysis, 2015-2020:
- **PPR:** WR6 produces 81.5% of WR1's output, WR12 produces 71.7%. RB6 is at
  69.5%, RB12 sags to **56.4%** (below WR24). WR value catches RB at RB4 and never
  looks back.
- **Standard:** the RB advantage holds nearly all the way through the top 24.
- **Half PPR:** they cross around WR12/RB12.

Lee & Liu (peer-reviewed, 1,350 leagues) confirm the underlying math: QB, K, and
DST scoring declines near-linearly by rank (small cliff), while RB/WR/TE drop
sharply then flatten. That is the formal case for "start more RB/WR early, let QB
and K and DST wait."

**Always confirm Alex's actual scoring settings before giving any draft advice.**
PPR vs. standard inverts the RB/WR recommendation. Superflex roughly doubles QB
value by removing the one-QB start constraint. TE premium is smaller than people
assume (one worked example moved a TE's value **+19.9%**, not ~50%).

### The exploitable edge is your leaguemates, not the players

Lee & Liu's strongest finding: drafters "use a more narrow range of strategies
than is likely optimal," building rosters that *look like* the required starting
lineup (representativeness heuristic). **The three most common team compositions
accounted for ~60% of teams and underperformed.** The compositions with win rates
clearly above 50% skewed toward more RB/WR and fewer K/DST resources.

They also documented **herding**: once one manager drafts a defense, the
conditional probability that the next manager also drafts one jumps far above
baseline, "for almost all kicker and defense selections" and for QBs in roughly
the first 20 picks. Copying the herd showed no win-rate benefit (Bayes factors
4.7 to 8.8 favoring no difference).

**Operating rule: never chase a K/DST/QB run.** Let the room reach. Take the skill
player they skipped.

### K and DST: last two rounds, then stream

Subvertadown's 3-season weekly projection study found K and DST have the lowest
projection accuracy of any position, "significantly worse" than even WR1. 4for4's
defense data confirms fantasy points allowed barely repeats year to year. Their
stated rule, worth quoting to Alex directly: draft a position early only if it is
scarce, has a high drop-off, is predictable, and does not depend on opponent. K
and DST fail three of four.

### Draft slot

Weak and contested. A ~4 million draft Monte Carlo (FantasySharks) found
traditional snake order biased toward early picks, worsening as drafters deviate
more from ADP, with third-round reversal reducing but not eliminating it. Lee &
Liu found early slots outperformed *except the literal 1.01*, and the authors
themselves flag it as possibly a one-season artifact needing replication.

FTN claims teams from the first three slots post "win rates 20-30% higher." That
article cites **no source, no methodology**, and shows structural signs of
low-effort SEO content. **Do not repeat that figure.**

### Stacking: genuinely contested, present both sides

- **For:** Establish The Run (FFPC ADP, 3 seasons). Pass-catchers attached to a QB
  who hit at "medium" or better beat ADP by **+31.2 points** (71% hit rate,
  n=63); attached to a big-hit QB, **+36.0 points** (74%, n=35). Recommends
  reaching 1 to 1.5 rounds.
- **Against:** One Week Season argues stacking is a variance-manipulation tool
  built for large-field tournaments, and that concentrating correlated risk is
  wrong when you only need to beat one opponent. Case study showed the best
  *unstacked* WR pair produced more combined WR1 weeks than the marquee stack.

Both are credible. They disagree on mechanism, not magnitude. Give Alex both and
note that the "against" case aligns with the formal H2H math in §8.

---

## 4. In-season protocol

This is where the real edge lives, since the draft strategy differences wash out
to 10-20 points.

### Waivers and FAAB

FantasyPros analyzed **600,000+ player adds from 2024**. On a $100 budget
(their figures are per $1,000, divided by 10 here):

| Position | Median winning bid |
|---|---|
| WR | $2.90 |
| QB | $2.10 |
| RB | $2.10 |
| TE | $2.00 |
| DST | $1.00 |
| K | $0.30 |

Week 1 median winning bid: **$1.10**, with outliers up to $76.

**The FAAB dead zone: bids of 10-19% of budget "rarely returned winning
production."** Too expensive to be churn, too cheap to lock a genuine weekly
starter. Advise Alex to bid either small (churn the bottom of the roster
constantly) or decisively large (20%+ for a player he believes is a true
difference-maker). The middle is where budget goes to die.

### Lineups: the variance rule

There is a formal treatment, though it is derived in basketball and applied to
fantasy by inference rather than direct test. Worked example: a 6-point underdog
with a 12-point SD wins 31% of the time. Trading 2 points of expected value for
higher variance (SD → 20) raises win probability to **34.5%**. Symmetrically, a
favorite cutting SD from 12 to 6 at a 2-point EV cost raises win probability from
69.1% to **74.8%**.

**Operating rule:**
- **Projected underdog → start the boom/bust player.** Ceiling wins games you are
  losing on median.
- **Projected favorite → start the safe floor.** Do not need the ceiling; need to
  not lose.

Always check the projected margin before answering a start/sit question. The same
two players produce opposite recommendations depending on which side of the
matchup Alex is on. This is the highest-leverage weekly habit in the whole skill
and almost nobody in a casual league does it.

### Trades

Behavioral biases are documented (Renee Miller, University of Rochester):
endowment effect (overvaluing your own roster), primacy (Week 1 anchoring),
recency, confirmation bias. The trade edge in a casual league comes from
exploiting these, mainly by buying players with strong volume and bad TD luck and
selling players with weak volume and great TD luck.

**No trade analyzer on the market has any published calibration evidence.** That
absence is the finding. Treat every "trade fairness" score as an unvalidated
heuristic against that site's own value chart. Reason from volume metrics instead.

No study was found testing whether active traders actually win more. If Alex wants
to know, pull his league's trade log against final standings via the platform API
and compute it. That is a better use of an afternoon than reading another take.

### Handcuffing does not work the way it is sold

Three independent lines converge:

1. **Lee & Liu (peer-reviewed, verified verbatim at source):** 793 teams that
   drafted both players in one of 32 known handcuff pairs won **51.04%** of games
   vs. **50.56%** for teams with no handcuff pairs. Hierarchical Bayesian test:
   **Bayes factor 4.2 in favor of sameness.** The same paper found "little to no
   evidence for the use" of handcuffing in the first place.
2. **283 team-seasons (2015-2018, 2020-2024):** primary backups finished RB24+
   only **13.8%** of the time, median finish RB51. Even when the starter missed
   6+ games, the rate rose only to 23.3%.
3. **The mechanism, and the actually useful version:** splitting that
   injury-window group by the backup's own early workload, *clean* backups (under
   35% of early carries) hit RB24+ just **6.5%** of the time, while committee
   backs who already had 35%+ of early carries hit **29.3%**. Verbatim: "The best
   predictor of a late-round back's season was touches he already had, not the
   injury he was waiting for."

**Operating rule: do not draft your own stud's backup. Draft ambiguous backfields
where the cheap back already has real touches.** Roughly 4x the hit rate.

---

## 5. Tools

### Run locally (verified against the GitHub API, 2026-08-16)

| Tool | Status | Notes |
|---|---|---|
| `nflreadpy` (Python) | **Active**, 193★ | **Use this.** Official successor to nfl_data_py |
| `nfl_data_py` (Python) | **ARCHIVED 2025-09-25** | Every tutorial still points here. Do not use |
| `nflfastR` (R) | Active, 536★ | Play-by-play engine |
| `nflreadr` (R) | Active, 110★ | Snap counts (2012+), NGS (2016+), depth charts |
| `ffanalytics` (R) | Active, 187★ | Scrapes and aggregates projections from ~10 sources |
| `espn-api` (Python) | Active, 937★, MIT | Best ESPN wrapper. Private leagues need `espn_s2` + `SWID` |
| Sleeper API | Official, no auth | `api.sleeper.app/v1`, GET-only. Easiest to build against |
| `yfpy` / `yahoo_fantasy_api` | Active | Yahoo needs OAuth2 app registration |
| `ffscrapr` / `ffsimulator` (R) | **Stale** since late 2024 | League API access + season sim. **Smoke-test before draft day** |
| Boris Chen tiers | Active (pushed 2026-08-14) | Gaussian mixture clustering on ECR → visual tiers. Free |

Per the automate-it rule: prefer pulling Alex's league via API and computing
answers over eyeballing a website. Sleeper is the easiest target if he has a
choice of platform.

### Projections reality check

Fantasy Football Analytics (2019-2023 MAE study): **no single projection source
wins consistently** year over year (CBS was #1 for QBs in 2019, 6th in 2021), but
a simple *average across sources* stayed top-3 or top-4 in every position every
year. Wisdom of crowds is the free lunch.

Their 2025 bias study is the reality check on the accuracy ceiling: over
2019-2024, elite players are systematically **over**-projected. RB1-5 miss
projections by ~55 points per season, QB6-10 by ~42 (worsening to ~80 recently),
WR1-5 by ~31, TE1-5 by ~23.

Footballguys' Harstad found a naive 50/50 blend of preseason ADP and four games
of actual production beat either alone in 4 of 5 position buckets, and a
professional projector beat that blend only "on the margins." **Consensus ADP is
already a strong model.** Beating it requires a specific reason, not vibes.

FantasyPros runs an annual accuracy competition over 150+ analysts with published
methodology. Two independently verified performers: Jody Smith (Draft Sharks) tops
the 2023-2025 multi-year draft leaderboard; Patrick Thorman (Establish The Run)
placed 2nd in 2025 in-season.

---

## 6. Do not bother

Ranked by how confidently the evidence says to skip it:

1. **Preseason strength of schedule.** One team repeated in six years.
2. **Handcuffing your own RB1.** 6.5% hit rate even in the injury scenario.
3. **Chasing a K/DST run.** Documented herding with no win-rate benefit.
4. **Last year's touchdown totals.** R² = 0.079.
5. **Efficiency stats as a projection input.** Yards per target R² = 0.08.
6. **Trade analyzer verdicts.** Zero published calibration.
7. **Agonizing over Zero RB vs. Robust RB.** 10-20 points across a season.
8. **Any "20-30% higher win rate" style claim with no methodology.** The one found
   in this research traced to unsourced SEO content.

---

## 7. How to answer Alex

- **Confirm format first.** Scoring (PPR/half/standard), league size, roster slots,
  superflex, waiver system. Half this document's advice inverts on these.
- **Lead with opportunity metrics.** Target share, routes, snap share, touch share.
- **Name the confidence level.** Distinguish "peer-reviewed, 1,350 leagues" from
  "one blog with a plausible method." Both appear here and they are not equal.
- **Check the projected margin before any start/sit call.** Underdog wants
  variance, favorite wants floor.
- **Flag the luck prior when he is results-reasoning.** Both directions: a loss
  is not proof of a bad process, and a win is not proof of a good one.
- **Never present a contested question as settled.** Stacking and xTD are live
  disagreements. Say so.
- **Automate the recurring stuff.** League pulls, waiver scans, and roster
  analysis belong in a script against the platform API, not in repeated manual
  lookups. Log anything reusable to the tools registry.

---

## 8. Why best-ball and DFS advice does not transfer

Alex will encounter enormous amounts of content optimized for the wrong game.

Haugh & Singal (*Management Science* 2021, tested with real money on FanDuel
across all 17 weeks of 2017) formally prove that contest structure determines the
objective function:

- **Double-up / head-to-head** (beat one threshold or one opponent): **minimize
  variance conditional on a positive expected edge.**
- **Top-heavy tournament** (climb a huge field): **maximize variance and
  diversify** across entries.

Season-long H2H is structurally the *first* case each week. Best ball is closer to
the second, and it additionally has **no waiver wire, no trades, and no lineup
decisions**, so its entire roster-construction logic assumes you cannot fix a bad
build in-season. That assumption is false in redraft.

So: "embrace volatility, draft for ceiling, load up WR" is correct advice for
best ball and misapplied in Alex's league. The right redraft frame is *acquire a
positive-expectation core, then manage variance week to week based on whether you
are favored*.

One more calibration point. Mahoney & Paniak (arXiv 2023) built an ML projection
plus integer-programming lineup optimizer and it landed at roughly the **31st
percentile** against real human DraftKings lineups. A competent model is not an
automatic edge over a motivated field.

---

## 9. Evidence and caveats

Full sourcing, confidence levels, and every unverified claim are in
`references/evidence.md`. The vault report is at
`~/Exobrain/Research/Fantasy Football Winning Strategy.md`.

Standing caveats:
- Academic work on **season-long redraft is thin**. The rigorous math (Hunter et
  al. 2016, Haugh & Singal 2021, Bergman et al. 2021) is nearly all DFS lineup
  optimization. Only Becker & Sun (2016) and Fry et al. (2007) touch season-long,
  and both are dated. On redraft strategy the practitioner analytics community is
  genuinely ahead of academia, so most sourcing here is industry work whose
  underlying datasets cannot be independently verified.
- **No formal equilibrium analysis of snake or auction drafts exists** in the
  peer-reviewed literature. No academic study of the winner's curse inside a
  fantasy auction exists either; Massey & Thaler (2013) is about real NFL front
  offices and applies only by analogy.
- **Nothing found decomposes final standings variance** into draft vs. in-season
  moves vs. schedule luck with an actual number. That would be the single most
  useful missing statistic for prioritizing effort.
- Getty et al. (2018), the most-cited skill-vs-luck paper, **was partially funded
  by FanDuel**, which had a regulatory interest in fantasy being ruled a game of
  skill. The paper states FanDuel exercised no editorial control. Mention the
  funding when citing it.
