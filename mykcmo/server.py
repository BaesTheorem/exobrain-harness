"""myKCMO MCP server: Kansas City, MO 311 service requests over stdio.

Three parts:
- HISTORY (data.kcmo.org, Socrata dataset d4px-6rwg): search, track, stats
  over the 311 feed since March 2021. Lags real time by 2-7 days.
- APP API (civicapi.py, api.mycivicapps.com): the backend of the official
  myKCMO app. Catalog, form questions, duplicate check, filing with photos,
  "my reports" and live status. Signed with a key from the APK, rebuilt by
  bin/mykcmo-refresh-key when the city rotates it.
- WEB FORM FALLBACK (webrai.py): the captcha-gated web form, for when the
  app key is rejected and cannot be refreshed.

INVARIANTS:
- Read tools are read-only against data.kcmo.org.
- All SoQL string literals pass through _soql_str (single quotes doubled).
- Status matching is case-insensitive (the dataset mixes "resolved"/"Resolved").
- report_submit.php is hit only by submit_311_report_webform, only after a
  human read the captcha and the caller passed confirm=True.
- report_an_issue is hit only by submit_311_report, only with confirm=True.
- Other people's reporter_* contact fields never leave civicapi (strip_reporter).
"""

import json
import os
import urllib.parse
import urllib.request
from datetime import datetime

import civicapi
import kcplace as geo
import streetcar
import webrai
from mcp.server import MCPServer

DATASET = "d4px-6rwg"  # 311 Call Center Reported Issues (March 2021 - present)
BASE_URL = f"https://data.kcmo.org/resource/{DATASET}.json"

# Observed current_status values, lowercased. "open" / "closed" filters
# expand to these sets.
OPEN_STATUSES = ("received", "new", "assigned", "referred", "active")
CLOSED_STATUSES = ("resolved", "closed", "canceled")

GROUPABLE_FIELDS = (
    "issue_type",
    "issue_sub_type",
    "current_status",
    "department_work_group",
    "council_district",
    "report_source",
    "source_category",
)

# Fields returned for list-style results; the full record adds the rest.
SUMMARY_FIELDS = (
    "reported_issue",
    "current_status",
    "open_date_time",
    "issue_type",
    "issue_sub_type",
    "incident_address",
    "council_district",
)

mcp = MCPServer(
    "mykcmo",
    instructions=(
        "Kansas City, MO 311 service requests (myKCMO). Live data: my_311_reports, "
        "get_311_report_status, live_311_map (the city's app backend). History and "
        "stats: search_311_requests etc. (open data, 2-7 day lag). Filing creates a "
        "REAL case: list_report_categories -> get_report_subtypes (questions) -> "
        "prepare_311_report (review, no captcha) -> submit_311_report(confirm=True). "
        "Confirm with Alex before submitting. The *_webform tools are a captcha "
        "fallback for when the app key is rejected. Streetcar problems are not 311: "
        "use prepare_streetcar_report -> submit_streetcar_report(confirm=True)."
    ),
)


def _soql_str(value: str) -> str:
    """Escape a string for embedding in a SoQL single-quoted literal."""
    return value.replace("'", "''")


def _fetch(params: dict[str, str]) -> list[dict]:
    url = BASE_URL + "?" + urllib.parse.urlencode(params)
    req = urllib.request.Request(url, headers={"Accept": "application/json"})
    token = os.environ.get("MYKCMO_SOCRATA_APP_TOKEN", "")
    if token:
        req.add_header("X-App-Token", token)
    with urllib.request.urlopen(req, timeout=30) as resp:
        return json.load(resp)


def _date_floor(day: str) -> str:
    """Validate YYYY-MM-DD and return a SoQL floating timestamp."""
    parsed = datetime.strptime(day, "%Y-%m-%d")
    return parsed.strftime("%Y-%m-%dT00:00:00")


def _status_clause(status: str) -> str:
    status = status.strip().lower()
    if status == "open":
        values = OPEN_STATUSES
    elif status == "closed":
        values = CLOSED_STATUSES
    else:
        values = (status,)
    quoted = ", ".join(f"'{_soql_str(v)}'" for v in values)
    return f"lower(current_status) in ({quoted})"


def _build_where(
    issue_type: str | None = None,
    status: str | None = None,
    address: str | None = None,
    district: str | None = None,
    opened_after: str | None = None,
    opened_before: str | None = None,
) -> list[str]:
    where: list[str] = []
    if issue_type:
        term = _soql_str(issue_type.lower())
        where.append(
            f"(lower(issue_type) like '%{term}%'"
            f" OR lower(issue_sub_type) like '%{term}%')"
        )
    if status:
        where.append(_status_clause(status))
    if address:
        where.append(f"lower(incident_address) like '%{_soql_str(address.lower())}%'")
    if district:
        where.append(f"council_district = '{_soql_str(district)}'")
    if opened_after:
        where.append(f"open_date_time >= '{_date_floor(opened_after)}'")
    if opened_before:
        where.append(f"open_date_time < '{_date_floor(opened_before)}'")
    return where


