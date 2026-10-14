#!/usr/bin/env python3
"""More discovery lanes for /job-search: boards with a public JSON (or RSS) path.

Added 2026-10-13, after a scouting pass probed each data path with curl. Every
source returns rows in one shape, and one gate decides them, so a new board is
a single function plus an entry in SOURCES.

  simplyhired      Indeed's listings, server-rendered; __NEXT_DATA__ JSON on the
                   search page. Plain urllib 403s, a Chrome TLS fingerprint
                   (curl_cffi) does not. Runs a remote pass and a KC pass.
  smartrecruiters  cross-company search, jobs.smartrecruiters.com/sr-jobs/search.
                   Quote the phrase (unquoted matches any word, ~13k rows). Its
                   location/remote params do nothing: gate 1 runs here.
  workable         cross-company search, jobs.workable.com/api/v1/jobs. The
                   workplace and location params work. No salary field.
  clearancejobs    POST api.clearancejobs.com/api/v1/jobs/search. Rows carry
                   clearance + salary_min/max; Secret/TS rows are declined.
  workingnomads    the site's own Elasticsearch index (_search?q=title:...).
  jobicy           documented API, geo=usa, salaryMin/Max/Period.
  remoteok         remoteok.com/api, one JSON array of recent jobs.
  jibe-<employer>  KC employers on the Jibe careers platform (/api/jobs):
                   Garmin (Olathe), H&R Block (KC MO), BJC / Saint Luke's.
  oracle-health    Oracle HCM requisition search (Oracle Health / Cerner, KC).
  higheredjobs     category RSS (IT support, network/system admin). No salary.
  hn-hiring        the monthly HN "Who is hiring" thread via the Algolia API.
                   Free text, so every in-lane remote post is a LEAD.
  jooble           Jooble REST API, keyed (JOOBLE_API_KEY in .env, 500-request
                   default limit, 2 calls per query). Aggregates many boards.
  adzuna           Adzuna API, keyed (ADZUNA_APP_ID/KEY). Free plan = 25 calls
                   in total; it runs daily and archives itself when they are
                   gone (state/adzuna-quota.json). Predicted salaries dropped.

Gates (the same rules as dice.py and indeed.py):
  title     KEEP an in-lane word, DROP seniority and specialist mismatches
  1 where   remote in the US at JOB_COMP_FLOOR, or KC metro at JOB_ONSITE_FLOOR
  2 type    contract / part-time / temporary / internship declined
  3 comp    band rule; no pay listed = LEAD (a JD read decides)

A seen-file (state/moreboards-seen.json, gitignored) records every URL, so a
run prints only postings it has not shown before. --all prints everything.
Survivors still need the JD read, status-aware dedup, and employer-ATS
verification before they earn a listing note.

Usage:
    python3 moreboards.py "security analyst" "IT analyst" --days 3
    python3 moreboards.py "identity" --sources workable,smartrecruiters --all
"""

import argparse
import datetime as dt
import html
import json
import os
import re
import sys
import time
import urllib.parse
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from comp_floors import comp_floor, onsite_floor  # noqa: E402

STATE = Path(__file__).resolve().parent / "state" / "moreboards-seen.json"
SEEN_TTL_DAYS = 60

DROP = re.compile(
    r"\b(senior|sr\.?|lead|principal|staff|manager|director|head of|architect|"
    r"engineer (iii|iv|v)|vp|vice president|chief|supervisory|"
    r"epic|cerner|workday|oracle|salesforce|dynamics 365|mainframe|sap|zendesk|"
    r"pre-?sales|sales|solutions engineer|account executive|customer success)\b", re.I)
KEEP = re.compile(
    r"\b(analyst|it support|it operations|it specialist|helpdesk|help desk|"
    r"service desk|security|identity|iam|grc|compliance|administrator|m365|"
    r"microsoft 365|intune|endpoint|desktop support|technical support|"
    r"systems? admin)\b", re.I)
