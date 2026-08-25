---
name: fantasy-football
description: Evidence-based fantasy football partner for Alex's season-long redraft league. Draft prep and live draft support, weekly lineup and waiver decisions, trade evaluation, and league analysis grounded in what the data actually shows predicts winning. Use when Alex mentions fantasy football, his league, a draft or mock draft, ADP, waivers or FAAB, start/sit, a trade offer, a player's value, "who should I start", "should I take X or Y", "is this trade fair", "join this draft", "drive my draft", "run the autopilot", or wants help preparing for, automating, or running his fantasy season.
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

## Live league data

`fantasy/bin/ff` in the harness reads the real league over the ESPN API
(read-only). Use it before answering anything that depends on current state:

- `ff standings` — table with the bye (top 2) and playoff (top 6) cutlines
- `ff roster` — Chaos Legion's current roster
- `ff raw --views mMatchup,mRoster,kona_player_info` — raw API for new features
- `ff refresh` — re-pull ESPN cookies from Chrome when auth expires (401/403)

Credentials live in the gitignored `fantasy/espn-credentials.json`; details and
the known two-teams-one-account quirk are in `fantasy/README.md`. The tool never
writes to ESPN. Extend it (waiver opportunity ranking, TD-regression scan,
projected-margin for the variance rule) rather than scraping the site by hand.

## Draft mode: the autopilot

`fantasy/draftbot/` drafts a full roster in the ESPN draft room against a ranked
board. Where `ff` is read-only by invariant, **this one writes** — it clicks the
draft button. Keep that boundary intact; never add pick-making to `ff`.

**Never be in the per-pick loop.** The clock is 30 seconds in mocks and 90 live,
and bot teams pick in about a second. A round trip out to Claude costs 20-60
seconds and can never keep up. So the agent runs *inside* the ESPN page on a
250ms timer and picks in milliseconds; supervise **between** picks, not during
them. This is the whole design, and violating it is how the first attempt failed.

```sh
python3 driver.py &     # holds a logged-in browser; reads url.txt
python3 arm.py board    # rebuild vor.json -- do this the MORNING OF the draft
python3 arm.py arm      # inject and start the autopilot
python3 arm.py queue N  # fill the ESPN queue (autopilot also self-fills)
python3 arm.py status   # roster counts, picks made, recent log
python3 peek.py         # the actual roster with byes; safe mid-pick
python3 arm.py off      # stop picking, leave the queue as a floor
python3 watch.py        # stream picks, one event per line
```

`arm.py` and `watch.py` share one command channel — **never run both at once**,
they race on `result.json`. `state.json` is written independently, so read that
for a race-free look at the room.

### Pre-draft checklist, in order

Everything must be armed and tested **before** the room opens. Building it
against a live clock is how picks get lost.

0. **The draft-morning sequence, in this exact order** (each later step
   consumes the one before it; running out of order builds the board on stale
   sources):

   ```sh
   python3 fantasy/ringer_board.py          # 1. re-pull the Ringer board
   python3 fantasy/examiner.py --refresh    # 2. re-pull FantasyPros ECR
   python3 fantasy/opportunity.py           # 3. 2025 volume + BUY/SELL flags
   python3 fantasy/vor.py                   # 4. build the board (or arm.py board)
   python3 fantasy/signoff.py status        # 5. THE GATE -- must exit clean
   python3 fantasy/tier_sheet.py            # 6. regen draft-sheet.html w/ flags
   ```

   Step 5 exits nonzero while any board-vs-ECR divergence is unsigned. Alex's
   standing rule (2026-08-24): **no counter-consensus pick reaches the draft
   without a signed thesis.** Source drift overnight can surface new
   divergences; each gets `signoff.py keep --thesis` (registers the bet in
   the ledger) or `correct` (re-slots to consensus; rebuild the board after
   correcting, then re-run the gate). A BUY flag from step 3 is exactly the
   kind of thesis a keep wants. Alex signs; MIST never signs for him.

   Also that morning: re-pull the league schedule to confirm the Week 8 idle
   week survived any late team change, and second-screen `draft-sheet.html`.
   **After the draft, before navigating away**: `draftbot/grade.py --judge
   both` (practice leagues 404 later; the live league keeps) and
   `examiner.py --live` for the audit trail.
