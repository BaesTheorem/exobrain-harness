# ASD-STE100 reference

MIST writes in Simplified Technical English (ASD-STE100 Issue 9) by default. This
folder holds the material that makes that possible without reading the 434-page
spec each session.

- `STE-RULES.md`: the digest of the writing rules and the words that trip MIST
  up. CLAUDE.md imports it (through the space-free symlink `~/.claude/ste-rules.md`),
  so it is in context in every session.
- `fetch-spec.sh`: downloads the official PDF and extracts `spec/ste100.txt`.
- `spec/`: the PDF and the extracted text. **Gitignored.** ASD gives the spec
  away free but does not permit redistribution. Run `fetch-spec.sh` to rebuild it.
- `bin/ste-check` (repo root): the checker. It parses the dictionary out of
  `spec/ste100.txt`, flags unapproved words with the spec's alternative, and
  flags sentences over the length limit. Run it on any procedure or document
  before it ships. See the docstring for the output format and its limits.

The spec lives at [asd-ste100.org](https://www.asd-ste100.org/). Issue 9 is the
edition dated 2025-01-15.
