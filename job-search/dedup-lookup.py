#!/usr/bin/env python3
"""Status-aware dedup lookup across Job Listings/ and archived listing notes.

Usage: dedup-lookup.py "<company or title fragment>" [...]
       dedup-lookup.py --url "<apply URL>" [...]
       dedup-lookup.py --stats
Prints matching listing notes with status/reapply/date_added so the caller can
apply the Re-Apply on Repost decision table instead of blanket-skipping.

--url exists for the aggregator lanes. Built In and WeWorkRemotely cards carry
the job title but not the employer name, so company-based matching cannot fire
until a JD read has already revealed the employer -- which is exactly the read
the note was written to prevent. The apply URL is known before the read, so
check leads by URL first. On 2026-09-02 that check found 5 of 12 Built In leads
already noted, one of which had cost a duplicate JD read that day.
"""
import os, re, sys, urllib.parse

import listings

ROOTS = ["/Users/alexhedtke/Exobrain/Projects/Get new job/Job Listings",
         "/Users/alexhedtke/Exobrain/Archive"]


def field(txt, key):
    m = re.search(r"^%s:\s*(.*)$" % key, txt, re.M)
    return m.group(1).strip().strip('"') if m else ""


def load():
    out = []
    for root in ROOTS:
        for dirpath, _, files in os.walk(root):
            for fn in files:
                if not fn.endswith(".md"):
                    continue
                p = os.path.join(dirpath, fn)
                try:
                    txt = open(p, encoding="utf-8", errors="replace").read(4000)
                except OSError:
                    continue
                if not re.search(r"^type:\s*['\"]?job-listing\b", txt, re.M):
                    continue
                out.append({"name": fn[:-3], "path": p, "status": field(txt, "status"),
                            "reapply": field(txt, "reapply"), "company": field(txt, "company"),
                            "role": field(txt, "role") or field(txt, "title"),
                            "date_added": field(txt, "date_added"),
                            "job_id": field(txt, "job_id"),
                            # schema field is apply_url; an earlier "url" lookup silently
                            # matched nothing because no note has a bare url: key
                            "url": field(txt, "apply_url")})
    # Near-miss notes are retired into a ledger (listings.py, Alex 2026-10-28);
    # their dedup still has to fire, so the ledger rows load as notes.
    for r in listings.load_ledger():
        out.append({"name": r["name"], "path": "ledger", "status": f"{r['status'] or 'skipped'} (retired)",
                    "reapply": "", "company": r["company"], "role": r["role"],
                    "date_added": r["date_added"], "job_id": r["job_id"], "url": r["apply_url"]})
    return out


SUFFIXES = r"\b(corporation|corp|incorporated|inc|llc|l\.?p|ltd|limited|company|co|group|holdings|international|plc)\b\.?"


def norm(s):
    """Lowercase, drop corporate suffixes and punctuation. 'Acme Corporation' -> 'acme'."""
    s = re.sub(SUFFIXES, " ", s.lower())
    return " ".join(re.sub(r"[^a-z0-9&]+", " ", s).split())


def company_match(term, n):
    """Match either direction on normalized names, whole words only.

    Plain substring missed 'Acme Corporation' against notes filed as 'Acme - ...'
    (2026-09-28): the search term was longer than the stored company. Reverse
    containment catches that; the whole-word bound and 3-char minimum keep a
    short stored name from matching every term that happens to contain it.
    """
    t = norm(term)
    for cand in (n["company"], n["name"].split(" - ")[0]):
        c = norm(cand)
        if not c or not t:
            continue
        if re.search(r"\b%s\b" % re.escape(t), c):
            return True
        if len(c) >= 3 and re.search(r"\b%s\b" % re.escape(c), t):
            return True
    return False


def norm_url(u):
    """Canonical form of an apply URL for comparison.

    Exact string equality missed a USAJOBS note on 2026-11-12: the API hands back
    https://www.usajobs.gov:443/job/891575400 while the note held the same URL
    without the port, so the scan wrote a new note over a 7-day-old candidate.
    Drops the scheme, a default port, "www.", a trailing slash, the fragment and
    utm_* tracking parameters. Other query parameters stay, because some boards
    carry the job id there (gh_jid, jk).
    """
    p = urllib.parse.urlsplit(u.strip().lower())
    host = p.hostname or ""
    if host.startswith("www."):
        host = host[4:]
    if p.port and p.port not in (80, 443):
        host = f"{host}:{p.port}"
    q = [(k, v) for k, v in urllib.parse.parse_qsl(p.query, keep_blank_values=True)
         if not k.startswith("utm_")]
    return host + p.path.rstrip("/") + ("?" + urllib.parse.urlencode(q) if q else "")


def url_match(term, n):
    """Same canonical URL, or the note's job_id is a whole path/query token of the URL.

    The job_id arm catches a board that serves one posting at two URL shapes. The
    6-character minimum keeps short ids from matching unrelated numbers.
    """
    if n["url"] and norm_url(n["url"]) == norm_url(term):
        return True
    jid = n["job_id"].strip("'\" ").lower()
    return len(jid) >= 6 and jid in re.split(r"[/?&=#._-]+", term.lower())


notes = load()
if "--stats" in sys.argv:
    from collections import Counter
    print("notes:", len(notes))
    for k, v in Counter(n["status"] or "(none)" for n in notes).most_common():
        print(f"  {k}: {v}")
    print("reapply:true ->")
    for n in notes:
        if n["reapply"].lower() == "true":
            print(f"  {n['name']} [{n['status']}]")
    sys.exit()

args = sys.argv[1:]
by_url = "--url" in args
if by_url:
    args = [a for a in args if a != "--url"]

for term in args:
    t = term.lower()
    if by_url:
        hits = [n for n in notes if url_match(term, n)]
    else:
        hits = [n for n in notes if t in n["name"].lower() or t in n["company"].lower()
                or company_match(term, n)]
    print(f"== {term} -> {len(hits)} hit(s)")
    for n in hits:
        print(f"   {n['name']} | status={n['status'] or '-'} | reapply={n['reapply'] or '-'} "
              f"| added={n['date_added'] or '-'} | id={n['job_id'] or '-'}")
