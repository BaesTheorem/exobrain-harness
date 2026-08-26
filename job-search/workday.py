#!/usr/bin/env python3
"""Workday-direct discovery lane for /job-search: poll tenant boards, diff, gate.

Closes the gap the source-coverage checklist named explicitly: `ats-watchlist.py`
polls Greenhouse/Lever/Ashby, but a large share of mid-market and enterprise
employers host on Workday, and those postings frequently never crosspost. Same
idea as that script -- cut search engines out of discovery for employers we know
about -- against a different ATS.

Every Workday tenant exposes an unauthenticated JSON search endpoint behind the
SPA. Verified live 2026-08-26 against r1rcm:

    list    POST https://<host>/wday/cxs/<tenant>/<site>/jobs
            body {"appliedFacets": {...}, "limit": 20, "offset": N, "searchText": ""}
    detail  GET  https://<host>/wday/cxs/<tenant>/<site><externalPath>

Three things make this lane unusually strong per request:

  - The **facets in a board URL are the gates**. A recruiter-shared URL like
    ...?Location_Country=<US>&timeType=<Full time>&locations=<Remote, USA>
    is gates 1 and 2 pre-applied server-side, so the poll returns an
    already-filtered set instead of a whole company's req list. `--add` parses
    those query params straight out of the URL.
  - The **detail endpoint carries the comp band** in `jobDescription`, so gate 3
    is mechanical (band rule included) with no browser and no JD guesswork.
  - `canApply` + `posted` are the ATS's own answer to "is this still open,"
    which is exactly the apply-flow signal the skill's verification section says
    a rendered listing page does NOT prove.

Facet IDs are opaque per-tenant GUIDs and are NOT portable between employers.
Never hand-copy one board's GUID onto another tenant -- `--add` resolves and
prints each facet's human label so the config is auditable.

Usage:
    python3 workday.py --add "<board URL with filters>" [--why "reason"]
    python3 workday.py --list
    python3 workday.py                  # poll, diff vs snapshot, gate, report
    python3 workday.py --full           # ignore the diff, gate everything in lane
"""

import argparse
import concurrent.futures
import datetime as dt
import html
import json
import os
import re
import urllib.parse
import urllib.request

UA = ("Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36")

COMP_FLOOR = 75_000  # standard-lane floor; see gitignored Claude Reference.md
HOURS_PER_YEAR = 2080

VAULT = os.path.expanduser("~/Exobrain")
STATE_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "state")
BOARDS = os.path.join(STATE_DIR, "workday-boards.json")
SNAPSHOT = os.path.join(STATE_DIR, "workday-snapshot.json")

PAGE = 20  # Workday silently caps `limit` at 20, same trap as the Himalayas API

# Query params that are NOT facets. Anything else in a board URL is passed
# through to appliedFacets, so a tenant's custom facet works without a code edit.
NON_FACET = {"source", "q", "clientRequestID", "sortBy", "lang", "redirect",
             "jobsite", "workerSubType_dummy"}

WORKDAY_HOST = re.compile(
    r"https?://([a-z0-9-]+\.(?:wd\d+\.myworkdayjobs\.com|myworkdaysite\.com))/"
    r"(?:([a-z]{2}-[A-Z]{2})/)?([A-Za-z0-9_-]+)", re.I)
LOCALE_SEG = re.compile(r"^[a-z]{2}-[A-Z]{2}$")

# Title pre-filter, mirroring nicheboards.py / ats-watchlist.py. "workday" stays
# in DROP on purpose: on a Workday-hosted board it still means an HRIS
# specialist req, which is a genuine tool mismatch for Alex.
DROP = re.compile(
    r"\b(senior|sr\.?|lead|principal|staff|manager|director|head of|architect|"
    r"engineer (iii|iv|v)|vp|vice president|chief|supervisory|"
    r"epic|cerner|workday|oracle|salesforce|dynamics 365|mainframe|sap|zendesk|"
    r"pre-?sales|sales engineer|solutions engineer|account executive|"
    r"customer success)\b", re.I)
