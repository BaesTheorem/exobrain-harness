#!/usr/bin/env python3
"""Law-firm careers boards lane for /job-search.

Alex's IT experience is at a law firm, and most law firms post staff roles on
ATSes that no other lane reads. This lane polls a hand-kept list of law-firm
boards directly and gates every posting like the other lanes (title filter
with the law-firm titles from lawfirm.py, remote US at the comp floor, KC metro
at the onsite floor, contract and part-time declined, band rule).

ATS data paths (measured 2026-11-02):
  virecruit  viGlobal viRecruit, the law-firm ATS (Spencer Fane, Kutak Rock,
             Armstrong Teasdale, BCLP, Jones Day, Steptoe, Jenner and others).
             RecDefault.aspx?FilterREID=<n> is server-rendered and carries the
             FULL JD of every posting inline, so one GET per board is the whole
             crawl. Each firm splits attorney and staff postings across REIDs
             that are not contiguous (BCLP staff are 51 and 56). An unknown
             REID returns HTTP 500. `--discover <tenant>` probes 1..70 and
             prints the board entries to pin. Apply is an ASP.NET postback, so
             the board URL is the apply entry point.
  ultipro    UKG UltiPro (Polsinelli, Husch Blackwell, Stinson). POST
             <board>/JobBoardView/LoadSearchResults returns JSON with titles,
             locations and posted dates. The detail page embeds a JSON object
             (CandidateOpportunityDetail) with the JD and the pay fields.
             Husch files remote seats under the location "Virtual Office".
  icims      iCIMS (Lewis Brisbois). /jobs/search?ss=1&in_iframe=1&pr=<page>
             is server-rendered job cards; the detail page carries the JD.
  adp        ADP Recruiting (Shook Hardy). The list API on my.adp.com wants the
             public myJobsToken from myjobs.adp.com/public/staffing/v1/
             career-site/<site> and a `rolecode: manager` header; the rows carry
             the full JD.
  paycor     Paycor Recruiting (Lewis Rice): one server-rendered table.
  ukgready   UKG Ready (Gilmore & Bell): JSON at /ta/rest/ui/recruitment/
             companies/%7C<CID>/job-requisitions, with the posted pay.
  rmk        SAP SuccessFactors career site (Dentons): /search/ HTML, 25 rows a
             page. A locationsearch filter matches text, not country, so the
             lane reads the whole board and gates locations itself.
  paylocity  Paylocity (Lathrop GPM staff): the board page embeds window.pageData.
  page       A firm with no job list, only a careers page (Seigfreid Bingham).
             The lane hashes the page text and prints PAGE CHANGED when it
             differs from the last run (state/lawfirms-pages.json).
  manual     A board with no data path yet. The lane prints it every run as
             NOT POLLED, so the gap stays visible.

Self-hosted viRecruit installs (Littler: videsktop.littler.com, Lathrop:
recruiting.lathropgpm.com/viDesktopEx) use the virecruit adapter; pass the
host to --discover. Littler ignores FilterREID until the redirect sets a
cookie, which the shared session keeps.

Firms on Greenhouse, Lever, Ashby and Workday belong in those lanes
(state/watchlist-extra.json, workday.py --add), and iCIMS/Paylocity firms in
the aggregator dataset are covered by aggregator.py, which tags law-firm rows.

The board list is state/lawfirm-boards.json (gitignored, like every employer
list here). Schema and a starter entry: lawfirm-boards.example.json. A
seen-file (state/lawfirms-seen.json) marks rows shown before; they print only
with --all. IT titles that a gate removed (seniority, location) print in a
LAW-FIRM IT WATCH list, because at a law firm Alex may want to see an IT
opening the gates reject (a KC cybersecurity manager seat, for example).

Usage:
    python3 lawfirms.py                 # new postings on every pinned board
    python3 lawfirms.py --all           # re-show postings seen before
    python3 lawfirms.py --discover spencerfanecareers --firm "Spencer Fane"

INVARIANTS
  * No compensation figure in this file; floors come from comp_floors.
  * A board that fails prints a `~ <firm> FAILED` line and keeps its seen rows.
"""

