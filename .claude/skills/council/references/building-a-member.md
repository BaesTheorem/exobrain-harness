# Building a council member note

A member note is the only source of truth for one council member. An isolated agent reads it and then speaks as that character in a debate about a real problem. So the note must be correct, specific about how the character thinks and decides, and strictly canonical.

The five original notes were built with this procedure on 2026-10-05: one research agent per character, in parallel, with this guide as the brief.

## Hard rules

1. **Canon only.** Every claim comes from the media of the character, inside the canon scope that the note states. No fanon, no adaptations outside the scope, no "fans say", no speculation, no trivia about actors or production. If you cannot confirm a fact in the corpus, leave it out.
2. **Cite.** Every bullet in "Life in canon" and "Character" ends with a citation in parentheses. A wiki page is a finding aid. The corpus is the authority. When they disagree, the corpus wins.
3. **Quotes are exact and verified.** Use 5 to 8 quotes. Each one is words that the character speaks (or writes) in the source, copied from the corpus. Keep each quote to 1 to 3 sentences, under approximately 60 words. Use `...` to cut words. Prefer lines that show values and reasoning over catchphrases. Many popular quotes on the internet are fan-made or misattributed. If the verifier cannot find a quote, the quote does not go in.
4. **No council instructions in the note.** The note describes the character. It does not tell an agent how to play the character. The skill and `prompts/member.md` do that.
5. **House style.** Short sentences (25 words maximum), active voice, simple present for the nature of the character and simple past for events. No em dashes, en dashes, or semicolons. No "should", "may", "would", "might", "e.g.", "i.e.", or "etc.". Facts, not praise words. Quotes keep the spelling of the source.
6. **No song lyrics.** A content filter stops the session when a model writes song lyrics. Name a song, but do not quote it.

## Note template

```markdown
---
type: council-member
seat: <slug>
name: <display name>
full_name: <full canonical name>
aliases: [<canonical names, titles, and nicknames>]
media: <work(s), creator(s), years>
canon_scope: <one sentence: what counts as canon here, and what is excluded>
tags: [council]
---
# <display name>

<Two or three sentences: who this character is in canon.>

## Canon scope
<Two to four sentences. The works used, and what is excluded and why it matters.>

## Life in canon
- <10 to 20 chronological bullets: the events that made them, and the decisions they made. Each ends with a citation.>

## Character
### Values
- <Value: the canon event that shows it. (citation)>
### How they decide
- <How they reason, weigh risk, treat counsel, deal with uncertainty, and act under pressure. Anchor each pattern to specific canon decisions. (citations)>
### Strengths and skills
### Flaws and limits
### Relationships

## Voice
- <Register, vocabulary, sentence shape, and habits, as the source shows them.>

## Quotes
> [!quote] <citation, and who the line is said to>
> <exact words>

## Sources
- <primary text or transcripts, with a public URL where one exists>
- <reference wiki pages used as finding aids, with URLs>
```

Length: approximately 1,200 to 1,800 words before the Quotes section.

## Build a corpus

Put the corpus in the gitignored `tmp/` folder of the harness. Never commit source text.

- **Books.** Find an EPUB or a text file. Archive.org items often hold an `.epub` and an OCR `_djvu.txt`, and `https://archive.org/metadata/<id>` shows the files. Split the text into one file per chapter, with the book and chapter in the first line, so that citations are exact. OCR drops accents and garbles some letters, so read the file and correct the quote.
- **Web fiction.** Use the release files of the author or of the official typesetting project. Compare the chapter numbers with the official index: editions can split or merge chapters.
- **Television.** Fan transcripts are the practical source. chakoteya.net holds Doctor Who and Star Trek. Fandom wikis often hold a `Transcript:` namespace: get the titles with the MediaWiki API (`action=query&list=allpages&apnamespace=<id>`), then the text with `prop=revisions&rvprop=content` in batches of 40. Move the excluded material (live-action remakes, comics, podcasts, commentary) to a separate folder, so that no quote comes from outside the canon scope.
- **Wiki pages as finding aids.** `action=parse&prop=wikitext&page=<title>` on the MediaWiki API of the wiki gives the source of a character page. These pages are large: search them, do not read them whole.

## Verify the quotes

```bash
python3 .claude/skills/council/scripts/verify-quotes.py NOTE.md CORPUS_DIR [CORPUS_DIR ...]
python3 .claude/skills/council/scripts/verify-quotes.py --text "one phrase" CORPUS_DIR
```

The script reads every `> [!quote]` callout in the note. It compares word order and ignores case, punctuation, and typography. It prints each file that contains the quote, with the text around the match. Use that context to confirm who speaks the line: presence alone does not prove the speaker. `FUZZY` means OCR or transcript noise, so open the file and copy the real words. The exit status is 1 if a quote is missing.

Before you trust the script on a new corpus, run one positive control (a line you know is in the source) and one negative control (a line you know is not). If the negative control is found, the corpus or the script is wrong.

## Install the note

Put the note in `~/Exobrain/Council/Members/<display name>.md`. The `/council` roster is the folder, so the member takes a seat at the next session. Add a line for the seat to the table in `SKILL.md` and in the vault hub note `Council/Council.md`.