def _trim(record: dict, full: bool = False) -> dict:
    if full:
        return {
            k: v
            for k, v in record.items()
            if not k.startswith(":@") and k != "lat_long"
        }
    return {k: record[k] for k in SUMMARY_FIELDS if k in record}


@mcp.tool()
def search_311_requests(
    query: str | None = None,
    issue_type: str | None = None,
    status: str | None = None,
    address: str | None = None,
    council_district: str | None = None,
    opened_after: str | None = None,
    opened_before: str | None = None,
    limit: int = 20,
) -> list[dict]:
    """Search Kansas City 311 service requests (March 2021 - present).

    All filters combine with AND. `query` is Socrata full-text search across
    every field; `issue_type` substring-matches type and sub-type (e.g.
    "pothole", "trash", "streetlight"); `status` is "open", "closed", or a
    literal value like "resolved"; `address` substring-matches the incident
    address; dates are YYYY-MM-DD. Data lags real time by roughly 2-7 days.
    """
    params: dict[str, str] = {
        "$order": "open_date_time DESC",
        "$limit": str(max(1, min(limit, 200))),
    }
    if query:
        params["$q"] = query
    where = _build_where(
        issue_type, status, address, council_district, opened_after, opened_before
    )
    if where:
        params["$where"] = " AND ".join(where)
    return [_trim(r) for r in _fetch(params)]


@mcp.tool()
def get_311_request(case_number: str) -> list[dict]:
    """Look up a 311 request by its case number (the number given when a
    request is filed, e.g. from the myKCMO app) or by work-order number.
    Returns the full record(s) including status, dates, and department.
    """
    case = _soql_str(case_number.strip())
    params = {
        "$where": f"reported_issue = '{case}' OR workorder_ = '{case}'",
        "$limit": "10",
    }
    return [_trim(r, full=True) for r in _fetch(params)]


@mcp.tool()
def get_311_requests(case_numbers: list[str]) -> dict[str, list[dict]]:
    """Look up several 311 requests at once by case or work-order number.
    Returns a map of the number you asked for to its record(s); a number with
    no match maps to an empty list (usually means it is newer than the feed's
    2-7 day lag).
    """
    wanted = [c.strip() for c in case_numbers if c.strip()]
    if not wanted:
        return {}
    literals = ", ".join(f"'{_soql_str(c)}'" for c in wanted)
    params = {
        "$where": f"reported_issue in({literals}) OR workorder_ in({literals})",
        "$limit": str(len(wanted) * 10),
    }
    found: dict[str, list[dict]] = {c: [] for c in wanted}
    for record in _fetch(params):
        for c in wanted:
            if c in (record.get("reported_issue"), record.get("workorder_")):
                found[c].append(_trim(record, full=True))
    return found


@mcp.tool()
def nearby_311_requests(
    latitude: float | None = None,
    longitude: float | None = None,
    radius_m: int = 800,
    status: str | None = None,
    issue_type: str | None = None,
    opened_after: str | None = None,
    limit: int = 25,
) -> list[dict]:
    """List 311 requests near a point (defaults to MYKCMO_HOME_LAT/LON env
    vars if coordinates are omitted). radius_m is meters. Useful for "what's
    reported near me / near this address" once you have coordinates.
    """
    if latitude is None or longitude is None:
        try:
            latitude = float(os.environ["MYKCMO_HOME_LAT"])
            longitude = float(os.environ["MYKCMO_HOME_LON"])
        except (KeyError, ValueError):
            raise ValueError(
                "No coordinates given and MYKCMO_HOME_LAT/MYKCMO_HOME_LON are "
                "not set; pass latitude and longitude explicitly."
            ) from None
    where = [
        f"within_circle(lat_long, {latitude}, {longitude}, {max(10, radius_m)})"
    ]
    where += _build_where(issue_type=issue_type, status=status, opened_after=opened_after)
    params = {
        "$where": " AND ".join(where),
        "$order": "open_date_time DESC",
        "$limit": str(max(1, min(limit, 200))),
    }
    return [_trim(r) for r in _fetch(params)]


@mcp.tool()
def kc_311_stats(
    group_by: str = "issue_type",
    status: str | None = None,
    council_district: str | None = None,
    opened_after: str | None = None,
    opened_before: str | None = None,
    top: int = 15,
) -> list[dict]:
    """Aggregate counts of 311 requests. group_by is one of: issue_type,
    issue_sub_type, current_status, department_work_group, council_district,
    report_source, source_category. Dates are YYYY-MM-DD.
    """
    if group_by not in GROUPABLE_FIELDS:
        raise ValueError(f"group_by must be one of {GROUPABLE_FIELDS}")
    params: dict[str, str] = {
        "$select": f"{group_by}, count(*) as count",
        "$group": group_by,
        "$order": "count DESC",
        "$limit": str(max(1, min(top, 100))),
    }
    where = _build_where(
        status=status,
        district=council_district,
        opened_after=opened_after,
        opened_before=opened_before,
    )
    if where:
        params["$where"] = " AND ".join(where)
    return _fetch(params)


