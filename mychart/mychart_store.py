"""mychart store: the local archive of every account, and change detection.

One SQLite file (data_dir()/mychart.db). Every sync writes a snapshot per
capability. Payloads are content-addressed, zlib-compressed blobs, so an
unchanged category costs one row. Extractors turn the standard objects into
items (one lab result, one message, one statement), and the item table is
what change detection, the digest, and search read.

INVARIANTS:
- A capability that failed in a sync never marks items gone. Only a
  successful read can say something disappeared.
- The first successful read of a capability for an account is a baseline:
  its items are recorded as new but never notified.
- The raw envelope is stored only when the standard object changed (or on
  the first snapshot), minus the antiforgery-token page fetches. Tokens
  change on every request, so storing every envelope would grow without
  limit while saying nothing new.
- "Changed" ignores fields that MyChart re-mints on every read (VOLATILE_KEY:
  tokens, signed content links, photo blob names, query keys). They differed
  between two syncs three minutes apart on a real account (2026-10-19).
- Nothing here talks to the network.
"""

from __future__ import annotations

import hashlib
import json
import re
import sqlite3
import time
import zlib
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any, Callable, Iterable

SCHEMA = """
CREATE TABLE IF NOT EXISTS blobs (
    sha TEXT PRIMARY KEY,
    data BLOB NOT NULL
);
CREATE TABLE IF NOT EXISTS syncs (
    id INTEGER PRIMARY KEY,
    account TEXT NOT NULL,
    started_at TEXT NOT NULL,
    finished_at TEXT,
    ok INTEGER,
    login_method TEXT,
    error TEXT,
    actions INTEGER DEFAULT 0,
    failures INTEGER DEFAULT 0
);
CREATE TABLE IF NOT EXISTS snapshots (
    id INTEGER PRIMARY KEY,
    sync_id INTEGER,
    account TEXT NOT NULL,
    capability TEXT NOT NULL,
    args TEXT NOT NULL DEFAULT '{}',
    fetched_at TEXT NOT NULL,
    ok INTEGER NOT NULL,
    error TEXT,
    standard_sha TEXT,
    envelope_sha TEXT,
    stable_sha TEXT
);
CREATE INDEX IF NOT EXISTS snapshots_by_cap ON snapshots(account, capability, args, fetched_at);
CREATE TABLE IF NOT EXISTS items (
    account TEXT NOT NULL,
    kind TEXT NOT NULL,
    key TEXT NOT NULL,
    first_seen TEXT NOT NULL,
    last_seen TEXT NOT NULL,
    gone_at TEXT,
    fingerprint TEXT,
    when_iso TEXT,
    summary TEXT,
    data TEXT,
    PRIMARY KEY (account, kind, key)
);
CREATE TABLE IF NOT EXISTS changes (
    id INTEGER PRIMARY KEY,
    sync_id INTEGER,
    account TEXT NOT NULL,
    kind TEXT NOT NULL,
    key TEXT NOT NULL,
    change TEXT NOT NULL,
    at TEXT NOT NULL,
    summary TEXT,
    notify INTEGER NOT NULL DEFAULT 0,
    notified_at TEXT
);
CREATE INDEX IF NOT EXISTS changes_by_time ON changes(at);
CREATE TABLE IF NOT EXISTS lab_values (
    account TEXT NOT NULL,
    result_key TEXT NOT NULL,
    test TEXT,
    component TEXT NOT NULL,
    component_id TEXT NOT NULL,
    value TEXT,
    numeric REAL,
    units TEXT,
    ref_low REAL,
    ref_high REAL,
    ref_text TEXT,
    abnormal INTEGER,
    status TEXT,
    resulted TEXT NOT NULL DEFAULT '',
    collected TEXT,
    collected_display TEXT,
    lab TEXT,
    PRIMARY KEY (account, result_key, component_id, resulted)
);
CREATE TABLE IF NOT EXISTS vital_readings (
    account TEXT NOT NULL,
    name TEXT NOT NULL,
    taken_at TEXT NOT NULL,
    value TEXT,
    numeric REAL,
    units TEXT,
    abnormal INTEGER,
    PRIMARY KEY (account, name, taken_at)
);
CREATE VIEW IF NOT EXISTS lab_values_merged AS
    SELECT lower(component) AS component_key,
           min(component) AS component,
           value, units,
           substr(coalesce(nullif(collected, ''), resulted), 1, 10) AS day,
           group_concat(DISTINCT account) AS accounts,
           count(*) AS copies,
           max(abnormal) AS abnormal,
           min(ref_text) AS ref_text,
           min(test) AS test,
           group_concat(DISTINCT lab) AS labs
    FROM lab_values
    GROUP BY lower(component), value, units, substr(coalesce(nullif(collected, ''), resulted), 1, 10);
"""


