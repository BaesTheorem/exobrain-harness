#!/usr/bin/env python3
"""
Reusable resume + cover-letter PDF builder for Alex's job search.

Why this exists: tailoring a resume to a JD used to mean hand-rebuilding the
HTML/CSS every time. Now the canonical content lives in data/resume_data.json,
per-JD tweaks live in a small tailoring JSON, and this script renders a
pixel-stable PDF whose metadata is scrubbed to look human-authored (not the
Skia/PDF + HeadlessChrome fingerprint a raw Chrome/Playwright print leaves).

Findings baked in (see ATS & AI-Screening Playbook in the vault):
  - Real, selectable, single-column text (the #1 ATS auto-fail is unparseable PDFs).
  - Standard section headings, standard fonts, no tables/columns/graphics.
  - Clean DocInfo metadata: Author = Alex Hedtke, Title = "Resume - Alex Hedtke",
    a normal word-processor Producer/Creator, plausible timestamps.
  - Human filename: Alex_Hedtke_Resume[_<Tag>].pdf.
The prose itself (burstiness, no AI vocabulary, no em dashes) is the job of
/de-ai on the tailored summary/bullets and the cover letter, not this script.

USAGE
  # Canonical resume:
  python3 build.py resume
  # Tailored resume for a JD:
  python3 build.py resume --tailor tailoring/acme.json
  # Cover letter (markdown body = everything from the date line down):
  python3 build.py cover --md tailoring/acme_cover.md --company "Acme Corp" --tag ACME

Output defaults to ~/Downloads/. Requires: playwright (chromium), pypdf, qpdf.

TAILORING SCHEMA (all keys optional):
  {
    "tag": "ACME",                          # filename suffix + PDF title
    "summary": "...override summary...",     # must keep the 11+/4+ tenure framing
    "skills_append": {"Security": "extra, truthful, ATS keywords"},
    "experience_bullets": {                  # replace a job's bullets (reorder/polish)
        "clyde": ["bullet 1", "bullet 2", ...]
    },
    "title_suffix": {                        # opt-in note appended to a job's title line
        "clyde": " (IT function outsourced, July 2026)"
    },
    "leadership_include": ["ea_kc"],         # switch on an optional canonical entry
    "leadership": [                          # replace the Leadership and Community entries
        {"title": "Role | Org | Dates", "bullets": ["..."]}
    ]
  }
Never add a skill/tool/cert the canonical data does not support. Surgical only.

"leadership_include" switches on a canonical Leadership entry marked "optional": true,
by id. Those entries are real and documented, they just aren't relevant to most JDs, so
they stay off unless the employer or the role makes them relevant (ea_kc for the EA,
nonprofit, and AI-policy lane). Nothing here is invented; the entry already exists.

"leadership" is a full replacement for the Leadership and Community section, for roles
where community/nonprofit work carries the application instead of sitting at the bottom
as garnish (the EA / policy / research lane). Entries must be truthful and already
documented in [[Claude Reference]]; this hook reorders and surfaces, it does not invent.
Per that note, never use it to tie Guild of the Rose to security, IT, or technical claims.

title_suffix is for TRUTHFUL context only, never for retitling. Its one sanctioned
use is noting why a role ended, and only on applications with no cover letter field
(the letter is the better venue when one exists). Off by default; leave it out.
"""
import argparse, datetime, html, json, os, subprocess, tempfile
from pathlib import Path

HERE = Path(__file__).resolve().parent
DATA = HERE / "data" / "resume_data.json"
DOWNLOADS = Path.home() / "Downloads"

# Make a generated PDF look like a normal Word export rather than a browser print.
HUMAN_PRODUCER = "Microsoft® Word for Microsoft 365"

RESUME_CSS = """
  @page { size: letter; margin: 0.75in; }
  * { box-sizing: border-box; }
  body { font-family: Arial, Helvetica, sans-serif; font-size: 10.5pt; line-height: 1.32; color: #000; margin: 0; }
  h1 { font-size: 25pt; font-weight: 700; text-align: center; margin: 0 0 3px 0; letter-spacing: .3px; }
  .contact { text-align: center; font-size: 10pt; margin: 0 0 14px 0; }
  h2 { font-size: 12.5pt; font-weight: 700; text-transform: uppercase; margin: 14px 0 5px 0; letter-spacing: .3px; }
  p { margin: 0 0 7px 0; }
  .role { font-weight: 700; margin: 8px 0 3px 0; }
  ul { margin: 0 0 6px 0; padding-left: 20px; }
  li { margin: 0 0 4px 0; }
  .skill { margin: 0 0 4px 0; }
  .inprog { font-style: italic; margin: 0 0 6px 0; }
"""