@mcp.tool()
def list_311_issue_types(since: str = "2025-01-01") -> list[dict]:
    """List the distinct issue types and sub-types used since a date
    (YYYY-MM-DD), with counts. Use this to find the right issue_type filter
    value before searching.
    """
    params = {
        "$select": "issue_type, issue_sub_type, count(*) as count",
        "$group": "issue_type, issue_sub_type",
        "$where": f"open_date_time >= '{_date_floor(since)}'",
        "$order": "issue_type, count DESC",
        "$limit": "500",
    }
    return _fetch(params)


@mcp.tool()
def report_issue_info() -> dict:
    """How to actually file a new 311 request with Kansas City, MO. Filing is
    not automatable (the web form is captcha-gated on purpose); this returns
    the official channels and deep links to hand to the user.
    """
    return {
        "web_form": "https://webrai.mycivicapps.com/1adb57d07d9ea1e1dd8160697f745c0d",
        "info_page": "https://www.kcmo.gov/talk-to-us/mykcmo",
        "ios_app": "https://apps.apple.com/us/app/mykcmo/id1553680855",
        "android_app": (
            "https://play.google.com/store/apps/details"
            "?id=com.civicapps.kansascitymo"
        ),
        "phone": "311 from inside the city, or 816-513-1313",
        "notes": (
            "MIST CAN file directly via list_report_categories -> "
            "get_report_subtypes -> prepare_311_report -> submit_311_report. "
            "Those channels are the manual fallback. Save the returned work "
            "order id: get_311_request tracks it once it reaches the "
            "open-data feed (2-7 day lag)."
        ),
    }


# ---------------------------------------------------------------------------
# WRITE side: file a real 311 request via the city web form.
#
# Flow (agent-in-the-loop; MIST reads the captcha, Alex confirms):
#   1. list_report_categories()          -> pick a report type
#   2. get_report_subtypes(type)         -> pick a sub_type, learn the rules
#   3. prepare_311_report(...)           -> returns a captcha image PATH
#      MIST reads that image with vision to get the answer, confirms w/ Alex
#   4. submit_311_report(pending_id, answer, confirm=True) -> work order id
#
# _PENDING holds one report's session + payload between steps 3 and 4. In
# process only (the server is long-lived per session); nothing hits disk.
# ---------------------------------------------------------------------------

_PENDING: dict[str, dict] = {}
_CAPTCHA_DIR = os.environ.get(
    "MYKCMO_CAPTCHA_DIR",
    os.path.expanduser("~/Documents/Exobrain harness/tmp/images"),
)


def _contact_defaults() -> dict:
    return {
        "first_name": os.environ.get("MYKCMO_CONTACT_FIRST", ""),
        "last_name": os.environ.get("MYKCMO_CONTACT_LAST", ""),
        "email": os.environ.get("MYKCMO_CONTACT_EMAIL", ""),
        "phone": os.environ.get("MYKCMO_CONTACT_PHONE", ""),
    }


@mcp.tool()
def prepare_311_report_webform(
    report_type: str,
    description: str,
    sub_type: str = "",
    address: str = "",
    latitude: str = "",
    longitude: str = "",
    first_name: str = "",
    last_name: str = "",
    email: str = "",
    phone: str = "",
    share_options: str = "private",
) -> dict:
    """Stage a real 311 request and fetch its captcha for MIST to read.

    Does NOT submit anything. It validates the type, geocodes `address` (or
    uses explicit latitude/longitude), opens a session, downloads the image
    captcha, and returns a `pending_id`, the `captcha_image_path` (a JPEG
    MIST must Read to solve), and a `review` summary of exactly what will be
    filed. Contact fields fall back to MYKCMO_CONTACT_* env vars.

    FALLBACK ONLY: use prepare_311_report (the app API, no captcha) unless it
    reports that the API key was rejected and mykcmo-refresh-key cannot fix it.
    Standard-template types only.

    Next: Read captcha_image_path, then call submit_311_report_webform(pending_id,
    captcha_answer, confirm=True) after Alex confirms the review.
    """
    info = webrai.fetch_subtypes(report_type)
    if info["template"].lower() != "standard":
        raise ValueError(
            f"{info['label']!r} uses a {info['template']!r} form, not auto-"
            "submittable. Use the web form / app (report_issue_info)."
        )
    if info["subtypes"] and not sub_type:
        raise ValueError(
            f"{info['label']!r} needs a sub_type. Options: "
            + ", ".join(f"{s['name']}={s['id']}" for s in info["subtypes"])
        )
    # Normalize a sub_type given by name to its id.
    if sub_type:
        for s in info["subtypes"]:
            if sub_type == s["id"] or sub_type.lower() == s["name"].lower():
                sub_type = s["id"]
                break

    location = None
    if info["location_required"]:
        if latitude and longitude:
            location = {
                "address": address,
                "lat": str(latitude),
                "lon": str(longitude),
                "city": "Kansas City",
                "state": "MO",
                "zip": "",
            }
        elif address:
            location = webrai.geocode(address)
        else:
            raise ValueError(
                f"{info['label']!r} requires a location; pass address or "
                "latitude+longitude."
            )

    contact = _contact_defaults()
    contact.update(
        {
            k: v
            for k, v in {
                "first_name": first_name,
                "last_name": last_name,
                "email": email,
                "phone": phone,
            }.items()
            if v
        }
    )
    if not contact["email"]:
        raise ValueError(
            "A contact email is required (pass email= or set "
            "MYKCMO_CONTACT_EMAIL). KC uses it to send the case confirmation."
        )

    opener = webrai.new_session()
    os.makedirs(_CAPTCHA_DIR, exist_ok=True)
    pending_id = webrai.captcha_id()
    img_path = os.path.join(_CAPTCHA_DIR, f"kc_311_captcha_{pending_id}.jpg")
    cap_uid = webrai.open_captcha(opener, img_path)
    read_path = webrai.enlarge(img_path)

    payload = webrai.build_payload(
        report_type=info["report_type"],
        sub_type=sub_type,
        description=description,
        location=location,
        first_name=contact["first_name"],
        last_name=contact["last_name"],
        email=contact["email"],
        phone=contact["phone"],
        template=info["template"],
        location_required=info["location_required"],
        description_required=info["description_required"],
        captcha_answer="",  # filled at submit
        unique_captcha_id=cap_uid,
        share_options=share_options,
    )
    _PENDING[pending_id] = {"opener": opener, "payload": payload, "label": info["label"]}

    return {
        "pending_id": pending_id,
        "captcha_image_path": read_path,
        "captcha_raw_path": img_path,
        "action_needed": (
            "Read captcha_image_path to solve the captcha, confirm the review "
            "with Alex, then call submit_311_report_webform(pending_id, captcha_answer, "
            "confirm=True)."
        ),
        "review": {
            "type": info["label"],
            "sub_type": sub_type,
            "description": description,
            "location": (location or {}).get("address", "(none)"),
            "coordinates": (
                f"{location['lat']},{location['lon']}" if location else "(none)"
            ),
            "contact": f"{contact['first_name']} {contact['last_name']} "
            f"<{contact['email']}> {contact['phone']}".strip(),
            "visibility": share_options,
            "disclaimer": info["disclaimer"] or None,
        },
    }


