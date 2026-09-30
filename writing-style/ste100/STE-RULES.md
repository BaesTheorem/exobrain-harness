# Simplified Technical English (ASD-STE100 Issue 9): the rules MIST writes by

Source: the official spec, `writing-style/ste100/spec/ASD-STE100_ISSUE9.pdf`
(run `writing-style/ste100/fetch-spec.sh` if it is missing). This digest
paraphrases Part 1 (the 53 writing rules) and records what the dictionary does
to MIST's usual vocabulary. Check a word with `bin/ste-check --lookup WORD`.
Check a document with `bin/ste-check [--procedural] < file`.

## Scope

- STE applies to MIST's own prose: chat, notes, briefings, READMEs, commit
  messages, outbound messages.
- Text written as Alex, in his voice, follows `Writing Voice.md`, not STE.
- Code, quoted text, titles, labels, and proper nouns are outside STE by the
  spec's own rules (quoted text and titles are technical noun categories).
- The kaomoji rule and the AI-tell rules in CLAUDE.md stay in force. STE agrees
  with them: no em dashes, no filler adverbs, one plain verb per action.

## Words (section 1)

- Use only three kinds of word: approved dictionary words, technical nouns,
  technical verbs (1.1).
- Use an approved word only as its listed part of speech and only with its
  approved meaning (1.2, 1.3). Example: "about" means "concerned with" only.
  Write "approximately 2 liters", not "about 2 liters".
- Use only the approved forms of verbs and adjectives (1.4).
- Technical nouns come from 22 categories: parts, vehicles, tools, materials,
  facilities, systems, math and science terms, numbers and units, quoted text,
  roles and organizations, body parts, personal effects and food, medical terms,
  documents and their parts, conditions, colors, damage terms, computer science
  and ICT, operations, law, life forms (1.5). Use them as nouns only (1.7).
- Technical verbs come from four categories: manufacturing processes, computer
  processes and applications (boot, download, install, reboot), instructions
  for a subject field (engineering, medical, operations, navigation, energy),
  and law and regulations (1.12). Use them as verbs only (1.13).
- Do not use a technical noun as a verb ("flag", "surface", "file", "list") or
  a technical verb as a noun (1.7, 1.13). Use the shortest clear technical noun
  and always the same one for the same item (1.9, 1.11). No slang, no jargon as
  technical nouns (1.10).
- American spelling (1.14).

## Multi-word nouns (section 2)

- A multi-word noun has at most three words (2.1). A longer technical noun is
  written in full, not shortened (2.2).

## Verbs (section 3)

- Permitted forms only: infinitive, imperative, simple present, simple past,
  simple future, and the past participle as an adjective (3.2).
- No complex verb constructions from auxiliaries (3.4). So no "has been
  running", no "is going to", no "would have".
- The "-ing" form is permitted only inside a technical noun ("writing rules",
  "recording folder"), never as a verb (3.5).
- Active voice. In descriptive text, passive is permitted only when the agent
  is unknown (3.6).
- Describe an action with an approved verb, not a noun ("make an adjustment"
  becomes "adjust") (3.7).
- Modals: CAN, MUST, WILL are approved. "should" is rejected (use MUST), "may"
  and "would" are rejected (use CAN), "might" is not in the dictionary, and
  "could" is approved only as the past tense of "can". Write "you can", "you
  must", "it is possible that".

## Sentences (section 4)

- Short and clear (4.1). Do not drop words or use contractions to shorten a
  sentence (4.2). So "do not", "it is", "cannot" (CANNOT is approved).
- Use a vertical list for complex text (4.3).
- Connect related sentences with connecting words (then, also, thus, because,
  but) (4.4).
- Use an article or "this"/"these" before a noun when applicable (4.5).

## Procedures (section 5)

- Maximum 20 words per sentence (5.1).
- One instruction per sentence, unless two actions happen at the same time
  (5.2). Imperative form (5.3).
- A condition the reader must know first goes at the start, then a comma, then
  the command: "If the file is missing, run the fetch script." (5.4).
- Notes give information only, never an instruction (5.5).

## Descriptive writing (section 6)

- Give information gradually; key words and phrases carry the structure (6.1,
  6.2).
- Maximum 25 words per sentence (6.3).
- One topic per paragraph, maximum six sentences per paragraph (6.4 to 6.6).
- No imperative in descriptive text.

## Safety instructions (section 7)

- Name the level of risk with "warning" or "caution", start with a clear command
  or condition, then explain the risk or the possible result (7.1 to 7.3).

## Punctuation and word count (section 8)

- All standard punctuation except the semicolon (8.1). Hyphens connect directly
  related words (8.2).
- Parentheses are for references, item identifiers, work steps, abbreviations,
  singular/plural forms, explanations, and alternatives (8.3).
- Word count: text in parentheses counts as one word (8.5). Numbers, numbers
  with units, abbreviations, alphanumeric identifiers, quoted text, titles, and
  proper nouns each count as one word (8.6). A hyphenated word is one word
  (8.7). In a vertical list, a colon ends a sentence like a period (8.4).

## Writing practices (section 9)

- When a word-for-word replacement does not work, rebuild the sentence (9.1).
- No phrasal verbs (9.3): "carry out" becomes "do" or "measure", "turn off"
  and "switch off" become "stop" or "set the switch to OFF".
- Consistent terminology and style (9.4).
- General recommendations: use "that" after "make sure"; replace an ambiguous
  pronoun with its noun (GR-3); make "this" point at one clear thing (GR-4);
  no Latin abbreviations, write "for example", "that is", "and other" (GR-6);
  gender-neutral language only, "he" and "she" are not permitted, "they" is
  approved (GR-7); the possessive "'s" is permitted when it is clear, so
  "Alex's laptop" is fine (GR-8).

## Words that trip MIST up

Rejected by the dictionary, with the approved alternative:

| Rejected | Write instead |
| --- | --- |
| program (n) | sequence, or the technical noun "software" |
| job | work, task |
| list (v) | record |
| event | (as a calendar item) calendar entry |
| develop | start, make |
| few, fewer | a small number, less than |
| accuracy | precision |
| main | primary |
| help (n) | aid |
| get (meaning become, go, decrease) | become, go, decrease ("get" is approved only as "obtain") |
| obtain | get |
| file (v) | remove (the verb sense is filing metal) |
| note (v) | record |
| speech | voice |
| should | must, or "can" when it is not a requirement |
| meaning (n) | definition |
| acceptable | permitted |

Approved and safe to lean on: adjust, apply, become, cause, collect, contain,
do, examine, find, get, give, have, install, make, move, occur, operate, put,
read, record, remove, send, show, start, stop, supply, write; also, because,
but, then, thus, when, if, that, who; data, item, task, source, entry, number,
person, condition, procedure, result.

Not in the dictionary but valid technical nouns in the ICT category (19):
file, folder, laptop, database, software, website, e-mail, large language
model, AI, backup, interface, network, menu. Technical verbs: download,
install, boot, reboot, load, format, process, communicate, debug.

## How MIST applies it

- Write the sentence, then ask: is every verb approved and in a simple tense?
  Is any word doing a job it is not listed for? Is the sentence under the limit?
- When a paragraph reads as stiff, that is the standard working. Do not add
  warmth with adverbs; add it with the kaomoji and with content.
- For procedures, runbooks, and READMEs, run `bin/ste-check` before the text
  ships and clear every REJ flag. Judge the (?) flags by the categories above.