COVER_CSS = """
  @page { size: letter; margin: 1in; }
  body { font-family: Arial, Helvetica, sans-serif; font-size: 11pt; line-height: 1.4; color: #000; margin: 0; }
  .name { font-size: 15pt; font-weight: 700; margin: 0 0 2px 0; }
  .contact { font-size: 10.5pt; margin: 0 0 16px 0; }
  p { margin: 0 0 11px 0; }
"""


def esc(s):
    return html.escape(str(s), quote=False)


def _ul(bullets):
    return "<ul>" + "".join(f"<li>{esc(b)}</li>" for b in bullets) + "</ul>"


def _with_suffix(title, suffix):
    """Attach an opt-in note to a role line, after the employer.

    Role lines are "Title | Employer | Dates", so a plain append would strand the
    note after the dates. Falls back to appending if the line isn't that shape.
    """
    if not suffix:
        return title
    parts = title.split(" | ")
    if len(parts) < 3:
        return title + suffix
    parts[1] += suffix
    return " | ".join(parts)


def _leadership(data, include):
    """Canonical Leadership entries, minus the opt-in ones this JD didn't ask for.

    An entry marked "optional": true stays off unless its id appears in the tailoring
    file's "leadership_include". That keeps community work in the canonical data (so it
    is never re-derived from scratch) while the default resume stays the length it was.
    """
    include = set(include)
    return [ld for ld in data.get("leadership", [])
            if not ld.get("optional") or ld.get("id") in include]


def build_resume_html(data, tailor):
    summary = tailor.get("summary", data["summary"])
    skills_append = tailor.get("skills_append", {})
    exp_override = tailor.get("experience_bullets", {})
    title_suffix = tailor.get("title_suffix", {})

    parts = [f'<!DOCTYPE html><html><head><meta charset="utf-8"><style>{RESUME_CSS}</style></head><body>']
    parts.append(f'<h1>{esc(data["name"])}</h1>')
    parts.append(f'<div class="contact">{esc(data["contact"])}</div>')

    parts.append("<h2>Professional Summary</h2>")
    parts.append(f"<p>{esc(summary)}</p>")

    parts.append("<h2>Technical Skills</h2>")
    for row in data["skills"]:
        text = row["text"]
        extra = skills_append.get(row["label"])
        if extra:
            # Append truthful ATS synonyms as a clean trailing sentence (avoids
            # misreading them as items of whatever clause the row ended on).
            text = text.rstrip()
            if not text.endswith("."):
                text += "."
            extra = extra.strip()
            if not extra.endswith("."):
                extra += "."
            text = text + " " + extra
        parts.append(f'<div class="skill"><b>{esc(row["label"])}:</b> {esc(text)}</div>')

    parts.append("<h2>Professional Experience</h2>")
    for job in data["experience"]:
        bullets = exp_override.get(job.get("id"), job["bullets"])
        role_title = _with_suffix(job["title"], title_suffix.get(job.get("id")))
        parts.append(f'<div class="role">{esc(role_title)}</div>')
        parts.append(_ul(bullets))

    parts.append("<h2>Education and Certifications</h2>")
    if data.get("education_inprogress"):
        parts.append(f'<p class="inprog">{esc(data["education_inprogress"])}</p>')
    for ed in data["education"]:
        parts.append(f'<div class="role">{esc(ed["title"])}</div>')
        parts.append(_ul(ed["bullets"]))

    leadership = tailor.get("leadership") or _leadership(data, tailor.get("leadership_include", []))
    if leadership:
        parts.append("<h2>Leadership and Community</h2>")
        for ld in leadership:
            parts.append(f'<div class="role">{esc(ld["title"])}</div>')
            parts.append(_ul(ld["bullets"]))

    parts.append("</body></html>")
    return "\n".join(parts)


def build_cover_html(data, body_md, company):
    # body_md = the letter from the date line down (author controls greeting/sign-off).
    blocks = [b.strip() for b in body_md.strip().split("\n\n") if b.strip()]
    body = "\n".join(f"<p>{esc(b).replace(chr(10), '<br>')}</p>" for b in blocks)
    return (
        f'<!DOCTYPE html><html><head><meta charset="utf-8"><style>{COVER_CSS}</style></head><body>'
        f'<div class="name">{esc(data["name"])}</div>'
        f'<div class="contact">{esc(data["contact"])}</div>'
        f"{body}</body></html>"
    )