# Off-lane analyst families (measured on the first run, 2026-10-13: Jobicy and
# SimplyHired return every kind of analyst for "analyst" queries).
OFF_LANE = re.compile(
    r"\b(behavior|bcba|financial|data|business|credit|research|budget|product|revops|"
    r"revenue|marketing|pricing|accounting|trade compliance|partnerships|account operations|"
    r"corporate development|financial crime|securities|interface|ehr|clinical|actuarial|"
    r"investment|supply chain|logistics|payroll|benefits|hr|people|fp&a|business systems|"
    r"business process|data validation|data product|operations risk|claims|compensation|"
    r"treasury|investor|patient|chart|eligibility|building science|procurement|reporting|"
    r"capital markets|operations|hris|human resources information|geographic information|gis|"
    r"lis|validation|program|commissions)\b[^|]{0,45}\banalyst",
    re.I)
OFF_LANE_AFTER = re.compile(
    r"\banalyst\b[^|]{0,6}\b(corporate development|product|revenue|marketing|pricing|"
    r"accounting|financial|business|data|clinical|investment|partnerships)\b", re.I)
# A strong in-lane word overrides OFF_LANE ("Data Security Analyst", "Data
# Loss Prevention Analyst", "Business & Tech Risk" stay in).
STRONG = re.compile(r"\bsecurity\b|cyber|identity|\biam\b|\bgrc\b|\bit\b|infosec|"
                    r"information technology|help ?desk|service desk|endpoint|access|"
                    r"loss prevention|tech risk|soc\b", re.I)
REMOTE = re.compile(r"\bremote\b|work from home|work at home|telecommut|anywhere|\bwfh\b", re.I)
KC_METRO = re.compile(
    r"kansas city|overland park|lenexa|olathe|lee'?s summit|independence, mo|"
    r"shawnee|leawood|merriam|mission, ks|prairie village|north kansas city|"
    r"liberty, mo|blue springs|grandview|raytown|gladstone|riverside, mo", re.I)
NON_US = re.compile(
    r"\b(canada|mexico|united kingdom|\buk\b|england|ireland|india|philippines|"
    r"germany|france|spain|netherlands|poland|brazil|argentina|colombia|"
    r"australia|singapore|viet ?nam|romania|portugal|latam|emea|apac|europe|hungary|"
    r"bulgaria|bengaluru|bangalore|hyderabad|pune|chennai|noida|gurgaon|manila|"
    r"costa rica|guatemala|egypt|nigeria|kenya|south africa|m/f/d|m/w/d)\b", re.I)
BAD_TYPE = re.compile(r"contract|part[- ]time|temporary|\btemp\b|intern|freelance|"
                      r"seasonal|per diem|1099|c2c", re.I)
BAD_CLEARANCE = re.compile(r"secret|ts/sci|top secret|\bq\b|polygraph", re.I)
MONEY = re.compile(r"\$\s?(\d[\d,]*(?:\.\d+)?)\s*(k)?", re.I)

UA = ("Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/141.0.0.0 Safari/537.36")


def _ensure_curl_cffi() -> None:
    """Re-exec under the harness .venv when this interpreter lacks curl_cffi."""
    try:
        import curl_cffi  # noqa: F401  (import probe only)
    except ImportError:
        venv = Path(__file__).resolve().parent.parent / ".venv" / "bin" / "python"
        if venv.exists() and Path(sys.executable).resolve() != venv.resolve():
            os.execv(str(venv), [str(venv), __file__, *sys.argv[1:]])
        sys.exit("curl_cffi missing: uv pip install --python .venv/bin/python curl_cffi")


_session = None


def http(url: str, body: dict | None = None, headers: dict | None = None) -> str:
    global _session
    if _session is None:
        from curl_cffi import requests as cr
        _session = cr.Session(impersonate="chrome")
    h = {"User-Agent": UA, "Accept": "application/json, text/html;q=0.9", **(headers or {})}
    for attempt in range(3):
        if body is None:
            r = _session.get(url, headers=h, timeout=40)
        else:
            r = _session.post(url, json=body, headers=h, timeout=40)
        if r.status_code in (429, 502, 503) and attempt < 2:
            time.sleep(5 * (attempt + 1))
            continue
        r.raise_for_status()
        return r.text
    return ""


