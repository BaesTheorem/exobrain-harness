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
import io
import json
import os
import re
import sys
import time
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

# Crawl bounds (added 2026-09-07 after an unfiltered auto-discovered board hung
# the lane). CVS Health reports total=19016 at ~0.75s a page: a whole-tenant
# crawl is ~950 sequential requests, and `with ThreadPoolExecutor` cannot exit
# until it finishes. Boards are newest-first (verified on wd1 and wd5 tenants),
# so the diff only ever needs the front of the list: cap the pages, cap the
# wall clock, and on an incremental poll stop once a run of full pages is
# entirely postings the snapshot already holds. Every early exit is printed.
MAX_PAGES = 100       # 2,000 postings newest-first, per board per run
BOARD_DEADLINE = 120  # seconds of wall clock per board before returning what we have
KNOWN_STREAK = 2      # consecutive full all-known pages => everything behind is older
STALE_DAYS = 45       # merged-snapshot entries unseen this long age out
# "Posted Today" / "Posted Yesterday" / "Posted 3 Days Ago"; not "Posted 14 Days
# Ago" and not "Posted 30+ Days Ago". A known req id carrying one of these when
# the snapshot last saw it as 30+ is a repost -- the re-apply signal this lane
# exists to catch, so it is surfaced instead of deduped away.
RECENT = re.compile(r"posted (today|yesterday|[1-7] days? ago)", re.I)

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
    r"customer success|sales)\b", re.I)
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
# A remote seat in another country is still gate 1 for a US candidate, and the
# location field says so in the tenant's own words ("Canada - Remote AB",
# "Mexico - Remote") or CrowdStrike's 3-letter title codes ("(Remote, GBR)").
# The first fixed run (2026-09-07) let 1 of 3 survivors and 9 of 24 leads
# through on this alone. "United States" must NOT match: keep to other
# countries and Canadian provinces.
NON_US = re.compile(
    r"\b(canada|canadian|alberta|ontario|quebec|british columbia|mexico|"
    r"united kingdom|\buk\b|england|scotland|ireland|brazil|japan|romania|"
    r"india|israel|australia|germany|france|spain|netherlands|poland|"
    r"singapore|malaysia|philippines|china|saudi|dubai|emirates|"
    r"latam|emea|apac|gbr|mex|bra|jpn|rou|ind|isr|aus|deu|fra|esp|nld|pol|"
    r"sgp|mys|phl|chn|can)\b", re.I)

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


def poll(board: dict, known: set | None = None) -> tuple[dict, dict]:
    """Newest-first crawl of one board under its pinned facets.

    Returns ({reqId: {...}}, meta) where meta = {pages, total, stopped}.
    `stopped` is "end of board" for a complete crawl and a printed reason
    otherwise (page cap, deadline, or caught-up-with-snapshot). `known` is the
    set of req ids the previous snapshot holds for this board; None or empty
    means a baseline, which crawls to the cap.

    `total` is read from page one only. wd5 tenants (Cigna and 11 others
    measured 2026-09-07) return total=0 on every later page while still
    returning postings, and re-reading it each page silently truncated every
    unfiltered board to 40 postings for the lane's first two weeks.
    """
    out: dict[str, dict] = {}
    meta = {"pages": 0, "total": None, "stopped": "end of board"}
    offset, total, streak = 0, None, 0
    started = time.monotonic()
    # Faceted boards come back in mixed order (R1's pinned board interleaves
    # 3-day-old and 30+-day-old reqs), so the caught-up early stop only applies
    # to unfiltered boards, whose newest-first order was verified across pages.
    can_catch_up = bool(known) and not (board.get("facets") or board.get("search"))
    while True:
        if meta["pages"] >= MAX_PAGES:
            meta["stopped"] = ("TRUNCATED at the %d-page cap -- board is larger than "
                               "the crawl; newest %d postings covered" % (MAX_PAGES, len(out)))
            break
        if time.monotonic() - started > BOARD_DEADLINE:
            meta["stopped"] = ("TRUNCATED at the %ds deadline after %d pages"
                               % (BOARD_DEADLINE, meta["pages"]))
            break
        d = _req(cxs(board, "/jobs"), {
            "appliedFacets": board.get("facets") or {},
            "limit": PAGE, "offset": offset,
            "searchText": board.get("search") or "",
        })
        meta["pages"] += 1
        if total is None:
            total = d.get("total") or 0
            meta["total"] = total
        page = d.get("jobPostings", [])
        if not page:
            break
        page_keys = []
        for j in page:
            bullets = j.get("bulletFields") or []
            key = bullets[0] if bullets else j.get("externalPath", "")
            page_keys.append(key)
            out[key] = {
                "title": j.get("title", ""),
                "loc": j.get("locationsText", ""),
                "posted_label": j.get("postedOn", ""),
                "path": j.get("externalPath", ""),
                "url": "https://%s/%s%s" % (board["host"], board["site"],
                                            j.get("externalPath", "")),
            }
        offset += len(page)
        if can_catch_up:
            if len(page) == PAGE and known is not None and all(k in known for k in page_keys):
                streak += 1
                if streak >= KNOWN_STREAK:
                    meta["stopped"] = ("caught up: %d consecutive pages already in the "
                                       "snapshot, everything behind them is older" % streak)
                    break
            else:
                streak = 0
        if len(page) < PAGE or (total and offset >= total):
            break
    return out, meta


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