KEEP = re.compile(
    r"\b(analyst|it support|it operations|it specialist|helpdesk|help desk|"
    r"service desk|security|identity|iam|grc|compliance|administrator|"
    r"m365|microsoft 365|intune|endpoint|desktop support|technical support)\b", re.I)

# Workday tenants spell "remote" many ways in the location field, and gating on
# the literal word alone is a false negative that kills a whole employer's
# inventory (Cigna posts every remote req as "United States Work at Home").
REMOTE = re.compile(
    r"\bremote\b|work at home|work from home|home[- ]based|telecommut|"
    r"\bwfh\b|\bvirtual\b|\banywhere\b", re.I)
# Checked against title AND location: the location field is the tenant's coarse
# bucket and routinely says "Remote" for a seat the title marks hybrid or
# city-bound (CrowdStrike "Analyst I ... (Hybrid, St Louis)" under "USA - Remote").
HYBRID = re.compile(r"\bhybrid\b|\bon-?site\b|\bin-?office\b", re.I)

# "$54,661.00 - $85,842.89 per year", "$28.50/hr", "between $80,000 and $95,000".
MONEY = r"\$\s?([\d,]+(?:\.\d{2})?)"
COMP_RANGE = re.compile(
    MONEY + r"\s*(?:-|to|and|through|–|—)\s*" + MONEY, re.I)
COMP_SINGLE = re.compile(MONEY)
HOURLY = re.compile(r"per hour|hourly|/\s?hr\b|an hour|hour\b", re.I)
ANNUAL = re.compile(r"per year|annual|/\s?yr\b|a year|annum", re.I)


def _req(url: str, body: dict | None = None, timeout: int = 20):
    headers = {"User-Agent": UA, "Accept": "application/json"}
    data = None
    if body is not None:
        data = json.dumps(body).encode("utf-8")
        headers["Content-Type"] = "application/json"
    req = urllib.request.Request(url, data=data, headers=headers)
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return json.loads(r.read().decode("utf-8", "replace"))


def parse_board_url(url: str) -> dict:
    """Split a myworkdayjobs board URL into {host, tenant, site, facets, search}."""
    m = WORKDAY_HOST.match(url)
    if not m:
        raise ValueError("not a myworkdayjobs.com / myworkdaysite.com board URL")
    host, _locale, site = m.group(1), m.group(2), m.group(3)
    if LOCALE_SEG.match(site):  # locale sat where the site segment was expected
        rest = url.split(host, 1)[1].strip("/").split("/")
        site = rest[1] if len(rest) > 1 else site
    tenant = host.split(".")[0]
    qs = urllib.parse.parse_qs(urllib.parse.urlparse(url).query)
    facets = {k: v for k, v in qs.items() if k not in NON_FACET}
    return {"host": host, "tenant": tenant, "site": site,
            "facets": facets, "search": (qs.get("q") or [""])[0]}


def cxs(board: dict, suffix: str = "") -> str:
    return "https://%s/wday/cxs/%s/%s%s" % (
        board["host"], board["tenant"], board["site"], suffix)


def poll(board: dict) -> dict:
    """Every posting on one board under its pinned facets: {reqId: {...}}."""
    out, offset, total = {}, 0, None
    while total is None or offset < total:
        d = _req(cxs(board, "/jobs"), {
            "appliedFacets": board.get("facets") or {},
            "limit": PAGE, "offset": offset,
            "searchText": board.get("search") or "",
        })
        total = d.get("total", 0)
        page = d.get("jobPostings", [])
        if not page:
            break
        for j in page:
            bullets = j.get("bulletFields") or []
            key = bullets[0] if bullets else j.get("externalPath", "")
            out[key] = {
                "title": j.get("title", ""),
                "loc": j.get("locationsText", ""),
                "posted_label": j.get("postedOn", ""),
                "path": j.get("externalPath", ""),
                "url": "https://%s/%s%s" % (board["host"], board["site"],
                                            j.get("externalPath", "")),
            }
        offset += len(page)
    return out


