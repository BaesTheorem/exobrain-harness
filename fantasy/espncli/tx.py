"""The write lane for Alex's ESPN league: lineup moves and waiver claims.

Kept out of client.py on purpose. `Espn` is read-only by invariant, and every
tool built on it (ff, espn) inherits that promise; this module is the one
place that POSTs, and bin/espn-tx is the only command that imports it. Every
write here verifies the RESULT with a read (roster slot changed, claim listed
as pending), never the request's status code alone.

ESPN's transaction endpoint, as the web client uses it (2026-09-07):

    POST {WRITES}/seasons/{season}/segments/0/leagues/{league}/transactions/
    {"isLeagueManager": false, "teamId": T, "type": "ROSTER" | "WAIVER" | "FREEAGENT",
     "memberId": "{SWID}", "scoringPeriodId": W, "executionType": "EXECUTE",
     "items": [{"playerId": P, "type": "LINEUP", "fromLineupSlotId": a, "toLineupSlotId": b}
               | {"playerId": P, "type": "ADD", "fromTeamId": 0, "toTeamId": T, "toLineupSlotId": 20}
               | {"playerId": P, "type": "DROP", "fromTeamId": T, "toTeamId": 0}]}
"""

from __future__ import annotations

import json
import urllib.error
import urllib.request
from typing import Any

from .client import BENCH, IR, SLOT, SLOT_BY_NAME, UA, Espn, EspnError

WRITES = "https://lm-api-writes.fantasy.espn.com/apis/v3/games/ffl"
FALLBACK = "https://fantasy.espn.com/apis/v3/games/ffl"


class EspnWriter:
    def __init__(self, api: Espn | None = None):
        self.api = api or Espn()
        self.team_id = int(self.api.creds["team_id"])

    def _post(self, body: dict[str, Any]) -> Any:
        last: Exception | None = None
        for base in (WRITES, FALLBACK):
            url = (f"{base}/seasons/{self.api.season}/segments/0/leagues/"
                   f"{self.api.league_id}/transactions/")
            h = {"User-Agent": UA, "Accept": "application/json",
                 "Content-Type": "application/json",
                 "Origin": "https://fantasy.espn.com",
                 "Referer": "https://fantasy.espn.com/",
                 "X-Fantasy-Source": "kona",
                 "X-Fantasy-Platform": "kona-PROD"}
            h.update(self.api._auth())  # noqa: SLF001 -- same cookies as every read; the writer is the client's one sibling
            req = urllib.request.Request(url, data=json.dumps(body).encode(), headers=h, method="POST")
            try:
                with urllib.request.urlopen(req, timeout=60) as r:
                    raw = r.read()
                    return json.loads(raw) if raw else {}
            except urllib.error.HTTPError as e:
                text = e.read()[:600].decode(errors="replace")
                last = EspnError(f"ESPN HTTP {e.code} on {base.split('//')[1].split('/')[0]}: {text}")
                if e.code in (404, 405):
                    continue
                raise last from None
        raise last or EspnError("no write host answered")

    def _base(self, kind: str) -> dict[str, Any]:
        settings = self.api.league("mSettings")
        return {"isLeagueManager": False, "teamId": self.team_id, "type": kind,
                "memberId": self.api.creds["SWID"],
                "scoringPeriodId": settings.get("scoringPeriodId", 1),
                "executionType": "EXECUTE", "items": []}

    # ---- lineup ----------------------------------------------------------

    def slot_of(self, player_id: int) -> int | None:
        data = self.api.league("mRoster")
        for e in self.api.roster_entries(data, self.team_id):
            if e["playerId"] == player_id:
                return e["lineupSlotId"]
        return None

    def move(self, player_id: int, to_slot: int, dry_run: bool = False) -> dict[str, Any]:
        frm = self.slot_of(player_id)
        if frm is None:
            raise EspnError("that player is not on the roster")
        body = self._base("ROSTER")
        body["items"] = [{"playerId": player_id, "type": "LINEUP",
                          "fromLineupSlotId": frm, "toLineupSlotId": to_slot}]
        if dry_run:
            return {"dry_run": body}
        resp = self._post(body)
        now = self.slot_of(player_id)
        return {"from": SLOT.get(frm, frm), "to": SLOT.get(to_slot, to_slot),
                "verified": now == to_slot, "now": SLOT.get(now, now), "response": resp}

    def swap(self, in_id: int, out_id: int, dry_run: bool = False) -> dict[str, Any]:
        """Bench player in, starter out, in ONE transaction.

        ESPN validates the roster after the whole transaction, so the two
        LINEUP items have to travel together: a lone "bench to WR" is rejected
        while the slot is occupied, and a lone "WR to bench" leaves the slot
        empty if the second call fails.
        """
        out_slot, in_slot = self.slot_of(out_id), self.slot_of(in_id)
        if out_slot is None or in_slot is None:
            raise EspnError("both players must be on the roster")
        if in_slot != BENCH:
            raise EspnError("the incoming player must be on the bench")
        body = self._base("ROSTER")
        body["items"] = [
            {"playerId": out_id, "type": "LINEUP", "fromLineupSlotId": out_slot, "toLineupSlotId": BENCH},
            {"playerId": in_id, "type": "LINEUP", "fromLineupSlotId": BENCH, "toLineupSlotId": out_slot},
        ]
        if dry_run:
            return {"dry_run": body}
        resp = self._post(body)
        now_in, now_out = self.slot_of(in_id), self.slot_of(out_id)
        return {"slot": SLOT.get(out_slot, out_slot), "verified": now_in == out_slot and now_out == BENCH,
                "in_now": SLOT.get(now_in, now_in), "out_now": SLOT.get(now_out, now_out), "response": resp}

    # ---- adds and claims -------------------------------------------------

    def claim(self, player_id: int, drop_id: int | None = None, waiver: bool = True,
              dry_run: bool = False) -> dict[str, Any]:
        body = self._base("WAIVER" if waiver else "FREEAGENT")
        body["items"] = [{"playerId": player_id, "type": "ADD", "fromTeamId": 0,
                          "toTeamId": self.team_id, "toLineupSlotId": BENCH}]
        if drop_id:
            body["items"].append({"playerId": drop_id, "type": "DROP",
                                  "fromTeamId": self.team_id, "toTeamId": 0})
        if dry_run:
            return {"dry_run": body}
        resp = self._post(body)
        pend = self.pending()
        listed = any(any(i.get("playerId") == player_id for i in p.get("items", [])) for p in pend)
        return {"verified": listed if waiver else self.slot_of(player_id) is not None,
                "pending_count": len(pend), "response": resp}

    def pending(self) -> list[dict[str, Any]]:
        data = self.api.league("mPendingTransactions")
        return [t for t in data.get("pendingTransactions", []) or []
                if t.get("teamId") == self.team_id]

    def cancel(self, transaction_id: str) -> Any:
        body = {"isLeagueManager": False, "teamId": self.team_id, "type": "WAIVER",
                "memberId": self.api.creds["SWID"], "executionType": "CANCEL",
                "id": transaction_id, "items": []}
        return self._post(body)


__all__ = ["EspnWriter", "BENCH", "IR", "SLOT_BY_NAME"]