import argparse
import concurrent.futures as cf
import datetime as dt
import hashlib
import html
import json
import re
import sys
import urllib.request
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from comp_floors import comp_floor, onsite_floor  # noqa: E402
from moreboards import (MONEY, UA, _ensure_curl_cffi, gate, http, parse_iso,  # noqa: E402
                        row)

HERE = Path(__file__).resolve().parent
BOARDS = HERE / "state" / "lawfirm-boards.json"
SEEN = HERE / "state" / "lawfirms-seen.json"
PAGES = HERE / "state" / "lawfirms-pages.json"
SEEN_TTL_DAYS = 90

IT_BROAD = re.compile(
    r"\b(it|information technology|information services|technology|security|cyber\w*|"
    r"systems?|network|help ?desk|service desk|desktop|deskside|support analyst|"
    r"application|infrastructure|identity|e-?discovery|litigation support|"
    r"practice support|trainer|soc|cloud|m365|microsoft)\b", re.I)
NOT_IT = re.compile(r"\b(paralegal|legal assistant|secretary|attorney|associate attorney|"
                    r"counsel|partner|summer associate|law clerk|docket|billing|"
                    r"recruit|marketing|business development|accounts|payroll)\b", re.I)
JD_REMOTE = re.compile(r"\b(fully remote|100% remote|remote position|remote role|"
                       r"work remotely|remote work arrangement|remote-first|"
                       r"virtual office|remote \(us|remote, us|remote within)\b", re.I)
JD_HYBRID = re.compile(r"\bhybrid\b|in[- ]office \d|days? (?:per|a) week in", re.I)
PAY_WINDOW = re.compile(r"(salary|pay range|compensation|hiring range|pay scale|"
                        r"base pay|wage)[^.]{0,220}", re.I)
NO_OFFICE = re.compile(r"no specific office|multiple locations|firmwide|remote", re.I)


def text(s: str) -> str:
    s = re.sub(r"(?is)<(script|style)\b.*?</\1>", " ", s or "")
    return re.sub(r"\s+", " ", html.unescape(re.sub(r"<[^>]+>", " ", s))).strip()


def jd_band(jd: str) -> tuple[float | None, float | None]:
    """Band from the pay sentence only; a bare '$' elsewhere in a JD is noise."""
    for m in PAY_WINDOW.finditer(jd):
        win = m.group(0)
        hourly = bool(re.search(r"hour|/hr|hourly", win, re.I))
        nums = []
        for n, k in MONEY.findall(win):
            v = float(n.replace(",", "")) * (1000 if k else 1)
            v = v * 2080 if hourly and v < 500 else v
            if v >= 10000:
                nums.append(v)
        if nums:
            return min(nums), max(nums)
    return None, None


# ---------------------------------------------------------------- adapters

def virecruit(b: dict) -> list[dict]:
    page = http(b["url"], headers={"Accept": "text/html"})
    out = []
    for blk in page.split("<h4>")[1:]:
        title = text(blk.split("</h4>")[0])
        office = re.search(r"Office <span>(.*?)</span>", blk)
        posted = re.search(r"Date Posted <span>(.*?)</span>", blk)
        where = text(office.group(1)) if office else ""
        jd = text(blk.split("</h4>", 1)[-1])
        try:
            pdate = dt.datetime.strptime(posted.group(1).strip(), "%b %d, %Y").date() if posted else None
        except ValueError:
            pdate = None
        out.append({"title": title, "where": where, "jd": jd, "posted": pdate,
                    "url": b["url"], "key": f"{b['url']}#{title}"})
    return out