def now_iso() -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%S%z")


def canonical(obj: Any) -> str:
    return json.dumps(obj, sort_keys=True, separators=(",", ":"), default=str)


def sha(text: str) -> str:
    return hashlib.sha256(text.encode()).hexdigest()


class Store:
    def __init__(self, path: Path):
        self.path = path
        path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
        self.db = sqlite3.connect(str(path))
        self.db.row_factory = sqlite3.Row
        self.db.execute("PRAGMA journal_mode=WAL")
        self.db.execute("PRAGMA foreign_keys=ON")
        self.db.executescript(SCHEMA)
        columns = {row[1] for row in self.db.execute("PRAGMA table_info(snapshots)")}
        if "stable_sha" not in columns:
            self.db.execute("ALTER TABLE snapshots ADD COLUMN stable_sha TEXT")
        path.chmod(0o600)

    def close(self) -> None:
        self.db.close()

    # ── blobs ──

    def put_blob(self, obj: Any) -> str:
        text = canonical(obj)
        digest = sha(text)
        self.db.execute(
            "INSERT OR IGNORE INTO blobs(sha, data) VALUES (?, ?)",
            (digest, zlib.compress(text.encode(), 6)),
        )
        return digest

    def get_blob(self, digest: str | None) -> Any:
        if not digest:
            return None
        row = self.db.execute("SELECT data FROM blobs WHERE sha = ?", (digest,)).fetchone()
        return json.loads(zlib.decompress(row["data"])) if row else None

    # ── syncs and snapshots ──

    def start_sync(self, account: str) -> int:
        cur = self.db.execute("INSERT INTO syncs(account, started_at) VALUES (?, ?)", (account, now_iso()))
        self.db.commit()
        return int(cur.lastrowid or 0)

    def finish_sync(self, sync_id: int, *, ok: bool, login_method: str | None, error: str | None,
                    actions: int, failures: int) -> None:
        self.db.execute(
            "UPDATE syncs SET finished_at=?, ok=?, login_method=?, error=?, actions=?, failures=? WHERE id=?",
            (now_iso(), int(ok), login_method, error, actions, failures, sync_id),
        )
        self.db.commit()

    def last_ok_snapshot(self, account: str, capability: str, args: str = "{}") -> sqlite3.Row | None:
        return self.db.execute(
            "SELECT * FROM snapshots WHERE account=? AND capability=? AND args=? AND ok=1 "
            "ORDER BY fetched_at DESC, id DESC LIMIT 1",
            (account, capability, args),
        ).fetchone()

    def record_snapshot(self, sync_id: int | None, account: str, action: dict[str, Any]) -> dict[str, Any]:
        """Store one bridge action result. Returns what changed."""
        capability = action.get("id", "?")
        args = canonical(action.get("args") or {})
        fetched = now_iso()
        if not action.get("ok"):
            error = action.get("error") or {}
            self.db.execute(
                "INSERT INTO snapshots(sync_id, account, capability, args, fetched_at, ok, error) "
                "VALUES (?, ?, ?, ?, ?, 0, ?)",
                (sync_id, account, capability, args, fetched, f"{error.get('name')}: {error.get('message')}"),
            )
            return {"capability": capability, "ok": False, "changes": []}

        previous = self.last_ok_snapshot(account, capability, args)
        standard = action.get("standard")
        stable_sha = sha(canonical(stable_view(standard)))
        previous_stable = None
        if previous is not None:
            previous_stable = previous["stable_sha"] or sha(canonical(stable_view(self.get_blob(previous["standard_sha"]))))
        changed = previous is None or previous_stable != stable_sha
        # An unchanged read points at the stored copy; only fresh tokens differ.
        standard_sha = previous["standard_sha"] if previous is not None and not changed else self.put_blob(standard)
        envelope_sha = None
        if action.get("envelope") is not None and changed:
            envelope_sha = self.put_blob(strip_token_fetches(action["envelope"]))
        self.db.execute(
            "INSERT INTO snapshots(sync_id, account, capability, args, fetched_at, ok, standard_sha, envelope_sha, "
            "stable_sha) VALUES (?, ?, ?, ?, ?, 1, ?, ?, ?)",
            (sync_id, account, capability, args, fetched, standard_sha, envelope_sha, stable_sha),
        )
        baseline = previous is None
        changes: list[dict[str, Any]] = []
        extractor = EXTRACTORS.get(capability) if args == "{}" else None
        if args == "{}" and capability == "get_lab_results":
            self._store_lab_values(account, standard)
        if args == "{}" and capability == "get_vitals":
            self._store_vitals(account, standard)
        if extractor is not None:
            items = list(extractor(standard))
            changes = self._merge_items(sync_id, account, capability, items, baseline=baseline, at=fetched)
        elif not baseline and changed and args == "{}":
            changes = [self._change(sync_id, account, capability, "*", "changed", fetched,
                                    f"{TITLES.get(capability, capability)} changed", notify=False)]
        return {"capability": capability, "ok": True, "baseline": baseline, "changes": changes}

    def _change(self, sync_id: int | None, account: str, kind: str, key: str, change: str, at: str,
                summary: str, *, notify: bool) -> dict[str, Any]:
        self.db.execute(
            "INSERT INTO changes(sync_id, account, kind, key, change, at, summary, notify) VALUES (?,?,?,?,?,?,?,?)",
            (sync_id, account, kind, key, change, at, summary, int(notify)),
        )
        return {"account": account, "kind": kind, "key": key, "change": change, "summary": summary,
                "notify": notify}

    def _merge_items(self, sync_id: int | None, account: str, capability: str, items: list[Item], *,
                     baseline: bool, at: str) -> list[dict[str, Any]]:
        changes: list[dict[str, Any]] = []
        seen: dict[str, set[str]] = {}
        for item in items:
            seen.setdefault(item.kind, set()).add(item.key)
            row = self.db.execute(
                "SELECT fingerprint, gone_at FROM items WHERE account=? AND kind=? AND key=?",
                (account, item.kind, item.key),
            ).fetchone()
            data = canonical(item.data)
            if row is None:
                self.db.execute(
                    "INSERT INTO items(account, kind, key, first_seen, last_seen, fingerprint, when_iso, summary, data) "
                    "VALUES (?,?,?,?,?,?,?,?,?)",
                    (account, item.kind, item.key, at, at, item.fingerprint, item.when, item.summary, data),
                )
                changes.append(self._change(sync_id, account, item.kind, item.key, "new", at, item.summary,
                                            notify=item.notify and not baseline))
                continue
            changed = row["fingerprint"] != item.fingerprint
            returned = row["gone_at"] is not None
            self.db.execute(
                "UPDATE items SET last_seen=?, gone_at=NULL, fingerprint=?, when_iso=?, summary=?, data=? "
                "WHERE account=? AND kind=? AND key=?",
                (at, item.fingerprint, item.when, item.summary, data, account, item.kind, item.key),
            )
            if changed or returned:
                changes.append(self._change(sync_id, account, item.kind, item.key, "changed", at, item.summary,
                                            notify=item.notify_on_change and not baseline))
        for kind in KINDS_BY_CAPABILITY.get(capability, ()):
            if kind not in GONE_MATTERS:
                continue
            present = seen.get(kind, set())
            for row in self.db.execute(
                "SELECT key, summary FROM items WHERE account=? AND kind=? AND gone_at IS NULL",
                (account, kind),
            ).fetchall():
                if row["key"] in present:
                    continue
                self.db.execute(
                    "UPDATE items SET gone_at=? WHERE account=? AND kind=? AND key=?",
                    (at, account, kind, row["key"]),
                )
                changes.append(self._change(sync_id, account, kind, row["key"], "gone", at,
                                            f"no longer listed: {row['summary']}",
                                            notify=GONE_MATTERS[kind] and not baseline))
        return changes

    def _store_lab_values(self, account: str, standard: Any) -> None:
        for row in lab_value_rows(standard):
            self.db.execute(
                "INSERT OR REPLACE INTO lab_values(account, result_key, test, component, component_id, value, "
                "numeric, units, ref_low, ref_high, ref_text, abnormal, status, resulted, collected, "
                "collected_display, lab) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                (account, *row),
            )

    def _store_vitals(self, account: str, standard: Any) -> None:
        for name, taken, value, numeric, units, abnormal in vital_rows(standard):
            self.db.execute(
                "INSERT OR REPLACE INTO vital_readings(account, name, taken_at, value, numeric, units, abnormal) "
                "VALUES (?,?,?,?,?,?,?)",
                (account, name, taken, value, numeric, units, abnormal),
            )

    def commit(self) -> None:
        self.db.commit()

    # ── reads ──

    def latest(self, account: str, capability: str, args: dict[str, Any] | None = None) -> dict[str, Any] | None:
        row = self.last_ok_snapshot(account, capability, canonical(args or {}))
        if row is None:
            return None
        return {"fetched_at": row["fetched_at"], "standard": self.get_blob(row["standard_sha"])}

    def latest_envelope(self, account: str, capability: str) -> Any:
        row = self.db.execute(
            "SELECT envelope_sha FROM snapshots WHERE account=? AND capability=? AND ok=1 AND envelope_sha IS NOT NULL "
            "ORDER BY fetched_at DESC, id DESC LIMIT 1",
            (account, capability),
        ).fetchone()
        return self.get_blob(row["envelope_sha"]) if row else None

    def changes_since(self, since: str | None = None, *, notify_only: bool = False,
                      unnotified: bool = False, account: str | None = None) -> list[sqlite3.Row]:
        sql = "SELECT * FROM changes WHERE 1=1"
        params: list[Any] = []
        if since:
            sql += " AND at >= ?"
            params.append(since)
        if notify_only:
            sql += " AND notify = 1"
        if unnotified:
            sql += " AND notified_at IS NULL"
        if account:
            sql += " AND account = ?"
            params.append(account)
        sql += " ORDER BY at, id"
        return self.db.execute(sql, params).fetchall()

    def mark_notified(self, ids: Iterable[int]) -> None:
        stamp = now_iso()
        self.db.executemany("UPDATE changes SET notified_at=? WHERE id=?", [(stamp, i) for i in ids])
        self.db.commit()

    def items(self, kind: str | None = None, account: str | None = None, *, include_gone: bool = False,
              limit: int = 500) -> list[sqlite3.Row]:
        sql = "SELECT * FROM items WHERE 1=1"
        params: list[Any] = []
        if kind:
            sql += " AND kind = ?"
            params.append(kind)
        if account:
            sql += " AND account = ?"
            params.append(account)
        if not include_gone:
            sql += " AND gone_at IS NULL"
        sql += " ORDER BY coalesce(when_iso, first_seen) DESC LIMIT ?"
        params.append(limit)
        return self.db.execute(sql, params).fetchall()

    def search(self, text: str, account: str | None = None, limit: int = 100) -> list[sqlite3.Row]:
        like = f"%{text.lower()}%"
        sql = ("SELECT account, kind, key, when_iso, summary FROM items "
               "WHERE (lower(summary) LIKE ? OR lower(data) LIKE ?)")
        params: list[Any] = [like, like]
        if account:
            sql += " AND account = ?"
            params.append(account)
        sql += " ORDER BY coalesce(when_iso, first_seen) DESC LIMIT ?"
        params.append(limit)
        return self.db.execute(sql, params).fetchall()

    def lab_trend(self, component: str, account: str | None = None) -> list[sqlite3.Row]:
        sql = ("SELECT * FROM lab_values WHERE lower(component) LIKE ? "
               + ("AND account = ? " if account else "")
               + "ORDER BY coalesce(nullif(collected, ''), resulted)")
        params: list[Any] = [f"%{component.lower()}%"]
        if account:
            params.append(account)
        return self.db.execute(sql, params).fetchall()

    def last_syncs(self) -> list[sqlite3.Row]:
        return self.db.execute(
            "SELECT s.* FROM syncs s JOIN (SELECT account, max(id) AS id FROM syncs GROUP BY account) m "
            "ON s.id = m.id ORDER BY s.account"
        ).fetchall()

    def last_good_sync(self, account: str) -> sqlite3.Row | None:
        return self.db.execute(
            "SELECT * FROM syncs WHERE account=? AND ok=1 ORDER BY id DESC LIMIT 1", (account,)
        ).fetchone()


