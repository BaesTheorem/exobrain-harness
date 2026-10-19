"""mychart: one command line for every MyChart account.

    mychart accounts                      every account, its sign-in, its last sync
    mychart accounts add clinic --host mychart.example.org --label "Example Health"
    mychart login clinic                  one-time sign-in; registers a passkey
    mychart sync [clinic|all] [--notify]  pull every category into the local store
    mychart new                           what changed in the latest syncs
    mychart show labs|meds|messages|...   read the store (--live to fetch first)
    mychart labs [--test a1c]             lab values over time, across accounts
    mychart run <capability> --arg k=v    any engine capability, live
    mychart search <text>                 search everything stored
    mychart fhir ...                      the FHIR R4 lane (see mychart_fhir.py)
    mychart ehi ...                       import and check a full EHI export

The engine is OpenRecord's mychart-cli library (README.md, Engine). Writes
(send a message, change an emergency contact) need --yes and never run when
MIST_UNATTENDED=1.
"""

from __future__ import annotations

import argparse
import fcntl
import getpass
import json
import os
import socket
import sqlite3
import subprocess
import sys
import time
from pathlib import Path
from typing import Any

import mychart_core as core
import mychart_store as st

ALIASES: dict[str, str] = {
    "profile": "get_profile",
    "summary": "get_health_summary",
    "meds": "get_medications",
    "medications": "get_medications",
    "allergies": "get_allergies",
    "problems": "get_health_issues",
    "issues": "get_health_issues",
    "conditions": "get_health_issues",
    "vitals": "get_vitals",
    "immunizations": "get_immunizations",
    "vaccines": "get_immunizations",
    "shots": "get_immunizations",
    "preventive": "get_preventive_care",
    "history": "get_medical_history",
    "goals": "get_goals",
    "appointments": "get_upcoming_visits",
    "upcoming": "get_upcoming_visits",
    "visits": "get_past_visits",
    "labs": "get_lab_results",
    "results": "get_lab_results",
    "imaging": "get_imaging_results",
    "messages": "get_messages",
    "inbox": "get_messages",
    "bills": "get_billing",
    "billing": "get_billing",
    "insurance": "get_insurance",
    "benefits": "get_insurance_benefits",
    "care-team": "get_care_team",
    "referrals": "get_referrals",
    "letters": "get_letters",
    "documents": "get_documents",
    "docs": "get_documents",
    "orders": "get_upcoming_orders",
    "questionnaires": "get_questionnaires",
    "ehi": "get_ehi_export",
    "linked": "get_linked_accounts",
    "emergency-contacts": "get_emergency_contacts",
}

# Organization config, not patient data, and the same for every patient.
SYNC_SKIP = {"get_message_recipients", "get_message_topics", "get_insurance_payers"}


def store() -> st.Store:
    return st.Store(core.data_dir() / "mychart.db")


def out(obj: Any) -> None:
    print(json.dumps(obj, indent=2, default=str))


def resolve_capability(name: str) -> str:
    return ALIASES.get(name, name)


def parse_args_kv(pairs: list[str] | None) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for pair in pairs or []:
        if "=" not in pair:
            raise core.MyChartError(f"--arg needs name=value, got {pair!r}")
        key, value = pair.split("=", 1)
        result[key] = value
    return result


# ── accounts ────────────────────────────────────────────────────────────────


def keychain_flags(name: str) -> str:
    have = [kind for kind in ("passkey", "password", "totp") if core.secret(name, kind)]
    return ",".join(have) or "none"