def ultipro(b: dict) -> list[dict]:
    base = b["url"].split("?")[0].rstrip("/")
    body = {"opportunitySearch": {"Top": 100, "Skip": 0, "QueryString": "",
                                  "OrderBy": [{"Value": "postedDateDesc", "PropertyName": "PostedDate",
                                               "Ascending": False}],
                                  "Filters": [{"t": "TermsSearchFilterDto", "fieldName": n,
                                               "extra": None, "values": []} for n in (4, 5, 6)]},
            "matchCriteria": {"PreferredJobs": [], "Educations": [], "LicenseAndCertifications": [],
                              "Skills": [], "hasNoLicenses": False, "SkippedSkills": []}}
    data = json.loads(http(base + "/JobBoardView/LoadSearchResults", body=body))
    out = []
    for o in data.get("opportunities", []):
        locs = [loc.get("LocalizedName") or loc.get("LocalizedDescription")
                or ((loc.get("Address") or {}).get("City") or "") for loc in o.get("Locations", [])]
        out.append({"title": o.get("Title", ""), "where": "; ".join(x for x in locs if x),
                    "posted": parse_iso(o.get("PostedDate")), "fulltime": o.get("FullTime"),
                    "url": f"{base}/OpportunityDetail?opportunityId={o['Id']}", "key": o["Id"],
                    "detail": "ultipro"})
    return out


def ultipro_detail(r: dict) -> None:
    page = http(r["url"], headers={"Accept": "text/html"})
    i = page.find("CandidateOpportunityDetail(")
    if i < 0:
        return
    d, _ = json.JSONDecoder().raw_decode(page[i + len("CandidateOpportunityDetail("):])
    r["jd"] = text(d.get("Description") or "")
    pr = d.get("PayRange") or {}
    lo = d.get("CompensationAnnualMinimum") or pr.get("PayRangeMinimum")
    hi = d.get("CompensationAnnualMaximum") or pr.get("PayRangeMaximum")
    if not (lo or hi) and (d.get("CompensationHourlyMinimum") or d.get("CompensationHourlyMaximum")):
        lo = (d.get("CompensationHourlyMinimum") or 0) * 2080 or None
        hi = (d.get("CompensationHourlyMaximum") or 0) * 2080 or None
    r["lo"], r["hi"] = lo, hi
    if d.get("OpportunityIsClosed"):
        r["closed"] = True


def icims(b: dict) -> list[dict]:
    host = b["url"].rstrip("/")
    out, seen = [], set()
    for pr in range(0, 20):
        page = http(f"{host}/jobs/search?ss=1&in_iframe=1&pr={pr}", headers={"Accept": "text/html"})
        cards = page.split('class="iCIMS_JobCardItem"')[1:]
        if not cards:
            break
        for c in cards:
            m = re.search(r'href="(https://[^"]+/jobs/(\d+)/[^"?]+)', c)
            if not m or m.group(2) in seen:
                continue
            seen.add(m.group(2))
            loc = re.search(r"Job Locations</span>\s*<span[^>]*>(.*?)</span>", c, re.S)
            h3 = re.search(r"<h3[^>]*>(.*?)</h3>", c, re.S)
            out.append({"title": text(h3.group(1)) if h3 else "",
                        "where": text(loc.group(1)) if loc else "",
                        "url": m.group(1) + "?in_iframe=1", "key": m.group(2), "detail": "icims",
                        "posted": None})
        if f"pr={pr + 1}" not in page:
            break
    return out


def icims_detail(r: dict) -> None:
    page = http(r["url"], headers={"Accept": "text/html"})
    body = page.split('class="iCIMS_JobContent', 1)[-1]
    r["jd"] = text(body)[:20000]
    loc = re.search(r"(?:Job Locations?|Location)\s*</dt>\s*<dd[^>]*>(.*?)</dd>", page, re.S)
    if loc:
        r["where"] = text(loc.group(1)) or r["where"]
    r["posted"] = parse_iso((re.search(r'"datePosted"\s*:\s*"([^"]+)"', page) or [None, None])[1])


