#!/usr/bin/env python3
"""Status-aware dedup lookup across Job Listings/ and archived listing notes.

Usage: dedup-lookup.py "<company or title fragment>" [...]
       dedup-lookup.py --stats
Prints matching listing notes with status/reapply/date_added so the caller can
apply the Re-Apply on Repost decision table instead of blanket-skipping.
"""
import os, re, sys

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
                if not re.search(r"^type:\s*job-listing", txt, re.M):
                    continue
                out.append({"name": fn[:-3], "path": p, "status": field(txt, "status"),
                            "reapply": field(txt, "reapply"), "company": field(txt, "company"),
                            "role": field(txt, "role") or field(txt, "title"),
                            "date_added": field(txt, "date_added"),
                            "job_id": field(txt, "job_id"), "url": field(txt, "url")})
    return out


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

for term in sys.argv[1:]:
    t = term.lower()
    hits = [n for n in notes if t in n["name"].lower() or t in n["company"].lower()]
    print(f"== {term} -> {len(hits)} hit(s)")
    for n in hits:
        print(f"   {n['name']} | status={n['status'] or '-'} | reapply={n['reapply'] or '-'} "
              f"| added={n['date_added'] or '-'} | id={n['job_id'] or '-'}")