VOLATILE_KEY = re.compile(r"token|nonce|uniqueid|querykey|photoblobfilename|contentlinkurl|rteupdateinprogress",
                          re.IGNORECASE)


def stable_view(obj: Any) -> Any:
    """The object minus the fields MyChart re-mints on every read."""
    if isinstance(obj, dict):
        return {k: stable_view(v) for k, v in obj.items() if not VOLATILE_KEY.search(k)}
    if isinstance(obj, list):
        return [stable_view(v) for v in obj]
    return obj


def strip_token_fetches(envelope: Any) -> Any:
    if isinstance(envelope, dict) and isinstance(envelope.get("requests"), list):
        return {**envelope, "requests": [r for r in envelope["requests"] if not (isinstance(r, dict)
                                                                              and r.get("purpose") == "token")]}
    return envelope


# ── Extractors ──────────────────────────────────────────────────────────────


@dataclass
class Item:
    kind: str
    key: str
    summary: str
    when: str | None
    fingerprint: str
    data: Any
    notify: bool = False
    notify_on_change: bool = False


def _g(obj: Any, *path: str, default: Any = None) -> Any:
    for part in path:
        if not isinstance(obj, dict):
            return default
        obj = obj.get(part)
    return default if obj is None else obj


def _list(obj: Any, *path: str) -> list[Any]:
    value = _g(obj, *path)
    return value if isinstance(value, list) else []