def plain_get(url: str, headers: dict) -> str:
    """urllib GET. ADP's list API answers {"count": 0} to curl_cffi (measured
    2026-11-03: same URL and headers, urllib gets the rows), so ADP uses this."""
    req = urllib.request.Request(url, headers={"User-Agent": UA, "Accept": "application/json", **headers})
    with urllib.request.urlopen(req, timeout=40) as r:
        return r.read().decode("utf-8", "replace")


def adp(b: dict) -> list[dict]:
    """ADP Recruiting (myjobs.adp.com/<site>). The list API wants the public
    myJobsToken from the career-site config plus a `rolecode` header."""
    site = re.search(r"myjobs\.adp\.com/([^/?#]+)", b["url"])
    if not site:
        raise ValueError("adp url must be https://myjobs.adp.com/<site>")
    domain = site.group(1)
    cfg = json.loads(http(f"https://myjobs.adp.com/public/staffing/v1/career-site/{domain}"))
    hdr = {"rolecode": "manager", "myjobstoken": cfg["myJobsToken"]}
    out: list[dict] = []
    for skip in range(0, 1000, 100):
        data = json.loads(plain_get(
            "https://my.adp.com/myadp_prefix/mycareer/public/staffing/v1/job-requisitions/"
            "apply-custom-filters?$orderby=postingDate%20desc&$select=reqId,jobTitle,"
            "publishedJobTitle,jobDescription,workLevelCode,postingDate,requisitionLocations"
            f"&$top=100&$skip={skip}&tz=America/Chicago", hdr))
        reqs = data.get("jobRequisitions") or []
        if skip == 0 and not reqs:
            raise ValueError("ADP list API returned 0 rows (count %s)" % data.get("count"))
        for q in reqs:
            locs = []
            for loc in q.get("requisitionLocations") or []:
                a = loc.get("address") or {}
                st = (a.get("countrySubdivisionLevel1") or {}).get("codeValue", "")
                locs.append(", ".join(x for x in (a.get("cityName"), st) if x)
                            or (loc.get("nameCode") or {}).get("longName", ""))
            wl = q.get("workLevelCode")
            wl = wl.get("shortName", "") if isinstance(wl, dict) else (wl or "")
            out.append({"title": q.get("publishedJobTitle") or q.get("jobTitle", ""),
                        "where": "; ".join(x for x in locs if x), "jd": text(q.get("jobDescription", "")),
                        "posted": parse_iso(q.get("postingDate")), "fulltime": "part" not in wl.lower(),
                        "url": f"https://myjobs.adp.com/{domain}/cx/job-details?reqId={q['reqId']}",
                        "key": str(q["reqId"])})
        if len(reqs) < 100 or len(out) >= int(data.get("count") or 0):
            break
    return out


def paycor(b: dict) -> list[dict]:
    """Paycor Recruiting (recruitingbypaycor.com): one server-rendered table."""
    page = http(b["url"], headers={"Accept": "text/html"})
    out = []
    for m in re.finditer(r'gnewtonJobLink">\s*<a href="([^"]+)">(.*?)</a>\s*</td>\s*'
                         r'<td class="gnewtonJobLocation"[^>]*>(.*?)</td>', page, re.S):
        url = html.unescape(m.group(1))
        jid = re.search(r"[?&]id=([^&]+)", url)
        out.append({"title": text(m.group(2)), "where": text(m.group(3)), "url": url,
                    "key": jid.group(1) if jid else url, "posted": None, "detail": "page"})
    if not out and "gnewtonJobLink" in page:
        raise ValueError("Paycor table changed: job links present but the row pattern missed")
    return out