@mcp.tool()
def submit_311_report_webform(
    pending_id: str,
    captcha_answer: str,
    confirm: bool = False,
) -> dict:
    """File the report staged by prepare_311_report_webform. This creates a REAL 311
    case with Kansas City. Requires confirm=True (get Alex's OK first) and the
    captcha_answer MIST read from the prepared captcha image.

    On a wrong captcha it re-fetches a new captcha and returns its path with
    retry=True (read it and call again). On success returns the work order id.
    """
    if not confirm:
        raise ValueError(
            "Refusing to file: this creates a real city 311 case. Confirm with "
            "Alex, then call again with confirm=True."
        )
    state = _PENDING.get(pending_id)
    if not state or "opener" not in state:
        raise ValueError(
            "Unknown or expired pending_id. Call prepare_311_report_webform again."
        )
    payload = dict(state["payload"])
    payload["custom_captcha"] = captcha_answer.strip()
    result = webrai.submit(state["opener"], payload)

    if result["ok"]:
        _PENDING.pop(pending_id, None)
        return {
            "ok": True,
            "work_order_id": result["work_order_id"],
            "type": state["label"],
            "message": result["message"]
            or "Report submitted to Kansas City 311.",
            "track_with": "get_311_request (appears in the feed in 2-7 days)",
        }

    if result["captcha_failed"]:
        # Bad captcha: mint a fresh one on the same session for another read.
        img_path = os.path.join(_CAPTCHA_DIR, f"kc_311_captcha_{pending_id}.jpg")
        new_uid = webrai.open_captcha(state["opener"], img_path)
        payload["unique_captcha_id"] = new_uid
        state["payload"] = payload
        return {
            "ok": False,
            "retry": True,
            "captcha_image_path": webrai.enlarge(img_path),
            "captcha_raw_path": img_path,
            "message": "Captcha was wrong; read the new image and resubmit.",
        }

    return {
        "ok": False,
        "retry": False,
        "error": result["error"] or "Submission failed.",
        "raw": result["raw"],
    }


# ---------------------------------------------------------------------------
# App-API write side (civicapi.py): the backend of the official myKCMO app.
# No captcha, every report type (including custom forms), photos, and live
# status. "My reports" are keyed by the device id in civic-config.json, which
# the KC 311 iPhone app shares, so reports filed on the phone show up here.
# ---------------------------------------------------------------------------


def _key_error(exc: Exception) -> dict:
    return {
        "ok": False,
        "error": f"The MyCivic API rejected the signature ({exc}). The city rotated the app key. "
        "Run mykcmo/bin/mykcmo-refresh-key, or fall back to prepare_311_report_webform.",
    }


def _subtype(cat: dict, sub_type: str) -> dict | None:
    subs = civicapi.subcategories(cat)
    if not subs:
        return None
    if not sub_type:
        raise ValueError(f"{cat['name']!r} needs a sub_type. Options: " + ", ".join(s["name"] for s in subs))
    low = sub_type.strip().lower()
    for s in subs:
        if low in (s["name"].lower(), s["subcat_id"]):
            return s
    raise ValueError(f"Unknown sub_type {sub_type!r}. Options: " + ", ".join(s["name"] for s in subs))