def _fp(*parts: Any) -> str:
    return sha(canonical(parts))[:16]


def _results(standard: Any, kind: str, label: str) -> Iterable[Item]:
    for order in _list(standard, "orders"):
        for result in _list(order, "results") or [order]:
            meta = _g(result, "orderMetadata", default={})
            when = _g(meta, "prioritizedInstantISO") or _g(meta, "latestUpdateInstantISO")
            status = _g(meta, "resultStatus", default="")
            name = _g(result, "name") or _g(order, "orderName", default="?")
            key = f"{_g(result, 'key') or _g(order, 'key', default=name)}|{when or ''}"
            # Real MyChart sends isAbnormal=false and abnormalFlagCategoryValue
            # "Unknown" even for values outside their range (engine labs README),
            # so the reference range is the only signal there is.
            abnormal = bool(_g(result, "isAbnormal")) or any(
                component_out_of_range(c) for c in _list(result, "resultComponents"))
            # MyChart's test-result list holds imaging too. Filing it under the
            # imaging kind, with the imaging extractor's key, makes the two
            # lists one item instead of two notifications.
            this_kind, this_label = kind, label
            if _g(meta, "resultType") == "IMAGING":
                this_kind, this_label = "imaging_result", "Imaging result"
            summary = f"{this_label}: {name}" + (f" ({status})" if status else "") + (f", {when[:10]}" if when else "")
            if abnormal:
                summary += ", a value outside its reference range"
            lab = _g(meta, "resultingLab", "name", default="")
            yield Item(this_kind, key, summary, when, _fp(status, _g(meta, "latestUpdateInstantISO")),
                       {"name": name, "status": status, "abnormal": abnormal, "lab": lab,
                        "provider": _g(meta, "orderProviderName")},
                       notify=True, notify_on_change=True)