def ukgready(b: dict) -> list[dict]:
    """UKG Ready (secure.entertimeonline.com/ta/<CID>.careers): JSON behind the SPA."""
    m = re.search(r"https://([^/]+)/ta/([A-Z0-9]+)\.careers", b["url"])
    if not m:
        raise ValueError("ukgready url must be https://<host>/ta/<CID>.careers")
    host, cid = m.groups()
    out: list[dict] = []
    for offset in range(1, 400, 50):
        data = json.loads(http(f"https://{host}/ta/rest/ui/recruitment/companies/%7C{cid}/"
                               f"job-requisitions?offset={offset}&size=50&sort=desc&lang=en-US"))
        reqs = data.get("job_requisitions") or []
        for q in reqs:
            loc = q.get("location") or {}
            freq = (q.get("base_pay_frequency") or "").upper()
            mult = 2080 if freq == "HOUR" else (12 if freq == "MONTH" else 1)
            lo, hi = q.get("base_pay_from"), q.get("base_pay_to")
            remote = q.get("is_remote_job") or q.get("remote")
            out.append({"title": q.get("job_title", ""), "jd": text(q.get("job_description", "")),
                        "where": ("Remote; " if remote else "") + ", ".join(
                            x for x in (loc.get("city"), loc.get("state")) if x),
                        "lo": lo * mult if lo else None, "hi": hi * mult if hi else None,
                        "fulltime": "part" not in ((q.get("employee_type") or {}).get("name", "").lower()),
                        "posted": parse_iso(q.get("published_date") or q.get("created_date")),
                        "url": f"https://{host}/ta/{cid}.careers?ShowJob={q['id']}", "key": str(q["id"])})
        if len(reqs) < 50:
            break
    return out


def rmk(b: dict) -> list[dict]:
    """SAP SuccessFactors career site (careers.<firm>.com/search/), 25 rows a page."""
    base = b["url"].rstrip("/")
    out, seen = [], set()
    for start in range(0, 1000, 25):
        page = http(f"{base}/search/?q=&sortColumn=referencedate&sortDirection=desc&startrow={start}",
                    headers={"Accept": "text/html"})
        rows = page.split('class="data-row')[1:]
        new = 0
        for r in rows:
            m = re.search(r'href="(/job/[^"]+)" class="jobTitle-link">([^<]+)', r)
            if not m or m.group(1) in seen:
                continue
            seen.add(m.group(1))
            new += 1
            loc = re.search(r'<span class="jobLocation">\s*(.*?)</span>', r, re.S)
            date = re.search(r'<span class="jobDate[^"]*">\s*([^<]+)', r)
            try:
                posted = dt.datetime.strptime(date.group(1).strip(), "%b %d, %Y").date() if date else None
            except ValueError:
                posted = None
            out.append({"title": text(m.group(2)), "where": text(loc.group(1)) if loc else "",
                        "url": base + m.group(1), "key": m.group(1), "posted": posted, "detail": "page"})
        if not new:
            break
    return out


def paylocity(b: dict) -> list[dict]:
    """Paylocity Recruiting: the board page embeds its job list as window.pageData."""
    page = http(b["url"], headers={"Accept": "text/html"})
    m = re.search(r"window\.pageData\s*=\s*(\{.*?\});\s*\n", page, re.S)
    if not m:
        raise ValueError("Paylocity pageData not found")
    out = []
    for j in json.loads(m.group(1)).get("Jobs", []):
        out.append({"title": j.get("JobTitle", ""),
                    "where": ("Remote; " if j.get("IsRemote") else "") + (j.get("LocationName") or ""),
                    "posted": parse_iso(j.get("PublishedDate")), "key": str(j["JobId"]), "detail": "page",
                    "url": f"https://recruiting.paylocity.com/Recruiting/Jobs/Details/{j['JobId']}"})
    return out


def page_detail(r: dict) -> None:
    """Generic detail read: the posting page's text is the JD."""
    r["jd"] = text(http(r["url"], headers={"Accept": "text/html"}))[:20000]


ADAPTERS = {"virecruit": virecruit, "ultipro": ultipro, "icims": icims, "adp": adp,
            "paycor": paycor, "ukgready": ukgready, "rmk": rmk, "paylocity": paylocity}
DETAIL = {"ultipro": ultipro_detail, "icims": icims_detail, "page": page_detail}


# ---------------------------------------------------------------- gating

