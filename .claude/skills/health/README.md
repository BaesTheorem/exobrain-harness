# Health Skill

## Gitignored Files

### `health-concerns-config.md`

Private config defining which health concerns are actively tracked, their frontmatter properties (name, type, scale), key correlations to flag, and pointers to the concern dossier notes in the Obsidian vault.

**To rebuild**: Create `health-concerns-config.md` in this directory with:
- A table of frontmatter properties (property name, type, scale, when to log)
- Key correlation rules (e.g., which combinations of values to flag)
- List of active concerns with paths to their dossier notes in `Health Log/Concerns/`

The evening winddown skill reads this file at runtime to prompt for symptom scores and write them to Health Log frontmatter.
