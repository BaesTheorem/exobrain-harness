# Fantasy Football Evidence Base

Compiled 2026-08-16 from a six-agent research pass. Organized by claim, with
source, sample size, and confidence. **Confidence reflects whether a primary
source was actually opened and read**, not how plausible the claim sounds.

Reading rule for this file: anything marked UNVERIFIED was found only in a search
summary or a paywalled snippet. Do not present those as fact. Several are widely
repeated in fantasy media, which is exactly why they are flagged.

---

## A. Luck vs. skill

### A1. Season-long home leagues: R\* = 0.19 (~80% luck) — HIGH, verified verbatim
Alex Cates, applying MIT's R\* methodology to ESPN public leagues.
https://www.alexcates.com/post/luck-vs-skill-how-much-does-luck-matter-in-season-long-fantasy-football

Sample: started from ~15,000 leagues per year, found ~1,500 repeated across 2019
and 2020, removed any team that failed to set a lineup in either year. **Final
sample 4,115 teams across 1,252 leagues.**

Verbatim: "When we calculate the R\* value we get 0.19. By this metric, that
suggests that fantasy football in the season-long version is 20% skill and 80%
luck, putting it in the ballpark of the stock market."

Points-for z-score year over year: **R² = 0.01**. The author notes wins, regular
season standing, and final standing all correlated *worse* than points, which
makes sense since points are the part under manager control.

Author's own stated limitations: sample much smaller than MIT's (they used 50,000
to 500,000 players), only two years compared, and one of them was the
COVID-disrupted 2020 season. **Single non-peer-reviewed blog post.** Methodology
is transparent and the author built a fantasy analytics product, so note mild
self-interest.

### A2. MIT DFS study — HIGH, full paper read
Getty, Li, Yano, Gao & Hosoi, "Luck and the Law: Quantifying Chance in Fantasy
Sports and Other Contests," *SIAM Review* 60(4), 869-887 (2018).
DOI: 10.1137/16M1102094

**Scope: FanDuel DAILY contests, 2013-2014 seasons. Not season-long redraft.**
This is constantly miscited as settling the season-long question. It does not.

R\* ranges 0 (coin flip) to 1 (pure skill). Approximate "transition game number"
above which skill dominates: **NBA ≈5, MLB ≈20, NFL ≈25, NHL ≈40.** NFL fantasy
sits closer to the chance end than MLB or NBA; only NHL is more chance-driven.

**Funding disclosure, verbatim from the paper: "This work was partially funded by
FanDuel. FanDuel did not exercise any editorial control over this paper."**
FanDuel had a live regulatory interest in fantasy being classified skill-based.
State the funding whenever citing it.

The widely-quoted "55% skill" figure for NFL **could not be located in the paper's
text or figures**. Do not repeat it.

### A3. Schedule luck — MEDIUM-HIGH
Fleaflicker platform-wide analysis, 2008 season, all Fleaflicker leagues.
https://www.fleaflicker.com/forums/site-announcements/topics/quantifying-luck-in-head-to-head-fantasy-leagues-13680

Teams averaged **3 "luck games" per season** (result opposite to implied win
probability vs. the field). **20% of teams finished "lucky"** (≥2 games over .500
in luck matchups), **20% unlucky**; 8% "very lucky," 8% "very unlucky."

Good teams were lucky 22% / unlucky 16%; bad teams lucky 18% / unlucky 21%.

Natural experiment in the same thread: identical season scores under two randomly
generated schedules produced "maybe 3 or 4 teams finished with the same record...
One team finished with a 4-game difference in wins."

Caveat: 2009 forum post, one season, informal methodology writeup.

### A4. Playoff randomness — MEDIUM (blog simulation, verifiable arithmetic)
The Fantasy Footballers, "How to Reduce Playoff Randomness."
https://www.thefantasyfootballers.com/articles/the-fantasy-architect-how-to-reduce-playoff-randomness-in-your-league/

Modeling a "skilled" team as 53% single-matchup win probability:
- Standard 3-round single elimination: **~28%** championship probability
- Two-week rounds: **29.5%** (only +1.5 despite doubling length)
- Double elimination: **32.2%**
- First-round byes: still 28% for that team, but roughly doubles its edge over an
  average team
- Each ~1 point/week of scoring edge ≈ **+0.7%** championship probability;
  7 points/week ≈ +5%

The 53% assumption is a modeling choice, not empirically derived. The compounding
arithmetic itself is standard and checkable.

---

## B. Player-level predictors

### B1. WR stat stickiness table — HIGH
4for4, 2017-2023, WRs with ≥30 targets in consecutive seasons.
https://www.4for4.com/2024/preseason/most-predictable-wide-receiver-stats

