#!/usr/bin/env python3
"""Is the posting still open? An API-first ladder, no browser on the first rung.

Most postings live on an ATS with a public JSON endpoint per job. A 404 there
is a definite answer at the cost of one small request, where a headless
browser load costs seconds and memory per posting. The ladder (after the
career-ops liveness checker, MIT):

  rung 1  ATS API     Greenhouse, Lever, SmartRecruiters: the per-job endpoint.
                      Workday: the CXS detail call and its `canApply` flag.
                      Ashby: the org board, then look for the job id.
  rung 2  plain GET   any other URL: HTTP status plus closed-banner phrases
                      in the page text ("no longer accepting", "position has
                      been filled", ...)
  rung 3  unknown     JS-rendered or blocked pages. Use jd-snapshot.py
                      (headless Chrome) or check by hand.

CONSERVATIVE BY DESIGN: a false "closed" costs a real job, so a posting is
`closed` only on a 404/410, `canApply: false`, an id missing from a board
that answered, or an explicit closed banner. A redirect, 403, 429, 5xx or a
timeout is `unknown`, never `closed`.

Usage:
    python3 job-search/liveness.py URL [URL ...]
    python3 job-search/liveness.py --note "<listing note>"
    python3 job-search/liveness.py --sweep [--write]   # every candidate note

`--write` marks a closed candidate note `status: closed` with
`closed_date` and `closed_evidence`. Applied, interviewing and offer notes are
reported, never changed.

Exit: 0 when every checked posting is open or unknown, 1 when any is closed.
"""

from __future__ import annotations

import argparse
import datetime as dt
import json
import re
import sys
import urllib.error
import urllib.request
from pathlib import Path

import jobprofile as P

UA = ("Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/155.0.0.0 Safari/537.36")
CLOSED_TEXT = re.compile(
    r"no longer (accepting applications|accepting|open|available)|"
    r"(position|job|role|requisition) (you are trying to apply for )?has been filled|"
    r"this (job|role|position|posting) (is|has) (closed|expired)|"
    r"(job|posting) (has )?expired|job (posting )?not found|"
    r"the job you are looking for (is no longer|does not exist)", re.I)
SCRIPT = re.compile(r"<(script|style|noscript)\b.*?</\1\s*>", re.I | re.S)
URL_KEYS = ("original_listing", "listing_url", "apply_url", "url")
PROTECTED = {"applied", "interviewing", "offer"}

GREENHOUSE = re.compile(r"(?:boards|job-boards)(?:-api)?\.greenhouse\.io/(?:v1/boards/)?([\w-]+)/jobs/(\d+)", re.I)
GH_EMBED = re.compile(r"[?&]gh_jid=(\d+)", re.I)
LEVER = re.compile(r"jobs\.lever\.co/([\w.-]+)/([0-9a-f-]{36})", re.I)
ASHBY = re.compile(r"jobs\.ashbyhq\.com/([\w.%-]+)/([0-9a-f-]{36})", re.I)
SMARTR = re.compile(r"(?:jobs|careers)\.smartrecruiters\.com/([\w-]+)/(\d+)", re.I)
WORKDAY = re.compile(r"https?://[\w.-]+\.myworkday(?:jobs|site)\.com/.*?/job/", re.I)


def http(url: str, timeout: int = 20) -> tuple[int, str]:
    req = urllib.request.Request(url, headers={"User-Agent": UA, "Accept": "application/json,text/html"})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            return r.status, r.read(8_000_000).decode("utf-8", "replace")
    except urllib.error.HTTPError as e:
        return e.code, ""


def verdict_from_status(code: int, rung: str) -> tuple[str, str]:
    if code == 200:
        return "open", f"{rung}: 200"
    if code in (404, 410):
        return "closed", f"{rung}: HTTP {code}"
    return "unknown", f"{rung}: HTTP {code}"