def to_row(firm: str, r: dict) -> dict:
    jd = r.get("jd", "")
    where = r["where"]
    remote = None
    if re.search(r"virtual office|\bremote\b", where, re.I) or (
            NO_OFFICE.search(where) and JD_REMOTE.search(jd) and not JD_HYBRID.search(jd)):
        remote = True
    lo, hi = r.get("lo"), r.get("hi")
    if lo is None and hi is None and jd:
        lo, hi = jd_band(jd)
    jtype = "" if r.get("fulltime") in (None, True) else "part-time"
    if re.search(r"\b(part[- ]time|temporary|contract)\b", r["title"], re.I):
        jtype = "contract/part-time"
    # The title often names the office ("... - Kansas City, MO"); gate reads it too.
    return row("lawfirm", r["title"], firm, where or "?", r["url"], remote=remote,
               lo=lo, hi=hi, jtype=jtype, posted=r.get("posted"))


def poll(b: dict) -> tuple[dict, list[dict] | None, str]:
    try:
        return b, ADAPTERS[b["kind"]](b), ""
    except Exception as e:  # noqa: BLE001  (one board failing is a reported gap, not a dead lane)
        return b, None, f"{type(e).__name__}: {str(e)[:80]}"


def vi_base(tenant: str) -> str:
    """'kutakrock-careers' -> viglobalcloud URL; a full host or URL is kept as given."""
    if "/" in tenant or "." in tenant:
        t = tenant if tenant.startswith("http") else "https://" + tenant
        return t.split("RecDefault.aspx")[0].rstrip("/") + ("" if "viRecruitSelfApply" in t
                                                            else "/viRecruitSelfApply")
    return f"https://{tenant}.viglobalcloud.com/viRecruitSelfApply"


