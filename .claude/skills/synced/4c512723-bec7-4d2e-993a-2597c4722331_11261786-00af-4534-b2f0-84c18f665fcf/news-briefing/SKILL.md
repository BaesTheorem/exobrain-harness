---
name: news-briefing
description: Comprehensive news intelligence briefing with bias analysis, blind spot detection, prediction market cross-referencing, and epistemic hygiene. Writes a cited, beautiful report to Obsidian. Use when the user asks for "news", "news briefing", "what's happening in the world", "headlines", "catch me up on news", "news report", or when triggered by the daily briefing.
---

# News Briefing

A personalized intelligence briefing that goes beyond headlines. Analyzes how stories are framed across the political spectrum, surfaces blind spots, cross-references prediction markets, and fact-checks key claims — all with citations.

**Output**: Standalone note in `/Users/alexhedtke/Documents/Exobrain/News Briefings/YYYY-MM-DD.md`
**Target length**: Under a 10-minute read (~2,000-2,500 words)
**Reference**: Read `[[Alex's Tastes]]` (`/Users/alexhedtke/Documents/Exobrain/Alex's Tastes.md`) for personalization context.

## Architecture

You are the **Lead Editor** (Opus). You delegate gathering to 3 subagents, then perform all analysis and synthesis yourself. Phase 2 analysis (bias, framing, blind spots, fact-checking) does NOT need separate subagents — you have the gathered data and can analyze it directly during synthesis.

```
Lead Editor (Opus)
    │
    ├── Gathering (3 parallel subagents)
    │   ├── Main news agent (global + interest areas) — sonnet
    │   ├── KC local agent — haiku
    │   └── Prediction markets agent — haiku
    │
    └── Synthesis: Lead Editor analyzes + writes briefing
        (bias/framing, blind spots, epistemic checks — all inline)
```

## Token Efficiency Rules

- **Defuddle all web pages.** Subagents must use `npx @anthropic/defuddle@latest "[URL]"` (via Bash) instead of raw WebFetch when reading article content. This strips navigation, ads, and boilerplate, often cutting page tokens by 60-80%. Only fall back to WebFetch if defuddle fails.
- **KC local and prediction markets use `model: "haiku"`** — these are structured data-gathering tasks that don't need Sonnet's reasoning.
- **Main news agent uses `model: "sonnet"`** — framing comparison requires noting subtle editorial choices.
- **Trim before returning.** Subagents should return structured summaries, not raw article text. Each story should be 5-10 lines max in the subagent output.

## Phase 1: News Gathering

Launch all 3 subagents in parallel.

### Agent 1: Main News (global + interest areas)

`model: "sonnet"`, `subagent_type: "general-purpose"`

```
You are a news research agent. Find today's top news stories across two categories.

USE DEFUDDLE: When reading any web page, run:
  npx @anthropic/defuddle@latest "[URL]"
This extracts clean article text and saves tokens. Only use WebFetch as a fallback.

CATEGORY A — GLOBAL/NATIONAL (find 6-8 stories):
- Search: "top news today [date]", "breaking news [date]"
- Check: AP News, Reuters, BBC, NPR, Al Jazeera, The Guardian
- For each story, note which outlets cover it and their exact headline phrasing (this is critical for framing analysis later)
- Prioritize by: impact scope, novelty, consequence severity
- Skip: sports, celebrity gossip, entertainment unless it has policy implications

CATEGORY B — INTEREST AREAS (find 3-5 stories not already in Category A):
1. AI safety, AI governance, AI policy, AI regulation
2. Cybersecurity, data breaches, infosec policy
3. Effective altruism, longtermism, existential risk
4. Life extension, anti-aging breakthroughs
5. Tech industry, labor market trends (especially tech/cybersecurity job market)

Search specialized sources: CSET Georgetown, GovAI, Schneier on Security, KrebsOnSecurity, EA Forum, LessWrong, congress.gov for new legislation.

OUTPUT FORMAT (structured, concise — 5-10 lines per story max):
For each story:
1. Headline / topic (neutral framing)
2. Category: Global or Interest
3. Sources covering it (outlet name + URL + their exact headline text, minimum 2 outlets for Global stories)
4. Key facts (3-5 bullet points)
5. Notable omissions between outlets (if any)
6. Why it matters to someone in AI governance + cybersecurity (for Interest stories)
```

### Agent 2: Kansas City Local

`model: "haiku"`, `subagent_type: "general-purpose"`

```
You are a local news research agent for Kansas City, Missouri/Kansas.
Find today's top 3-5 KC-area news stories.

USE DEFUDDLE: When reading any web page, run:
  npx @anthropic/defuddle@latest "[URL]"
Only use WebFetch as a fallback.

SEARCH: "Kansas City news today [date]", "KC news [date]"
CHECK: Kansas City Star, KCUR, Fox4KC, KSHB, The Beacon KC
ALSO: KC city council, KC tech, KC events, KC transit/streetcar

OUTPUT (keep it brief — 3-4 lines per story):
For each story:
1. Headline with source URL
2. 1-2 sentence summary
3. Why it matters locally
```

### Agent 3: Prediction Markets

`model: "haiku"`, `subagent_type: "general-purpose"`