def row(src, title, company, where, url, *, remote=None, lo=None, hi=None,
        jtype="", posted=None, extra=""):
    return {"src": src, "title": (title or "").strip(), "company": (company or "").strip(),
            "where": (where or "").strip(), "url": url, "remote": remote,
            "lo": lo, "hi": hi, "type": jtype or "", "posted": posted, "extra": extra}


def parse_iso(s) -> dt.date | None:
    if not s:
        return None
    try:
        return dt.datetime.fromisoformat(str(s).replace("Z", "+00:00")[:25]).date()
    except ValueError:
        try:
            return dt.date.fromisoformat(str(s)[:10])
        except ValueError:
            return None


def money_band(text: str) -> tuple[float | None, float | None]:
    """'$60,000 - $71,000 a year', '$45 - $55 an hour', '$90k-$120k'."""
    if not text:
        return None, None
    nums = []
    for n, k in MONEY.findall(text):
        v = float(n.replace(",", ""))
        nums.append(v * 1000 if k else v)
    if not nums:
        return None, None
    mult = 2080 if re.search(r"hour|/hr|hourly", text, re.I) else (
        12 if re.search(r"month", text, re.I) else 1)
    return nums[0] * mult, nums[-1] * mult


# ---------------------------------------------------------------- sources

def simplyhired(q, days):
    out = []
    t = 1 if days <= 1 else (3 if days <= 3 else 7)
    for where in ("Remote", "Kansas City, MO"):
        url = ("https://www.simplyhired.com/search?" +
               urllib.parse.urlencode({"q": q, "l": where, "t": t}))
        page = http(url, headers={"Accept": "text/html"})
        m = re.search(r'<script id="__NEXT_DATA__"[^>]*>(.*?)</script>', page, re.S)
        if not m:
            raise RuntimeError(f"no __NEXT_DATA__ for {where}")
        pp = json.loads(m.group(1))["props"]["pageProps"]
        for j in pp.get("jobs", []):
            # On an l=Remote search every row carries remoteAttributes ["Remote"]
            # while location names the employer's city, so say where the flag
            # came from; the JD read confirms it.
            attrs = j.get("remoteAttributes") or []
            loc = j.get("location") or ""
            if attrs and "remote" not in loc.lower():
                loc += f" [SimplyHired: {'/'.join(attrs)}]"
            lo, hi = money_band(j.get("salaryInfo") or "")
            ms = j.get("dateOnIndeed")
            out.append(row("simplyhired", j.get("title"), j.get("company"), loc,
                           "https://www.simplyhired.com" + (j.get("botUrl") or ""),
                           remote="Remote" in attrs, lo=lo, hi=hi,
                           jtype=",".join(j.get("jobTypes") or []),
                           posted=dt.date.fromtimestamp(ms / 1000) if ms else None))
    return out


def smartrecruiters(q, days):
    out = []
    for offset in range(0, 300, 100):
        d = json.loads(http("https://jobs.smartrecruiters.com/sr-jobs/search?" + urllib.parse.urlencode(
            {"keyword": f'"{q}"', "limit": 100, "offset": offset})))
        rows = d.get("content") or []
        for j in rows:
            loc = j.get("location") or {}
            if (loc.get("country") or "").lower() not in ("us", ""):
                continue
            where = j.get("shortLocation") or ", ".join(
                x for x in (loc.get("city"), loc.get("region")) if x)
            if loc.get("hybrid"):
                where += " (hybrid)"
            out.append(row("smartrecruiters", j.get("name"), (j.get("company") or {}).get("name"),
                           where, j.get("applyUrl"), remote=bool(loc.get("remote")),
                           jtype=(j.get("typeOfEmployment") or {}).get("label", ""),
                           posted=parse_iso(j.get("releasedDate"))))
        if len(rows) < 100:
            break
    return out