1. **Be in the draft room before it opens.** Absence is not falling behind, it is
   ESPN drafting your whole team. It made 73 picks in ~90 seconds on 2026-08-24
   because every team was flagged AUTO. Entering clears the flag on *upcoming*
   picks only; what is already drafted is gone.
2. **Exactly one connection per team.** If the bot drives, Alex must not open the
   draft room in his own browser, or ESPN bumps one session with "Duplicate
   Connection" and the bot goes blind against a frozen board. He watches the
   bot's window instead.
3. **The queue cannot be preloaded.** ESPN silently ignores queue clicks before
   the draft starts — the click lands and nothing happens. The autopilot fills it
   in the first seconds after the clock starts, and only while not on the clock.
4. Confirm `arm.py status` reports the right round and a nonzero valued count.
5. **Arm once, before the room opens.** Re-arming mid-draft wipes the in-page log
   and pick history (the roster is read from the page, so nothing real is lost,
   but the diagnostics are).
6. A **practice draft can be paused** from the League Manager tab, which makes
   mocks the place to fix things. The live draft will not wait.

### It scores on value over replacement

Fixed on 2026-08-24, replacing raw board rank. Rank compares a player to the
whole field; a pick is decided by how much better he is than the man you could
have at that position anyway. Ranking on the field is why the first two mocks
took a QB in round 4 and never took a tight end.

`fantasy/vor.py` splits the work by what each source is good at. **The Ringer**
decides *who* is the best player at a position; **ESPN's 2026 projections**,
which come back already scored in this league's full-PPR settings, decide *how
much* a WR3 is worth against an RB5. Value is the player's slot on his position's
projection curve minus the replacement slot (QB13, RB30, WR34, TE14 — starters,
flex weighted to WR).

This reproduces §3's positional rules without hand-tuned constants, which is why
it is the right fix:

- **QB waits by itself.** The curve is a cliff at Josh Allen then nearly flat:
  QB2 to QB10 spans only 30 points across a season. No "don't draft a QB before
  round N" rule is needed, and none is used.
- **A tight end finally competes.** The elite TEs price near 83 VOR against a
  14th TE who is dreadful, so one gets taken while one still exists.
- **The receiver lean falls out of the curve** rather than a bonus constant.

Byes are a tiebreak only, never a reason to reach: a small penalty for stacking a
week already on the roster, and a small bonus for Week 8, free because the league
has 13 teams and Alex's idle week is 8.

**Rebuild the board on draft morning** (`arm.py board`). Both inputs move through
the preseason, and `vor.json` is gitignored derived data.

**Still open:** replacement level is static, so late in a draft it understates
how thin a position has actually become; there is no tier awareness; and there is
no model of what will still be there at the next pick.

### The judge is not the board

`grade.py` scores rosters on the same projections the board drafts from, so
alone it measures execution, never board error. The fix is standing:

- **Grade every drafted room twice**: `python3 fantasy/consensus.py` (CBS +
  FFToday full-PPR averages; FFToday `LeagueID=190` is full PPR) then
  `grade.py --judge both`. Read the **rank gap**; ~0 is robust, large positive
  means the board flatters us. First measurement (2026-08-24): our #3 was the
  judge's #8, driven by the Barkley call and a WR tail our board rates 14-28
  positional ranks rosier than consensus.
- **FIREWALL: `vor.py` never reads `consensus.json`.** A judge the drafter
  ingests stops being a judge.
- **Register disagreements, settle with reality**: `fantasy/ledger.py` holds
  board-vs-consensus calls as predictions; `ledger.py settle` scores them with
  actual ESPN season points weekly in season. Only settled results may change
  how the board is built.
- **The elite-bias correction is parked at strength 0** (`VOR_BIAS_STRENGTH`
  in `vor.py`): shrinking elite projections toward published reality graded
  worse under the consensus judge because all projection sources share the
  same elite optimism. Only the ledger can justify enabling it.

### Verification discipline

Measure the **result, not the action**. Two bugs shipped because success was
checked at the wrong layer: a pick logged "Mike Evans" while drafting a different
player, and a queue filler reported 21 adds when ESPN had accepted zero. Both
reported intent.