YoY self-correlation: Slot Rate 0.75, Targets/G 0.70, Fantasy PPG 0.68,
Receptions/G 0.68, Yards/G 0.67, aDOT 0.65, TPRR 0.64, Open Score 0.59,
First Downs/Route Run 0.58, YPRR 0.56, **TD Rate 0.19**, Drop Rate 0.14,
Contested Catch Rate 0.02, Route Rate 0.01.

Predicting *next* season's fantasy PPG: Yards/G 0.67, Targets/G 0.62,
Receptions/G 0.61, YPRR 0.59, First Downs/Route Run 0.57, TPRR 0.53.

Two counterintuitive notes from 4for4 themselves: Route Rate's near-zero
stickiness is likely a filter artifact (rostered WRs are already saturated near
their ceiling). Slot Rate and aDOT are highly sticky but **do not correlate with
next-year fantasy points on their own** — they describe role, not value.

### B2. Volume vs. efficiency regressions — HIGH
Chase Stuart, Football Perspective, 2007-2012 PFF data, 344 WR seasons (≥40
targets both years, same team).
https://www.footballperspective.com/yards-per-route-run-yards-per-target-and-targets-per-route-run/

- N+1 TPRR = 0.062 + 0.671 × N-TPRR, **R² = 0.41**
- N+1 YPRR = 0.843 + 0.474 × N-YPRR, **R² = 0.21**
- N+1 Y/T = 5.84 + 0.28 × N-Y/T, **R² = 0.08**

Note: the article's "47.4% is predictive" phrasing is the author's gloss on the
regression *coefficient*, not R². Cite the R² values.

### B3. Rushing stats barely predict — HIGH
SumerSports, "Sticky Football Stats."
https://sumersports.com/the-zone/sticky-football-stats-predictive-nfl-metrics/

Target share YoY ≈ **0.70** since 2021. Rushing stats have "some of the lowest
year-over-year correlations"; **EPA per rush attempt has "virtually negligible"**
YoY correlation; stickiest RB stat found was tackled-for-loss rate at ~0.40.

Verbatim: "While rushing statistics are excellent descriptive statistics, they
have little predictive value in the long term."

### B4. Touchdown regression — HIGH
RotoViz, 2008-2017, WRs with ≥50 targets in both years, n=530.
https://www.rotoviz.com/2018/05/projecting-upside-the-predictability-of-receiving-touchdowns/

Total receiving TDs → next-season TDs **R² = 0.079**; red-zone TDs → next total
TDs **R² = 0.029**; 10-zone TDs → next total TDs **R² = 0.018**.

Verbatim: "The R-squared values are all close to zero, indicating that total, red
zone, and 10 zone receiving TDs do not correlate with next-season TDs."

Same article quotes Hermsmeyer: air yards "helps us explain 80 percent of a wide
receiver's receiving yards."

**UNVERIFIED, do not state as fact:** the claim that of 167 flex-eligible
10+-TD seasons only ~11% saw a TD increase the next year, averaging -5.2 to -5.5
TDs. Directionally consistent with B4 but not traced to an open source.

**CONTESTED, unresolved:** two xTD figure sets disagree. One says raw TDs and xTD
predict next season about equally (~0.52 each) with xTD merely stickier (0.60 vs
0.52). Another says xTD out-predicts raw TDs (R² 0.283 vs 0.275) and is much
stickier (0.382 vs 0.276). Neither traced to an open primary source. Present xTD
as directionally useful, not settled.

### B5. WOPR — MEDIUM, exact figures unverified
Weighted Opportunity Rating = 1.5 × target share + 0.7 × air yards share, created
by Josh Hermsmeyer.

**The commonly cited 0.6303 YoY stability and the "R² = 0.746" claim could not be
confirmed against a primary source** (RotoViz origin pieces are paywalled). The
0.6303 figure appears in a GitHub README:
https://github.com/kcuilla/fantasy_football_receiving_opps

The *qualitative* claim (WOPR is among the stickiest WR metrics) is independently
corroborated by Fantasy Classroom (2012-2022 nflverse data, ≥10 games both
seasons), which names WOPR, air yards share, and target share "the three best
metrics" for WR predictability.
https://fantasyclassroom.org/Blogs/sticky-stats/wr-sticky-season-totals

### B6. Draft capital hit rates — MEDIUM-HIGH
DynastyNerds, 11 draft classes.
https://www.dynastynerds.com/analytics/nfl-draft-capital-fantasy-football/

QB: Round 1 → 59.5% at least one QB1 season, 75.7% QB2+. **Rounds 2-7 combined
(all non-first-round QBs): 4 QB1 seasons out of 90 QBs (4.4%)**, only 10/90
reached QB2. (The n=90 bucket is Rounds 2-7: 7+16+15+15+20+17. Round 2 alone
contributes 1 of those 4 QB1 seasons, so do not relabel this as "Rounds 3-7.")