def workable(q, days):
    out = []
    for params in ({"query": q, "location": "United States", "workplace": "remote"},
                   {"query": q, "location": "Kansas City, Missouri, United States"}):
        token = None
        for _ in range(3):
            p = dict(params, **({"pageToken": token} if token else {}))
            d = json.loads(http("https://jobs.workable.com/api/v1/jobs?" + urllib.parse.urlencode(p)))
            for j in d.get("jobs", []):
                loc = j.get("location") or {}
                where = ", ".join(x for x in (loc.get("city"), loc.get("subregion"),
                                              loc.get("countryName")) if x)
                if j.get("workplace") == "hybrid":
                    where += " (hybrid)"
                out.append(row("workable", j.get("title"), (j.get("company") or {}).get("title"),
                               where, j.get("url"), remote=j.get("workplace") == "remote",
                               jtype=j.get("employmentType") or "", posted=parse_iso(j.get("created"))))
            token = d.get("nextPageToken")
            if not token:
                break
    return out


def clearancejobs(q, days):
    out = []
    for page in (1, 2):
        d = json.loads(http("https://api.clearancejobs.com/api/v1/jobs/search",
                            {"keywords": q, "remote": True, "limit": 50, "page": page}))
        for j in d.get("data", []):
            locs = j.get("locations") or []
            where = "; ".join(x.get("location") or "" for x in locs)
            types = " ".join(str(x.get("type") or "") for x in locs)
            out.append(row("clearancejobs", j.get("job_name"), j.get("company_name"),
                           where + (f" ({types})" if "hybrid" in types.lower() else ""),
                           j.get("job_url"), remote="remote" in where.lower(),
                           lo=float(j["salary_min"]) if j.get("salary_min") else None,
                           hi=float(j["salary_max"]) if j.get("salary_max") else None,
                           posted=parse_iso(j.get("created_at")),
                           extra=f"clearance: {j.get('clearance') or 'none listed'}"))
        if len(d.get("data", [])) < 50:
            break
    return out


def workingnomads(q, days):
    words = " AND ".join(f"title:{w}" for w in q.split())
    d = json.loads(http("https://www.workingnomads.com/jobsapi/_search?" + urllib.parse.urlencode(
        {"q": words, "size": 100, "sort": "pub_date:desc"})))
    out = []
    for h in d.get("hits", {}).get("hits", []):
        j = h["_source"]
        if j.get("expired"):
            continue
        locs = ", ".join(j.get("locations") or [])
        if locs and not re.search(r"usa|united states|anywhere|worldwide|americas", locs, re.I):
            continue
        lo, hi = money_band(j.get("salary_range") or "")
        out.append(row("workingnomads", j.get("title"), j.get("company"), f"Remote ({locs or 'any'})",
                       j.get("apply_url") or f"https://www.workingnomads.com/jobs/{j.get('slug')}",
                       remote=True, lo=lo, hi=hi,
                       jtype="full-time" if j.get("position_type") == "ft" else (j.get("position_type") or ""),
                       posted=parse_iso(j.get("pub_date"))))
    return out


def jobicy(q, days):
    tag = q.split()[-1] if len(q.split()) > 1 else q
    d = json.loads(http("https://jobicy.com/api/v2/remote-jobs?" + urllib.parse.urlencode(
        {"count": 100, "geo": "usa", "tag": tag})))
    out = []
    for j in d.get("jobs", []):
        mult = {"hourly": 2080, "monthly": 12}.get(j.get("salaryPeriod") or "", 1)
        lo = float(j["salaryMin"]) * mult if j.get("salaryMin") else None
        hi = float(j["salaryMax"]) * mult if j.get("salaryMax") else None
        out.append(row("jobicy", html.unescape(j.get("jobTitle") or ""), j.get("companyName"),
                       f"Remote ({j.get('jobGeo')})", j.get("url"), remote=True, lo=lo, hi=hi,
                       jtype=",".join(j.get("jobType") or []), posted=parse_iso(j.get("pubDate"))))
    return out


def remoteok(q, days):
    d = json.loads(http("https://remoteok.com/api"))
    words = [w.lower() for w in q.split()]
    out = []
    for j in d[1:]:
        text = (j.get("position", "") + " " + " ".join(j.get("tags") or [])).lower()
        if not all(w in text for w in words):
            continue
        loc = j.get("location") or "Remote"
        if NON_US.search(loc):
            continue
        out.append(row("remoteok", j.get("position"), j.get("company"), f"Remote ({loc})",
                       j.get("url"), remote=True, lo=j.get("salary_min") or None,
                       hi=j.get("salary_max") or None, posted=parse_iso(j.get("date"))))
    return out


