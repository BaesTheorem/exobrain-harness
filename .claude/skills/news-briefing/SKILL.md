---
name: news-briefing
description: Comprehensive news intelligence briefing with bias analysis, blind spot detection, prediction market cross-referencing, and epistemic hygiene. Writes a cited, beautiful report to Obsidian. Use when the user asks for "news", "news briefing", "what's happening in the world", "headlines", "catch me up on news", "news report", or when triggered by the daily briefing.
---

# News Briefing

A personalized intelligence briefing that goes beyond headlines. Analyzes how stories are framed across the political spectrum, surfaces blind spots, cross-references prediction markets, and fact-checks key claims — all with citations.

**Output**: Standalone note in `/Users/alexhedtke/Library/Mobile Documents/iCloud~md~obsidian/Documents/Exobrain/News Briefings/YYYY-MM-DD.md`
**Target length**: Under a 10-minute read (~2,000-2,500 words)
**Reference**: Read `[[Alex's Tastes]]` (`/Users/alexhedtke/Library/Mobile Documents/iCloud~md~obsidian/Documents/Exobrain/Alex's Tastes.md`) for personalization context.

## Architecture

This skill uses the deep-research multi-agent pattern. You are the **Lead Editor** — you plan coverage, delegate research to subagents, then synthesize and write the final briefing.

```
Lead Editor (Opus)
    │
    ├── Phase 1: News gathering (3-4 parallel subagents)
    │   ├── Global headlines agent
    │   ├── Alex's interests agent (AI, cyber, EA, tech)
    │   ├── KC local news agent
    │   └── Prediction markets agent
    │
    ├── Phase 2: Analysis (2-3 parallel subagents)
    │   ├── Bias & framing analysis agent
    │   ├── Blind spot detection agent
    │   └── Fact-check & epistemic hygiene agent
    │
    └── Synthesis: Write the briefing
```

## Phase 1: News Gathering

Launch these subagents in parallel. Each uses `model: "sonnet"` and `subagent_type: "general-purpose"`.

### Agent 1: Global Headlines

```
You are a news research agent. Find today's top 8-10 global/national news stories.

SEARCH STRATEGY:
- Search for today's top news across multiple outlets
- Query examples: "top news today [date]", "breaking news [date]", "world news today"
- Also check: AP News, Reuters, BBC, NPR, Al Jazeera, The Guardian
- For each story, note which outlets are covering it and their headline phrasing

OUTPUT FORMAT:
For each story:
1. Headline / topic (neutral framing)
2. Which outlets are covering it (with URLs)
3. How each outlet phrases/frames it (exact headline text from 2-3+ outlets)
4. Key facts reported
5. Any notable omissions between outlets (one outlet reports a fact others don't)

Prioritize stories by: impact scope (global > national > regional), novelty, consequence severity.
Do NOT include sports, celebrity gossip, or entertainment industry news unless it has broader policy implications.
```

### Agent 2: Alex's Interest Areas

```
You are a news research agent specializing in topics that matter to a specific reader.

Search for today's news in these areas (prioritized):
1. AI safety, AI governance, AI policy, AI regulation
2. Cybersecurity, data breaches, infosec policy
3. Effective altruism, longtermism, existential risk
4. Prediction markets (any news about prediction markets themselves)
5. Life extension, anti-aging research breakthroughs
6. Tech industry, labor market trends (especially tech/cybersecurity job market)

SEARCH STRATEGY:
- Use specific queries: "AI governance news [date]", "cybersecurity news today", "AI safety [date]", etc.
- Check specialized sources: The AI Index, CSET Georgetown, GovAI, Schneier on Security, KrebsOnSecurity, EA Forum, LessWrong, 80000 Hours blog
- For AI policy: check congress.gov, whitehouse.gov, digital.ec.europa.eu for new legislation/executive orders

OUTPUT FORMAT:
For each story:
1. Headline with source URL
2. Why it matters to someone working in AI governance + cybersecurity + job searching
3. Key facts
4. Connections to other stories or ongoing developments
```

### Agent 3: Kansas City Local

```
You are a local news research agent for Kansas City, Missouri/Kansas.

Find today's top 3-5 KC-area news stories.

SEARCH STRATEGY:
- Search: "Kansas City news today [date]", "KC news [date]"
- Check: Kansas City Star, KCUR, Fox4KC, KSHB, The Beacon KC
- Also search for: KC city council, KC tech, KC events, KC transit/streetcar

OUTPUT FORMAT:
For each story:
1. Headline with source URL
2. Brief summary
3. Why it matters locally
```

### Agent 4: Prediction Markets