def discover(tenant: str, firm: str) -> None:
    """Probe FilterREID 1..70 on a viRecruit tenant (or host) and print board entries."""
    _ensure_curl_cffi()
    found: dict[tuple, int] = {}

    def probe(n: int):
        url = f"{vi_base(tenant)}/RecDefault.aspx?FilterREID={n}"
        try:
            rows = virecruit({"url": url})
        except Exception:  # noqa: BLE001  (an unknown REID answers 500)
            return n, None
        return n, tuple(sorted(r["title"] for r in rows))

    with cf.ThreadPoolExecutor(8) as ex:
        for n, titles in ex.map(probe, range(1, 71)):
            if titles and titles not in found:
                found[titles] = n
    entries = []
    for titles, n in sorted(found.items(), key=lambda kv: kv[1]):
        print(f"REID {n}: {len(titles)} postings, e.g. {', '.join(titles[:3])}")
        entries.append({"firm": firm, "kind": "virecruit", "url":
                        f"{vi_base(tenant)}/RecDefault.aspx?FilterREID={n}"})
    print(json.dumps(entries, indent=1))


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--all", action="store_true", help="re-show postings seen before")
    ap.add_argument("--verbose", action="store_true", help="list declined and dropped rows")
    ap.add_argument("--no-save", action="store_true")
    ap.add_argument("--discover", metavar="TENANT", help="viRecruit tenant to probe for REIDs")
    ap.add_argument("--firm", default="", help="firm name for --discover output")
    a = ap.parse_args()
    if a.discover:
        discover(a.discover, a.firm or a.discover)
        return
    _ensure_curl_cffi()
    if not BOARDS.exists():
        sys.exit(f"lawfirms lane DID NOT RUN: {BOARDS} missing (copy lawfirm-boards.example.json)")
    boards = json.loads(BOARDS.read_text())["boards"]
    floor, onsite = comp_floor(), onsite_floor()
    today = dt.date.today()
    seen = json.loads(SEEN.read_text()) if SEEN.exists() else {}
    seen = {k: v for k, v in seen.items()
            if (today - dt.date.fromisoformat(v)).days <= SEEN_TTL_DAYS}

    buckets: dict[str, list] = {k: [] for k in ("survivor", "lead", "decline", "drop")}
    watch, failed, manual, keys, n_rows, n_new = [], [], [], set(), 0, 0
    polled = [b for b in boards if b["kind"] in ADAPTERS]
    manual = [b for b in boards if b["kind"] not in ADAPTERS and b["kind"] != "page"]
    pages = json.loads(PAGES.read_text()) if PAGES.exists() else {}
    page_lines = []
    for b in (b for b in boards if b["kind"] == "page"):
        try:
            body = text(http(b["url"], headers={"Accept": "text/html"}))
        except Exception as e:  # noqa: BLE001
            failed.append(f"{b['firm']} (page): {str(e)[:80]}")
            continue
        digest = hashlib.sha256(body.encode()).hexdigest()[:16]
        old = pages.get(b["url"])
        if old is None:
            page_lines.append(f"~ PAGE BASELINE: {b['firm']} {b['url']}")
        elif old["hash"] != digest:
            page_lines.append(f"** PAGE CHANGED: {b['firm']} (last change {old['since']}): read it "
                              f"for a new staff opening {b['url']}")
        if old is None or old["hash"] != digest:
            pages[b["url"]] = {"hash": digest, "since": today.isoformat()}
    with cf.ThreadPoolExecutor(6) as ex:
        results = list(ex.map(poll, polled))
    for b, rows, err in results:
        if rows is None:
            failed.append(f"{b['firm']} ({b['kind']}): {err}")
            continue
        for r in rows:
            key = f"{b['kind']}:{r['key']}"
            if key in keys:
                continue  # a posting listed on two REIDs of one firm
            keys.add(key)
            n_rows += 1
            if key in seen and not a.all:
                continue
            n_new += 1
            title_it = IT_BROAD.search(r["title"]) and not NOT_IT.search(r["title"])
            if r.get("detail") and title_it:
                try:
                    DETAIL[r["detail"]](r)
                except Exception as e:  # noqa: BLE001
                    r["jd"] = ""
                    failed.append(f"{b['firm']} detail {r['title'][:40]}: {str(e)[:60]}")
            if r.get("closed"):
                continue
            j = to_row(b["firm"], r)
            verdict, why = gate(j, floor, onsite)
            buckets[verdict].append((j, why))
            if verdict in ("drop", "decline") and title_it:
                watch.append((j, why))
    if not a.no_save:
        for k in keys:
            seen.setdefault(k, today.isoformat())
        SEEN.parent.mkdir(exist_ok=True)
        SEEN.write_text(json.dumps(seen, indent=0, sort_keys=True))
        PAGES.write_text(json.dumps(pages, indent=1, sort_keys=True))

    print(f"lawfirms: {len(polled)} boards polled, {len(failed)} failed, {n_rows} postings, "
          f"{n_new} not shown before | {len(buckets['survivor'])} survivors | "
          f"{len(buckets['lead'])} leads | {len(buckets['decline'])} declined | "
          f"{len(buckets['drop'])} title-dropped")
    for f in failed:
        print(f"~ {f} FAILED")
    for line in page_lines:
        print(line)
    for b in manual:
        print(f"~ NOT POLLED: {b['firm']} ({b.get('why', 'no data path')}) {b['url']}")

    def show(head, items):
        print(f"\n{head}")
        for j, why in sorted(items, key=lambda x: (x[0]["company"], x[0]["title"])):
            comp = (f"${int(j['lo'] or 0):,}-${int(j['hi'] or 0):,}" if j["lo"] or j["hi"]
                    else "unlisted")
            print(f"  {j['title']} @ {j['company']} | {j['where']} | {comp} | "
                  f"posted {j['posted'] or '?'}  {why}")
            print(f"    {j['url']}")

    show("SURVIVORS -- verify the seat on the posting, then the note pipeline", buckets["survivor"])
    show("LEADS -- pay unlisted; the JD read decides gate 3", buckets["lead"])
    show("LAW-FIRM IT WATCH -- IT titles a gate removed (Alex's call)", watch)
    if a.verbose:
        show("DECLINED", [x for x in buckets["decline"] if x not in watch])


if __name__ == "__main__":
    main()