JIBE = {"garmin": "careers.garmin.com", "hrblock": "careers.hrblock.com", "bjc": "jobs.bjc.org"}


def jibe(employer):
    def fetch(q, days):
        host = JIBE[employer]
        d = json.loads(http(f"https://{host}/api/jobs?" + urllib.parse.urlencode(
            {"keywords": q, "limit": 100})))
        out = []
        for j in (x["data"] for x in d.get("jobs", [])):
            tags = " ".join(str(t) for k, v in j.items() if k.startswith("tags") for t in (v or []))
            where = j.get("full_location") or ", ".join(
                x for x in (j.get("city"), j.get("state")) if x)
            if re.search(r"hybrid", tags, re.I):
                where += " (hybrid)"
            out.append(row(f"jibe-{employer}", j.get("title"), j.get("hiring_organization") or employer,
                           where, j.get("apply_url") or f"https://{host}/jobs/{j.get('slug')}",
                           remote=bool(re.search(r"remote", tags + where, re.I)),
                           jtype=j.get("employment_type") or "", posted=parse_iso(j.get("posted_date"))))
        return out
    return fetch


def oracle_health(q, days):
    url = ("https://eeho.fa.us2.oraclecloud.com/hcmRestApi/resources/latest/recruitingCEJobRequisitions"
           "?onlyData=true&expand=requisitionList.secondaryLocations"
           f"&finder=findReqs;siteNumber=CX_45001,keyword={urllib.parse.quote(q)},limit=100,sortBy=POSTING_DATES_DESC")
    d = json.loads(http(url))
    out = []
    for it in d.get("items", []):
        for j in it.get("requisitionList", []):
            out.append(row("oracle-health", j.get("Title"), "Oracle Health", j.get("PrimaryLocation"),
                           f"https://eeho.fa.us2.oraclecloud.com/hcmUI/CandidateExperience/en/sites/CX_45001/job/{j.get('Id')}",
                           remote=bool(re.search(r"remote", j.get("Title") or "", re.I)),
                           posted=parse_iso(j.get("PostedDate"))))
    return out


def higheredjobs(q, days):
    out = []
    words = [w.lower() for w in q.split()]
    for cat in (163, 175):
        xml = http(f"https://www.higheredjobs.com/rss/categoryFeed.cfm?catID={cat}",
                   headers={"Accept": "application/rss+xml, text/xml"})
        for item in re.findall(r"<item>(.*?)</item>", xml, re.S):
            def tag(name, item=item):
                m = re.search(rf"<{name}>(.*?)</{name}>", item, re.S)
                return html.unescape(re.sub(r"<!\[CDATA\[|\]\]>", "", m.group(1))).strip() if m else ""
            title = tag("title")
            if not all(w in title.lower() for w in words[:1]):
                continue
            pub = tag("pubDate")
            try:
                posted = dt.datetime.strptime(pub[:16], "%a, %d %b %Y").date()
            except ValueError:
                posted = None
            out.append(row("higheredjobs", title, "", title, tag("link"),
                           remote=bool(REMOTE.search(title)), posted=posted))
    return out


def hn_hiring(q, days):
    d = json.loads(http("https://hn.algolia.com/api/v1/search_by_date?" + urllib.parse.urlencode(
        {"tags": "story,author_whoishiring", "query": "Who is hiring", "hitsPerPage": 3})))
    thread = next((h for h in d.get("hits", []) if "who is hiring" in (h.get("title") or "").lower()), None)
    if not thread:
        raise RuntimeError("no current Who is hiring thread")
    t = json.loads(http(f"https://hn.algolia.com/api/v1/items/{thread['objectID']}"))
    words = [w.lower() for w in q.split()]
    out = []
    for c in t.get("children", []):
        text = html.unescape(re.sub(r"<[^>]+>", " ", c.get("text") or ""))
        first = text.split("\n")[0][:160]
        if not all(w in text.lower() for w in words) or not REMOTE.search(text):
            continue
        lo, hi = money_band(text)
        out.append(row("hn-hiring", first, first.split("|")[0], "Remote (see post)",
                       f"https://news.ycombinator.com/item?id={c['id']}", remote=True,
                       lo=lo if lo and lo > 20000 else None, hi=hi if hi and hi > 20000 else None,
                       posted=parse_iso(c.get("created_at")), extra=f"thread: {thread['title']}"))
    return out


