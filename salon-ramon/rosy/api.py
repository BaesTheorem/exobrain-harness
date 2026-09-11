"""Thin client for Rosy Salon Software's /api/v2.

Shapes worth knowing, all learned from the site's own Backbone code:
- Collections come back HAL-ish: {"_embedded": {"employees": [...]}}. A salon
  with nothing to return omits `_embedded` entirely, so `_items` treats a
  missing key as an empty list rather than a KeyError.
- Appointments carry `cancellationId`; the site's own `isCancelled()` is
  `cancellationId > 0`, NOT a status string. Availability math must use the
  same rule or it will treat cancelled slots as busy forever.
- Times are naive local strings ("2026-09-14 18:00:00" on reads,
  "2026-09-14T18:00:00" on writes) in the salon's timezone.
"""

from __future__ import annotations

import json
from datetime import date, timedelta
import urllib.error
import urllib.parse
import urllib.request

from .config import API, CHROME_UA
from .session import Context


class RosyError(RuntimeError):
    """The API refused a call."""


class Api:
    def __init__(self, ctx: Context, salon_id: int):
        self.ctx = ctx
        self.salon_id = salon_id

    def _request(self, method: str, path: str, params: dict | None = None, body=None):
        url = f"{API}{path}"
        if params:
            url += "?" + urllib.parse.urlencode(params)
        data = json.dumps(body).encode() if body is not None else None
        req = urllib.request.Request(
            url,
            method=method,
            data=data,
            headers={
                "User-Agent": CHROME_UA,
                "Authorization": f"Bearer {self.ctx.token}",
                "accept": "application/json",
                "content-type": "application/json",
                "origin": "https://online.rosysalonsoftware.com",
            },
        )
        try:
            with urllib.request.urlopen(req, timeout=45) as resp:
                raw = resp.read()
                return json.loads(raw) if raw else None
        except urllib.error.HTTPError as exc:
            detail = exc.read().decode("utf-8", "replace")[:500]
            raise RosyError(f"{method} {path} -> HTTP {exc.code}: {detail}") from exc

    @staticmethod
    def _items(payload, key: str) -> list[dict]:
        if not payload:
            return []
        return (payload.get("_embedded") or {}).get(key, [])

    # -- reads -------------------------------------------------------------

    def salon(self) -> dict:
        payload = self._request(
            "GET",
            f"/salons/{self.salon_id}",
            {"includes": "hours,cancellation,creditCardProcessing,scheduling"},
        )
        if not payload:
            raise RosyError("salon lookup came back empty")
        return payload

    def employees(self) -> list[dict]:
        payload = self._request(
            "GET",
            "/employees",
            {
                "salonId": self.salon_id,
                "includes": "schedule,imageUrl,description,performsServices,servicesCount",
                "active": "true",
                "online": "true",
                "renters": "false",
            },
        )
        return self._items(payload, "employees")

    def services(self) -> list[dict]:
        payload = self._request(
            "GET",
            "/services",
            {
                "salonId": self.salon_id,
                "includes": "defaults,serviceGroupName,serviceGroupSortInfo",
                "active": "true",
                "onlyServicesWithProviders": "true",
            },
        )
        return self._items(payload, "services")

    def employee_services(self, service_id: int) -> list[dict]:
        """Per-provider duration, price and process time for one service."""
        payload = self._request(
            "GET",
            "/employeeServices",
            {"salonId": self.salon_id, "includes": "serviceActive", "serviceId": service_id},
        )
        return self._items(payload, "employeeServices")

    def timesheets(self, start: str, end: str) -> list[dict]:
        """Time-off (eventType 0) and extra time-on (eventType 1) blocks."""
        payload = self._request(
            "GET", "/timesheets", {"salonId": self.salon_id, "from": start, "to": end}
        )
        return self._items(payload, "timesheets")

    def appointments_on(self, date: str) -> list[dict]:
        payload = self._request("GET", "/appointments", {"salonId": self.salon_id, "on": date})
        return self._items(payload, "appointments")

    def my_appointments(self, start: str, end: str | None = None) -> list[dict]:
        """This customer's appointments in [start, end).

        `to` is EXCLUSIVE. `from=X&to=X` returns nothing at all, which once made
        a successful booking read back as "nothing booked" -- the one false
        negative that invites a double-booking. Use `my_appointments_on` for a
        single day rather than passing the same date twice.
        """
        params = {"salonId": self.salon_id, "clientId": self.ctx.customer_id, "from": start}
        if end:
            params["to"] = end
        payload = self._request("GET", "/appointments", params)
        return self._items(payload, "appointments")

    def my_appointments_on(self, day: date) -> list[dict]:
        return self.my_appointments(day.isoformat(), (day + timedelta(days=1)).isoformat())

    # -- writes ------------------------------------------------------------

    def create_appointments(self, appointments: list[dict]):
        """POST the booking. The response is NOT proof; callers re-read."""
        return self._request("POST", "/appointments", body=appointments)

    def cancel_appointment(self, appointment_id: int):
        return self._request(
            "DELETE",
            f"/appointments/{appointment_id}",
            body={"customerId": self.ctx.customer_id},
        )
