"""GraphQL client for meetup.com, via the web app's own endpoint (www.meetup.com/gql2).

Meetup's documented API (api.meetup.com/gql-ext) is OAuth-only, and the OAuth consumer keys
behind it are handed out on paid plans. The website itself talks to a second, much richer
GraphQL endpoint that answers anonymous requests for search, events, groups, and locations,
and reads the browser's session cookie for anything personal. This client speaks to that
endpoint. It is unofficial and Meetup can change it whenever it likes. Field names come from
the endpoint's own introspection (September 2026); every read below was verified live.

INVARIANTS:
- ``eventSearch`` with an empty ``query`` returns nothing. Keyword-less browsing goes through
  ``recommendedEvents``, which is what the site's own "find events" page uses.
- ``eventSearch.totalCount`` is offset + rows returned so far and says nothing about the
  result-set size. The only end-of-results signal is ``pageInfo.hasNextPage``. ``first`` is approximate (the server pads
  a few extra rows), so ``_pages`` truncates to the caller's limit.
- ``radius`` is in miles. Date filters are ISO-8601 with an explicit UTC offset, and
  ``Event.dateTime`` comes back in the event's own local offset, so it prints correctly with
  no timezone lookup.
- A rejected cookie does not raise: ``self`` is simply ``null``. Treat that as auth failure.
"""

from __future__ import annotations

import json
import urllib.error
import urllib.request
from typing import Any, Callable

Json = dict[str, Any]
Transport = Callable[[str, str, bytes | None, dict[str, str]], tuple[int, bytes]]

GQL_URL = "https://www.meetup.com/gql2"
SITE = "https://www.meetup.com"
# gql2 accepts any User-Agent (checked: python-urllib's default gets a 200), so say who we are.
UA = "meetup-cli/1.0 (+https://github.com/BaesTheorem/exobrain-harness)"
PAGE_SIZE = 50
MAX_RESULTS = 500  # what ``limit=0`` (everything) actually means, so a bad query cannot run away

# -- fragments -------------------------------------------------------------------------------

EVENT_CORE = """
fragment EventCore on Event {
  id title dateTime endTime duration eventType eventUrl status rsvpState maxTickets isOnline
  isFeatured isAttending isSaved
  feeSettings { amount currency required accepts }
  venue { id name address city state postalCode country lat lon venueType }
  group { id name urlname city state timezone }
  going: rsvps(filter: { rsvpStatus: [YES] }) { totalCount }
}
"""

EVENT_DETAIL = """
fragment EventDetail on Event {
  ...EventCore
  description howToFindUs createdTime guestsAllowed numberOfAllowedGuests waitlistMode shortUrl
  eventHosts { name memberId }
  waitlist: rsvps(filter: { rsvpStatus: [WAITLIST] }) { totalCount }
  series {
    id description
    weeklyRecurrence { weeklyDaysOfWeek weeklyInterval }
    monthlyRecurrence { monthlyDayOfWeek monthlyWeekOfMonth }
  }
  topics { edges { node { name urlkey } } }
}
""" + EVENT_CORE

GROUP_CORE = """
fragment GroupCore on Group {
  id name urlname city state country timezone link isPrivate privacy joinMode status foundedDate
  isMember
  memberships { totalCount }
  stats { eventRatings { average totalRatings } }
  topicCategory { name }
}
"""

GROUP_DETAIL = """
fragment GroupDetail on Group {
  ...GroupCore
  description lat lon zip
  activeTopics { name urlkey }
  organizer { name }
}
""" + GROUP_CORE

# -- operations ------------------------------------------------------------------------------

Q_EVENT_SEARCH = EVENT_CORE + """
query EventSearch($filter: EventSearchFilter!, $sort: KeywordSort, $first: Int, $after: String) {
  eventSearch(filter: $filter, sort: $sort, first: $first, after: $after) {
    pageInfo { hasNextPage endCursor }
    edges { node { ...EventCore } }
  }
}
"""

Q_RECOMMENDED = EVENT_CORE + """
query Recommended($filter: RecommendedEventsFilter!, $sort: RecommendedEventsSort, $first: Int, $after: String) {
  recommendedEvents(filter: $filter, sort: $sort, first: $first, after: $after) {
    pageInfo { hasNextPage endCursor }
    edges { node { ...EventCore } }
  }
}
"""