def _env(key: str) -> str | None:
    """Keys live in the gitignored harness .env, same lookup as comp_floors."""
    if os.environ.get(key):
        return os.environ[key]
    env = Path(__file__).resolve().parent.parent / ".env"
    for line in env.read_text().splitlines() if env.exists() else []:
        if line.startswith(key + "="):
            return line.split("=", 1)[1].strip().strip('"')
    return None


def jooble(q, days):
    """Jooble REST API (POST /api/<key>). Key emailed on signup 2026-10-13;
    default limit 500 requests, so two calls per query (remote + KC)."""
    key = _env("JOOBLE_API_KEY")
    if not key:
        raise RuntimeError("JOOBLE_API_KEY missing from .env")
    since = (dt.date.today() - dt.timedelta(days=days)).isoformat()
    out = []
    for where, extra in (("Remote", {}), ("Kansas City, MO", {"radius": "40"})):
        d = json.loads(http(f"https://jooble.org/api/{key}", {
            "keywords": q if where != "Remote" else f"{q} remote", "location": where,
            "datecreatedfrom": since, "page": "1", "ResultOnPage": "50", **extra}))
        for j in d.get("jobs", []):
            lo, hi = money_band(j.get("salary") or "")
            loc = j.get("location") or ""
            out.append(row("jooble", html.unescape(j.get("title") or ""), j.get("company"), loc,
                           j.get("link"), remote=bool(REMOTE.search(loc + " " + (j.get("title") or ""))),
                           lo=lo, hi=hi, jtype=j.get("type") or "", posted=parse_iso(j.get("updated")),
                           extra=f"via {j.get('source')}" if j.get("source") else ""))
    return out


ADZUNA_QUOTA = Path(__file__).resolve().parent / "state" / "adzuna-quota.json"
ADZUNA_FREE_CALLS = 25


class ArchivedSource(Exception):
    """The source is retired; main() reports it as ARCHIVED, not as a failure."""


def _adzuna_quota() -> dict:
    # One call was spent by hand on 2026-10-13 to test the key.
    return (json.loads(ADZUNA_QUOTA.read_text()) if ADZUNA_QUOTA.exists()
            else {"calls": 1, "limit": ADZUNA_FREE_CALLS, "archived": None})


def _adzuna_archive(q: dict, why: str) -> None:
    q["archived"] = f"{dt.date.today().isoformat()}: {why}"
    ADZUNA_QUOTA.parent.mkdir(exist_ok=True)
    ADZUNA_QUOTA.write_text(json.dumps(q, indent=1))
    raise ArchivedSource(q["archived"])