def gate(j: dict, d: dict) -> tuple[str, str]:
    """Gates 1-3 on a listing row plus its detail page.

    Returns ("pass" | "lead" | "decline", why). Gate 4 (fit) is a JD read
    and stays with the human. Order matters: the ATS's own open/closed
    answer first, then employment type, then the location tests from most
    to least specific (a hybrid marker or a foreign country in either field
    beats a coarse "Remote" bucket), then comp under the band rule.
    """
    if d["can_apply"] is False or d["posted"] is False:
        return "decline", "ATS says not accepting applications"
    if d["time_type"] and "full" not in d["time_type"].lower():
        return "decline", "gate 2: %s" % d["time_type"]
    where = d["loc"] or j["loc"]
    title = d["title"] or j["title"]
    if HYBRID.search(title) or HYBRID.search(where):
        return "decline", 'gate 1: hybrid/onsite marker in "%s | %s"' % (title, where)
    if NON_US.search(title) or NON_US.search(where):
        return "decline", 'gate 1: non-US seat in "%s | %s"' % (title, where)
    if not REMOTE.search(where):
        return "decline", "gate 1: %s" % where
    verdict, why = gate_comp(d["lo"], d["hi"])
    return verdict, ("gate 3: %s" % why) if verdict == "decline" else why


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