def ex_labs(standard: Any) -> Iterable[Item]:
    return _results(standard, "lab_result", "Lab result")


def ex_imaging(standard: Any) -> Iterable[Item]:
    return _results(standard, "imaging_result", "Imaging result")


def ex_messages(standard: Any) -> Iterable[Item]:
    for conv in _list(standard, "conversations"):
        subject = _g(conv, "subject", default="(no subject)")
        messages = _list(conv, "messages")
        if not messages:
            when = _g(conv, "latestMessageInstantISO")
            yield Item("message", f"{_g(conv, 'hthId')}|{when}", f"Message thread: {subject}", when,
                       _fp(when), {"conversation": _g(conv, "hthId"), "subject": subject},
                       notify=True)
            continue
        for msg in messages:
            from_patient = bool(_g(msg, "isFromPatient"))
            sender = _g(msg, "senderName", default="?")
            when = _g(msg, "deliveryInstantISO")
            yield Item("message", str(_g(msg, "wmgId") or f"{_g(conv, 'hthId')}|{when}"),
                       f"{'Sent' if from_patient else 'Message from ' + sender}: {subject}", when,
                       _fp(when), {"conversation": _g(conv, "hthId"), "subject": subject, "sender": sender,
                                   "from_patient": from_patient},
                       notify=not from_patient)


def ex_billing(standard: Any) -> Iterable[Item]:
    yield from ex_unavailable_bills(standard)
    total = _g(standard, "totalDue")
    if total is not None:
        yield Item("balance", "total", f"Balance due: ${total}", None, _fp(total), {"totalDue": total},
                   notify=False, notify_on_change=True)
    for account in _list(standard, "accounts"):
        for stmt in _list(account, "statements"):
            when = _g(stmt, "dateISO")
            yield Item("statement", str(_g(stmt, "RecordID") or when),
                       f"Statement {when or '?'}: {_g(stmt, 'StatementAmountDisplay', default='')}".strip(),
                       when, _fp(_g(stmt, "StatementAmountDisplay")), stmt, notify=True)
        for visit in _list(account, "visits"):
            key = "|".join(str(_g(visit, k, default="")) for k in ("HospitalAccountId", "StartDateDisplay",
                                                                     "Description"))
            due = _g(visit, "SelfAmountDue", default="")
            yield Item("bill", key, f"Bill: {_g(visit, 'Description', default='?')} "
                                    f"({_g(visit, 'StartDateDisplay', default='')}), you owe {due}",
                       parse_display_time(_g(visit, "StartDateDisplay", default="")) or None,
                       _fp(due, _g(visit, "ChargeAmount")),
                       {k: _g(visit, k) for k in ("Description", "StartDateDisplay", "ChargeAmount",
                                                   "SelfAmountDue", "InsuranceAmountDue")},
                       notify=True, notify_on_change=True)