```
You are a prediction markets research agent. Find current odds and trends for topics likely in today's news.

SEARCH STRATEGY:
- Polymarket: WebSearch "site:polymarket.com [topic]"
- Metaculus: WebSearch "site:metaculus.com [topic]"
- Manifold Markets: WebSearch "site:manifold.markets [topic]"

ALWAYS CHECK (regardless of today's headlines):
- US presidential approval / election markets
- AI regulation / AI timeline markets
- Major geopolitical events (active conflicts, treaties)
- Economic indicators (recession probability, Fed rate decisions)

Also search: "polymarket trending", "metaculus active questions"

OUTPUT (structured table format):
For each relevant market:
1. Market question (exact text)
2. Platform + URL
3. Current probability/odds
4. 7-day trend: direction + magnitude
5. Related topic (e.g., "US politics", "AI regulation", "economy")
```

## Phase 2: Synthesis — Lead Editor

After all agents return, **you** (Opus) perform the analysis and write the briefing. Do not delegate this.

### Analysis Steps (do these mentally before writing)

1. **Bias & framing analysis** — For the top 3-5 global stories, compare how outlets headline and frame the story. Note loaded language, passive vs active voice, context included/omitted. Assign editorial divergence: Low / Medium / High.

2. **Blind spot detection** — Alex is center/grey-tribe, rationalist-adjacent, primarily reads blogs (ACX, LessWrong, EA Forum) and algorithmic feeds. Identify 2-4 stories from the gathered data (or that the agents missed) that his information diet would miss:
   - Mainstream stories ignored by rationalist blogs
   - Non-English / non-Western sources
   - Labor, housing, healthcare stories the algorithm won't surface
   - Stories from the political right or left with genuine signal

3. **Epistemic hygiene** — For the top 3-5 claims in today's news:
   - Cross-reference with prediction market data (news implies certainty but markets show uncertainty?)
   - Flag misleading statistics, correlation-as-causation, or narrative ahead of evidence
   - Note when "breaking news" is a repackaged older story

### Briefing Structure

Write to `/Users/alexhedtke/Documents/Exobrain/News Briefings/YYYY-MM-DD.md`:

```markdown
# News Briefing — [Day of Week], [Month] [Day], [Year]

*Generated [timestamp]. ~[N]-minute read.*

---

## Top Stories

(Top 5-8 stories, global + interest combined, ranked by impact)

### [N]. [Neutral Headline]
[2-4 sentence summary, neutral voice]

**How it's being framed:**
| Outlet | Headline | Lean |
|--------|----------|------|
| [Source 1] | "[Exact headline]" | Center |
| [Source 2] | "[Exact headline]" | Left |
| [Source 3] | "[Exact headline]" | Right |

> **Framing divergence**: [Low/Medium/High] — [1-sentence insight]

**Prediction market context:** [Market] on [Platform] at [X%] ([trend] over 7d) — [Source](url)
*Or: No active prediction markets for this story.*

**Epistemic note:** [Fact-check flags or missing context. Omit if clean.]

**Sources:** [linked list]

---

## In Your Orbit
*Stories relevant to AI governance, cybersecurity, EA, and your job search.*

(2-4 stories not already covered above)
- **[Headline]** — [1-2 sentences]. [Why it matters to you]. [Source](url)

---

## Kansas City

(2-4 stories)
- **[Headline]** — [1-2 sentences]. [Source](url)

---

## Blind Spots
*Stories you probably won't see in your usual feeds.*

(2-4 stories)
- **[Headline]** — [1-2 sentences]. *Blind spot: [why your diet misses this].* [Source](url)

---

## Market Watch

| Market | Platform | Current | 7-day Trend | Related Story |
|--------|----------|---------|-------------|---------------|
| [Question] | [Polymarket](url) | 73% | ↑ from 68% | #[N] |

---

## Epistemic Health Check
*Claims in today's news that deserve extra scrutiny.*

(1-3 items)
- **Claim**: "[The claim]"
- **Assessment**: [Verified / Missing Context / Misleading / Unverified]
- **What's missing**: [Brief explanation]
- **Source**: [url]

---

*Generated by Alex's Exobrain. All headlines linked to sources. Cross-reference before acting.*
```

### Writing Guidelines

- **Every headline, market, and factual claim must have a clickable source link.** No exceptions.
- **Neutral voice** in summaries. Editorial framing goes in the analysis sections.
- Full framing table for top 3-5 stories; 1-line framing note for the rest.
- **Prediction markets**: Include URL, current odds, and trend. If no market exists, say so — that itself is information.
- **Trim ruthlessly** to stay under 10 minutes. Top 3-5 get deep analysis; the rest get 1-2 sentences.
- Personalize: connect stories to Alex's priorities (AI governance, job search, Sec+ study) explicitly.
- Use `[[wikilinks]]` to link to relevant Obsidian notes.

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
When called directly via `/news-briefing`, write the full briefing note and append the summary to the daily note. Notify via macOS:
```bash
osascript -e 'display notification "News briefing ready — [N] stories covered" with title "Exobrain" sound name "Purr"'
```

## Deduplication

Before writing, check if `/Users/alexhedtke/Documents/Exobrain/News Briefings/YYYY-MM-DD.md` already exists:
- Standalone: ask Alex if he wants to regenerate or skip.
- From daily briefing: skip and just write the daily note summary from the existing briefing.

## Future: Part 2 — Audio/Podcast Version
*Not yet implemented.* TTS conversion to self-hosted podcast RSS feed. See project memory for details.