def check(url: str) -> tuple[str, str]:
    """Return (open | closed | unknown, evidence)."""
    try:
        if m := GREENHOUSE.search(url):
            return verdict_from_status(http(f"https://boards-api.greenhouse.io/v1/boards/{m[1]}/jobs/{m[2]}")[0],
                                       "greenhouse api")
        if m := LEVER.search(url):
            return verdict_from_status(http(f"https://api.lever.co/v0/postings/{m[1]}/{m[2]}")[0], "lever api")
        if m := SMARTR.search(url):
            return verdict_from_status(http(f"https://api.smartrecruiters.com/v1/companies/{m[1]}/postings/{m[2]}")[0],
                                       "smartrecruiters api")
        if m := ASHBY.search(url):
            code, body = http(f"https://api.ashbyhq.com/posting-api/job-board/{m[1]}")
            if code != 200:
                return verdict_from_status(code, "ashby board")
            ids = {j.get("id") for j in json.loads(body).get("jobs", [])}
            return ("open", "ashby board lists the id") if m[2] in ids else \
                   ("closed", "ashby board answered without this id")
        if WORKDAY.search(url):
            import workday
            board = workday.parse_board_url(url)
            path = "/job/" + url.split("/job/", 1)[1].split("?")[0]
            try:
                d = workday.detail(board, path)
            except urllib.error.HTTPError as e:
                # A withdrawn posting answers 403 with errorCode S22 ("permission
                # denied"); an open one on the same path shape answers 200
                # (positive control 2026-10-23). Any other 403 is a block.
                try:
                    body = json.loads(e.read().decode("utf-8", "replace") or "{}")
                except (json.JSONDecodeError, OSError):
                    body = {}
                if e.code == 403 and body.get("errorCode") == "S22":
                    return "closed", "workday cxs: 403 S22 (posting withdrawn)"
                return verdict_from_status(e.code, "workday cxs")
            if d.get("can_apply") is False:
                return "closed", "workday cxs: canApply false"
            return ("open", f"workday cxs: canApply {d.get('can_apply')}, posted {d.get('posted')}")
        code, body = http(url)
        if code in (404, 410):
            return "closed", f"page: HTTP {code}"
        if code != 200:
            return "unknown", f"page: HTTP {code} (try jd-snapshot.py)"
        # Visible text only. SPA ATSes (Rippling, Phenom) ship their UI strings,
        # "This job post is no longer available" among them, inside <script> on
        # every page, open or closed (two false closures on 2026-10-23).
        visible = re.sub(r"<[^>]+>", " ", SCRIPT.sub(" ", body))
        if hit := CLOSED_TEXT.search(visible):
            return "closed", f'page text: "{hit.group(0)}"'
        if len(re.sub(r"\s+", "", visible)) < 2000:
            return "unknown", "page: little server-rendered text (JS app, try jd-snapshot.py)"
        return "open", "page: 200, no closed banner"
    except (urllib.error.URLError, TimeoutError, ValueError, json.JSONDecodeError) as e:
        return "unknown", f"error: {str(e)[:80]}"


def fm_field(txt: str, key: str) -> str:
    m = re.search(rf"^{key}:\s*['\"]?([^'\"\n]*)", txt.split("\n---", 1)[0], re.M)
    return m.group(1).strip() if m else ""


def note_url(txt: str) -> str:
    for k in URL_KEYS:
        v = fm_field(txt, k)
        if v.startswith("http"):
            return v
    return ""


def mark_closed(path: Path, txt: str, evidence: str) -> None:
    head, sep, body = txt.partition("\n---")
    head = re.sub(r"^status:.*$", "status: closed", head, count=1, flags=re.M)
    today = dt.date.today().isoformat()
    head += f"\nclosed_date: {today}\nclosed_evidence: \"{evidence.replace(chr(34), chr(39))}\""
    path.write_text(head + sep + body, encoding="utf-8")


def candidate_notes() -> list[Path]:
    out = []
    root = P.listings_dir()
    for p in root.rglob("*.md") if root.exists() else []:
        txt = p.read_text(encoding="utf-8", errors="replace")[:3000]
        if re.search(r"^type:\s*['\"]?job-listing", txt, re.M) and fm_field(txt, "status") in (
                "candidate", *PROTECTED):
            out.append(p)
    return sorted(out)


def main() -> int:
    ap = argparse.ArgumentParser(description="API-first posting liveness check")
    ap.add_argument("urls", nargs="*")
    ap.add_argument("--note", action="append", default=[])
    ap.add_argument("--sweep", action="store_true", help="every candidate/applied note")
    ap.add_argument("--write", action="store_true", help="mark closed candidate notes")
    a = ap.parse_args()

    jobs: list[tuple[str, Path | None]] = [(u, None) for u in a.urls]
    for n in [*a.note, *(candidate_notes() if a.sweep else [])]:
        p = Path(n)
        u = note_url(p.read_text(encoding="utf-8", errors="replace"))
        if u:
            jobs.append((u, p))
        else:
            print(f"NO-URL   {p.name}")
    if not jobs:
        if a.sweep:
            print("no candidate or applied notes with a posting URL")
            return 0
        ap.error("give URLs, --note, or --sweep")

    closed = 0
    for url, note in jobs:
        verdict, why = check(url)
        label = note.name if note else url
        print(f"{verdict.upper():8} {label} | {why}")
        if verdict == "closed":
            closed += 1
            if note and a.write:
                txt = note.read_text(encoding="utf-8")
                if fm_field(txt, "status") in PROTECTED:
                    print(f"         not changed: status {fm_field(txt, 'status')}")
                else:
                    mark_closed(note, txt, why)
                    print("         -> status: closed")
    return 1 if closed else 0


if __name__ == "__main__":
    sys.exit(main())