def adzuna(q, days):
    """Adzuna API on the free plan: 25 calls in total (the paid plan is GBP 8 a
    month). Alex chose 2026-10-13 to run it daily until the calls are gone, then
    archive it. The script counts calls in state/adzuna-quota.json and archives
    the source itself, when the count reaches the limit or when Adzuna answers
    with an auth or quota error. Delete that file to re-enable it (for example
    after a paid upgrade, with "limit" raised). Salaries flagged
    salary_is_predicted are estimates and are dropped."""
    quota = _adzuna_quota()
    if quota.get("archived"):
        raise ArchivedSource(quota["archived"])
    app_id, key = _env("ADZUNA_APP_ID"), _env("ADZUNA_APP_KEY")
    if not (app_id and key):
        raise RuntimeError("ADZUNA_APP_ID / ADZUNA_APP_KEY missing from .env")
    out = []
    for what, where in ((f"{q} remote", None), (q, "Kansas City")):
        if quota["calls"] >= quota["limit"]:
            _adzuna_archive(quota, f"used all {quota['limit']} free calls")
        params = {"app_id": app_id, "app_key": key, "results_per_page": 50, "what": what,
                  "max_days_old": days, "sort_by": "date", "content-type": "application/json"}
        if where:
            params |= {"where": where, "distance": 60}
        try:
            body = http("https://api.adzuna.com/v1/api/jobs/us/search/1?" + urllib.parse.urlencode(params))
        except Exception as e:  # noqa: BLE001  (classify the failure below)
            resp = getattr(e, "response", None)
            status = getattr(resp, "status_code", None)
            text = (getattr(resp, "text", "") or str(e)).lower()
            if status in (401, 403, 429) or re.search(r"limit|exceed|quota|plan|usage", text):
                quota["calls"] += 1
                _adzuna_archive(quota, f"Adzuna refused the call (HTTP {status}): {text[:80]}")
            raise
        quota["calls"] += 1
        ADZUNA_QUOTA.parent.mkdir(exist_ok=True)
        ADZUNA_QUOTA.write_text(json.dumps(quota, indent=1))
        for j in json.loads(body).get("results", []):
            predicted = str(j.get("salary_is_predicted")) == "1"
            loc = (j.get("location") or {}).get("display_name", "")
            title = j.get("title") or ""
            out.append(row("adzuna", title, (j.get("company") or {}).get("display_name"), loc,
                           j.get("redirect_url"), remote=bool(REMOTE.search(title + " " + loc)),
                           lo=None if predicted else j.get("salary_min"),
                           hi=None if predicted else j.get("salary_max"),
                           jtype=" ".join(x for x in (j.get("contract_type"), j.get("contract_time")) if x),
                           posted=parse_iso(j.get("created"))))
    return out


SOURCES = {
    "simplyhired": simplyhired, "smartrecruiters": smartrecruiters, "workable": workable,
    "clearancejobs": clearancejobs, "workingnomads": workingnomads, "jobicy": jobicy,
    "remoteok": remoteok, "jibe-garmin": jibe("garmin"), "jibe-hrblock": jibe("hrblock"),
    "jibe-bjc": jibe("bjc"), "oracle-health": oracle_health, "higheredjobs": higheredjobs,
    "hn-hiring": hn_hiring, "jooble": jooble, "adzuna": adzuna,
}
# Rationed sources: run only when named in --sources. Empty since 2026-10-13:
# adzuna runs daily and archives itself when its free calls are gone.
OPT_IN: set[str] = set()
# HN posts and HigherEdJobs titles are matched by keyword only, so they get
# no date window beyond the thread / feed itself.
NO_DATE_WINDOW = {"hn-hiring"}


# ---------------------------------------------------------------- gate