RB: Round 1 (n=15) → 66.7% RB1, 80.0% RB2+, 86.7% top-30. Round 2 (n=24) → 33.3%
RB1, 70.8% RB2+. Round 4 → **6.3%** RB1.

### B7. NFL draft round vs. career fantasy PPG — HIGH
PFF, 1993-2016, all drafted skill players via PFR.
https://www.pff.com/news/fantasy-football-narrative-street-are-draft-slot-and-fantasy-performance-correlated

First-round career fantasy PPG: RB 10.3, WR 7.2, TE 4.6, declining each round.
**Round-level R² ≈ 0.85-0.95** for round vs. PPG and round vs. games played at
RB/WR/TE. Individual-pick-level R² drops to ~0.30 (RB/WR/TE) and ~0.10 (QB).

**UNVERIFIED:** the claim that draft capital correlates better than raw pick
number (0.69 vs 0.57 RB, 0.66 vs 0.59 WR). Found only in search synthesis.

### B8. RB age cliff — HIGH for shape, contested on exact age
Northwestern Sports Analytics Group, 2007-2016 half-PPR.
https://sites.northwestern.edu/nusportsanalytics/2020/12/29/the-nfl-running-back-age-cliff/

Top-20 RB finishes by age: 22 at age 27, 23 at age 28, then **11 at age 29, 8 at
age 30**. Among elite RBs (top-5 finish plus 3+ top-20 seasons, 2006-2016), "over
half... experienced a top-10 season at age 28 before falling outside the top 10
the very next year."

**Competing, UNVERIFIED:** Fantasy Football Blueprint puts the break at 27→28 with
a median 22% per-game production loss, and claims 93.8% of RB peak seasons since
2016 come from ages 21-28. The shape is agreed; the inflection point is not.

### B9. WR breakout age — MEDIUM
LevelUpFantasy, built on nflverse + CollegeFootballData. College Dominator Rating
≥20% defines breakout.
https://levelupfantasy.com/tools/wr-breakout-age/

Top-24 PPR season hit rates: broke out before age 20 → **38.6%**; late breakout →
**9.2%**; never broke out in college → **10.4%**. Thresholds: Generational <19.0,
Elite Early <20.0, Late-Bloom ≥21.0.

### B10. Offensive line impact — HIGH
DraftSharks, 4 seasons of half-PPR team totals vs. O-line metrics.
https://www.draftsharks.com/article/offensive-line-performance-fantasy-production

QB production: Adjusted Sack Rate **r² = 0.139**; PFF Pass Block Grade ~0.15.
RB production: Adjusted Line Yards **r² = 0.289** (rushing only). O-line "has
basically no impact on RB receiving production."

Cuts against the generic "always check the O-line" advice. DraftSharks' own read:
tiebreaker for QBs, not a signal.

### B11. Strength of schedule is not predictive — HIGH
Footballguys, 6 seasons of team fantasy-points-allowed data.
https://www.footballguys.com/article/15StengthofScheduleMyth

Verbatim: "there is little predictive quality for strength of schedule from one
season to the next... **just one team has repeated as the stingiest against any
position over the past six years.**"

Corroborated by 4for4 (2015-2025): QB defense YoY r = **0.27** (the highest), RB
0.22, WR essentially noise (23% top-5-to-top-5 repeat, 23% bottom-5-to-bottom-5).

**UNVERIFIED:** that playoff-weeks (15-17) SOS is useful. Plausible, unconfirmed.

### B12. Injury prediction — LOW, real gap
**No NFL-specific, fantasy-relevant injury-recurrence study was found.** This is a
genuine hole in the literature, not a search failure.

Best available is general sports science: a four-year longitudinal ML study in
professional soccer found prior muscle injury significantly predicts future
injury, with a workload-based classifier reaching AUC-PR 83%, balanced accuracy
72%. https://pmc.ncbi.nlm.nih.gov/articles/PMC12653399/

**Do not extrapolate soccer injury models to NFL RB workload without saying so.**

---

## C. Draft strategy

### C1. Strategy choice barely matters — HIGH (public code)
dlm1223, "fantasy-football-optimization." Half-PPR Yahoo 12-team, projections
from FantasyData/FFA/FFToday 2008-2018, ADP from fantasyfootballcalculator.com,
**2,000 simulated seasons per strategy variant**.
https://github.com/dlm1223/fantasy-football-optimization

Two separate verbatim sentences from the README's conclusion (do not splice them
into one quote): "Zero RB (4&5) seems to be better than zero WR (6&7)" and "many
of them perform similarly, **finishing within 10-20 points**." Backup QB and TE
handling mattered more than RB/WR sequencing.