def facet_labels(board: dict) -> dict:
    """Human labels for the pinned facet GUIDs -- the positive control on --add."""
    labels: dict[str, list[str]] = {}
    wanted = {v for vals in (board.get("facets") or {}).values() for v in vals}
    if not wanted:
        return labels
    d = _req(cxs(board, "/jobs"), {"appliedFacets": board["facets"],
                                   "limit": 1, "offset": 0, "searchText": ""})

    def walk(values, param):
        for v in values:
            if v.get("id") in wanted:
                labels.setdefault(param, []).append(
                    "%s (%s open)" % (v.get("descriptor", "?"), v.get("count", "?")))
            # Nested groups rebind the parameter: `locationMainGroup` wraps a
            # child group whose own facetParameter is the `locations` a board
            # URL actually pins. Without this the label silently goes missing.
            walk(v.get("values") or [], v.get("facetParameter") or param)

    for f in d.get("facets", []):
        walk(f.get("values") or [], f.get("facetParameter", "?"))
    return labels


def in_lane(title: str) -> bool:
    return bool(KEEP.search(title)) and not DROP.search(title)


def parse_comp(text: str) -> tuple[float | None, float | None, str]:
    """(low, high, basis) annualized from JD prose. (None, None, ...) if absent."""
    for sent in re.split(r"(?<=[.;])\s+", text):
        if "$" not in sent:
            continue
        if not re.search(r"pay|salary|compensation|rate|range", sent, re.I):
            continue
        hourly = bool(HOURLY.search(sent)) and not ANNUAL.search(sent)
        mult = HOURS_PER_YEAR if hourly else 1
        basis = "hourly x2080" if hourly else "annual"
        m = COMP_RANGE.search(sent)
        if m:
            lo = float(m.group(1).replace(",", "")) * mult
            hi = float(m.group(2).replace(",", "")) * mult
            return lo, hi, basis
        m = COMP_SINGLE.search(sent)
        if m:
            v = float(m.group(1).replace(",", "")) * mult
            return v, v, basis
    return None, None, "not stated"


def gate_comp(lo: float | None, hi: float | None) -> tuple[str, str]:
    """Band rule: a listed range passes if the floor falls anywhere inside it."""
    if lo is None and hi is None:
        return "lead", "comp not stated in JD -- needs a judgment call"
    top = hi if hi is not None else lo
    if top is not None and top < COMP_FLOOR:
        return "decline", "band top $%s under floor" % f"{int(top):,}"
    if lo is not None and lo < COMP_FLOOR:
        return "pass", "BAND-STRADDLE: bottom $%s under floor" % f"{int(lo):,}"
    return "pass", "clears floor"


def detail(board: dict, path: str) -> dict:
    d = _req(cxs(board, path))
    info = d.get("jobPostingInfo", {}) or {}
    raw = info.get("jobDescription", "") or ""
    text = html.unescape(re.sub(r"\s+", " ", re.sub(r"<[^>]+>", " ", raw)))
    lo, hi, basis = parse_comp(text)
    return {
        "title": info.get("title", ""),
        "loc": info.get("location", ""),
        "start": info.get("startDate", ""),
        "req": info.get("jobReqId", ""),
        "time_type": info.get("timeType", ""),
        "can_apply": info.get("canApply"),
        "posted": info.get("posted"),
        "url": info.get("externalUrl", ""),
        "lo": lo, "hi": hi, "basis": basis,
        "jd_chars": len(text),
    }


def load(path: str) -> dict:
    if os.path.exists(path):
        with open(path, encoding="utf-8") as f:
            return json.load(f)
    return {}