def gate(j: dict, floor: int, onsite: int) -> tuple[str, str]:
    t = j["title"]
    if not KEEP.search(t) or DROP.search(t) or ((OFF_LANE.search(t) or OFF_LANE_AFTER.search(t)) and not STRONG.search(t)):
        return "drop", "title pre-filter"
    if j["extra"].startswith("clearance:") and BAD_CLEARANCE.search(j["extra"]):
        return "decline", f"needs {j['extra']}"
    where = j["where"]
    if NON_US.search(where) or re.search(r"\bm/[fw]/d\b", t, re.I):
        return "decline", f"gate1 non-US {where!r}"
    hybrid = bool(re.search(r"hybrid|on-?site", where + " " + t, re.I))
    remote = (j["remote"] or REMOTE.search(where + " " + t)) and not hybrid
    tag = ""
    if not remote:
        if not KC_METRO.search(where + " " + t):
            return "decline", f"gate1 location {where!r}"
        floor, tag = onsite, f" [KC-LOCAL: ${onsite:,} onsite floor]"
    if j["type"] and BAD_TYPE.search(j["type"]):
        return "decline", f"gate2 {j['type']}"
    if BAD_TYPE.search(t):
        return "decline", "gate2 title says contract/part-time"
    lo, hi = j["lo"], j["hi"]
    if hi is None and lo is None:
        return "lead", "comp unlisted" + tag
    top = hi if hi is not None else lo
    if top is not None and top < floor:
        return "decline", f"gate3 band tops at ${int(top):,}" + tag
    flag = f" [BAND-STRADDLE: bottom ${int(lo):,}]" if lo and lo < floor else ""
    return "survivor", flag + tag


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("queries", nargs="+")
    ap.add_argument("--days", type=int, default=3)
    ap.add_argument("--sources", default=",".join(k for k in SOURCES if k not in OPT_IN),
                    help="comma list; default all except the rationed: " + ",".join(OPT_IN))
    ap.add_argument("--all", action="store_true", help="print rows already shown on earlier runs")
    ap.add_argument("--verbose", action="store_true", help="list declined rows")
    ap.add_argument("--no-save", action="store_true", help="do not update the seen-file")
    a = ap.parse_args()
    _ensure_curl_cffi()

    floor, onsite = comp_floor(), onsite_floor()
    today = dt.date.today()
    cutoff = today - dt.timedelta(days=a.days)
    seen = json.loads(STATE.read_text()) if STATE.exists() else {}
    seen = {u: d for u, d in seen.items()
            if dt.date.fromisoformat(d) >= today - dt.timedelta(days=SEEN_TTL_DAYS)}

    buckets: dict[str, list] = {k: [] for k in ("survivor", "lead", "decline", "drop")}
    urls = set()
    fresh_seen = 0
    print(f"moreboards | remote floor ${floor:,} | KC onsite floor ${onsite:,} | window {a.days}d\n")
    for name in [s.strip() for s in a.sources.split(",") if s.strip()]:
        fn = SOURCES.get(name)
        if not fn:
            print(f"== {name}: unknown source")
            continue
        got, errs = [], []
        archived = ""
        for q in a.queries:
            try:
                got += fn(q, a.days)
            except ArchivedSource as e:
                archived = str(e)
                break
            except Exception as e:  # noqa: BLE001  (one failing board must not stop the lane)
                errs.append(f"{q!r}: {str(e)[:90]}")
        kept = 0
        for j in got:
            if not j["url"] or j["url"] in urls:
                continue
            if name not in NO_DATE_WINDOW and j["posted"] and j["posted"] < cutoff:
                continue
            urls.add(j["url"])
            if j["url"] in seen and not a.all:
                fresh_seen += 1
                continue
            kept += 1
            verdict, why = gate(j, floor, onsite)
            buckets[verdict].append((j, why))
        status = "NOT RUN" if errs and not got else ("PARTIAL" if errs else "ok")
        print(f"== {name:16s} {status:8s} {len(got):4d} rows, {kept:3d} new in window"
              + (f"  ERRORS: {'; '.join(errs)}" if errs else ""))
        if archived:
            print(f"   ~ {name} ARCHIVED ({archived}). Not a failure; the source is retired.")
        if name == "adzuna" and not archived:
            quota = _adzuna_quota()
            print(f"   ~ adzuna free calls used: {quota['calls']}/{quota['limit']}")

    print(f"\n{len(urls)} unique in window | {fresh_seen} already shown | "
          f"{len(buckets['survivor'])} survivors | {len(buckets['lead'])} leads | "
          f"{len(buckets['decline'])} declined | {len(buckets['drop'])} title-dropped\n")
    sections = [("SURVIVORS -- JD read + employer-ATS verify", "survivor"),
                ("LEADS -- comp unlisted, JD read decides", "lead")]
    if a.verbose:
        sections.append(("DECLINED", "decline"))
    for head, key in sections:
        print(head)
        for j, why in sorted(buckets[key], key=lambda x: x[0]["src"]):
            comp = (f"${int(j['lo'] or 0):,}-${int(j['hi'] or 0):,}"
                    if j["lo"] or j["hi"] else "unlisted")
            extra = f" | {j['extra']}" if j["extra"] else ""
            print(f"  [{j['src']}] {j['title']} @ {j['company']} | {j['where']} | {comp} | "
                  f"{j['posted'] or '?'}{extra}  {why}")
            print(f"    {j['url']}")
        print()

    if not a.no_save:
        for u in urls:
            seen.setdefault(u, today.isoformat())
        STATE.parent.mkdir(exist_ok=True)
        STATE.write_text(json.dumps(seen, indent=0, sort_keys=True))


if __name__ == "__main__":
    main()