### C2. Zero RB origin and decline — HIGH origin, MEDIUM decline
Origin: Shawn Siegele, "Zero RB, Antifragility, and the Myth of Value-Based
Drafting," RotoViz, Nov 2013.
https://www.rotoviz.com/2013/11/zero-rb-antifragility-and-the-myth-of-value-based-drafting/

Decline: FTN, "The Death of Zero RB" (2025).
https://ftnfantasy.com/nfl/the-death-of-zero-rb
Documents 13 sub-RB40 ADP backs finishing RB15+ from 2017-2024, then shows that
through Week 8 of 2025 only one sub-RB40 back was inside the top 15 while **14 of
the top 16 ADP backs were hitting as RB2 or better**. The data table is real but
selective/illustrative rather than exhaustive.

Counter-evidence with an important caveat: PlayerProfiler, "How Zero RB Killed
Zero RB," reporting a Bessette/Meade **500,000-run Monte Carlo** on MFL10 data
finding RB-TE-RB-RB-RB the most common league-winning sequence. **That simulation
is best-ball (no waiver wire)**, which structurally disables Zero RB's core
mechanism. The article explicitly says the strategy remains viable in leagues
with in-season transactions.
https://www.playerprofiler.com/article/zero-rb-draft-strategy/

Related: Establish The Run, "The Death of the Running Back Dead Zone" (FFPC full
PPR, 2017-2022) documents RBs in Rounds 3-6 having consistently poor win rates
while Rounds 7-10 ran above expectation, and the pattern eroding as ADP corrected.
https://establishtherun.com/the-death-of-the-running-back-dead-zone/

### C3. Value-Based Drafting — HIGH
Origin, Joe Bryant, Footballguys. https://www.footballguys.com/article/bryant_vbd
Verbatim: "I introduced VBD to the fantasy football world back in 1996... The
value of a player is determined not by the number of points he scores. His value
is determined by how much he outscores his peers at his particular position."

Internal critique: Adam Harstad, "Rethinking VBD" (2015).
https://www.footballguys.com/article/HarstadValueOverBaseline
Two flaws: (1) season-total VBD punishes injured elite players (a 7-game
Gronkowski scored *lower* raw VBD than a healthy mediocre TE), fix is per-game
VBD; (2) "worst starter" baseline undervalues top players at thin-start positions
(QB/TE) vs. deep-start ones (RB).

**No study was found isolating whether VBD beats naive ADP-following in
outcomes.** Related: Benn Stancil (Mode) found ~35% of the variation in CBS vs.
ESPN draft results is explained by differences in their projections, rising to
**70% for players drafted in the first 10 rounds** — evidence that ADP already
*is* crowd-sourced VBD.
https://mode.com/blog/fantasy-football-predetermined-by-draft/

### C4. Positional value by scoring format — HIGH
Sharp Football Analysis. The article says "over the past decade" against a 2021
publish date, so roughly 2011-2020; the exact window is not stated.
https://www.sharpfootballanalysis.com/fantasy/fantasy-football-high-scorers-replacement-value-and-repeating-starting-weeks/

PPR: WR6 = 81.5% of WR1's output, WR12 = 71.7%. RB6 = 69.5%, **RB12 = 56.4%**
(below WR24). WR catches RB at the RB4 spot and never looks back.
Standard: RB advantage holds nearly through the top 24.
Half PPR: they cross around WR12/RB12.

TE has the steepest raw drop-off (TE1-to-TE5 gap averaged 138 points vs. 119 RB,
77 WR, 30/19/10 for QB/K/DEF) but the **weakest week-to-week repeatability**:
66.4% of TEs with a top-12 week repeat it, vs. 75.9% RB, 78.7% WR, 79.9% QB.

### C5. Snake draft slot bias — MEDIUM
FantasySharks, "Lab Test: The Snake Draft." **~4 million simulated drafts (~half a
billion picks)**, 12-team/12-round, ADP from 7 years of MyFantasyLeague data.
https://www.fantasysharks.com/lab-test-the-snake-draft/

Traditional snake is measurably biased toward early picks, worsening as drafters
deviate more from ADP. A "Single-Slant Snake" (third-round reversal) reduces but
does not eliminate it. Verbatim: "The #1 and 2 spots are where you want to be,
and be ready to work the wire if you draw #11."

Caveat: publication date unclear (references "a presidential election year,"
likely 2008-2012), so dated relative to current ADP shape.

### C6. FTN draft-slot claim — REJECT
FTN's 2026 article claims teams drafting from the first three slots "post win
rates 20-30% higher than those drafting in the middle" over five years of FFPC
data. **No source, no linked study, no methodology.** The article also has
structural tells of low-effort or AI-generated content (a section appearing in the
body with no corresponding table-of-contents entry, ranking lists that do not
reconcile across formats). **Do not repeat this figure.**