def _question_view(q: dict) -> dict:
    kinds = {1: "yes/no", 2: "MM/yyyy", 3: "text", 4: "choice", 5: "MM-dd-yyyy HH:mm", 6: "MM-dd-yyyy", 7: "HH:mm"}
    out = {"caption": q["caption"], "kind": kinds.get(int(q["type"]), str(q["type"])),
           "required": str(q.get("IS_INPUT_REQUIRED", "")).lower() in ("yes", "1")}
    if q.get("dropdown_options"):
        out["options"] = [o["value"] for o in q["dropdown_options"]]
        out["multiple"] = q.get("allow_multiple_select") == "yes"
    return out


@mcp.tool()
def list_report_categories() -> list[str]:
    """List the 41 report types Kansas City accepts (pothole, illegal dumping,
    streetlights, etc.), from the live app catalog. Pass one to
    get_report_subtypes and prepare_311_report.
    """
    return [c["name"] for c in civicapi.catalog()["categories"]]


@mcp.tool()
def get_report_subtypes(report_type: str) -> dict:
    """For a report type, return its sub-types and, per sub-type, the form
    questions to answer, whether a location is required, the city's
    disclaimer, and whether a duplicate at the same address is blocked.
    """
    cat = civicapi.find_category(report_type)
    subs = civicapi.subcategories(cat) or [None]
    out = []
    for sub in subs:
        out.append({
            "sub_type": sub["name"] if sub else "",
            "questions": [_question_view(q) for q in civicapi.questions(cat, sub)],
            "location_required": civicapi.flag(cat, sub, "location_required") == "yes",
            "duplicates": {"0": "allowed", "1": "warn", "2": "blocked"}.get(
                civicapi.flag(cat, sub, "prevent_duplicate_issue") or "0", "allowed"),
            "disclaimer": civicapi.flag(cat, sub, "disclaimer_text") if civicapi.flag(cat, sub, "enable_disclaimer") == "yes" else None,
        })
    return {"report_type": cat["name"], "multiple_subtypes": cat.get("allow_multiple_subtypes") == "yes", "sub_types": out}


@mcp.tool()
def prepare_311_report(
    report_type: str,
    description: str = "",
    sub_type: str = "",
    address: str = "",
    latitude: float | None = None,
    longitude: float | None = None,
    answers: dict[str, str | list[str]] | None = None,
    photo_paths: list[str] | None = None,
    anonymous: bool = False,
    share_options: str = "private",
    add_location_line: bool = True,
) -> dict:
    """Stage a real 311 report through the myKCMO app API. Submits NOTHING.

    Validates the type, sub_type and form answers (keyed by question caption;
    see get_report_subtypes), geocodes `address` unless latitude/longitude are
    given, asks the city whether a duplicate exists at that address, and
    returns a `pending_id` plus a `review` of exactly what will be filed.
    Contact info comes from MYKCMO_CONTACT_* unless anonymous=True.

    Location: explicit latitude/longitude win, then the first photo's EXIF
    GPS, then the geocoded `address`. With add_location_line, the description
    gets one line with the GPS point, the nearest address and the nearest
    intersection, and empty free-text questions that ask where (location,
    address, intersection, cross street) get the same facts.

    Next: show the review to Alex, then submit_311_report(pending_id, confirm=True).
    """
    try:
        cat = civicapi.find_category(report_type)
        sub = _subtype(cat, sub_type)
        qs = civicapi.questions(cat, sub)
        given = {k.strip().lower(): v for k, v in (answers or {}).items()}
        encoded: dict[str, str] = {}
        missing = []
        for q in qs:
            val = given.get(q["caption"].strip().lower())
            if val in (None, "", []):
                if str(q.get("IS_INPUT_REQUIRED", "")).lower() in ("yes", "1") and int(q["type"]) != 1:
                    missing.append(_question_view(q))
                encoded[q["caption"]] = "NO" if int(q["type"]) == 1 else ""
                continue
            encoded[q["caption"]] = civicapi.encode_answer(q, val)
        if missing:
            return {"ok": False, "error": "Answer the required questions in `answers`.", "questions": missing}
        if civicapi.flag(cat, sub, "description_required") == "yes" and not description.strip():
            return {"ok": False, "error": f"{cat['name']!r} requires a description."}

        loc = None
        source = ""
        needs_loc = civicapi.flag(cat, sub, "location_required") == "yes"
        photo_gps = next((g for p in (photo_paths or []) if (g := geo.exif_gps(os.path.expanduser(p)))), None)
        if latitude is not None and longitude is not None:
            loc = {"street": address or f"{latitude:.5f}, {longitude:.5f}", "lat": latitude, "lon": longitude,
                   "city": "Kansas City", "state": "MO", "zip": ""}
            source = "given point"
        elif photo_gps:
            loc = {"street": address, "lat": photo_gps[0], "lon": photo_gps[1],
                   "city": "Kansas City", "state": "MO", "zip": ""}
            source = "photo GPS"
        elif address:
            loc = civicapi.geocode(address)
            source = "geocoded address"
        elif needs_loc:
            return {"ok": False, "error": f"{cat['name']!r} requires a location: pass address, latitude+longitude, "
                    "or a photo with GPS."}

        place = geo.describe(loc["lat"], loc["lon"], source) if loc and add_location_line else None
        if loc and place and not loc["street"]:
            loc["street"] = place["address"].split(",")[0] or f"{loc['lat']:.5f}, {loc['lon']:.5f}"
        if place:
            if "Location: GPS" not in description:
                description = (description.rstrip() + "\n\n" + place["line"]).strip()
            for q in qs:
                if int(q["type"]) == 3 and not encoded.get(q["caption"]) and (fill := geo.answer_for(q["caption"], place)):
                    encoded[q["caption"]] = fill

        dup = {"allow_duplicate": "0", "message": ""}
        if loc and (civicapi.flag(cat, sub, "prevent_duplicate_issue") or "0") != "0":
            dup = civicapi.check_duplicate(cat, sub, loc)
        if dup["allow_duplicate"] == "2":
            return {"ok": False, "duplicate": "blocked", "error": dup["message"]}

        photos = [os.path.expanduser(p) for p in (photo_paths or [])]
        for ph in photos:
            if not os.path.exists(ph):
                return {"ok": False, "error": f"Photo not found: {ph}"}
        contact = None if anonymous else {k: v for k, v in _contact_defaults().items() if v}
        cfg = civicapi.load_config()
        pending_id = cfg["device_uid"][:4] + os.urandom(4).hex()
        _PENDING[pending_id] = {"cat": cat, "sub": sub, "loc": loc, "notes": description, "answers": encoded,
                                "contact": contact, "share": share_options, "photos": photos}
    except civicapi.KeyRejected as exc:
        return _key_error(exc)

    review = {
        "type": cat["name"],
        "sub_type": sub["name"] if sub else "",
        "answers": encoded,
        "description": description,
        "location": loc["street"] if loc else "(none)",
        "coordinates": f"{loc['lat']},{loc['lon']} ({source})" if loc else "(none)",
        "intersection": place["intersection"] if place else None,
        "photos": len(photos),
        "contact": "anonymous" if not contact else " ".join(
            str(contact.get(k, "")) for k in ("first_name", "last_name", "email", "phone")).strip(),
        "visibility": share_options,
        "disclaimer": civicapi.flag(cat, sub, "disclaimer_text") if civicapi.flag(cat, sub, "enable_disclaimer") == "yes" else None,
    }
    if dup["allow_duplicate"] == "1":
        review["duplicate_warning"] = dup["message"]
    return {"ok": True, "pending_id": pending_id, "review": review,
            "action_needed": "Confirm the review with Alex, then submit_311_report(pending_id, confirm=True)."}