def cmd_accounts(args: argparse.Namespace) -> int:
    accounts = core.load_accounts()
    if not accounts:
        print("No accounts yet. Add one: mychart accounts add <name> --host <mychart host> --label <name>")
        return 0
    s = store()
    last = {row["account"]: row for row in s.last_syncs()}
    rows = []
    for name, acct in sorted(accounts.items()):
        sync = last.get(name)
        rows.append({
            "name": name,
            "label": acct.label,
            "host": acct.host,
            "sign_in": keychain_flags(name),
            "fhir": ("signed in" if core.secret(name, "fhir") else "base set") if acct.fhir_base else "no",
            "enabled": acct.enabled,
            "last_sync": (f"{sync['started_at'][:16]} {'ok' if sync['ok'] else 'FAILED'}"
                          if sync and sync["finished_at"] else "never"),
        })
    if args.json:
        out(rows)
        return 0
    for r in rows:
        flag = "" if r["enabled"] else " (disabled)"
        print(f"{r['name']:<10} {r['label'] or r['host']}{flag}")
        print(f"{'':<10} host {r['host']} | sign-in {r['sign_in']} | FHIR {r['fhir']} | last sync {r['last_sync']}")
    return 0


def cmd_accounts_add(args: argparse.Namespace) -> int:
    acct = core.add_account(args.name, args.host, label=args.label or "", username=args.username or "",
                            fhir_base=args.fhir_base or "")
    print(f"Added {acct.name} ({acct.host}). Next: mychart login {acct.name}")
    return 0


def cmd_accounts_set(args: argparse.Namespace) -> int:
    enabled = True if args.enable else False if args.disable else None
    acct = core.update_account(args.name, host=args.host, label=args.label, username=args.username,
                               fhir_base=args.fhir_base, enabled=enabled)
    print(f"Updated {acct.name}.")
    return 0


def cmd_accounts_remove(args: argparse.Namespace) -> int:
    if not args.yes:
        print(f"This removes {args.name} and its Keychain secrets. The passkey stays registered on the MyChart "
              f"account until you delete it there (or run: mychart run delete_passkey). Re-run with --yes.")
        return 1
    core.remove_account(args.name)
    print(f"Removed {args.name}.")
    return 0


def cmd_accounts_find(args: argparse.Namespace) -> int:
    found = core.public_capability("search_mycharts", {"query": args.query, "limit": str(args.limit)})
    matches = (found or {}).get("matches", []) if isinstance(found, dict) else found
    if args.json:
        out(found)
        return 0
    for m in matches or []:
        note = f"  [{m['unavailable']}]" if m.get("unavailable") else ""
        print(f"{m.get('hostname', '?'):<45} {m.get('name', '')}{note}")
    if not matches:
        print("No match.")
    return 0


# ── login ───────────────────────────────────────────────────────────────────


def code_prompt(event: dict[str, Any]) -> dict[str, Any] | None:
    kind = event.get("event")
    if kind == "need_2fa":
        delivery = event.get("delivery") or {}
        where = f" ({delivery.get('method')} to {delivery.get('contact')})" if delivery.get("method") else ""
        attempt = event.get("attempt", 1)
        prefix = "Code rejected. " if attempt > 1 else ""
        return {"code": input(f"{prefix}MyChart sent a code{where}. Code: ").strip()}
    if kind == "code_rejected":
        print(f"  (code rejected: {event.get('message')})", file=sys.stderr)
    return None