def render_pdf(html_str, out_path, title, author="Alex Hedtke"):
    """Render HTML to PDF (Playwright), then scrub metadata + linearize (qpdf)."""
    from playwright.sync_api import sync_playwright

    with tempfile.NamedTemporaryFile("w", suffix=".html", delete=False, encoding="utf-8") as f:
        f.write(html_str)
        html_path = f.name
    raw_pdf = out_path + ".raw"
    try:
        with sync_playwright() as p:
            b = p.chromium.launch()
            pg = b.new_page()
            pg.goto("file://" + html_path)
            pg.wait_for_load_state("networkidle")
            pg.pdf(path=raw_pdf, format="Letter", print_background=True,
                   prefer_css_page_size=True)
            b.close()
        _clean_metadata(raw_pdf, out_path, title, author)
    finally:
        for p_ in (html_path, raw_pdf):
            try:
                os.remove(p_)
            except OSError:
                pass


def _clean_metadata(src, dst, title, author):
    import pypdf

    reader = pypdf.PdfReader(src)
    writer = pypdf.PdfWriter(clone_from=reader)
    # Drop the Skia/PDF + HeadlessChrome DocInfo, write a human word-processor story.
    now = datetime.datetime.now()
    stamp = "D:" + now.strftime("%Y%m%d%H%M%S") + "-05'00'"
    writer.add_metadata({
        "/Title": title,
        "/Author": author,
        "/Creator": HUMAN_PRODUCER,
        "/Producer": HUMAN_PRODUCER,
        "/Subject": "",
        "/Keywords": "",
        "/CreationDate": stamp,
        "/ModDate": stamp,
    })
    # Remove the XMP packet (parallel metadata mirror) so it can't contradict DocInfo.
    try:
        if "/Metadata" in writer._root_object:  # noqa: SLF001 (pypdf has no public API to drop the XMP packet)
            del writer._root_object["/Metadata"]  # noqa: SLF001
    except Exception:
        pass
    tmp = dst + ".tmp"
    with open(tmp, "wb") as fh:
        writer.write(fh)
    # qpdf full-rewrite (linearize) drops orphaned objects and old byte ranges.
    try:
        subprocess.run(["qpdf", "--linearize", tmp, dst], check=True,
                       stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        os.remove(tmp)
    except (subprocess.CalledProcessError, FileNotFoundError):
        os.replace(tmp, dst)  # qpdf missing: still better than the raw print


def _verify(path):
    import pypdf
    m = pypdf.PdfReader(path).metadata or {}
    return {k: m.get(k) for k in ("/Title", "/Author", "/Creator", "/Producer")}


def main():
    ap = argparse.ArgumentParser(description="Build Alex's resume / cover-letter PDFs with clean metadata.")
    sub = ap.add_subparsers(dest="cmd", required=True)

    pr = sub.add_parser("resume", help="Build a resume (canonical or tailored).")
    pr.add_argument("--tailor", help="Path to a tailoring JSON (surgical overrides).")
    pr.add_argument("--out", help="Output PDF path (default ~/Downloads/Alex_Hedtke_Resume[_Tag].pdf).")

    pc = sub.add_parser("cover", help="Build a cover letter from a markdown body.")
    pc.add_argument("--md", required=True, help="Markdown file: letter from the date line down.")
    pc.add_argument("--company", required=True, help="Company name (for the PDF title).")
    pc.add_argument("--tag", required=True, help="Short company tag for the filename.")
    pc.add_argument("--out", help="Output PDF path (default ~/Downloads/Alex_Hedtke_Cover_Letter_Tag.pdf).")

    args = ap.parse_args()
    data = json.loads(DATA.read_text(encoding="utf-8"))

    if args.cmd == "resume":
        tailor = {}
        if args.tailor:
            tailor = json.loads(Path(args.tailor).read_text(encoding="utf-8"))
        tag = tailor.get("tag")
        out = args.out or str(DOWNLOADS / (f"Alex_Hedtke_Resume_{tag}.pdf" if tag else "Alex_Hedtke_Resume.pdf"))
        title = f"Resume - {data['name']}"
        render_pdf(build_resume_html(data, tailor), out, title)
        print(f"Resume -> {out}\n  metadata: {_verify(out)}")

    elif args.cmd == "cover":
        body = Path(args.md).read_text(encoding="utf-8")
        out = args.out or str(DOWNLOADS / f"Alex_Hedtke_Cover_Letter_{args.tag}.pdf")
        title = f"Cover Letter - {data['name']}"
        render_pdf(build_cover_html(data, body, args.company), out, title)
        print(f"Cover letter -> {out}\n  metadata: {_verify(out)}")


if __name__ == "__main__":
    main()