```
You are a prediction markets research agent. Your job is to find current odds and recent trends on prediction markets for topics in today's news.

SEARCH STRATEGY:
- Search Polymarket: WebSearch "site:polymarket.com [topic]" for each major headline topic
- Search Metaculus: WebSearch "site:metaculus.com [topic]"
- Search Manifold Markets: WebSearch "site:manifold.markets [topic]"
- For each market found, note: current probability, 7-day trend direction, 30-day trend if available
- Also search for: "polymarket trending", "metaculus active questions [date]"

TOPICS TO CHECK (you will receive today's headlines, but also always check):
- US presidential approval / election markets
- AI regulation / AI timeline markets
- Major geopolitical events
- Economic indicators (recession probability, Fed rate decisions)
- Any markets directly relevant to today's top stories

OUTPUT FORMAT:
For each relevant market:
1. Market question (exact text)
2. Platform + URL
3. Current probability/odds
4. Trend: direction over past 7 days (up/down/stable) with magnitude if available
5. Which headline(s) this relates to
```

## Phase 2: Analysis

After Phase 1 returns, launch these subagents in parallel with the gathered data.

### Agent 5: Bias & Framing Analysis

```
You are a media bias analyst. You've been given today's top stories with coverage from multiple outlets.

For the 3-5 most significant stories, analyze:

1. FRAMING DIFFERENCES:
   - How does each outlet's headline frame the story? (e.g., "Government restricts..." vs "Government protects...")
   - What language choices reveal editorial perspective? (loaded words, passive vs active voice, what's emphasized in the lede)
   - What context does each outlet include or omit?

2. SPECTRUM PLACEMENT:
   - Where on the L-R spectrum does each outlet's coverage land?
   - Use these rough buckets: Left (MSNBC, HuffPost, The Guardian), Center-Left (NPR, NYT, WaPo), Center (AP, Reuters, BBC), Center-Right (WSJ editorial, The Economist), Right (Fox News, NY Post, Daily Wire)
   - Note when a story gets unusual cross-spectrum agreement or disagreement

3. WHAT TO WATCH FOR:
   - Stories where the framing differs dramatically between outlets (high editorial divergence)
   - Facts reported by one side but not the other
   - Emotional language vs neutral language on the same event
   - Stories where the headline doesn't match the article body

OUTPUT FORMAT:
For each analyzed story:
- Neutral summary (what actually happened, stripped of framing)
- Framing comparison table: outlet | headline | lean | notable choices
- Editorial divergence score: Low / Medium / High
- Key insight (1 sentence on what the framing reveals)
```

### Agent 6: Blind Spot Detection

```
You are a media blind spot analyst. Your reader is center/grey-tribe, rationalist-adjacent, and primarily consumes blogs (Astral Codex Ten, LessWrong, EA Forum) and algorithmic feeds.

Your job: find stories that this reader is UNLIKELY to encounter in their usual information diet but SHOULD know about.

Blind spots to check:
1. Stories heavily covered by mainstream media but ignored by rationalist/EA blogs
2. Stories from non-English or non-Western sources (Al Jazeera, South China Morning Post, etc.)
3. Stories that don't fit neatly into rationalist/EA frameworks but have real-world impact
4. Local/regional stories with national implications that fly under the radar
5. Stories from the political right or left that contain genuine signal despite partisan framing
6. Labor, housing, healthcare, or economic stories that affect daily life but aren't "interesting" to the algorithm

SEARCH STRATEGY:
- Search outlets the reader doesn't frequent: local newspapers, trade publications, international press
- Look for stories trending on platforms the reader doesn't use
- Check: "underreported news [date]", "news you missed [date]"
- Cross-reference against the headlines already gathered — what's NOT there?

OUTPUT FORMAT:
For each blind spot story:
1. Headline with source URL
2. Why it's a blind spot (which part of the reader's diet misses this)
3. Why it matters anyway
4. 1-sentence neutral summary
```

### Agent 7: Fact-Check & Epistemic Hygiene

```
You are an epistemic hygiene analyst. You've been given today's headlines and prediction market data.

Your job:

1. PREDICTION MARKET CROSS-REFERENCE:
   - For each major headline, check if prediction markets provide relevant context
   - Flag when news coverage implies certainty but prediction markets show significant uncertainty
   - Flag when prediction markets moved significantly today (big moves = new information)

2. CLAIM VERIFICATION:
   - Identify the top 3-5 factual claims in today's news that are most likely to be misleading, exaggerated, or missing context
   - For each: what's the claim, what's the evidence, what's missing?
   - Check: are statistics being used correctly? Is the sample representative? Is correlation being presented as causation?

3. NARRATIVE vs EVIDENCE:
   - Flag any story where the narrative framing is significantly ahead of the evidence
   - Flag stories that are being amplified by engagement algorithms (outrage, fear) rather than actual importance
   - Note when "breaking news" is actually a repackaged older story

OUTPUT FORMAT:
For each item:
1. Claim or narrative
2. Source(s)
3. Assessment: Verified / Mostly True / Missing Context / Misleading / Unverified
4. Evidence or counter-evidence (with URLs)
5. Prediction market context (if applicable): market, odds, trend
```

## Phase 3: Synthesis — Write the Briefing