def ex_unavailable_bills(standard: Any) -> Iterable[Item]:
    """Visits whose charges MyChart would not detail (see the bridge's
    recoverBilling). Recorded so the gap shows, never notified."""
    seen: dict[str, int] = {}
    for visit in _list(standard, "unavailableVisits"):
        when = _g(visit, "startDate") or "?"
        seen[when] = seen.get(when, 0) + 1
        yield Item("bill", f"unavailable|{when}|{seen[when]}",
                   f"Bill: visit on {when}, charges not available from MyChart", when, _fp(when), visit,
                   notify=False)


def _visits(standard: Any, kind: str, label: str, notify: bool) -> Iterable[Item]:
    for visit in _list(standard, "visits"):
        when = _g(visit, "instantISO")
        name = _g(visit, "VisitTypeName", default="Visit")
        yield Item(kind, str(_g(visit, "Csn") or _g(visit, "Id") or when),
                   f"{label}: {name}" + (f" on {local_time(when)}" if when else ""),
                   when, _fp(when, name), {"name": name, "when": when, "csn": _g(visit, "Csn")},
                   notify=notify, notify_on_change=notify)


def ex_upcoming(standard: Any) -> Iterable[Item]:
    return _visits(standard, "appointment", "Appointment", True)


def ex_past(standard: Any) -> Iterable[Item]:
    return _visits(standard, "past_visit", "Visit", False)


def ex_letters(standard: Any) -> Iterable[Item]:
    for letter in _list(standard, "letters"):
        when = _g(letter, "dateISO")
        yield Item("letter", str(_g(letter, "hnoId") or when),
                   f"Letter: {_g(letter, 'reason', default='?')} from {_g(letter, 'providerName', default='?')}",
                   when, _fp(when), {k: _g(letter, k) for k in ("hnoId", "csn", "reason", "providerName")},
                   notify=True)


def ex_documents(standard: Any) -> Iterable[Item]:
    for doc in _list(standard, "documents"):
        when = _g(doc, "dateISO")
        yield Item("document", str(_g(doc, "docID") or _g(doc, "dcsID")),
                   f"Document: {_g(doc, 'docType', default='?')} {_g(doc, 'docDesc', default='')}".strip()
                   + (f", {when}" if when else ""),
                   when, _fp(when, _g(doc, "docType")),
                   {k: _g(doc, k) for k in ("dcsID", "docType", "docDesc", "docExt", "dateISO")},
                   notify=True)


def ex_medications(standard: Any) -> Iterable[Item]:
    for med in _list(standard, "prescriptions"):
        name = _g(med, "patientFriendlyName", "text") or _g(med, "name", default="?")
        yield Item("medication", str(_g(med, "id") or name), f"Medication: {name}",
                   None, _fp(_g(med, "sig"), _g(med, "refillDetails", "refillsRemaining")),
                   {"name": _g(med, "name"), "sig": _g(med, "sig"), "start": _g(med, "startDate"),
                    "prescriber": _g(med, "authorizingProvider", "name")},
                   notify=True)


def ex_health_issues(standard: Any) -> Iterable[Item]:
    for entry in _list(standard, "dataList"):
        issue = _g(entry, "healthIssueItem", default={})
        name = _g(issue, "name", default="?")
        yield Item("health_issue", str(_g(issue, "id") or name), f"Health issue: {name}", None,
                   _fp(name, _g(issue, "formattedDateNoted")),
                   {"name": name, "noted": _g(issue, "formattedDateNoted"),
                    "external_orgs": _g(entry, "externalOrgs")},
                   notify=True)


def ex_allergies(standard: Any) -> Iterable[Item]:
    for entry in _list(standard, "dataList"):
        allergy = _g(entry, "allergyItem", default={})
        name = _g(allergy, "name", default="?")
        yield Item("allergy", str(_g(allergy, "id") or name), f"Allergy: {name}", None,
                   _fp(_g(allergy, "reaction"), _g(allergy, "severity")),
                   {k: _g(allergy, k) for k in ("name", "type", "reaction", "severity", "formattedDateNoted")},
                   notify=True)


