# resume-builder

Reusable PDF builder for Alex's resume and cover letters. Replaces hand-rebuilding
the HTML/CSS every time a resume is tailored to a JD.

## Why
Tailoring used to mean re-authoring a one-off HTML file. Now:
- Canonical resume content lives in `data/resume_data.json` (single source of truth).
- Per-JD tweaks live in a small `tailoring/<company>.json` (surgical overrides only).
- `build.py` renders a layout-stable PDF and **scrubs the metadata** so it doesn't
  carry the `Skia/PDF` + `HeadlessChrome` fingerprint a raw Chrome/Playwright print
  leaves (Title becomes "Resume - Alex Hedtke", Author "Alex Hedtke", Producer a
  normal word-processor string).

## Usage
```bash
cd "Exobrain harness/resume-builder"

# Canonical resume -> ~/Downloads/Alex_Hedtke_Resume.pdf
python3 build.py resume

# Tailored resume -> ~/Downloads/Alex_Hedtke_Resume_ACME.pdf
python3 build.py resume --tailor tailoring/acme.json

# Cover letter (markdown = letter from the date line down)
python3 build.py cover --md tailoring/acme_cover.md --company "Acme Corp" --tag ACME

# Job-search convention (Alex 2026-06-24): for a real application, write the PDF
# straight into that listing's dedicated folder instead of Downloads, via --out:
python3 build.py resume --tailor tailoring/acme.json \
  --out "/Users/alexhedtke/Exobrain/Projects/Get new job/Job Listings/Acme Corp - <Role>/Alex_Hedtke_Resume_ACME.pdf"
```
`--out <path>` overrides the default `~/Downloads/` destination for either subcommand.
The `/job-search` skill owns the per-listing folder convention; the builder just
writes wherever `--out` points (default stays Downloads for ad-hoc one-offs).
Requires: `playwright` (chromium), `pypdf`, `qpdf`.

## Tailoring schema (`tailoring/<company>.json`, all keys optional)
```json
{
  "tag": "ACME",
  "summary": "...override summary (KEEP the 11+/4+ tenure framing)...",
  "skills_append": { "Security": "Additional focus on <truthful ATS keywords>." },
  "experience_bullets": { "clyde": ["reordered / polished bullet", "..."] }
}
```
Job ids for `experience_bullets`: `clyde`, `geeksquad` (see `data/resume_data.json`).

**Hard rules (from [[Claude Reference]] "Tailored Resumes"):** surgical edits only.
Never add a skill/tool/cert the canonical data doesn't support. Don't change titles,
dates, employers, or section structure. The summary must always open with
"11+ years in IT, with 4+ years in an enterprise environment [role-relevant X]".

## ATS / AI-screening practices baked in
See the vault note **[[ATS & AI-Screening Playbook]]** (`Projects/Get new job/`).
The builder handles the document-side defenses automatically:
- Real selectable single-column text (the #1 ATS auto-fail is unparseable PDFs).
- Standard headings + fonts, no tables/columns/graphics/headers-footers.
- Clean DocInfo metadata + XMP packet removed + `qpdf --linearize` full rewrite.
- Human filename: `Alex_Hedtke_Resume[_Tag].pdf`.

What the builder does NOT do (still your job): the **prose**. Run `/de-ai` on any
tailored summary/bullets and on every cover letter so the writing keeps human
burstiness and no AI vocabulary. Keep tailoring truthful.

## Personal data (gitignored)
The harness repo is public, so the real resume content and PII are kept out of git:
- `data/resume_data.json` -- real canonical resume (name, contact, work history). **Gitignored.** Rebuild from `data/resume_data.example.json`.
- `tailoring/*.json` / `tailoring/*.md` -- real per-JD files. **Gitignored**, except `tailoring/example.json` and `tailoring/example_cover.md` which ship as templates.

To set up on a fresh machine: `cp data/resume_data.example.json data/resume_data.json` and fill it in (or restore from the daily backup, which is not size-limited and includes gitignored files).

## Updating the canonical resume
Edit `data/resume_data.json`. That is now the source of truth for the resume content
(the PDF at `Projects/Get new job/Alex_Hedtke_Resume.pdf` is a rendered artifact).
Regenerate with `python3 build.py resume`.
