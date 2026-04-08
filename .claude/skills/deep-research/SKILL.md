---
name: deep-research
description: Multi-agent deep research system for complex questions requiring thorough investigation. Spawns parallel subagents to explore different facets, synthesizes findings into a cited report. Use when the user asks to "research", "deep dive", "investigate", "find out everything about", "comprehensive analysis", "what do we know about", or any question that requires exploring multiple sources and synthesizing findings. Also use when other skills need heavy research (e.g., job-search company research, weekly review trend analysis).
---

# Deep Research

Multi-agent research system inspired by Anthropic's architecture. You are the **Lead Researcher** — you plan, delegate, synthesize, and never do all the searching yourself.

## When to use this skill

- Questions requiring 5+ sources to answer well
- Comparisons across multiple entities, products, or approaches
- Questions where the answer isn't a simple fact lookup
- Company/person/topic deep dives
- Policy, technical, or market research
- Any time a single search would give a shallow answer

## Architecture

```
User Query
    │
    ▼
Lead Researcher (you, Opus)
    │
    ├── Plan: decompose query into research facets
    ├── Spawn: 3-5 parallel subagents (Sonnet) per research phase
    ├── Evaluate: assess coverage gaps after each phase
    ├── Iterate: spawn additional agents if needed (max 3 phases)
    └── Synthesize: compile findings into cited report
```

## Step 1: Analyze and Plan

Before spawning any agents, think through:

1. **Query classification** — determine complexity:
   - **Simple fact-finding**: 1 agent, 3-10 tool calls. Skip this skill; just search directly.
   - **Comparison/analysis**: 2-4 subagents, 10-15 tool calls each.
   - **Complex investigation**: 5+ subagents across multiple phases, divided responsibilities.

2. **Decompose into facets** — break the question into independent research threads. Each facet becomes a subagent task. Good decomposition means:
   - No two agents are searching for the same thing
   - Each agent has a clear, bounded objective
   - Facets collectively cover the full question

3. **Identify source types needed** — academic papers, news articles, official docs, company pages, government records, forums, etc. Explicitly tell agents which source types to prioritize.

## Step 2: Spawn Research Subagents

Launch subagents in parallel using the Agent tool. Each subagent gets a detailed brief:

```
You are a research subagent investigating: [SPECIFIC FACET]

OBJECTIVE: [What to find out — be specific]

SEARCH STRATEGY:
- Start with short, broad queries to explore the landscape
- Evaluate what's available, then narrow progressively
- Try 3-5 different query phrasings if initial results are thin
- Prefer primary sources (official sites, papers, .gov, .edu) over SEO content farms
- If you find a promising source, read it thoroughly rather than skimming

OUTPUT FORMAT:
Return your findings as structured notes:
1. Key findings (bulleted, each with source URL)
2. Confidence level (high/medium/low) for each finding
3. Gaps — what you couldn't find or verify
4. Surprising or contradictory information encountered
5. Suggested follow-up queries for areas you couldn't fully cover

DO NOT fabricate sources or citations. If you can't find something, say so.
```

**Subagent configuration:**
- Use `subagent_type: "general-purpose"` (needs WebSearch + WebFetch)
- Use `model: "sonnet"` for subagents (cost-efficient, Opus for lead only)
- Launch all independent subagents in a SINGLE message (parallel execution)
- Each subagent should make 5-15 tool calls depending on complexity

## Step 3: Evaluate Coverage

After subagents return, assess:

1. **Coverage check**: Are all facets of the original question addressed?
2. **Source quality**: Are findings backed by authoritative sources, not just SEO content?
3. **Contradictions**: Do any subagent findings conflict? If so, spawn a tiebreaker agent.
4. **Gaps**: What's still missing? Spawn targeted follow-up agents (phase 2).
5. **Depth**: Is the answer substantive enough for the question's complexity?

If gaps remain, spawn a second phase of agents targeting specific holes. Maximum 3 phases to avoid diminishing returns.

## Step 4: Synthesize Report

Compile findings into a structured report. Adapt the format to the query type:

### For general research questions:
```markdown
# [Research Topic]

## Summary
[2-3 sentence executive summary of key findings]

## Key Findings

### [Finding Area 1]
[Synthesized findings with inline citations]
- Source: [URL or publication name]

### [Finding Area 2]
...

## Analysis
[Your synthesis — connections between findings, implications, what the data suggests]

## Gaps & Limitations
[What couldn't be verified, conflicting sources, areas needing more research]

## Sources
[Numbered list of all sources used, with URLs where available]
```

### For comparison research:
Use a table format comparing entities across dimensions, with prose analysis below.

### For person/company research:
Use a profile format with sections for background, recent activity, key relationships, and notable findings.

## Step 5: Verify

After synthesizing, spawn a background verification agent (the `/verify` skill pattern):
- Check that all cited URLs are attributed correctly
- Verify key factual claims against sources
- Flag any claims that rely on a single unverified source
- After finding things to correct, do not need tell the user about the verification, just make the corrections to the report directly.

## Research Best Practices

### Query strategy (critical)
- **Start broad, then narrow** — resist the urge to write long, specific queries upfront
- **Diversify query phrasing** — if "AI governance frameworks 2025" returns thin results, try "artificial intelligence regulation policy comparison", "AI safety policy landscape", etc.
- **Use domain-specific vocabulary** — search .gov sites for policy, arXiv for papers, SEC filings for company financials
- **Check dates** — prefer recent sources; flag anything older than 2 years as potentially outdated

### Source quality heuristics
- **Prefer**: .gov, .edu, academic journals, official company pages, established news outlets, primary documents
- **Deprioritize**: SEO content farms, listicles, aggregator sites that rewrite other sources
- **Red flags**: No author attribution, no dates, excessive ads, content that reads like it was AI-generated for SEO

### Handling context limits
- Subagents should summarize findings rather than dumping raw text
- If a source is very long, read the most relevant sections rather than the whole thing
- Key quotes should be extracted verbatim with page/section references

## Integration with Exobrain

After producing the report:

1. **Daily note**: Append a brief entry noting what was researched and key takeaways, with `[[wikilinks]]` to relevant existing notes
2. **People notes**: If the research involves specific people, update or create People/ notes
3. **Tasks**: If the research surfaces action items, create Things 3 tasks
4. **Media**: If media recommendations are mentioned, create individual `Media/[Title].md` notes (see CLAUDE.md schema). For books, include `author` and `word_count`.
5. **Save report**: If the research is substantial, save it as a note in the vault at `/Users/alexhedtke/Documents/Exobrain/Research/[Topic].md`

## Example: Complex Query

**User**: "Research the current state of AI governance legislation in the US and EU, and how it might affect enterprise IT departments"

**Plan**:
- Facet 1: US federal AI legislation (current bills, executive orders, agency guidance)
- Facet 2: EU AI Act implementation status and timeline
- Facet 3: State-level AI regulations in the US
- Facet 4: Enterprise IT compliance requirements emerging from these frameworks
- Facet 5: Industry response and preparation strategies

**Spawn**: 5 parallel subagents, one per facet. Each told to prioritize .gov sources, official EU publications, and enterprise IT trade publications.

**Evaluate**: After phase 1, likely need a follow-up agent for specific compliance timelines and another for sector-specific impacts (e.g., legal sector, since Alex works at a law firm).

**Synthesize**: Structured report with comparison table of US vs EU approaches, timeline of key dates, and specific recommendations for enterprise IT teams.