### C7. Stacking — CONTESTED, present both
**For:** Establish The Run, "Deep Dive: Stacking in Season-Long Fantasy." FFPC
20-round ADP, 3 seasons, top-300 ADP only.
https://establishtherun.com/deep-dive-stacking-in-season-long-fantasy/
QB hit rates (n=88 QBs over 3 years, "hit" = beat the 293-point FFPC median):
Minimum 49%, Small 38%, Medium 23%, Big 13% (11/88, ~4/year).
Pass-catchers attached to a Minimum-Hit-or-better QB (n=329): 61% hit rate, **+11.9
points vs. ADP**. Medium-Hit-or-better (n=63): 71%, **+31.2**. Big Hit (n=35): 74%,
**+36.0**. Reversed: a hit pass-catcher made his QB 34% more likely to hit, worth
+19.6 points vs. expectation (n=150).
Recommends reaching 1 to 1.5 rounds, especially where first place pays ≥25% of pool.

**Against:** One Week Season ("Hilow"), "Exposing the Fallacies of Stacking in Best
Ball and Redraft."
https://oneweekseason.com/exposing-the-fallacies-of-stacking-in-best-ball-and-redraft/
Argues stacking is a variance-manipulation tool for large-field GPP payout
structures, and porting it to redraft is a category error. 2020 case study: the
best *unstacked* WR pairing (Adams + Ridley, different teams) produced 12 combined
WR1 weeks vs. 11 for the marquee Thielen+Jefferson stack, which had both hit WR1
simultaneously only once. Claims stacking "actually reduces the overall upside of
a roster" when you need to beat one opponent rather than climb a field.

Qualitative case study vs. quantitative sample. They disagree on **mechanism**, not
just magnitude. The "against" case aligns with Haugh & Singal's formal H2H result
(E1).

**UNVERIFIED:** "stacked QB/WR has 15.3% boom vs 12.0% non-stacked, 24.0% bust vs
18.8%" and "stacking costs 0.3 wins." Not traceable.

### C8. Late-Round QB — UNVERIFIED
Origin: JJ Zachariason's self-published "The Late-Round Quarterback" (2012).
**Effectiveness evidence could not be verified** — lateroundqb.com and FantasyLabs
both blocked automated fetching (406 / cert errors). A human would need to visit
directly. Do not assert this strategy works or fails.

---

## D. Behavioral edges and market inefficiency

### D1. Lee & Liu — the single best empirical source — HIGH, full text read
Lee, M.D. & Liu, S. (2022). "Drafting Strategies in Fantasy Football: A Study of
Competitive Sequential Human Decision Making." *Judgment and Decision Making*
17(4), 691-719. **1,350 real leagues, 2017 NFL season, Sleeper platform,
~188,000 human picks.** Peer-reviewed.
https://www.sas.upenn.edu/~baron/journal/22/220318/jdm220318.html

Abstract, verbatim: "We find people are sensitive to some important environmental
regularities in the order in which they draft players, but also present evidence
that they use a more narrow range of strategies than is likely optimal in terms of
team composition. We find little to no evidence for the use of the complicated but
well-documented strategy known as handcuffing, and no evidence of irrational
influence from individual-level biases for different NFL teams. We do, however,
identify a set of circumstances for which there is clear evidence that people's
choices are strongly influenced by the immediately preceding choice made by a
competitor."

**Handcuffing effectiveness, verified verbatim from the full text:** "There are
793 teams that picked both players for one of the 32 pairs in Table 2. These
teams won 51.04% of their games, compared to 50.56% for the teams that had no
handcuff pairs. A hierarchical test of whether these winning proportions are the
same or different found a **Bayes factor of 4.2 in favor of sameness**, using a
Gaussian effect size prior."

Note: two separate findings that are easy to conflate. The paper found (a) people
mostly do not *use* handcuffing, and (b) among the 793 who did, it did not help.

**Roster composition:** the three most common compositions accounted for ~60% of
teams and underperformed. The eight compositions with win rates clearly above 50%
skewed toward more RB/WR and fewer K/DST. Attributed to the representativeness
heuristic (building rosters that *look like* the starting-lineup requirement).

**Herding:** conditional probability of drafting a DEF/K immediately after an
opponent does is "clearly greater" than the unconditional baseline, for "almost
all kicker and defense selections" and QBs in roughly the first 20 picks. Teams
that copied the herd did **not** win more (Bayes factors 4.7-8.8 favoring no
difference).

**ADP calibration:** ADP-to-season-points correlation **-0.56 (RB), -0.55 (WR)**;
weaker and less well calibrated for QB/TE; DST scoring "highly unpredictable."

