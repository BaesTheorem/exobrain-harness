"""myKCMO MCP server: Kansas City, MO 311 service requests over stdio.

Read/track/stats against the city's open-data portal (Socrata SODA API,
dataset d4px-6rwg, the live myKCMO 311 feed since March 2021). Submitting a
new request is NOT automated: the myKCMO web form is gated behind reCAPTCHA
by design, so `report_issue_info` returns the official channels instead.

INVARIANTS:
- Read-only against data.kcmo.org; no tool ever POSTs anywhere.
- All SoQL string literals pass through _soql_str (single quotes doubled).
- Status matching is case-insensitive (the dataset mixes "resolved"/"Resolved").
"""

import json
import os
import urllib.parse
import urllib.request
from datetime import datetime

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
            "Submissions need the web form, app, or a call; they are "
            "captcha-gated so MIST cannot file them directly. Save the case "
            "number from the confirmation: get_311_request tracks it here "
            "once it appears in the open-data feed (2-7 day lag)."
        ),
    }


if __name__ == "__main__":
    mcp.run()