def cmd_login(args: argparse.Namespace) -> int:
    if core.unattended():
        raise core.MyChartError("login needs a person at the keyboard; it never runs unattended")
    acct = core.get_account(args.name)
    print(f"Signing in to {acct.label or acct.name} ({acct.host}).")
    username = args.username or acct.username or input("MyChart username: ").strip()
    password = getpass.getpass("MyChart password: ")
    if not password:
        raise core.MyChartError("no password given")
    want_passkey = args.method == "passkey" and not core.secret(acct.name, "passkey")
    request = {
        "op": "session",
        "account": {"host": acct.host},
        "auth": {"user": username, "pass": password},
        "interactive": True,
        "setup_passkey": want_passkey,
        "setup_totp": args.method == "totp" and not core.secret(acct.name, "totp"),
        "list_passkeys": args.method == "passkey",
        "keep_session": True,
        "actions": [{"id": "get_profile"}],
    }
    result = core.call_bridge(request, on_event=core.chain(core.make_secret_saver(acct), code_prompt, totp_saver(acct)),
                              verbose=args.verbose)
    login = result.login or {}
    if not login.get("ok"):
        raise core.MyChartError(f"sign-in failed: {login.get('message') or login.get('state') or result.fatal}")
    if username != acct.username:
        core.update_account(acct.name, username=username)
    profile = next((a.get("standard") for a in result.actions if a.get("ok")), None) or {}
    who = profile.get("name") if isinstance(profile, dict) else None
    print(f"Signed in{f' as {who}' if who else ''}.")
    if want_passkey:
        if result.of("passkey_created"):
            print("Registered a passkey for this tool and saved it in the Keychain. "
                  "MyChart shows it under its security settings. Later runs need no password and no code.")
        else:
            refused = result.of("passkey_refused")
            print(f"MyChart did not accept a passkey: {refused[0].get('message') if refused else 'unknown reason'}.")
            print("Options: mychart login --method totp (adds an authenticator to the account), or "
                  "--save-password and enter a code on each sign-in.")
    if args.method == "totp" and result.of("totp_created"):
        print("Turned on authenticator-app sign-in for this account and saved the secret in the Keychain.")
    if args.save_password or args.method in ("password", "totp"):
        core.set_secret(acct.name, "password", password)
        print("Saved the password in the Keychain.")
    passkeys = result.of("passkeys")
    if passkeys:
        count = len(passkeys[0].get("passkeys") or [])
        print(f"Passkeys on this account: {count}.")
    return 0


def totp_saver(acct: core.Account):
    def hook(event: dict[str, Any]) -> dict[str, Any] | None:
        if event.get("event") == "totp_created" and event.get("secret"):
            core.set_secret(acct.name, "totp", event["secret"])
        return None

    return hook


# ── sync ────────────────────────────────────────────────────────────────────


def sync_capabilities(only: list[str] | None = None) -> list[str]:
    if only:
        return [resolve_capability(c) for c in only]
    caps = core.capabilities()
    return [
        c["id"] for c in caps
        if c["kind"] == "read" and c["hasProcessor"] and not c["notImplemented"]
        and not any(p.get("required") for p in c["params"]) and c["id"] not in SYNC_SKIP
    ]


def host_resolves(host: str, wait: float = 0) -> bool:
    deadline = time.monotonic() + wait
    while True:
        try:
            socket.getaddrinfo(host, 443)
            return True
        except OSError:
            if time.monotonic() >= deadline:
                return False
            time.sleep(10)