**Draft slot:** early slots outperformed *except the literal 1.01*, which did
poorly. The authors themselves flag this as possibly a single-season artifact
needing replication. **Treat as unreplicated.**

### D2. Cognitive biases — MEDIUM
Renee Miller, cognitive scientist, University of Rochester; author of *Cognitive
Bias in Fantasy Sports: Is Your Brain Sabotaging Your Team?*
https://www.rochester.edu/newscenter/cognitive-bias-definition-examples-fantasy-sports-532612/
Named biases with fantasy framing: endowment effect (overvaluing owned players),
primacy (Week 1 anchoring), recency, confirmation bias. Source is a university
press release, not a peer-reviewed paper.

### D3. Hot hand — LIVE DISAGREEMENT
- Losak, Weinbach & Paul (2023), *Journal of Sports Economics* 24(3), 374-401.
  DOI: 10.1177/15270025221128955. **No real hot-hand effect and no profitable
  hot-hand DFS strategy**, but consumers believe in it and act on it anyway.
- Baris & Losak (2026), *International Journal of Sport Finance* 21(1), 38-52.
  DOI: 10.1177/15586235251403232. Finds **real short-term streak effects** that
  predict DFS outcomes, with DraftKings salaries under-pricing hot pitchers.

Same authorial lineage, three years apart, opposite conclusions. Both baseball.
Unsettled.

### D4. DFS winnings concentration — MEDIUM, not peer reviewed
Miller & Singer, "For Daily Fantasy-Sports Operators, the Curse of Too Much
Skill," *Sports Business Journal* July 2015, reprinted by McKinsey. Source of the
often-quoted **"1.3% of DFS players account for 40% of entry fees and win 91% of
profits"** (2015 MLB DFS data). Industry/consulting analysis, not peer-reviewed;
underlying dataset not published.

---

## E. Formal optimization literature

### E1. Haugh & Singal — the strongest paper in the set — VERY HIGH, full text read
Haugh, M.B. & Singal, R. (2021). "How to Play Fantasy Sports Strategically (and
Win)." *Management Science* 67(1), 72-92.

Builds on Hunter/Vielma/Zaman (2016) but explicitly models opponents' unknown
lineups via a Dirichlet-multinomial process fit with Dirichlet regression, and
formally connects DFS lineup construction to **mean-variance portfolio
optimization**, reducing it to binary quadratic programs. Tested with real money
on FanDuel NFL across all 17 weeks of 2017.

**The result that matters for redraft:**
- **Double-up / head-to-head** (beat one threshold): **minimize variance
  conditional on a positive expected edge.**
- **Top-heavy tournament**: **maximize variance and diversify** entries.

Season-long H2H is structurally the first case each week. Best ball is closer to
the second.

Realized weekly percentile finishes ranged from 0.07th to ~34th percentile even
for a theoretically sound strategy, which is itself a variance lesson.

### E2. Hunter, Vielma & Zaman (2016) — HIGH
"Picking Winners in Daily Fantasy Sports Using Integer Programming."
arXiv:1604.01455. Seed paper for the DFS portfolio literature. Models
win-probability across N lineups as a submodular set function, assumes jointly
Gaussian lineup scores, formulates entry construction as integer programming.

### E3. Mahoney & Paniak (2023) — HIGH, sobering
"Method and Validation for Optimal Lineup Creation for Daily Fantasy Football
Using Machine Learning and Linear Programming." arXiv:2309.15253.
Neural-network projections (2018 season) feeding a mixed-integer LP. Optimized
lineups beat random lineups but landed only around the **31st percentile
(median)** against real human DraftKings lineups. Preprint, not peer-reviewed.
**A competent model is not an automatic edge over a motivated field.**

### E4. Season-long optimization — the thin shelf
- Becker, A. & Sun, X. (2016). "An Analytical Approach for Fantasy Football Draft
  and Lineup Management." *JQAS* 12(1), 17-30. DOI: 10.1515/jqas-2013-0009.
  Mixed-integer optimization over draft + weekly lineups with the season
  championship as objective. Abstract reports "promising performance" with no
  effect size given.
- Fry, M.J., Lundberg, A.W. & Ohlmann, J.W. (2007). "A Player Selection Heuristic
  for a Sports League Draft." *JQAS* 3(2), Article 5. DOI: 10.2202/1559-0410.1050.
  Stochastic dynamic program relaxed to a deterministic DP. Not football-specific,
  and 2007 pre-dates modern PPR usage patterns.

### E5. Winner's curse — applies only by analogy
Massey, C. & Thaler, R.H. (2013). "The Loser's Curse: Decision Making and Market
Efficiency in the National Football League Draft." *Management Science* 59(7),
1479-1495. DOI: 10.1287/mnsc.1120.1657. **About real NFL front offices, not
fantasy auctions.** No peer-reviewed study of the winner's curse inside a fantasy
auction exists.