- Confirm the **roster count grew** after every pick, never that a click fired.
- Take each player's name from **that row's own player anchor**, never by scanning
  page text for a name. Both earlier schemes (walking a fixed number of parents,
  then matching names across a blob of text) resolved rows to the wrong player.
- **Log the size of the board actually scored on every pick.** ESPN's table keeps
  only ~32 of ~190 rows in the DOM and `innerText` returns '' for anything without
  a layout box, so the bot silently scored a pool of 1 to 19 players and called it
  the board for two mocks. One `board=N` in the pick log would have caught it on
  the first pick. **Use `textContent`, and sweep ESPN's position filter** so every
  position's best available players are in the window by construction — otherwise
  a kicker, ranked past 200, is never visible and the last round finds no
  candidate.
- When a check's failure mode is a quiet zero, **run a known-good fixture through
  it**. A kicker count silently read 0 forever because there is no word boundary
  between the `3` of `TE2/3` and the `K` in the run-together limits string.
- **Any metric that is quietly a subset is the dangerous kind.** A pool of 19 and
  a pool of 190 both produce a confident pick and a plausible-looking roster.

## The living document

**`~/Exobrain/Areas/Adventure & Creativity/Fantasy Football/Fantasy Football Playbook.md`**

That note is the operational source of truth for the current season. **Read it at
the start of any fantasy task**, because it holds the current state (draft date,
draft slot, roster, league observations, season log) that this skill deliberately
does not duplicate.

**Keep it current.** Write back to it whenever something is learned or decided:

- Draft date or slot gets set, or any league setting changes
- A draft happens (record the roster and the reasoning)
- A rule here meets reality and does not survive (correct the rule in the note,
  do not just log the outcome)
- Anything on its **Open questions** list gets answered
- A useful observation about a specific leaguemate's tendencies
- Weekly decisions worth remembering, in the **Season log**

Update its `updated:` frontmatter field when writing. This skill holds the
durable evidence; the note holds this season. When the two disagree about a
league setting, the note wins.

The research report behind all of it is
`~/Exobrain/Research/Fantasy Football Winning Strategy.md`.

---

## 0. Alex's league: "Roll for First Down" (full settings, 2026-08-16)

Mirrored in the playbook note above. If a setting changes, fix it in **both**, and
treat the note as authoritative.

ESPN, run by a friend of Alex's (name in the playbook note, not here).
**12 teams, snake, full PPR head-to-head points.**
Draft not yet scheduled. **Draft order randomized one hour before the draft**, so
slot cannot be planned for. **90 seconds per pick.**

| Setting | Value |
|---|---|
| Roster | 16 (9 starters, 7 bench, 1 IR) |
| Starters | QB, RB, RB, WR, WR, TE, FLEX, D/ST, K |
| Position maximums | RB 8, WR 8, QB 4, TE 3, D/ST 3, K 3 |
| **Waivers** | **Reset weekly to inverse order of standings. NOT FAAB.** 1-day period |
| Regular season | 14 weeks, 1 week per matchup, **no tie breakers** |
| Playoffs | **6 of 12 teams**, all rounds 1 week (weeks 15/16/17), **top 2 get byes** |
| Seeding tiebreak | Total points for |
| Reseeding | Off |
| Keepers | None, either year. Pure redraft |
| Trades | No limit, deadline Dec 2 2026, 1-day review, **5 votes to veto** |
| **Lineup protection** | **OFF** |
| Lineup locks | Individually at each player's gametime |

### The two settings that matter most

**1. The first-round bye is worth roughly double the championship.** All playoff
rounds are one week, so a bye removes an entire coin flip. Using the §1 model of a
53% team: winning three single-week rounds is 0.53³ = **14.9%**. Winning two is
0.53² = **28.1%**. Seeding top-2 out of 12 is close to a **2x multiplier on title
odds**, and it is the highest-leverage regular-season goal in this league by a
wide margin. Note 6 of 12 teams make the playoffs, so merely qualifying is close
to a coin flip and is not the thing to optimize. **Play for the bye, not the
berth.** Since the seeding tiebreaker is total points for, raw points matter
independently of record.

**2. Waivers are reverse-standings priority, not FAAB, which inverts §4's bidding
advice.** The FAAB dead-zone guidance does not apply here. What applies instead:

