---
name: de-ai
description: Remove AI-generated patterns from text to make it sound more human and authentic. Use whenever you are generating text to share externally (such as cover letters, social media posts, etc) or the user says "make this sound human", "de-AI this", "this sounds too AI", "make it natural", "humanize this", "rewrite this naturally", or pastes text that they want cleaned up from AI-sounding language.
---

# Remove AI-Generated Patterns from Text

## Purpose
Transform AI-generated text to sound more human by removing telltale patterns and adding authentic details.

## Usage

```
/de-ai
[text to modify]
```

Or just:
```
/de-ai
```
(Will use the most recent assistant output)

Or with directions:
```
/de-ai
Make the third paragraph sound more like a startup founder wrote it
```

## Core Transformations

### 1. Add Specific Details
- Replace generalizations with concrete examples
- Add operational details only an insider would know
- Include actual numbers, names, timeframes (ask the user for those details if you need them, do not make them up)

### 2. Break Rhythm
- Vary sentence length dramatically
- Add pauses and afterthoughts
- Split flowing sentences into fragments

### 3. Insert Human Reactions
- Add "I" statements and personal observations
- Include what surprised or impressed you
- Show where you're witnessing from

### 4. Reorder by Importance
- Lead with what actually mattered to you
- Break logical flow for emotional truth
- Group by impact, not category

### 5. Leave Imperfections
- Allow informal punctuation
- Keep conversational fragments
- (Disregard if this is for a professional context)

### 6. Remove Em Dashes
- NEVER use "—" (em dash) - it's a massive AI tell
- Replace with periods, commas, or parentheses
- Use regular hyphens for compound words

### 7. Cut Hedging
- Remove "it's important to note"
- Delete unnecessary qualifiers
- Say what you mean directly

## 8. Don't use the "It's not X. It's Y." "correctio" pattern
- Remove any two-part clause that tries to use the "it isn't just [thing]. It's [other thing]."
- Some substitutes:
  - Direct assertion: Just state X, or Y without the negation. "It isn't just X." or "It's Y." (Often stronger.)
  - Reframing: "Think of it less as X and more as Y."
  - Concession + pivot: "Sure, it looks like X, but what's actually happening is Y."
  - Analogy: "It's like Y" (skip the contrast entirely).
  - Question + answer: "So what is it really? Y."
  - Intensifier: "It's Y, full stop." or "It's Y, plain and simple."
  - Parallel structure without negation: "Where most people see X, this is Y."
- The correctio pattern is heavily overused in AI-generated text because it creates easy rhetorical momentum. Cutting the "It's not X" half and just stating the point directly is usually the best fix.

## Overused AI Words to Replace

**Verbs:** delve → look into, leverage → use, utilize → use, underscore → show, showcase → show, foster → build, navigate → handle, streamline → simplify

**Adjectives:** comprehensive → complete, crucial → key, pivotal → important, meticulous → careful, robust → strong, commendable → good, invaluable → useful, cutting-edge → new

**Nouns:** landscape → field, realm → area, tapestry → mix, symphony → combination, synergy → teamwork, paradigm → model, framework → structure

**Phrases to delete entirely:**
- "it's important to note that"
- "in today's fast-paced world"
- "this is a testament to"
- "whether you're a beginner or an expert"
- "at its core"
- "strikes a balance between"

## Implementation

The skill:
1. Identifies AI patterns in the text
2. Suggests specific replacements
3. Adds concrete details where possible
4. Varies sentence structure
5. Removes hedging language
6. Preserves the core message while making it sound human

## Examples

**Before:** "She demonstrates exceptional problem-solving capabilities and leverages cross-functional collaboration to drive innovative solutions."

**After:** "She solved our GPU memory issue in two days. Pulled in someone from infrastructure to help - they figured it out together."

**Before:** "This comprehensive approach underscores our commitment to delivering cutting-edge solutions."

**After:** "We built it this way because we wanted it to actually work."

## The Test

Read it aloud. Does it sound like a specific person talking? Not professional writing - but THIS person, in THIS context, explaining THIS thing.