Q_EVENTS = EVENT_DETAIL + """
query Events($ids: [ID]) { events(where: { ids: $ids }) { ...EventDetail } }
"""

Q_GROUP = GROUP_DETAIL + EVENT_CORE + """
query Group($urlname: String!, $first: Int) {
  groupByUrlname(urlname: $urlname) {
    ...GroupDetail
    upcoming: events(status: ACTIVE, first: $first, sort: ASC) {
      totalCount
      edges { node { ...EventCore } }
    }
    past: events(status: PAST, first: 1, sort: DESC) {
      totalCount
      edges { node { id title dateTime } }
    }
  }
}
"""

Q_GROUP_EVENTS = EVENT_CORE + """
query GroupEvents($urlname: String!, $status: EventStatus, $sort: SortOrder, $first: Int, $after: String) {
  groupByUrlname(urlname: $urlname) {
    events(status: $status, sort: $sort, first: $first, after: $after) {
      pageInfo { hasNextPage endCursor }
      edges { node { ...EventCore } }
    }
  }
}
"""

Q_GROUP_SEARCH = GROUP_CORE + """
query GroupSearch($filter: GroupSearchFilter!, $first: Int, $after: String) {
  groupSearch(filter: $filter, first: $first, after: $after) {
    pageInfo { hasNextPage endCursor }
    edges { node { ...GroupCore } }
  }
}
"""

Q_SIMILAR = EVENT_CORE + """
query Similar($eventId: ID!, $first: Int) {
  similarEvents(eventId: $eventId, first: $first) { edges { node { ...EventCore } } }
}
"""

Q_LOCATIONS = """
query Locations($query: String!) {
  locationSearch(query: $query) { name city state country zip lat lon timeZone }
}
"""

Q_SELF = """
query Self {
  self { id name email city state memberUrl isOrganizer isProOrganizer organizedGroupCount }
}
"""

Q_MY_EVENTS = EVENT_CORE + """
query MyEvents($first: Int!, $after: String, $status: [EventStatus]) {
  self {
    memberEvents(first: $first, after: $after, eventStatus: $status,
                 sort: { sortField: LOCAL_TIME, sortOrder: ASC }) {
      pageInfo { hasNextPage endCursor }
      edges { rsvpState node { ...EventCore } }
    }
  }
}
"""

Q_MY_GROUPS = GROUP_CORE + """
query MyGroups($first: Int, $after: String) {
  self {
    memberships(first: $first, after: $after) {
      pageInfo { hasNextPage endCursor }
      edges { metadata { role status } node { ...GroupCore } }
    }
  }
}
"""

M_RSVP = """
mutation Rsvp($input: RsvpInput!) {
  rsvp(input: $input) { errors { code field message } rsvp { id status guestsCount } }
}
"""

M_SAVE = """
mutation Save($input: SaveEventInput!) {
  saveEvent(input: $input) { errors { code field message } event { id isSaved } }
}
"""

M_UNSAVE = """
mutation Unsave($input: UnsaveEventInput!) {
  unsaveEvent(input: $input) { errors { code field message } event { id isSaved } }
}
"""


def _clean(params: Json) -> Json:
    return {k: v for k, v in params.items() if v is not None}


class MeetupError(Exception):
    """A GraphQL error, a transport failure, or a missing login."""

    def __init__(
        self,
        message: str,
        *,
        errors: list[Json] | None = None,
        http_status: int | None = None,
        auth: bool = False,
    ):
        self.message = message
        self.errors = errors or []
        self.http_status = http_status
        self.auth = auth
        super().__init__(message)

    def __str__(self) -> str:
        return self.message