@mcp.tool()
def submit_311_report(pending_id: str, confirm: bool = False) -> dict:
    """File the report staged by prepare_311_report. This creates a REAL 311
    case with Kansas City. Requires confirm=True after Alex OKs the review.
    Returns the work order number; track it with my_311_reports.
    """
    if not confirm:
        raise ValueError("Refusing to file: this creates a real city 311 case. Confirm with Alex, then pass confirm=True.")
    st = _PENDING.get(pending_id)
    if not st or "cat" not in st:
        raise ValueError("Unknown or expired pending_id. Call prepare_311_report again.")
    try:
        cfg = civicapi.load_config()
        zip_bytes, meta = civicapi.photo_zip(st["photos"]) if st["photos"] else (None, [])
        issue = civicapi.build_issue(st["cat"], st["sub"], st["loc"], st["notes"], st["answers"],
                                     st["contact"], st["share"], meta, cfg)
        result = civicapi.submit(issue, zip_bytes, cfg)
    except civicapi.KeyRejected as exc:
        return _key_error(exc)
    status = result.get("response_status") or {}
    if status.get("response_code") != 1:
        return {"ok": False, "error": status.get("response_message") or "Submission failed.", "raw": result}
    _PENDING.pop(pending_id, None)
    auto = civicapi.flag(st["cat"], st["sub"], "autoresponse_text")
    return {"ok": True, "work_order": status.get("work_order"), "message": status.get("response_message"),
            "city_says": auto or None, "track_with": "my_311_reports (live, no feed lag)"}


@mcp.tool()
def my_311_reports(start: int = 0) -> dict:
    """Reports filed from this harness or the KC 311 iPhone app (they share a
    device id), with live status straight from the city's app backend.
    """
    try:
        data = civicapi.my_reports(start)
    except civicapi.KeyRejected as exc:
        return _key_error(exc)
    return {"total": data.get("total_record"), "has_more": bool(int(data.get("has_more") or 0)),
            "reports": [{
                "id": r.get("id"),
                "case_number": civicapi.case_number(r) or None,
                "type": r.get("name") or r.get("issue_type"),
                "sub_type": r.get("subcategory") or r.get("sub_type"),
                "status": r.get("status"),
                "address": r.get("address"),
                "description": r.get("description"),
                "added_on": r.get("added_on"),
                "new_updates": r.get("new_update_count"),
            } for r in data.get("my_issues", [])],
            "note": "case_number is null until the report syncs to the city's 311 system."}


