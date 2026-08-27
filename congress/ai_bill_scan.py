#!/usr/bin/env python3
"""Scan a whole Congress for AI-related bills and tally who signed what, by party.

Reads govinfo's BILLSTATUS bulk-data zips -- the authoritative Library of
Congress feed that congress.gov itself renders -- so sponsor, cosponsor, party,
committee, and action data are primary-source and complete, not scraped or
recalled. No API key, no rate limit: the per-chamber zip is ~12-30 MB.

    # one-time (or whenever you want fresh data)
    curl -sSL -o /tmp/billstatus/s.zip \\
      https://www.govinfo.gov/bulkdata/BILLSTATUS/119/s/BILLSTATUS-119-s.zip
    curl -sSL -o /tmp/billstatus/hr.zip \\
      https://www.govinfo.gov/bulkdata/BILLSTATUS/119/hr/BILLSTATUS-119-hr.zip

    python3 congress/ai_bill_scan.py /tmp/billstatus/*.zip -o /tmp/ai-bills.json

Emits JSON: every AI-related bill with its sponsor and cosponsors (name, party,
state, signing date), plus a per-member index so you can ask "which Republicans
have put their name on AI-risk legislation" and get an answer backed by
signatures rather than vibes.

Classification into buckets (risk/oversight, kids, deepfakes, security, China,
deregulation, adoption) is KEYWORD-BASED and therefore a first pass, not a
verdict -- the `bucket` field is a sorting aid for a human read, and every bill
carries its full title so the call can be checked.
"""
import argparse
import json
import re
import sys
import xml.etree.ElementTree as ET
import zipfile

# A title has to hit one of these to count as AI-related. Deliberately broad --
# false positives are cheap to drop by eye, a missed bill is invisible.
AI_TITLE = re.compile(
    r"\bartificial intelligence\b|\bA\.?I\.?\b|deep ?fakes?\b|machine learning"
    r"|algorithmic|chat ?bots?\b|frontier model|foundation model"
    r"|superintelligen|large language model|generative", re.I)

# Subject terms that mark an AI bill even when the short title hides it.
AI_SUBJECT = re.compile(r"artificial intelligence|machine learning", re.I)

BUCKETS = [
    # (bucket, regex over title) -- first match wins, so order matters.
    ("deregulation/preemption",
     r"preempt|uniformity|moratorium|sandbox|regulatory relief|unleash"
     r"|streamlin|permitting|red tape"),
    ("risk/oversight/liability",
     r"risk|safety|safe\b|oversight|accountab|audit|evaluat|transparen"
     r"|liabilit|whistleblower|guardrail|red.?team|assur|govern|standards"
     r"|impact assessment|civil rights|discriminat|due process"),
    ("children/companion-bots",
     r"child|kid|minor|youth|teen|student|school|companion|guard\b|parent"),
    ("deepfakes/likeness/elections",
     r"deep ?fake|fake|likeness|voice|impersonat|fraud|scam|election"
     r"|nonconsensual|intimate|take it down|no fakes|provenance|watermark"),
    ("security/China/export",
     r"china|chinese|adversar|export|chip|semiconductor|theft|espionage"
     r"|national security|defense|nuclear|biosecur|bioweapon|weapon"
     r"|critical infrastructure|cyber"),
    ("energy/data centers",
     r"data ?cent|energy|electric|grid|water|ratepayer|utility"),
    ("workforce/adoption/promotion",
     r"workforce|training|education|adopt|leadership|innovat|competitive"
     r"|research|small business|rural|health|medic|agricultur|modern"),
]


def text(node, path, default=""):
    if node is None:
        return default
    found = node.findtext(path)
    return found.strip() if found else default


def bucket_for(title):
    low = title.lower()
    for name, pattern in BUCKETS:
        if re.search(pattern, low):
            return name
    return "other"


def person(item):
    return {
        "name": text(item, "fullName"),
        "bioguide": text(item, "bioguideId"),
        "party": text(item, "party"),
        "state": text(item, "state"),
        "date": text(item, "sponsorshipDate") or None,
        "original": text(item, "isOriginalCosponsor") == "True",
        "withdrawn": text(item, "sponsorshipWithdrawnDate") or None,
    }