---

## F. In-season management

### F1. FAAB bid distribution — MEDIUM
FantasyPros, **600,000+ player adds from 2024** across dynasty and redraft.
https://www.fantasypros.com/2025/09/fantasy-football-waiver-wire-pickups-win-championships/

Redraft median winning bids (their figures are per $1,000; divide by 10 for a $100
budget): QB $21, RB $21, WR $29, TE $20, K $3, DST $10.
Week 1 redraft: 12,227 adds, median winning bid $11, outliers to $766.

**"FAAB dead zone": bids of $100-$190 per $1,000 (10-19% of budget) "rarely
returned winning production."**

Dynasty: 340,000+ adds; ~71% won for ≤2.5% of budget; under 5% went for 10%+.

Caveat: industry self-reported analysis, no published methodology or dataset, and
conflates dynasty with redraft in places.

**UNVERIFIED:** "nearly 50% of championship roster players go undrafted." Appears
only in SEO advice content with no data behind it.

### F2. Variance strategy — MEDIUM (math solid, fantasy application untested)
The Only Colors, "Game Theory: Expectation, Variance, and Underdog Strategies."
https://www.theonlycolors.com/2013/5/22/4353884/game-theory-expectation-variance-and-underdog-strategies

Worked example: 6-point underdog with 12-point SD wins 31% of the time (Z > 0.5).
Trading 2 points of EV for higher variance (SD → 20) raises it to **34.5%**
(Z > 0.4). Symmetrically, a favorite cutting SD from 12 to 6 at a 2-point EV cost
goes from 69.1% to **74.8%**.

**This is a general-sports derivation using a basketball example.** The math is
just statistics and ports cleanly, but direct empirical validation in fantasy
football specifically was not found. Present as a well-grounded inference.

### F3. Handcuffing, the practitioner study — MEDIUM-HIGH
Fantasy Football Blueprint, 2015-2018 and 2020-2024 (2019 excluded, reason
unstated), every team-season with a clear lead RB by Week 4 and a clear primary
backup. **n = 283 team-seasons.**
https://www.fantasyfootballblueprint.com/2026/08/06/10-handcuffing-running-backs/

All primary backups: **13.8%** finished RB24+, **28.6%** RB36+, median finish
**RB51**. Backup hit rate barely moves when the starter misses 1-2 games (12.6%)
or 3-5 games (10.0%). Only at 6+ games missed (which happened in **15.2%** of
team-seasons) did RB24+ rise to **23.3%**.

Baseline: a random non-handcuff bench RB hit RB24+ **10.5%** of the time.

**The key split.** Within the 6+-games-missed group, *clean* backups (under 35% of
early carries) hit RB24+ only **6.5%**, while committee backs already holding 35%+
of early carries hit **29.3%**. Verbatim: "The best predictor of a late-round
back's season was touches he already had, not the injury he was waiting for."

Industry blog, not peer-reviewed, underlying dataset not independently verified,
but methodology is clear and the numbers are specific and non-round.

### F4. Bench value — HIGH (but best-ball scoped)
4for4 Monte Carlo, "What is the Value of a Bench Player in Fantasy Football? Part
III." Best-ball format.
https://www.4for4.com/2015/preseason/what-value-bench-player-fantasy-football-part-iii
A backup DEF retains **75.2%** of starter value as a first bench option (DEF
week-to-week SD ~7 points swamps the <2 point/game gap between DEF1 and DEF16). A
backup K retains only **28.5%** (K SD ~3.25 points).

---

## G. Tools, verified 2026-08-16

All GitHub facts pulled from `api.github.com`, not search summaries.

| Tool | Last push | Stars | License | Status |
|---|---|---|---|---|
| nflfastR | 2026-08-13 | 536 | NOASSERTION | Active |
| nflreadr | 2026-08-05 | 110 | NOASSERTION | Active |
| **nflreadpy** | 2026-08-05 | 193 | MIT | Active. **Use this for Python** |
| **nfl_data_py** | — | 434 | MIT | **ARCHIVED 2025-09-25** |
| ffanalytics | 2026-07-16 | 187 | none detected | Active |
| espn-api | 2026-05-04 | 937 | MIT | Active |
| yfpy | 2026-04-21 | 258 | GPL-3.0 | Active |
| yahoo_fantasy_api | 2026-04-03 | 108 | MIT | Active |
| fftiers (Boris Chen) | 2026-08-14 | 189 | none detected | Active |
| ffscrapr | 2024-11-01 | 93 | NOASSERTION | **Stale ~21 months** |
| ffsimulator | 2024-10-03 | 22 | NOASSERTION | **Stale ~22 months** |