def ex_immunizations(standard: Any) -> Iterable[Item]:
    for imm in _list(standard, "immunizations"):
        name = _g(imm, "name", default="?")
        dates = _g(imm, "formattedAdministeredDates", default=[])
        yield Item("immunization", str(_g(imm, "id") or name), f"Immunization: {name}", None,
                   _fp(dates), {"name": name, "dates": dates, "org": _g(imm, "organizationName")},
                   notify=False)


def ex_referrals(standard: Any) -> Iterable[Item]:
    for ref in _list(standard, "referralList"):
        yield Item("referral", str(_g(ref, "internalId") or _g(ref, "externalId")),
                   f"Referral to {_g(ref, 'referredToProviderName', default='?')}"
                   f" ({_g(ref, 'status', default='?')})",
                   None, _fp(_g(ref, "status"), _g(ref, "end")),
                   {k: _g(ref, k) for k in ("status", "referredToProviderName", "referredToFacility",
                                             "referredByProviderName", "start", "end")},
                   notify=True, notify_on_change=True)


def ex_orders(standard: Any) -> Iterable[Item]:
    for order in _list(standard, "orderList"):
        name = _g(order, "orderName", default="?")
        key = f"{name}|{_g(order, 'orderedDate', default='')}"
        yield Item("order", key, f"Ordered: {name} ({_g(order, 'orderType', default='')}, "
                                 f"{_g(order, 'status', default='')})",
                   None, _fp(_g(order, "status")), order, notify=True)


EXTRACTORS: dict[str, Callable[[Any], Iterable[Item]]] = {
    "get_lab_results": ex_labs,
    "get_imaging_results": ex_imaging,
    "get_messages": ex_messages,
    "get_billing": ex_billing,
    "get_upcoming_visits": ex_upcoming,
    "get_past_visits": ex_past,
    "get_letters": ex_letters,
    "get_documents": ex_documents,
    "get_medications": ex_medications,
    "get_health_issues": ex_health_issues,
    "get_allergies": ex_allergies,
    "get_immunizations": ex_immunizations,
    "get_referrals": ex_referrals,
    "get_upcoming_orders": ex_orders,
}

KINDS_BY_CAPABILITY: dict[str, tuple[str, ...]] = {
    "get_lab_results": ("lab_result", "imaging_result"),
    "get_imaging_results": ("imaging_result",),
    "get_messages": ("message",),
    "get_billing": ("balance", "statement", "bill"),
    "get_upcoming_visits": ("appointment",),
    "get_past_visits": ("past_visit",),
    "get_letters": ("letter",),
    "get_documents": ("document",),
    "get_medications": ("medication",),
    "get_health_issues": ("health_issue",),
    "get_allergies": ("allergy",),
    "get_immunizations": ("immunization",),
    "get_referrals": ("referral",),
    "get_upcoming_orders": ("order",),
}

# Kinds whose disappearance means something, and whether to notify on it.
GONE_MATTERS: dict[str, bool] = {
    "appointment": True,  # cancelled, or it happened
    "medication": True,  # discontinued
    "health_issue": False,  # resolved
    "bill": False,  # paid off
}

TITLES: dict[str, str] = {
    "get_profile": "Profile",
    "get_health_summary": "Health summary",
    "get_vitals": "Vitals",
    "get_preventive_care": "Preventive care",
    "get_medical_history": "Medical history",
    "get_goals": "Goals",
    "get_insurance": "Insurance",
    "get_insurance_benefits": "Insurance benefits",
    "get_care_team": "Care team",
    "get_questionnaires": "Questionnaires",
    "get_care_journeys": "Care journeys",
    "get_activity_feed": "Activity feed",
    "get_education_materials": "Education materials",
    "get_ehi_export": "EHI export options",
    "get_linked_accounts": "Linked accounts",
    "get_emergency_contacts": "Emergency contacts",
}

KIND_LABELS: dict[str, tuple[str, str]] = {
    "lab_result": ("lab result", "lab results"),
    "imaging_result": ("imaging result", "imaging results"),
    "message": ("message", "messages"),
    "statement": ("statement", "statements"),
    "bill": ("bill update", "bill updates"),
    "balance": ("balance change", "balance changes"),
    "appointment": ("appointment change", "appointment changes"),
    "letter": ("letter", "letters"),
    "document": ("document", "documents"),
    "medication": ("medication change", "medication changes"),
    "health_issue": ("health issue", "health issues"),
    "allergy": ("allergy change", "allergy changes"),
    "referral": ("referral", "referrals"),
    "order": ("new order", "new orders"),
}


