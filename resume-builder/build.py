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
    }
  }
Never add a skill/tool/cert the canonical data does not support. Surgical only.
"""
import argparse, datetime, html, json, os, subprocess, sys, tempfile
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


def build_resume_html(data, tailor):
    summary = tailor.get("summary", data["summary"])
    skills_append = tailor.get("skills_append", {})
    exp_override = tailor.get("experience_bullets", {})

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
        parts.append(f'<div class="role">{esc(job["title"])}</div>')
        parts.append(_ul(bullets))

    parts.append("<h2>Education and Certifications</h2>")
    if data.get("education_inprogress"):
        parts.append(f'<p class="inprog">{esc(data["education_inprogress"])}</p>')
    for ed in data["education"]:
        parts.append(f'<div class="role">{esc(ed["title"])}</div>')
        parts.append(_ul(ed["bullets"]))

    if data.get("leadership"):
        parts.append("<h2>Leadership and Community</h2>")
        for ld in data["leadership"]:
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
        if "/Metadata" in writer._root_object:
            del writer._root_object["/Metadata"]
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