Sleeper API: https://docs.sleeper.com/ — official, no auth, GET-only,
`api.sleeper.app/v1`. Covers users, leagues, rosters, matchups, transactions,
drafts, players. Easiest platform to build against.

ESPN private leagues need `espn_s2` and `SWID` cookies. Yahoo needs OAuth2 app
registration.

### G1. Projection accuracy
FantasyPros accuracy competition: https://www.fantasypros.com/nfl/accuracy/
Ranks 150-212+ analysts. Method: snapshot rankings at kickoff, player pool = top-N
by ECR union top-N by actual finish, each rank slot converted to an expected point
value, compared to actual, converted to z-scores, worst week dropped after Week 8,
weeks 1-17 summed. 2025 in-season winner Justin Boone (Yahoo), 2nd Patrick Thorman
(Establish The Run). 2025 draft winner Seth Miller. Multi-year 2023-2025 draft
leader Jody Smith (Draft Sharks).

**GAP: could not confirm whether FantasyPros' own ECR consensus is entered as a
competitor.** The popular claim "consensus beats most individual experts" was not
verified in this competition specifically (the leaderboard is JS-rendered).

Fantasy Football Analytics MAE studies:
https://fantasyfootballanalytics.net/2024/12/which-fantasy-football-projections-are-most-accurate.html
2019-2023 across CBS, ESPN, FantasySharks, FFToday, NumberFire, NFL, RTSports. **No
source wins consistently** (CBS #1 for QBs in 2019, 6th in 2021). Their simple
cross-source average stayed top-3 or top-4 in every position every year.
Note mild conflict of interest: FFA sells an aggregate-projection product.

2025 bias study: https://fantasyfootballanalytics.net/2025/07/fantasy-football-projections-exploring-positional-bias-in-projections.html
Elite players systematically over-projected 2019-2024: **RB1-5 by ~55 points/season,
QB6-10 by ~42 (worsening to ~80 recently), WR1-5 by ~31, TE1-5 by ~23.**

Footballguys (Harstad), 2015 correlations against rest-of-season performance:

| Position | ADP | Early-season | ADP+Early blend | Expert projections |
|---|---|---|---|---|
| QB | 0.260 | 0.215 | 0.296 | 0.404 |
| RB | 0.309 | 0.644 | 0.655 | 0.651 |
| WR | 0.648 | 0.632 | 0.706 | 0.669 |
| TE | 0.295 | 0.559 | 0.533 | 0.716 |
| All | 0.548 | 0.659 | 0.697 | 0.703 |

https://www.footballguys.com/article/HarstadFiT3
A naive 50/50 ADP + 4-game blend beat either alone in 4 of 5 buckets. A skilled
projector beat the blend, but "the improvement is mostly on the margins."

### G2. Trade analyzers
Many exist (FantasySP, Fantasy Alarm, DraftSharks, FantasyTradeAnalyzers,
FantasyFootballCalculator, FantasyNerds). **Zero independent calibration or
backtesting evidence was found for any of them.** That absence is the finding.

### G3. K/DST predictability
Subvertadown, 3-season (2017-2019) weekly projection accuracy study: K and DST have
the lowest weekly projection correlation of any position, "significantly worse"
than even WR1. QB is the most predictable.
Stated rule: "Draft a certain position early if: scarce, high point drop-off,
predictable, and low dependence on opponent... If the opposite, then draft late or
not at all (plan on streaming, e.g., D/ST, Kicker)."

**UNVERIFIED:** "the gap between the No. 2 defense and the No. 12 defense is less
than 2 points per game." Directionally consistent with the verified data above.

---

## H. Known gaps in the literature

These are real holes, not search failures. Say so when the question comes up.

1. **No decomposition of final-standings variance** into draft % vs. in-season
   moves % vs. schedule luck %. The most useful missing number for prioritizing
   effort.
2. **No NFL-specific injury-recurrence study** relevant to fantasy.
3. **No formal equilibrium analysis of snake or auction drafts.** Lee & Liu is
   empirical/behavioral; Fry et al. is single-decision-maker DP.
4. **No auction-vs-snake skill-edge study** of any kind.
5. **No quantitative league-size-to-replacement-level model.** All qualitative.
6. **No study on whether active traders win more.**
7. **No season-long "points left on the bench" figure** (only best-ball bench
   value percentages).
8. **No academic value-of-information result** for how much a good model beats ADP
   in NFL fantasy. Closest data point is E3's 31st percentile, which is modest.
9. Academic work on season-long redraft is thin generally. Practitioner analytics
   leads academia here, which means most sourcing above is industry work whose
   datasets cannot be independently verified.
