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
- Also catch: "not only...but also", "It is not just..., it's...", "no..., just..."
- Some substitutes:
  - Direct assertion: Just state X, or Y without the negation. "It isn't just X." or "It's Y." (Often stronger.)
  - Reframing: "Think of it less as X and more as Y."
  - Concession + pivot: "Sure, it looks like X, but what's actually happening is Y."
  - Analogy: "It's like Y" (skip the contrast entirely).
  - Question + answer: "So what is it really? Y."
  - Intensifier: "It's Y, full stop." or "It's Y, plain and simple."
  - Parallel structure without negation: "Where most people see X, this is Y."
- The correctio pattern is heavily overused in AI-generated text because it creates easy rhetorical momentum. Cutting the "It's not X" half and just stating the point directly is usually the best fix.

## 9. Break the Rule of Three
- AI loves listing exactly three adjectives, three phrases, or three examples
- Vary list lengths: use two, four, or one. Three consecutive triplets is a dead giveaway.
- "innovative, dynamic, and forward-thinking" → pick the one that actually matters and just say that

## 10. Stop Elegant Variation
- AI avoids repeating a word by cycling through synonyms ("the protagonist", "the key player", "the eponymous character" all for the same person)
- Just repeat the word. Humans do. Forced synonyms sound stilted.

## 11. Remove Trailing "-ing" Clauses
- AI tacks participial phrases onto sentence ends as fake analysis: "...highlighting the importance of X", "...underscoring broader trends", "...reflecting a shift toward Y"
- These add no content. Delete them or rewrite as a separate sentence with a concrete claim.

## 12. Kill "Challenges and Future Prospects" Framing
- AI defaults to a conclusion shape: "Despite its [positives], [subject] faces challenges such as..." followed by vague speculation about the future
- If there are real challenges, state them concretely. If you're speculating, don't.

## 13. Fix Formatting Tells
- **Overuse of bold**: Don't bold "key terms" mechanically. Bold sparingly or not at all.
- **Inline-header lists**: Bullet lists where every item is "**Bold label**: description" scream AI. Use prose or plain bullets.
- **Title Case in headings**: Use sentence case unless the style guide says otherwise.
- **Overuse of em dashes**: Covered in rule 6 above.
- **Curly quotes**: Use straight quotes and apostrophes (' and ") unless the platform renders them automatically.
- **Emoji as formatting**: Don't use emoji as bullet markers or section decorators in prose.

## 14. Remove Vague Attributions
- "Experts argue", "Industry reports suggest", "Observers have cited", "Some critics argue" — these are weasel phrases
- Either name the source or cut the claim

## 15. Watch for Promotional Tone
- Travel-guide or press-release language: "nestled in the heart of", "boasts a vibrant", "showcasing a rich tapestry of"
- If it reads like a brochure, rewrite it as something a person would actually say

## Overused AI Words to Replace

(Source: [Wikipedia: Signs of AI writing](https://en.wikipedia.org/wiki/Wikipedia:Signs_of_AI_writing))

**Verbs:** delve → look into, leverage → use, utilize → use, underscore → show, showcase → show/present, foster → build, navigate → handle, streamline → simplify, garner → get/earn, bolster → strengthen, encompass → include, cultivate → grow/develop, emphasize → stress/point out, highlight → point out/note, enhance → improve, align with → match/fit, resonate with → connect with, ensure → make sure, boast → have/feature

**Adjectives:** comprehensive → complete/full, crucial → key/important, pivotal → important, meticulous → careful/thorough, robust → strong/solid, commendable → good, invaluable → useful/essential, cutting-edge → new/latest, vibrant → lively/active, profound → deep/serious, intricate → complex/detailed, enduring → lasting, groundbreaking → new/original, renowned → well-known, diverse → varied

**Nouns:** landscape → field/area/scene, realm → area/domain, tapestry → mix/blend, symphony → combination, synergy → teamwork, paradigm → model/approach, framework → structure, interplay → interaction/relationship, intricacies → details/complexity, focal point → center/focus, testament → proof/sign

**Copula avoidance** (AI substitutes "is/are" with fancier verbs):
- "serves as" → "is"
- "marks" / "represents" → "is"
- "boasts" / "features" → "has"
- "maintains" / "offers" → just use "is" or "has"

**Significance/legacy filler** (delete or rewrite concretely):
- "plays a vital/significant/crucial/pivotal role"
- "underscores the importance of"
- "reflects broader [trends/themes]"
- "setting the stage for"
- "shaping the future of"
- "represents a shift"
- "key turning point"
- "evolving landscape"
- "indelible mark"
- "deeply rooted"

**Phrases to delete entirely:**
- "it's important to note that"
- "in today's fast-paced world"
- "this is a testament to"
- "whether you're a beginner or an expert"
- "at its core"
- "strikes a balance between"
- "valuable insights"
- "contributing to"
- "commitment to"
- "diverse array"
- "natural beauty"
- "nestled in"
- "in the heart of"

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