- **Priority resets every week based on standings, so hoarding it is worthless.**
  There is no cost to using your claim. A manager "saving" waiver priority in a
  resetting-priority league is making a free mistake. Claim every week there is
  anyone worth claiming.
- **Winning gives you bad priority.** This is a rich-get-poorer mechanic: the
  better Alex's record, the further back he sits. He cannot count on the wire to
  fix roster holes in the second half of the season.
- **Therefore Zero RB is structurally weaker in this league than the research
  implies.** Zero RB's entire mechanism is mining the waiver wire for RBs while
  others paid draft capital (§3). That mechanism is throttled here by
  reverse-standings priority *and* by 192 players rostered across 12 teams of 16.
  Combined with the market having already arbitraged the strategy, do not run it.
- **Early-season claims are the cheap ones.** Priority is most favorable before he
  climbs the standings, and Week 1-4 breakouts are where the wire actually
  produces starters.

### The rest of the format read

- **Full PPR is the WR-friendly extreme.** RB12 produces 56.4% of RB1's output and
  lands **below WR24**; WR12 is at 71.7%. WR value catches RB at the RB4 spot and
  never looks back. Lean receiver. Pass-catching backs gain real value, since
  every reception is a full point.
- **One QB slot, so wait on QB.** Not superflex. QB scoring declines near-linearly
  by rank, QB6 returns ~72% of QB1, and NFL Rounds 2-7 produced 4 QB1 seasons in
  90 tries. Nothing here justifies early QB.
- **Required K and D/ST guarantee the herding edge fires** (§3), and the punt
  has a measured limit (2026-08-24): observed rooms drain all startable defenses
  in rounds 12-13 and kickers in round 14, so waiting to the final two rounds
  donates ~35-40 projected points. **Take the best D/ST at round 11 and K at
  round 13, one round ahead of the run, then stream in-season.** Never mid-round
  capital, and never chase a run that starts earlier than that.
- **Kicker scoring is distance-weighted** (0-39 = 3, 40-49 = 4, 50-59 = 5, 60+ = 6,
  miss = -1). Still stream, but favor strong legs on offenses that stall in field
  goal range, and prefer domes/good weather in the late weeks.
- **D/ST scores on yards allowed *and* points allowed**, with harsh negatives
  (-7 at 550+ yards). Stream against weak offenses; avoid defenses facing
  high-total games regardless of reputation.
- **Lineup Protection is OFF and players lock individually at gametime.** An
  inactive starter scores zero and nothing saves Alex from it. Two consequences:
  a checklist before the first kickoff every week is worth real points, and
  because locks are individual he can wait on late-window and Monday players to
  make information-rich decisions. This is free edge in a casual league.
- **The IR slot** stashes an injured high-upside player without spending a bench
  spot. ESPN typically requires OUT/IR designation, not questionable.
- **7 bench spots plus no-limit acquisitions** supports constant bottom-of-roster
  churn over hoarding handcuffs (§4).
- **5 votes to veto in a 12-team league is a high bar**, so this is a trade-friendly
  league. Trade deadline is Dec 2, 2026.
- **No keepers**, so there is zero future value to protect. Rookies and young
  players are worth only their 2026 production.
- **90 seconds per pick means the board must be built beforehand.** Boris Chen's
  free tier clustering (§5) is the right tool: at 90 seconds Alex needs to read a
  tier, not evaluate a player.
- **Slot is randomized one hour prior**, so the §3 draft-slot discussion is
  informational only. Prepare for all 12 slots or, better, prepare tiers that are
  slot-agnostic.
- **Playoff weeks are 15, 16, 17.** Playoff-weeks strength of schedule is the one
  SOS use case the research could not rule out, though it remains UNVERIFIED. Do
  not weight it heavily; preseason SOS is dead (§2).

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

For the two local tools built against ESPN, see **Live league data** (`ff`, read
only) and **Draft mode** (`draftbot`, the only thing here that writes).

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
`~/Exobrain/Research/Fantasy Football Winning Strategy.md`, and the living
season playbook is at
`~/Exobrain/Areas/Adventure & Creativity/Fantasy Football/Fantasy Football Playbook.md`.

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
