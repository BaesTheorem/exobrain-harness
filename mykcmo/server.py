"""myKCMO MCP server: Kansas City, MO 311 service requests over stdio.

Two halves:
- READ (data.kcmo.org, Socrata dataset d4px-6rwg): search, track, stats over
  the live myKCMO 311 feed since March 2021.
- WRITE (webrai.mycivicapps.com): file a real 311 request. The city web form
  has a soft anti-spam gate (optional reCAPTCHA v3, else a distorted-text
  image captcha). We take the image path with a human (MIST) reading the
  captcha via vision, so submitting is a three-step, agent-in-the-loop flow:
  get_report_subtypes -> prepare_311_report (returns a captcha image to read)
  -> submit_311_report (with the read answer). See webrai.py and README for
  why this is scoped to Alex's own, human-confirmed, one-at-a-time requests.

INVARIANTS:
- Read tools are read-only against data.kcmo.org.
- All SoQL string literals pass through _soql_str (single quotes doubled).
- Status matching is case-insensitive (the dataset mixes "resolved"/"Resolved").
- report_submit.php is hit only by submit_311_report, only after a human read
  the captcha and the caller passed confirm=True.
"""

import json
import os
import urllib.parse
import urllib.request
from datetime import datetime

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
        "Kansas City, MO 311 service requests (myKCMO) via the city's "
        "open-data portal. Read-only; data lags real time by 2-7 days."
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
def list_report_categories() -> list[str]:
    """List the report types Kansas City accepts (pothole, illegal dumping,
    streetlights, etc.). Pass one of these to get_report_subtypes and
    prepare_311_report.
    """
    return sorted(webrai.REPORT_TYPES)


@mcp.tool()
def get_report_subtypes(report_type: str) -> dict:
    """For a report type (label like "A Pothole" or a raw "10871_x" value),
    return its sub-types, the template kind, whether a location/description is
    required, and any disclaimer text. Only "Standard" template types can be
    auto-filed here; custom "form_type" types need the app/web form.
    """
    info = webrai.fetch_subtypes(report_type)
    info["auto_submittable"] = info["template"].lower() == "standard"
    if not info["auto_submittable"]:
        info["note"] = (
            "This type uses a custom form (template != Standard); file it via "
            "the web form or myKCMO app. report_issue_info() has the links."
        )
    return info


@mcp.tool()
def prepare_311_report(
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

    Next: Read captcha_image_path, then call submit_311_report(pending_id,
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
        "captcha_image_path": img_path,
        "action_needed": (
            "Read captcha_image_path to solve the captcha, confirm the review "
            "with Alex, then call submit_311_report(pending_id, captcha_answer, "
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
def submit_311_report(
    pending_id: str,
    captcha_answer: str,
    confirm: bool = False,
) -> dict:
    """File the report staged by prepare_311_report. This creates a REAL 311
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
    if not state:
        raise ValueError(
            "Unknown or expired pending_id. Call prepare_311_report again."
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
            "captcha_image_path": img_path,
            "message": "Captcha was wrong; read the new image and resubmit.",
        }

    return {
        "ok": False,
        "retry": False,
        "error": result["error"] or "Submission failed.",
        "raw": result["raw"],
    }


if __name__ == "__main__":
    mcp.run()