class SyncLock:
    def __init__(self) -> None:
        self.path = core.data_dir() / "sync.lock"
        self.fh = None

    def __enter__(self) -> SyncLock:
        self.fh = open(self.path, "w")
        try:
            fcntl.flock(self.fh, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError as exc:
            raise core.MyChartError("another sync is running") from exc
        return self

    def __exit__(self, *exc: object) -> None:
        if self.fh:
            fcntl.flock(self.fh, fcntl.LOCK_UN)
            self.fh.close()


def sync_account(s: st.Store, acct: core.Account, capability_ids: list[str], *, verbose: bool = False,
                 quiet: bool = False) -> dict[str, Any]:
    sync_id = s.start_sync(acct.name)
    summary: dict[str, Any] = {"account": acct.name, "ok": 0, "failed": [], "changes": [], "baseline": []}

    def on_event(event: dict[str, Any]) -> None:
        if event.get("event") != "action":
            return None
        result = s.record_snapshot(sync_id, acct.name, event)
        s.commit()
        if result["ok"]:
            summary["ok"] += 1
            summary["changes"].extend(result["changes"])
            if result.get("baseline"):
                summary["baseline"].append(result["capability"])
        else:
            summary["failed"].append(f"{event.get('id')}: {(event.get('error') or {}).get('message', '?')}")
        if not quiet:
            mark = "ok" if result["ok"] else "FAILED"
            print(f"  {acct.name} {event.get('id')}: {mark}", file=sys.stderr)
        return None

    actions = [{"id": cid, "envelope": True} for cid in capability_ids]
    error = None
    method = None
    try:
        result = core.run_actions(acct, actions, on_event=on_event, verbose=verbose)
        login = result.login or {}
        method = login.get("method")
        if not login.get("ok"):
            error = f"sign-in failed: {login.get('message') or login.get('state') or result.fatal or result.rc}"
    except core.MyChartError as exc:
        error = str(exc)
    ok = error is None and not summary["failed"]
    s.finish_sync(sync_id, ok=error is None, login_method=method, error=error,
                  actions=summary["ok"] + len(summary["failed"]), failures=len(summary["failed"]))
    summary["error"] = error
    summary["complete"] = ok
    return summary


def cmd_sync(args: argparse.Namespace) -> int:
    accounts = core.select_accounts(args.account)
    # An account nobody has signed in to yet is not a failure: skip it quietly,
    # so the scheduled sync can be installed before the first login.
    waiting = [a for a in accounts if not core.auth_for(a)]
    accounts = [a for a in accounts if core.auth_for(a)]
    for acct in waiting:
        print(f"{acct.name}: not signed in yet (run: mychart login {acct.name}); skipped", file=sys.stderr)
    if not accounts:
        return 0
    offline = [a.name for a in accounts if not host_resolves(a.host, wait=args.wait_network)]
    if offline:
        # A sleeping Mac wakes before its Wi-Fi does. No DNS is not a sign-in
        # failure, so it never raises an alert; the next scheduled run retries.
        print(f"no network for {', '.join(offline)}; skipped this run", file=sys.stderr)
        accounts = [a for a in accounts if a.name not in offline]
        if not accounts:
            return 0
    capability_ids = sync_capabilities(args.only.split(",") if args.only else None)
    s = store()
    results = []
    with SyncLock():
        for acct in accounts:
            if not args.quiet:
                print(f"Syncing {acct.name} ({len(capability_ids)} categories)...", file=sys.stderr)
            results.append(sync_account(s, acct, capability_ids, verbose=args.verbose, quiet=args.quiet))
    sent = notify_pending(s) if args.notify else None
    failed_login = [r for r in results if r["error"]]
    if args.notify and failed_login:
        alert_sync_failure(failed_login)
    if args.json:
        out({"results": results, "notified": sent})
    else:
        for r in results:
            new = [c for c in r["changes"] if c["change"] == "new"]
            print(f"{r['account']}: {r['ok']} categories stored, {len(r['failed'])} failed, "
                  f"{len(r['changes'])} changes ({len(new)} new)"
                  + (f", baseline for {len(r['baseline'])}" if r["baseline"] else ""))
            if r["error"]:
                print(f"  error: {r['error']}")
            for line in r["failed"][:10]:
                print(f"  failed: {line}")
        if sent:
            print(f"Notified: {sent}")
    return 0 if not failed_login else 1


# ── notifications ───────────────────────────────────────────────────────────


def mist_notify_bin() -> Path:
    return core.HOME.parent / "mist-voice" / "bin" / "mist-notify"


def notify(message: str, *, context: str, link: str | None = None, ident: str = "mychart") -> bool:
    binary = mist_notify_bin()
    if os.environ.get("MYCHART_NO_NOTIFY") == "1" or not binary.exists():
        print(f"[notify suppressed] {message}", file=sys.stderr)
        return False
    cmd = [str(binary), message, "MyChart", "Purr", link or "console", "--discord", "--group", "mychart",
           "--id", ident, "--context", context[-4000:]]
    return subprocess.run(cmd, capture_output=True, text=True).returncode == 0


def digest_lines(rows: list[sqlite3.Row], labels: dict[str, str]) -> tuple[str, str]:
    """(banner text with counts only, local context with the summaries)."""
    counts: dict[str, dict[str, int]] = {}
    for row in rows:
        counts.setdefault(row["account"], {})
        counts[row["account"]][row["kind"]] = counts[row["account"]].get(row["kind"], 0) + 1
    parts = []
    for account, kinds in counts.items():
        bits = []
        for kind, n in kinds.items():
            one, many = st.KIND_LABELS.get(kind, (kind.replace("_", " "), kind.replace("_", " ") + "s"))
            bits.append(f"{n} {one if n == 1 else many}")
        parts.append(f"{labels.get(account, account)}: {', '.join(bits)}")
    banner = "New in MyChart. " + ". ".join(parts) + "."
    context = "\n".join(f"- [{labels.get(r['account'], r['account'])}] {r['change']}: {r['summary']} ({r['at'][:16]})"
                        for r in rows)
    context = ("MyChart changes found by `mychart sync` (details are in the local store; "
               "`mychart new` shows them):\n" + context)
    return banner, context


def notify_pending(s: st.Store) -> str | None:
    rows = s.changes_since(notify_only=True, unnotified=True)
    if not rows:
        return None
    accounts = core.load_accounts()
    labels = {n: (a.label or n) for n, a in accounts.items()}
    banner, context = digest_lines(rows, labels)
    hosts = {accounts[r["account"]].host for r in rows if r["account"] in accounts}
    link = f"https://{next(iter(hosts))}/" if len(hosts) == 1 else None
    if notify(banner, context=context, link=link):
        s.mark_notified([r["id"] for r in rows])
        return banner
    return None


def alert_sync_failure(results: list[dict[str, Any]]) -> None:
    # One alert per account per day, so a broken sign-in does not page 4x a day.
    state_path = core.data_dir() / "alert-state.json"
    state = json.loads(state_path.read_text()) if state_path.exists() else {}
    today = time.strftime("%Y-%m-%d")
    fresh = [r for r in results if state.get(r["account"]) != today]
    if not fresh:
        return
    names = ", ".join(r["account"] for r in fresh)
    detail = "\n".join(f"{r['account']}: {r['error']}" for r in fresh)
    if notify(f"MyChart sync could not sign in for {names}. Run: mychart status",
              context=f"mychart sync failures:\n{detail}\nIf the passkey was removed, run mychart login <account>.",
              ident="mychart-failure"):
        for r in fresh:
            state[r["account"]] = today
        core.write_json_atomic(state_path, state)


# ── reading the store ───────────────────────────────────────────────────────


def cmd_new(args: argparse.Namespace) -> int:
    s = store()
    since = args.since
    if not since:
        # Default: everything since the start of the previous sync day.
        since = time.strftime("%Y-%m-%dT00:00:00", time.localtime(time.time() - 86400 * args.days))
    rows = s.changes_since(since, notify_only=not args.all, account=args.account)
    if args.json:
        out([dict(r) for r in rows])
        return 0
    if not rows:
        print(f"No changes since {since[:10]}" + ("" if args.all else " (use --all for minor changes)") + ".")
        return 0
    for r in rows:
        print(f"{r['at'][:16]}  {r['account']:<9} {r['change']:<7} {r['summary']}")
    return 0


def item_kind_for(capability: str) -> tuple[str, ...]:
    return st.KINDS_BY_CAPABILITY.get(capability, ())


def cmd_show(args: argparse.Namespace) -> int:
    capability = resolve_capability(args.what)
    accounts = core.select_accounts(args.account)
    s = store()
    if args.live:
        for acct in accounts:
            sync_account(s, acct, [capability], verbose=args.verbose, quiet=True)
    if args.json or not item_kind_for(capability):
        payload = {}
        for acct in accounts:
            snap = s.latest(acct.name, capability)
            if snap is None:
                payload[acct.name] = None
                continue
            data = snap["standard"]
            if args.concise:
                envelope = s.latest_envelope(acct.name, capability)
                data = core.render(capability, envelope, "concise") if envelope is not None else data
            payload[acct.name] = {"fetched_at": snap["fetched_at"], "data": data}
        out(payload)
        return 0
    kinds = item_kind_for(capability)
    shown = 0
    for acct in accounts:
        snap = s.latest(acct.name, capability)
        stamp = snap["fetched_at"][:16] if snap else "never synced"
        print(f"== {acct.label or acct.name} (synced {stamp})")
        for kind in kinds:
            for row in s.items(kind, acct.name, include_gone=args.include_gone, limit=args.limit):
                when = (row["when_iso"] or "")[:10]
                gone = "  [no longer listed]" if row["gone_at"] else ""
                print(f"  {when:<10}  {row['summary']}{gone}")
                shown += 1
    if not shown:
        print("Nothing stored yet. Run: mychart sync")
    return 0


def cmd_labs(args: argparse.Namespace) -> int:
    s = store()
    if args.test:
        rows = s.lab_trend(args.test, args.account)
        if args.json:
            out([dict(r) for r in rows])
            return 0
        for r in rows:
            date = (r["collected"] or r["resulted"] or "")[:16]
            flag = " *" if r["abnormal"] else ""
            ref = f"  ref {r['ref_text']}" if r["ref_text"] else ""
            print(f"{date:<17} {r['account']:<9} {r['component']}: {r['value']} {r['units'] or ''}{flag}{ref}")
        if not rows:
            print(f"No stored lab values match {args.test!r}.")
        return 0
    sql = ("SELECT component, count(*) AS n, max(coalesce(nullif(collected, ''), resulted)) AS latest, "
           "group_concat(DISTINCT account) AS accounts FROM lab_values "
           + ("WHERE account = ? " if args.account else "")
           + "GROUP BY lower(component) ORDER BY latest DESC")
    rows = s.db.execute(sql, (args.account,) if args.account else ()).fetchall()
    if args.json:
        out([dict(r) for r in rows])
        return 0
    for r in rows:
        print(f"{(r['latest'] or '')[:10]:<11} {r['n']:>3}x  {r['component']}  ({r['accounts']})")
    if not rows:
        print("No lab values stored yet. Run: mychart sync")
    return 0


def cmd_search(args: argparse.Namespace) -> int:
    rows = store().search(args.text, args.account, args.limit)
    if args.json:
        out([dict(r) for r in rows])
        return 0
    for r in rows:
        print(f"{(r['when_iso'] or '')[:10]:<11} {r['account']:<9} {r['summary']}")
    if not rows:
        print("No match.")
    return 0


def cmd_sql(args: argparse.Namespace) -> int:
    path = core.data_dir() / "mychart.db"
    db = sqlite3.connect(f"file:{path}?mode=ro", uri=True)
    db.row_factory = sqlite3.Row
    rows = db.execute(args.query).fetchall()
    out([dict(r) for r in rows])
    return 0


# ── live capabilities ───────────────────────────────────────────────────────


def cmd_capabilities(args: argparse.Namespace) -> int:
    caps = core.capabilities(verbose=args.verbose)
    if args.json:
        out(caps)
        return 0
    for c in caps:
        if c["lessFrequentlyUsed"] and not args.all:
            continue
        mark = {"write": "!", "account": "#", "public": "~"}.get(c["kind"], " ")
        params = " ".join(f"{p['name']}{'' if p.get('required') else '?'}" for p in c["params"])
        print(f"{mark} {c['id']:<28} {params}")
    print("\n! writes (need --yes)   # account settings   ~ no account needed   ? optional argument")
    return 0


def cmd_run(args: argparse.Namespace) -> int:
    capability = resolve_capability(args.capability)
    caps = {c["id"]: c for c in core.capabilities()}
    cap = caps.get(capability)
    if cap is None:
        raise core.MyChartError(f"unknown capability {capability!r}. List them: mychart capabilities --all")
    cap_args = parse_args_kv(args.arg)
    if args.mode:
        cap_args["mode"] = args.mode
    if cap["kind"] == "public":
        out(core.public_capability(capability, cap_args, verbose=args.verbose))
        return 0
    write = cap["kind"] in ("write", "account")
    if write:
        if core.unattended():
            raise core.MyChartError(f"{capability} changes the record and this session is unattended")
        if not args.yes:
            print(f"{capability} changes your MyChart record ({cap['description']}). "
                  f"Arguments: {json.dumps(cap_args)}. Re-run with --yes to do it.")
            return 1
        if args.account in (None, "all"):
            raise core.MyChartError("a write needs one --account")
    accounts = core.select_accounts(args.account)
    s = store()
    results: dict[str, Any] = {}
    rc = 0
    for acct in accounts:
        envelope = cap["kind"] == "read" and cap["hasProcessor"] and not args.mode
        res = core.run_actions(acct, [{"id": capability, "args": cap_args, "envelope": envelope}],
                               allow_write=write, verbose=args.verbose)
        login = res.login or {}
        if not login.get("ok"):
            results[acct.name] = {"error": login.get("message") or login.get("state") or res.fatal}
            rc = 1
            continue
        for action in res.actions:
            if cap["kind"] == "read" and not args.mode:
                s.record_snapshot(None, acct.name, action)
                s.commit()
            if action.get("ok"):
                results[acct.name] = action.get("standard")
            else:
                results[acct.name] = {"error": action.get("error")}
                rc = 1
    out(results if len(accounts) > 1 else next(iter(results.values()), None))
    return rc


# ── status ──────────────────────────────────────────────────────────────────


def cmd_status(args: argparse.Namespace) -> int:
    engine = core.engine_path()
    checkout = engine.parent.parent.parent
    commit = subprocess.run(["git", "-C", str(checkout), "log", "-1", "--format=%h %cd", "--date=short"],
                            capture_output=True, text=True).stdout.strip() if checkout.exists() else ""
    print(f"engine   {'ok' if engine.exists() else 'MISSING'}  {engine}  {commit}")
    try:
        node = subprocess.run([core.node_bin(), "--version"], capture_output=True, text=True).stdout.strip()
    except core.MyChartError as exc:
        node = str(exc)
    print(f"node     {node}")
    db = core.data_dir() / "mychart.db"
    print(f"store    {db} ({db.stat().st_size // 1024} KB)" if db.exists() else "store    empty")
    if core.unattended():
        print("mode     unattended: writes and prompts are off")
    print()
    return cmd_accounts(args)


# ── parser ──────────────────────────────────────────────────────────────────


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="mychart", description="One CLI for every MyChart account.")
    parser.add_argument("--json", action="store_true", help="machine-readable output")
    parser.add_argument("-v", "--verbose", action="store_true", help="show engine logs on stderr")
    sub = parser.add_subparsers(dest="command", required=True)

    p = sub.add_parser("accounts", help="list, add, change, remove, or find accounts")
    p.set_defaults(func=cmd_accounts)
    asub = p.add_subparsers(dest="accounts_command")
    a = asub.add_parser("add", help="add an account")
    a.add_argument("name")
    a.add_argument("--host", required=True, help="the MyChart host, e.g. mychart.example.org")
    a.add_argument("--label")
    a.add_argument("--username")
    a.add_argument("--fhir-base", help="the organization's FHIR R4 base URL (mychart fhir find)")
    a.set_defaults(func=cmd_accounts_add)
    a = asub.add_parser("set", help="change an account")
    a.add_argument("name")
    a.add_argument("--host")
    a.add_argument("--label")
    a.add_argument("--username")
    a.add_argument("--fhir-base")
    a.add_argument("--enable", action="store_true")
    a.add_argument("--disable", action="store_true")
    a.set_defaults(func=cmd_accounts_set)
    a = asub.add_parser("remove", help="remove an account and its Keychain secrets")
    a.add_argument("name")
    a.add_argument("--yes", action="store_true")
    a.set_defaults(func=cmd_accounts_remove)
    a = asub.add_parser("find", help="find a MyChart host by health-system name (no sign-in)")
    a.add_argument("query")
    a.add_argument("--limit", type=int, default=10)
    a.set_defaults(func=cmd_accounts_find)

    p = sub.add_parser("login", help="sign in once and register a passkey")
    p.add_argument("name")
    p.add_argument("--username")
    p.add_argument("--method", choices=["passkey", "password", "totp"], default="passkey",
                   help="passkey (default, adds a passkey), totp (turns on authenticator 2FA), password")
    p.add_argument("--save-password", action="store_true", help="also keep the password in the Keychain")
    p.set_defaults(func=cmd_login)

    p = sub.add_parser("status", help="engine, store, and accounts")
    p.set_defaults(func=cmd_status)

    p = sub.add_parser("sync", help="pull every category into the local store")
    p.add_argument("account", nargs="?", default="all")
    p.add_argument("--only", help="comma-separated capabilities or aliases")
    p.add_argument("--notify", action="store_true", help="send one digest of new items (banner + Discord)")
    p.add_argument("--quiet", action="store_true")
    p.add_argument("--wait-network", type=float, default=0, metavar="SECONDS",
                   help="wait this long for DNS before skipping a run (for scheduled runs)")
    p.set_defaults(func=cmd_sync)

    p = sub.add_parser("new", help="changes found by recent syncs")
    p.add_argument("--since", help="ISO date or time")
    p.add_argument("--days", type=int, default=7, help="look back this many days (default 7)")
    p.add_argument("--account")
    p.add_argument("--all", action="store_true", help="include minor changes")
    p.set_defaults(func=cmd_new)

    p = sub.add_parser("show", help="read one category from the store")
    p.add_argument("what", help="labs, meds, messages, appointments, visits, bills, letters, documents, "
                                "allergies, problems, immunizations, referrals, orders, vitals, profile, "
                                "insurance, or any capability id")
    p.add_argument("--account", default="all")
    p.add_argument("--live", action="store_true", help="fetch it first")
    p.add_argument("--concise", action="store_true", help="with --json: the concise projection")
    p.add_argument("--include-gone", action="store_true")
    p.add_argument("--limit", type=int, default=200)
    p.set_defaults(func=cmd_show)

    p = sub.add_parser("labs", help="lab values over time")
    p.add_argument("--test", help="component name to trend, e.g. a1c, ldl, vitamin d")
    p.add_argument("--account")
    p.set_defaults(func=cmd_labs)

    p = sub.add_parser("search", help="search everything stored")
    p.add_argument("text")
    p.add_argument("--account")
    p.add_argument("--limit", type=int, default=100)
    p.set_defaults(func=cmd_search)

    p = sub.add_parser("sql", help="read-only SQL over the store")
    p.add_argument("query")
    p.set_defaults(func=cmd_sql)

    p = sub.add_parser("capabilities", help="everything the engine can do")
    p.add_argument("--all", action="store_true")
    p.set_defaults(func=cmd_capabilities)

    p = sub.add_parser("run", help="run one capability live")
    p.add_argument("capability")
    p.add_argument("--account", default="all")
    p.add_argument("--arg", action="append", help="name=value, repeatable")
    p.add_argument("--mode", choices=["json", "standard", "concise", "raw"])
    p.add_argument("--yes", action="store_true", help="confirm a write")
    p.set_defaults(func=cmd_run)

    import mychart_ehi
    import mychart_fhir

    mychart_fhir.register(sub)
    mychart_ehi.register(sub)
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    if args.command == "accounts" and getattr(args, "accounts_command", None) is None:
        args.func = cmd_accounts
    try:
        return int(args.func(args) or 0)
    except core.MyChartError as exc:
        print(f"mychart: {exc}", file=sys.stderr)
        return 1
    except KeyboardInterrupt:
        return 130


if __name__ == "__main__":
    sys.exit(main())