def merge_snapshot(prev: dict, snap: dict) -> dict:
    """Union of what this run saw with what the snapshot already held.

    A bounded crawl never reaches the back of a big board, so overwriting the
    snapshot with just this run's pages would forget older postings and report
    them as new on the next run. Entries carry `last_seen` and age out after
    STALE_DAYS so closed reqs leave the file. A board that failed this run
    keeps its previous entry untouched: the old code dropped it, which turned
    the next successful poll into a baseline and lost every posting that went
    up in between.
    """
    today = dt.date.today()
    stamp = today.isoformat()
    merged: dict = {}
    for key, jobs in snap.items():
        keep = {}
        for jid, j in prev.get(key, {}).items():
            seen = j.get("last_seen") or stamp  # legacy entries had no stamp
            try:
                age = (today - dt.date.fromisoformat(seen)).days
            except ValueError:
                age = 0
            if age <= STALE_DAYS:
                keep[jid] = j
        for jid, j in jobs.items():
            keep[jid] = {**j, "last_seen": stamp}
        merged[key] = keep
    for key, jobs in prev.items():
        if key not in merged and not key.startswith("__"):
            merged[key] = jobs
    merged["__meta__"] = {"written": stamp,
                          "crawl": "v2: newest-first, %d-page cap, %ds deadline, "
                                   "caught-up early stop, %d-day aging"
                                   % (MAX_PAGES, BOARD_DEADLINE, STALE_DAYS)}
    return merged


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
    board["warm"] = bool(args.warm)
    board["added"] = dt.date.today().isoformat()
    jobs, meta = poll(board)
    labels = facet_labels(board)
    print("board  %s  (%s)" % (key, board["host"]))
    if meta["stopped"] != "end of board":
        print("   crawl: %s" % meta["stopped"])
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
    ap.add_argument("--warm", action="store_true",
                    help="mark as a warm-referral employer (see the vault "
                         "Claude Reference warm-connection lane)")
    ap.add_argument("--list", action="store_true", help="show boards and exit")
    ap.add_argument("--full", action="store_true",
                    help="gate every in-lane posting, not just new ones")
    ap.add_argument("--days", type=int, default=0,
                    help="only report postings started within N days (0 = any)")
    ap.add_argument("--workers", type=int, default=6)
    args = ap.parse_args()
    # Line-buffered even when piped to a file: a run killed by a timeout must
    # leave the header and per-board lines behind, not zero bytes.
    if isinstance(sys.stdout, io.TextIOWrapper):
        sys.stdout.reconfigure(line_buffering=True)

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
    prev.pop("__meta__", None)
    snap: dict[str, dict] = {}
    metas: dict[str, dict] = {}
    failures: list[tuple[str, str]] = []
    with concurrent.futures.ThreadPoolExecutor(max_workers=args.workers) as ex:
        # --full re-gates everything, so it must also crawl everything (to the
        # cap): with the snapshot passed in, a caught-up board would stop at
        # two pages and "full" would mean the newest 40.
        futs = {ex.submit(poll, b, None if args.full else set(prev.get(key, {}))): key
                for key, b in boards.items()}
        for fut in concurrent.futures.as_completed(futs):
            key = futs[fut]
            try:
                snap[key], metas[key] = fut.result()
            except Exception as e:  # noqa: BLE001 -- one dead tenant must not kill the sweep
                failures.append((key, "%s: %s" % (type(e).__name__, str(e)[:70])))

    targets, baselined = [], 0
    reposts: set[tuple[str, str]] = set()
    warm_offlane: list[tuple[str, str]] = []
    for key, jobs in sorted(snap.items()):
        first_poll = key not in prev
        if first_poll and not args.full:
            baselined += 1
            continue
        for jid, j in jobs.items():
            old = prev.get(key, {}).get(jid)
            if old is not None and not args.full:
                if (RECENT.search(j["posted_label"])
                        and not RECENT.search(old.get("posted_label", ""))):
                    reposts.add((key, jid))
                else:
                    continue
            if in_lane(j["title"]):
                targets.append((key, jid, j))
            elif boards[key].get("warm"):
                # No silent caps: at a warm-referral employer an off-lane title
                # is worth Alex seeing anyway, because a referral is worth more
                # than a title match. Surfaced as a count + list, not dropped.
                warm_offlane.append((key, j["title"]))

    print("polled %d ok, %d failed, %d baselined (diff starts next run)"
          % (len(snap), len(failures), baselined))
    for key, err in failures:
        print("   ! %-28s %s" % (key, err))
    for key in sorted(metas):
        m = metas[key]
        if m["stopped"] != "end of board":
            print("   ~ %-28s %d pages, %d postings%s -- %s"
                  % (key, m["pages"], len(snap[key]),
                     " of %d" % m["total"] if m["total"] else "", m["stopped"]))
    print("in-lane postings to gate: %d (%d repost%s)\n"
          % (len(targets), len(reposts), "" if len(reposts) == 1 else "s"))

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
                declines.append((key, jid, j, "detail fetch failed: %s"
                                 % type(e).__name__, None))
                continue
            row = (key, jid, j, d)
            if cutoff and d["start"]:
                try:
                    if dt.date.fromisoformat(d["start"]) < cutoff:
                        continue
                except ValueError:
                    pass
            verdict, why = gate(j, d)
            if verdict == "pass":
                survivors.append((*row, why))
            elif verdict == "lead":
                leads.append((*row, why))
            else:
                declines.append((key, jid, j, why, d))

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
        for key, jid, j, d, why in rows:
            print("-" * 72)
            tag = "  ** WARM REFERRAL **" if boards[key].get("warm") else ""
            if (key, jid) in reposts:
                tag += "  ** REPOST -- re-apply candidate **"
            print("[%s] %s%s" % (key, d["title"] or j["title"], tag))
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
    for key, jid, j, why, _d in declines:
        tag = " ** WARM **" if boards[key].get("warm") else ""
        if (key, jid) in reposts:
            tag += " ** REPOST **"
        print("  [%s]%s %-52s %s" % (key, tag, j["title"][:52], why))

    if reposts:
        print("\nREPOSTS (%d) -- a req id the snapshot already held, back at the top"
              " of its board with a fresh date. Re-apply signal; see the row's"
              " verdict above:" % len(reposts))
        for key, jid in sorted(reposts):
            print("  [%s] %s  (%s)" % (key, snap[key][jid]["title"], jid))

    if warm_offlane:
        print("\nOFF-LANE TITLES AT WARM-REFERRAL EMPLOYERS (%d) -- shown because a"
              " referral outweighs a title match; Alex triages:" % len(warm_offlane))
        for key, title in warm_offlane:
            print("  [%s] %s" % (key, title))

    save(SNAPSHOT, merge_snapshot(prev, snap))
    print("\nsnapshot written: %s" % SNAPSHOT)


if __name__ == "__main__":
    main()