def parse_bill(xml_bytes):
    try:
        bill = ET.fromstring(xml_bytes).find("bill")
    except ET.ParseError:
        return None
    if bill is None:
        return None

    title = text(bill, "title")
    subjects = [s.findtext("name", "") for s in
                bill.iterfind("subjects/legislativeSubjects/item")]
    policy = text(bill, "policyArea/name")
    haystack_subj = " ".join(subjects + [policy])
    if not (AI_TITLE.search(title) or AI_SUBJECT.search(haystack_subj)):
        return None

    sponsors = [person(i) for i in bill.iterfind("sponsors/item")]
    cosponsors = [person(i) for i in bill.iterfind("cosponsors/item")]
    actions = [{"date": text(a, "actionDate"), "text": text(a, "text"),
                "type": text(a, "type")}
               for a in bill.iterfind("actions/item")]
    committees = sorted({text(c, "name")
                         for c in bill.iterfind("committees/item")} - {""})

    return {
        "id": f"{text(bill, 'type')}{text(bill, 'number')}",
        "congress": text(bill, "congress"),
        "title": title,
        "introduced": text(bill, "introducedDate"),
        "policyArea": policy,
        "subjects": subjects,
        "bucket": bucket_for(title),
        "sponsors": sponsors,
        "cosponsors": cosponsors,
        "committees": committees,
        "latestAction": text(bill, "latestAction/text"),
        "latestActionDate": text(bill, "latestAction/actionDate"),
        "actionCount": len(actions),
        # "moved" = anything past introduction/referral, i.e. real committee or
        # floor activity. A bill with only IntroReferral actions is inert.
        "moved": any(a["type"] not in ("IntroReferral", "") for a in actions),
        "becameLaw": bool(bill.find("laws")),
        "url": text(bill, "legislationUrl"),
    }


def scan(paths):
    bills = []
    for path in paths:
        with zipfile.ZipFile(path) as zf:
            names = [n for n in zf.namelist() if n.lower().endswith(".xml")]
            for i, name in enumerate(names, 1):
                rec = parse_bill(zf.read(name))
                if rec:
                    bills.append(rec)
                if i % 2000 == 0:
                    print(f"  {path}: {i}/{len(names)} scanned, "
                          f"{len(bills)} AI bills", file=sys.stderr)
    bills.sort(key=lambda b: (b["id"][0], int(re.sub(r"\D", "", b["id"]) or 0)))
    return bills


def index_members(bills):
    """Per-member roll-up: what they sponsored, what they cosponsored, buckets."""
    members = {}
    for bill in bills:
        for role, people in (("sponsor", bill["sponsors"]),
                             ("cosponsor", bill["cosponsors"])):
            for p in people:
                if p["withdrawn"]:
                    continue
                key = p["bioguide"] or p["name"]
                m = members.setdefault(key, {
                    "name": p["name"], "party": p["party"], "state": p["state"],
                    "sponsored": [], "cosponsored": [], "buckets": {}})
                m["sponsored" if role == "sponsor" else "cosponsored"].append(
                    {"id": bill["id"], "title": bill["title"],
                     "bucket": bill["bucket"], "date": p["date"]})
                m["buckets"][bill["bucket"]] = m["buckets"].get(bill["bucket"], 0) + 1
    for m in members.values():
        m["total"] = len(m["sponsored"]) + len(m["cosponsored"])
    return members


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("zips", nargs="+", help="govinfo BILLSTATUS zip(s)")
    ap.add_argument("-o", "--out", default="-", help="JSON output path")
    ap.add_argument("--party", help="only index members of this party (R/D/I)")
    args = ap.parse_args()

    bills = scan(args.zips)
    members = index_members(bills)
    if args.party:
        members = {k: v for k, v in members.items() if v["party"] == args.party}

    payload = {"billCount": len(bills), "bills": bills,
               "members": dict(sorted(members.items(),
                                      key=lambda kv: -kv[1]["total"]))}
    out = json.dumps(payload, indent=1)
    if args.out == "-":
        print(out)
    else:
        with open(args.out, "w") as fh:
            fh.write(out)
        print(f"{len(bills)} AI-related bills, {len(members)} members "
              f"-> {args.out}", file=sys.stderr)


if __name__ == "__main__":
    main()