@mcp.tool()
def get_311_report_status(issue_id: str) -> dict:
    """Live detail and staff timeline for one report, by its MyCivic id (the
    `id` from my_311_reports). Other people's contact info is removed.
    """
    try:
        d = civicapi.report_detail(issue_id)
    except civicapi.KeyRejected as exc:
        return _key_error(exc)
    timeline = [{"when": h.get("dateofupdate"), "title": h.get("title"), "details": h.get("details")}
                for h in sorted(d.get("history_object") or [], key=lambda h: str(h.get("timestamp", "")))]
    return {"case_number": civicapi.case_number(d) or None, "status": d.get("status"), "type": d.get("type"),
            "sub_type": d.get("subtype"), "address": d.get("address"), "description": d.get("description"),
            "photos": d.get("issue_image") or [], "timeline": timeline,
            "resolution": d.get("issue_resolution") or [], "can_add_note": d.get("citizen_allow_to_send_note") == 1}


@mcp.tool()
def live_311_map(latitude: float | None = None, longitude: float | None = None, status: str = "open",
                 report_types: list[str] | None = None, limit: int = 50) -> list[dict]:
    """Public 311 reports near a point, live from the app backend (no 2-7 day
    lag, unlike nearby_311_requests). status: open, closed or all. Defaults to
    MYKCMO_HOME_LAT/LON. Reporter contact info is never included.
    """
    lat = latitude if latitude is not None else float(os.environ.get("MYKCMO_HOME_LAT", "39.0997"))
    lon = longitude if longitude is not None else float(os.environ.get("MYKCMO_HOME_LON", "-94.5786"))
    types = [civicapi.find_category(t)["name"] for t in report_types] if report_types else None
    try:
        rows = civicapi.public_map(lat, lon, status, types)
    except civicapi.KeyRejected as exc:
        return [_key_error(exc)]
    import math

    def dist(r: dict) -> float:
        dy = (float(r.get("issue_latitude") or 0) - lat) * 111_000
        dx = (float(r.get("issue_longitude") or 0) - lon) * 111_000 * math.cos(math.radians(lat))
        return math.hypot(dx, dy)

    rows.sort(key=dist)
    def case_no(r: dict) -> str | None:
        tp = r.get("thirdparty_params") or {}
        if isinstance(tp, str):
            try:
                tp = json.loads(tp)
            except ValueError:
                return None
        return tp.get("case_number") if isinstance(tp, dict) else None

    return [{"id": r.get("report_id"), "case_number": case_no(r),
             "type": r.get("issue_name"), "sub_type": r.get("subtype"), "status": r.get("issue_status"),
             "address": r.get("issue_address"), "meters": round(dist(r)),
             "submitted": r.get("issue_submitted_date")} for r in rows[:limit]]


@mcp.tool()
def request_311_updates(report_ids: list[str] | None = None, method: str = "Email", confirm: bool = False) -> dict:
    """File a "311 Request Update" for each open report in my_311_reports (or
    only `report_ids`). Without confirm=True it returns the list it would
    send. With confirm=True it files one REAL request per report. method:
    Email or Phone Call; the contact comes from MYKCMO_CONTACT_*.
    """
    try:
        mine = civicapi.my_reports().get("my_issues", [])
    except civicapi.KeyRejected as exc:
        return _key_error(exc)
    closed = ("resolved", "closed", "cancel", "complete")
    targets = [r for r in mine if not any(c in str(r.get("status", "")).lower() for c in closed)
               and (not report_ids or str(r.get("id")) in report_ids)]
    contact = _contact_defaults()
    reach = contact["email"] if method == "Email" else contact["phone"]
    plan = []
    for r in targets:
        cn = civicapi.case_number(r)
        plan.append({"id": r["id"], "case_number": cn,
                     "reference": f"request #{cn}" if cn else f"myKCMO app report {r['id']}",
                     "sub_type": r.get("subcategory") or r.get("sub_type"), "address": r.get("address") or ""})
    if not confirm:
        return {"ok": True, "would_file": plan, "contact": f"{method}: {reach}",
                "action_needed": "Confirm with Alex, then call again with confirm=True."}
    if not reach:
        return {"ok": False, "error": f"No contact for {method}. Set MYKCMO_CONTACT_EMAIL or MYKCMO_CONTACT_PHONE."}
    results = []
    for p in plan:
        answers = {
            "What is your request number?": p["case_number"] or p["reference"],
            "If you do not have your request number, please provide us the location reported.": p["address"],
            "How would you like us to contact you?": method,
            "Please provide us the contact information for your preferred method.": reach,
        }
        staged = prepare_311_report("311 Request Update", description=f"Please send an update on {p['reference']}: "
                                    f"{p['sub_type']} at {p['address']}.", answers=answers, add_location_line=False)
        if not staged.get("ok"):
            results.append({**p, "ok": False, "error": staged.get("error")})
            continue
        sent = submit_311_report(staged["pending_id"], confirm=True)
        results.append({**p, "ok": sent.get("ok"), "work_order": sent.get("work_order"), "error": sent.get("error")})
    return {"ok": all(r["ok"] for r in results), "results": results}