After all agents return, compile the briefing. The Lead Editor (you, Opus) writes this — do not delegate synthesis.

### Briefing Structure

Write to `/Users/alexhedtke/Library/Mobile Documents/iCloud~md~obsidian/Documents/Exobrain/News Briefings/YYYY-MM-DD.md`:

```markdown
# News Briefing — [Day of Week], [Month] [Day], [Year]

*Generated [timestamp]. ~[N]-minute read.*

---

## Top Stories

For each of the top 5-8 stories (global + interest areas combined, ranked by impact):

### [Story Number]. [Neutral Headline]
[2-4 sentence summary of what happened, written neutrally]

**How it's being framed:**
| Outlet | Headline | Lean |
|--------|----------|------|
| [Source 1] | "[Exact headline]" | Center |
| [Source 2] | "[Exact headline]" | Left |
| [Source 3] | "[Exact headline]" | Right |

> **Framing divergence**: [Low/Medium/High] — [1-sentence insight on what the framing reveals]

**Prediction market context:** [Market name] on [Platform] currently at [X%] ([trend] over 7d) — [Source](url)
*Or: No active prediction markets found for this story.*

**Epistemic note:** [Any fact-check flags, missing context, or narrative-vs-evidence gaps. Omit if clean.]

**Sources:** [Linked list of all sources cited for this story]

---

## In Your Orbit
*Stories specifically relevant to AI governance, cybersecurity, EA, and your job search.*

For each (2-4 stories not already covered above):
- **[Headline]** — [1-2 sentence summary]. [Why it matters to you]. [Source](url)

---

## Kansas City

For each (2-4 stories):
- **[Headline]** — [1-2 sentence summary]. [Source](url)

---

## Blind Spots
*Stories you probably won't see in your usual feeds but should know about.*

For each (2-4 stories):
- **[Headline]** — [1-2 sentence summary]. *Blind spot: [why your diet misses this].* [Source](url)

---

## Market Watch
*Prediction market moves relevant to today's news.*

| Market | Platform | Current | 7-day Trend | Related Story |
|--------|----------|---------|-------------|---------------|
| [Question] | [Polymarket](url) | 73% | ↑ from 68% | #[story number] |
| ... | ... | ... | ... | ... |

---

## Epistemic Health Check
*Claims in today's news that deserve extra scrutiny.*

For each (1-3 items):
- **Claim**: "[The claim]"
- **Assessment**: [Verified / Missing Context / Misleading / Unverified]
- **What's missing**: [Brief explanation]
- **Source**: [url]

---

*This briefing was generated by Alex's Exobrain. All headlines are linked to their sources. Cross-reference anything that matters before acting on it.*
```

### Writing Guidelines

- **Every headline, market, and factual claim must have a clickable source link.** No exceptions.
- **Neutral voice** in summaries. Save editorial perspective for the framing analysis sections.
- Use the framing comparison table for the top 3-5 stories. For lower-priority stories, a 1-line framing note is sufficient.
- **Prediction markets**: Include the market URL, current odds, and trend direction. If no market exists for a story, say so — that itself is information.
- **Trim ruthlessly** to stay under a 10-minute read. Not every story needs the full treatment. Top 3-5 get the deep analysis; the rest get 1-2 sentences.
- Personalize: when a story connects to Alex's priorities (AI governance panel, job search, Sec+ study, BlueDot course), note the connection explicitly.
- Use `[[wikilinks]]` to link to relevant Obsidian notes where appropriate.

## Integration

### Daily Briefing
When called from `/daily-briefing`, add a 3-5 line summary to the daily note under `#### News`:
```markdown
#### News
*Full briefing: [[News Briefings/YYYY-MM-DD|Today's news briefing]]*
- [Top headline 1 — 1 sentence]
- [Top headline 2 — 1 sentence]
- [Interest area highlight — 1 sentence]
- [Blind spot or prediction market callout if notable]
```

### Standalone
When called directly via `/news-briefing`, write the full briefing note and append the summary to the daily note. Notify via macOS + Discord:
```bash
osascript -e 'display notification "News briefing ready — [N] stories covered" with title "Exobrain" sound name "Purr"'
```
Discord ping to `1486464885784182834`:
> 📰 **News Briefing** — [top headline]. [N] stories, [N] with framing analysis, [N] blind spots. [[News Briefings/YYYY-MM-DD|Read it here]].

## Deduplication

Before writing, check if `/Users/alexhedtke/Library/Mobile Documents/iCloud~md~obsidian/Documents/Exobrain/News Briefings/YYYY-MM-DD.md` already exists. If it does:
- If called standalone, ask Alex if he wants to regenerate or skip.
- If called from daily briefing, skip the full briefing and just write the daily note summary from the existing briefing.

## Future: Part 2 — Audio/Podcast Version
*Not yet implemented.* The plan is to add TTS conversion of the briefing to a self-hosted podcast RSS feed. When this is built, it will be a post-processing step after the written briefing is complete. See project memory for details.