DISPLAY_TIME = re.compile(r"[A-Z][a-z]{2} \d{1,2}, \d{4}(?: \d{1,2}:\d{2} [AP]M)?")


def parse_display_time(text: str) -> str:
    """'Jan 10, 2026 9:00 AM' (the first one, if MyChart lists several) to
    '2026-01-10T09:00'. Empty when there is nothing to parse."""
    match = DISPLAY_TIME.search(text or "")
    if not match:
        return ""
    for fmt, out in (("%b %d, %Y %I:%M %p", "%Y-%m-%dT%H:%M"), ("%b %d, %Y", "%Y-%m-%d")):
        try:
            return datetime.strptime(match.group(0), fmt).strftime(out)
        except ValueError:
            continue
    return ""


def local_time(iso: str) -> str:
    """An ISO instant as local 'YYYY-MM-DD HH:MM'. Instants without a zone are
    the organization's wall clock already, so they pass through."""
    try:
        moment = datetime.fromisoformat(iso.replace("Z", "+00:00"))
    except ValueError:
        return iso[:16].replace("T", " ")
    if moment.tzinfo is not None:
        moment = moment.astimezone()
    return moment.strftime("%Y-%m-%d %H:%M")


def _num(value: Any) -> float | None:
    if isinstance(value, bool):
        return None
    if isinstance(value, (int, float)):
        return float(value)
    try:
        return float(str(value).replace(",", "").strip())
    except (TypeError, ValueError):
        return None


NO_VERDICT = {"", "unknown", "normal", "none"}


def component_out_of_range(comp: Any) -> bool | None:
    """True or False when a verdict exists, None when there is nothing to
    judge (a text value, or no range). A real flag from MyChart wins."""
    res = _g(comp, "componentResultInfo", default={})
    flag = str(_g(res, "abnormalFlagCategoryValue") or _g(res, "abnormalFlagDisplay") or "").strip()
    if flag.lower() not in NO_VERDICT:
        return True
    ref = _g(res, "referenceRange", default={})
    numeric = _num(_g(res, "numericValue"))
    low, high = _num(_g(ref, "low")), _num(_g(ref, "high"))
    if numeric is None or (low is None and high is None):
        return None
    lower_bad = low is not None and (numeric <= low if _g(ref, "lowerBoundExclusive") else numeric < low)
    upper_bad = high is not None and (numeric >= high if _g(ref, "upperBoundExclusive") else numeric > high)
    return lower_bad or upper_bad


def lab_value_rows(standard: Any) -> Iterable[tuple[Any, ...]]:
    for order in _list(standard, "orders"):
        for result in _list(order, "results"):
            meta = _g(result, "orderMetadata", default={})
            if _g(meta, "resultType") == "IMAGING":
                continue
            resulted = _g(meta, "prioritizedInstantISO") or _g(meta, "latestUpdateInstantISO") or ""
            collected_display = _g(meta, "collectionTimestampsDisplay", default="")
            collected = parse_display_time(collected_display)
            result_key = str(_g(result, "key") or _g(order, "key") or "")
            test = _g(result, "name") or _g(order, "orderName")
            for comp in _list(result, "resultComponents"):
                info = _g(comp, "componentInfo", default={})
                res = _g(comp, "componentResultInfo", default={})
                ref = _g(res, "referenceRange", default={})
                name = _g(info, "commonName") or _g(info, "name") or "?"
                numeric = _num(_g(res, "numericValue"))
                low, high = _num(_g(ref, "low")), _num(_g(ref, "high"))
                abnormal = component_out_of_range(comp)
                abnormal = None if abnormal is None else int(abnormal)
                yield (
                    result_key, test, name, str(_g(info, "componentID") or name),
                    _g(res, "valueText"), numeric, _g(info, "units"), low, high,
                    _g(ref, "formattedReferenceRange"), abnormal, _g(meta, "resultStatus"),
                    resulted, collected, collected_display, _g(meta, "resultingLab", "name"),
                )


def vital_rows(standard: Any) -> Iterable[tuple[Any, ...]]:
    for sheet in _list(standard, "flowsheets"):
        rows = {r.get("id"): r for r in _list(sheet, "rows") if isinstance(r, dict)}
        for reading in _list(sheet, "readings"):
            row = rows.get(_g(reading, "rowId"), {})
            name = row.get("name") or _g(reading, "rowId") or "?"
            yield (name, _g(reading, "instantTakenIso", default=""), _g(reading, "value"),
                   _num(_g(reading, "value")), row.get("unitsDisplayName"),
                   int(bool(_g(reading, "isAbnormal"))))
