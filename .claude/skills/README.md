# Skills

Each directory here is one Claude Code skill: a `SKILL.md` with frontmatter (name, trigger description) plus any scripts or references it needs. Claude Code loads them from this folder when the harness is the working directory.

## Links that point outside this repo

Skills cite two kinds of wikilinks that do not resolve inside the repo. `[[project_*]]`, `[[feedback_*]]` and `[[reference_*]]` point at MIST's private memory store (`~/.claude/projects/<project-slug>/memory/`, indexed by its `MEMORY.md`). Every other `[[...]]` link, and vault-relative paths like `Projects/...` or `Areas/...`, point at the owner's Obsidian vault. Neither is published. On a fresh clone those links are dead until you build your own memory store and vault; the skill text around each link says what the note holds, so the procedure still reads without it.

`synced/` is the Claude CLI's local cache of claude.ai-synced skills. It is gitignored and never committed.