class MeetupClient:
    def __init__(
        self,
        cookie: str | None = None,
        timeout: float = 30.0,
        transport: Transport | None = None,
        page_size: int = PAGE_SIZE,
    ):
        self.cookie = cookie
        self.timeout = timeout
        self.page_size = page_size
        self._transport: Transport = transport or self._urllib_transport
        self.last_errors: list[Json] = []

    # -- transport ---------------------------------------------------------------------------

    def _urllib_transport(self, method: str, url: str, body: bytes | None, headers: dict[str, str]) -> tuple[int, bytes]:
        req = urllib.request.Request(url, data=body, method=method, headers=headers)
        try:
            with urllib.request.urlopen(req, timeout=self.timeout) as resp:
                return resp.status, resp.read()
        except urllib.error.HTTPError as e:
            return e.code, e.read()
        except (urllib.error.URLError, TimeoutError, OSError) as e:
            raise MeetupError(f"{method} {url}: {e}") from e

    def gql(self, query: str, variables: Json | None = None, *, authed: bool = False) -> Json:
        """Run one operation and return its ``data``. Raises MeetupError on any error."""
        if authed and not self.cookie:
            raise MeetupError(
                "this command needs a Meetup login: run `meetup auth set` with your browser's "
                "cookie header (see meetup/secrets/README.md)",
                auth=True,
            )
        headers = {
            "Content-Type": "application/json",
            "Accept": "application/json",
            "User-Agent": UA,
            "Origin": SITE,
            "Referer": SITE + "/",
        }
        if self.cookie:
            headers["Cookie"] = self.cookie
        body = json.dumps({"query": query, "variables": variables or {}}).encode()
        status, raw = self._transport("POST", GQL_URL, body, headers)
        try:
            payload = json.loads(raw)
        except ValueError:
            snippet = raw[:200].decode("utf-8", "replace").strip()
            raise MeetupError(f"HTTP {status}: non-JSON response: {snippet}", http_status=status) from None
        if status >= 400:
            raise MeetupError(f"HTTP {status}: {json.dumps(payload)[:300]}", http_status=status)
        errors = payload.get("errors") or []
        data = payload.get("data")
        if errors and not data:
            raise MeetupError("; ".join(str(e.get("message", e)) for e in errors), errors=errors)
        # Partial data with errors is normal on private fields (a private group's member list,
        # say); keep the data and let the caller inspect last_errors if it cares.
        self.last_errors = errors
        data = data or {}
        if authed and "self" in data and data["self"] is None:
            raise MeetupError(
                "Meetup did not accept the login cookie (`self` came back null); "
                "re-copy it from the browser with `meetup auth set`",
                auth=True,
            )
        return data

    def _pages(self, query: str, variables: Json, path: tuple[str, ...], limit: int, *, authed: bool = False) -> list[Json]:
        """Walk a Relay-style connection at ``path`` until ``limit`` edges or the last page."""
        cap = limit if limit > 0 else MAX_RESULTS
        edges_out: list[Json] = []
        after: str | None = None
        while len(edges_out) < cap:
            want = min(self.page_size, cap - len(edges_out))
            data = self.gql(query, {**variables, "first": want, "after": after}, authed=authed)
            conn: Any = data
            for key in path:
                conn = (conn or {}).get(key)
            if not conn:
                break
            edges = conn.get("edges") or []
            edges_out.extend(edges)
            info = conn.get("pageInfo") or {}
            if not edges or not info.get("hasNextPage") or not info.get("endCursor"):
                break
            after = info["endCursor"]
        return edges_out[:cap]

    @staticmethod
    def _nodes(edges: list[Json]) -> list[Json]:
        return [e["node"] for e in edges if e.get("node")]

    # -- reads (no login needed) -------------------------------------------------------------

    def location_search(self, query: str) -> list[Json]:
        return [loc for loc in self.gql(Q_LOCATIONS, {"query": query}).get("locationSearch") or [] if loc]

    def event_search(
        self,
        query: str,
        lat: float,
        lon: float,
        *,
        radius: float | None = None,
        start: str | None = None,
        end: str | None = None,
        event_type: str | None = None,
        sort: str = "RELEVANCE",
        limit: int = 20,
    ) -> list[Json]:
        if not query.strip():
            raise MeetupError("eventSearch needs a keyword; use recommended_events() to browse")
        flt = _clean({
            "query": query,
            "lat": lat,
            "lon": lon,
            "radius": radius,
            "startDateRange": start,
            "endDateRange": end,
            "eventType": event_type,
        })
        variables = {"filter": flt, "sort": {"sortField": sort}}
        return self._nodes(self._pages(Q_EVENT_SEARCH, variables, ("eventSearch",), limit))

    def recommended_events(
        self,
        lat: float,
        lon: float,
        *,
        radius: float | None = None,
        start: str | None = None,
        end: str | None = None,
        event_type: str | None = None,
        sort: str = "DATETIME",
        limit: int = 20,
    ) -> list[Json]:
        flt = _clean({
            "lat": lat,
            "lon": lon,
            "radius": radius,
            "startDateRange": start,
            "endDateRange": end,
            "eventType": event_type,
        })
        variables = {"filter": flt, "sort": {"sortField": sort}}
        return self._nodes(self._pages(Q_RECOMMENDED, variables, ("recommendedEvents",), limit))

    def events(self, ids: list[str]) -> list[Json]:
        if not ids:
            return []
        return [e for e in self.gql(Q_EVENTS, {"ids": ids}).get("events") or [] if e]

    def event(self, event_id: str) -> Json | None:
        found = self.events([event_id])
        return found[0] if found else None

    def group(self, urlname: str, upcoming: int = 5) -> Json | None:
        return self.gql(Q_GROUP, {"urlname": urlname, "first": upcoming}).get("groupByUrlname")

    def group_events(self, urlname: str, *, past: bool = False, limit: int = 20) -> list[Json]:
        variables = {"urlname": urlname, "status": "PAST" if past else "ACTIVE", "sort": "DESC" if past else "ASC"}
        return self._nodes(self._pages(Q_GROUP_EVENTS, variables, ("groupByUrlname", "events"), limit))

    def group_search(self, query: str, lat: float, lon: float, *, radius: float | None = None, limit: int = 20) -> list[Json]:
        flt = _clean({"query": query, "lat": lat, "lon": lon, "radius": radius})
        return self._nodes(self._pages(Q_GROUP_SEARCH, {"filter": flt}, ("groupSearch",), limit))

    def similar_events(self, event_id: str, limit: int = 10) -> list[Json]:
        conn = self.gql(Q_SIMILAR, {"eventId": event_id, "first": limit}).get("similarEvents") or {}
        return self._nodes(conn.get("edges") or [])[:limit]

    # -- personal (cookie required) ----------------------------------------------------------

    def self_member(self) -> Json:
        """The logged-in member. Raises MeetupError(auth=True) when the cookie is rejected."""
        return self.gql(Q_SELF, authed=True).get("self") or {}

    def my_events(self, *, past: bool = False, limit: int = 20) -> list[Json]:
        variables = {"status": ["PAST"] if past else ["ACTIVE"]}
        out = []
        for edge in self._pages(Q_MY_EVENTS, variables, ("self", "memberEvents"), limit, authed=True):
            node = edge.get("node")
            if node:
                node["myRsvp"] = edge.get("rsvpState")
                out.append(node)
        return out

    def my_groups(self, *, limit: int = 50) -> list[Json]:
        out = []
        for edge in self._pages(Q_MY_GROUPS, {}, ("self", "memberships"), limit, authed=True):
            node = edge.get("node")
            if node:
                meta = edge.get("metadata") or {}
                node["myRole"] = meta.get("role")
                node["myStatus"] = meta.get("status")
                out.append(node)
        return out

    def _mutate(self, mutation: str, key: str, variables: Json) -> Json:
        result = self.gql(mutation, variables, authed=True).get(key) or {}
        errs = result.get("errors") or []
        if errs:
            raise MeetupError("; ".join(f"{e.get('field') or key}: {e.get('message')}" for e in errs), errors=errs)
        return result

    def rsvp(self, event_id: str, going: bool, guests: int = 0) -> Json:
        payload = _clean({"eventId": event_id, "response": "YES" if going else "NO", "guestsCount": guests or None})
        return self._mutate(M_RSVP, "rsvp", {"input": payload})

    def save_event(self, event_id: str, save: bool = True) -> Json:
        if save:
            return self._mutate(M_SAVE, "saveEvent", {"input": {"eventId": event_id}})
        return self._mutate(M_UNSAVE, "unsaveEvent", {"input": {"eventId": event_id}})