def save(path: str, obj: dict) -> None:
    os.makedirs(STATE_DIR, exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(obj, f, indent=1)


def discover_vault() -> dict:
    """Workday tenants already in the tracker, so re-apply reposts surface too.

    No facets: we only know the employer hosts here, not which slice Alex cares
    about, so these are polled whole and gated client-side.
    """
    found: dict[str, dict] = {}
    for root, dirs, files in os.walk(VAULT):
        dirs[:] = [d for d in dirs if not d.startswith(".")]
        for name in files:
            if not name.endswith(".md"):
                continue
            try:
                with open(os.path.join(root, name), encoding="utf-8",
                          errors="replace") as f:
                    text = f.read(65536)
            except OSError:
                continue
            if "type: job-listing" not in text[:600]:
                continue
            for m in WORKDAY_HOST.finditer(text):
                try:
                    b = parse_board_url(m.group(0))
                except ValueError:
                    continue
                b["facets"], b["search"] = {}, ""
                b["why"] = "auto: %s" % name[:-3]
                found.setdefault("%s/%s" % (b["tenant"], b["site"]), b)
    return found


def cmd_add(args) -> None:
    board = parse_board_url(args.url)
    key = "%s/%s" % (board["tenant"], board["site"])
    board["why"] = args.why or "added manually"
    board["added"] = dt.date.today().isoformat()
    jobs = poll(board)
    labels = facet_labels(board)
    print("board  %s  (%s)" % (key, board["host"]))
    print("facets pinned from the URL:")
    if board["facets"]:
        for param, vals in board["facets"].items():
            shown = labels.get(param) or []
            shown += ["<label unresolved>"] * (len(vals) - len(shown))
            # strict=False: a tenant can return fewer labels than pinned GUIDs
            # (stale facet), and an unresolved label is a warning, not a crash.
            for guid, label in zip(vals, shown, strict=False):
                print("   %-32s %s   [%s]" % (param, label, guid[:12] + "..."))
    else:
        print("   (none -- whole board will be polled)")
    lane = [j for j in jobs.values() if in_lane(j["title"])]
    print("live postings under these filters: %d  (%d match the title lane)"
          % (len(jobs), len(lane)))
    boards = load(BOARDS)
    boards[key] = board
    save(BOARDS, boards)
    print("saved to %s" % BOARDS)


def cmd_list(_args) -> None:
    boards = load(BOARDS)
    auto = discover_vault()
    print("pinned boards: %d" % len(boards))
    for key, b in sorted(boards.items()):
        print("  %-28s %-34s facets=%d  %s"
              % (key, b["host"], len(b.get("facets") or {}), b.get("why", "")))
    fresh = {k: v for k, v in auto.items() if k not in boards}
    print("auto-discovered from job-listing notes: %d new" % len(fresh))
    for key, b in sorted(fresh.items()):
        print("  %-28s %s" % (key, b.get("why", "")))


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--add", dest="url", help="pin a board URL (filters included)")
    ap.add_argument("--why", help="note why this board is on the watchlist")
    ap.add_argument("--list", action="store_true", help="show boards and exit")
    ap.add_argument("--full", action="store_true",
                    help="gate every in-lane posting, not just new ones")
    ap.add_argument("--days", type=int, default=0,
                    help="only report postings started within N days (0 = any)")
    ap.add_argument("--workers", type=int, default=6)
    args = ap.parse_args()

    if args.url:
        return cmd_add(args)
    if args.list:
        return cmd_list(args)

    boards = load(BOARDS)
    for key, b in discover_vault().items():
        boards.setdefault(key, b)
    if not boards:
        print("no Workday boards configured. Add one:\n"
              "  python3 workday.py --add \"<board URL>\" --why \"...\"")
        return

    print("floor $%s | %d Workday boards (%d pinned + auto-discovered)"
          % (f"{COMP_FLOOR:,}", len(boards), len(load(BOARDS))))

    prev = load(SNAPSHOT)
    snap: dict[str, dict] = {}
    failures: list[tuple[str, str]] = []
    with concurrent.futures.ThreadPoolExecutor(max_workers=args.workers) as ex:
        futs = {ex.submit(poll, b): key for key, b in boards.items()}
        for fut in concurrent.futures.as_completed(futs):
            key = futs[fut]
            try:
                snap[key] = fut.result()
            except Exception as e:  # noqa: BLE001 -- one dead tenant must not kill the sweep
                failures.append((key, "%s: %s" % (type(e).__name__, str(e)[:70])))

    targets, baselined = [], 0
    for key, jobs in sorted(snap.items()):
        first_poll = key not in prev
        if first_poll and not args.full:
            baselined += 1
            continue
        for jid, j in jobs.items():
            if not args.full and jid in prev.get(key, {}):
                continue
            if in_lane(j["title"]):
                targets.append((key, jid, j))

    print("polled %d ok, %d failed, %d baselined (diff starts next run)"
          % (len(snap), len(failures), baselined))
    for key, err in failures:
        print("   ! %-28s %s" % (key, err))
    print("in-lane postings to gate: %d\n" % len(targets))

    cutoff = (dt.date.today() - dt.timedelta(days=args.days)) if args.days else None
    survivors, leads, declines = [], [], []
    with concurrent.futures.ThreadPoolExecutor(max_workers=args.workers) as ex:
        futs = {ex.submit(detail, boards[k], j["path"]): (k, jid, j)
                for k, jid, j in targets}
        for fut in concurrent.futures.as_completed(futs):
            key, jid, j = futs[fut]
            try:
                d = fut.result()
            except Exception as e:  # noqa: BLE001 -- a dead detail page is not fatal
                declines.append((key, j, "detail fetch failed: %s"
                                 % type(e).__name__, None))
                continue
            row = (key, j, d)
            if cutoff and d["start"]:
                try:
                    if dt.date.fromisoformat(d["start"]) < cutoff:
                        continue
                except ValueError:
                    pass
            if d["can_apply"] is False or d["posted"] is False:
                declines.append((key, j, "ATS says not accepting applications", d))
                continue
            if d["time_type"] and "full" not in d["time_type"].lower():
                declines.append((key, j, "gate 2: %s" % d["time_type"], d))
                continue
            where = d["loc"] or j["loc"]
            title = d["title"] or j["title"]
            if HYBRID.search(title) or HYBRID.search(where):
                declines.append((key, j, "gate 1: hybrid/onsite marker in \"%s | %s\""
                                 % (title, where), d))
                continue
            if not REMOTE.search(where):
                declines.append((key, j, "gate 1: %s" % where, d))
                continue
            verdict, why = gate_comp(d["lo"], d["hi"])
            if verdict == "pass":
                survivors.append((*row, why))
            elif verdict == "lead":
                leads.append((*row, why))
            else:
                declines.append((key, j, "gate 3: %s" % why, d))

    def band(d):
        if d["lo"] is None:
            return "unlisted"
        if d["lo"] == d["hi"]:
            return "$%s (%s)" % (f"{int(d['lo']):,}", d["basis"])
        return "$%s - $%s (%s)" % (f"{int(d['lo']):,}", f"{int(d['hi']):,}", d["basis"])

    def show(rows, header):
        print("=" * 72)
        print("%s (%d)" % (header, len(rows)))
        print("=" * 72)
        for key, j, d, why in rows:
            print("-" * 72)
            print("[%s] %s" % (key, d["title"] or j["title"]))
            print("  %s | %s | req %s | started %s"
                  % (d["loc"] or j["loc"], d["time_type"], d["req"], d["start"]))
            print("  comp: %s -- %s" % (band(d), why))
            print("  apply-flow: canApply=%s posted=%s | JD %d chars archived"
                  % (d["can_apply"], d["posted"], d["jd_chars"]))
            print("  %s" % (d["url"] or j["url"]))

    show(survivors, "SURVIVORS -- all 4 gates pass mechanically")
    show(leads, "LEADS -- comp not stated, JD read decides")
    print("=" * 72)
    print("DECLINED (%d)" % len(declines))
    print("=" * 72)
    for key, j, why, _d in declines:
        print("  [%s] %-52s %s" % (key, j["title"][:52], why))

    save(SNAPSHOT, snap)
    print("\nsnapshot written: %s" % SNAPSHOT)


if __name__ == "__main__":
    main()