# ---------------------------------------------------------------------------
# KC Streetcar (streetcar.py): not part of 311. Default channel is an email
# to info@kcstreetcar.org (send it with the Gmail tools); the Authority's
# Google Form is the second channel, same prepare -> confirm -> submit flow.
# ---------------------------------------------------------------------------


@mcp.tool()
def prepare_streetcar_report(
    description: str,
    latitude: float | None = None,
    longitude: float | None = None,
    photo_path: str = "",
    stop: str = "",
    car_number: str = "NA",
    when: str = "",
    comment: str = "",
    staff_name: str = "",
    kind: str = "Issue",
) -> dict:
    """Stage a report for the KC Streetcar Authority. Sends NOTHING.

    Returns three channels and a `recommended` pick:
    - `see_say`: a text for 816-837-4800, the See Say line that reaches a
      streetcar dispatcher now (safety, behavior, cleanliness, damage, on
      board or at a stop). Two-way: dispatch can text back.
    - `email`: to/subject/body for info@kcstreetcar.org, the canonical inbox
      (tracker/display problems, service, feedback). Attach the photo.
    - the Google Form (`pending_id`), a second channel with no photos that
      routes to an inbox we cannot see. Location: explicit point, else the photo's
    EXIF GPS, else MYKCMO_HOME_LAT/LON; the nearest stop, address and
    intersection are filled in. `stop` overrides the nearest-stop guess.
    `when` is "YYYY-MM-DD HH:MM" (default now). car_number: 801-814 or NA.
    kind: Tracker/Display, Service Disruption, Safety, Accessibility,
    Station Condition, or Other (goes in the email subject).
    The form requires an email: MYKCMO_CONTACT_EMAIL.

    Next: show the review to Alex and send the recommended channel after he
    confirms. The form only on request: submit_streetcar_report(pending_id, confirm=True).
    """
    contact = _contact_defaults()
    if not contact["email"]:
        return {"ok": False, "error": "The streetcar form requires an email. Set MYKCMO_CONTACT_EMAIL."}
    source = "given point"
    if (latitude is None or longitude is None) and photo_path:
        gps = geo.exif_gps(os.path.expanduser(photo_path))
        if gps:
            latitude, longitude, source = gps[0], gps[1], "photo GPS"
    if latitude is None or longitude is None:
        return {"ok": False, "error": "Pass latitude+longitude or a photo with GPS, so the report names the stop."}
    loc = streetcar.location_text(latitude, longitude, source)
    if stop:
        loc = f"{stop} stop (reported). " + loc
    try:
        at = datetime.strptime(when, "%Y-%m-%d %H:%M") if when else datetime.now()
    except ValueError:
        return {"ok": False, "error": "when must be YYYY-MM-DD HH:MM."}
    fields = streetcar.build(
        email=contact["email"], name=f"{contact['first_name']} {contact['last_name']}".strip(),
        phone=contact["phone"], when=at, location=loc, car=car_number, description=description,
        comment=comment, staff=staff_name,
    )
    pending_id = "sc" + os.urandom(5).hex()
    _PENDING[pending_id] = {"streetcar": fields}
    email = streetcar.email_draft(when=at, location=loc, car=car_number, description=description, kind=kind,
                                  contact=contact, has_photo=bool(photo_path))
    sms = streetcar.sms_draft(location=loc, car=car_number, description=description, kind=kind)
    return {"ok": True, "recommended": streetcar.recommended_channel(kind), "see_say": sms, "email": email,
            "attach": photo_path or None, "see_say_web": streetcar.SEE_SAY_WEB, "pending_id": pending_id, "review": {
        "to": "KC Streetcar Authority (official comment form)", "when": at.strftime("%Y-%m-%d %H:%M"),
        "location": loc, "car": car_number or "NA", "description": description, "comment": comment,
        "contact": f"{contact['first_name']} {contact['last_name']} <{contact['email']}> {contact['phone']}".strip(),
    }}


@mcp.tool()
def submit_streetcar_report(pending_id: str, confirm: bool = False) -> dict:
    """Second channel: post the staged report to the KC Streetcar Google Form.
    The default channel is the email from prepare_streetcar_report. This posts
    a REAL comment. Requires confirm=True after Alex OKs it."""
    if not confirm:
        raise ValueError("Refusing to send: this posts a real comment to KC Streetcar. Confirm with Alex first.")
    st = _PENDING.get(pending_id)
    if not st or "streetcar" not in st:
        raise ValueError("Unknown or expired pending_id. Call prepare_streetcar_report again.")
    result = streetcar.submit(st["streetcar"])
    if result["ok"]:
        _PENDING.pop(pending_id, None)
        return {"ok": True, "message": "Recorded by the KC Streetcar comment form."}
    return {"ok": False, "error": "The form did not confirm the response.", **result,
            "fallback": f"Email {streetcar.EMAIL_FALLBACK} or call {streetcar.PHONE}."}


if __name__ == "__main__":
    mcp.run()
