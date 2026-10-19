"""mychart core: account registry, Keychain secrets, and the engine bridge.

The engine is OpenRecord's mychart-cli library, built from a local checkout
(see README.md). bridge/bridge.mjs drives it; this module spawns the bridge,
speaks its newline-delimited JSON protocol, and owns every secret.

INVARIANTS:
- Secrets (password, TOTP seed, passkey, session, FHIR tokens) live only in
  the macOS Keychain, service SERVICE. They travel to the bridge on stdin,
  never in argv, env, or a file.
- A passkey event from the bridge is saved to the Keychain the moment it
  arrives, before any later event is read. The stored signCount must never
  fall behind the server.
- When MIST_UNATTENDED=1, no capability of kind write or account runs and no
  prompt is shown, whatever the caller asks for.
- Account data (accounts.json, the store) lives under data_dir(), which git
  ignores. Nothing here writes into a tracked path.
"""

from __future__ import annotations

import base64
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable

HOME = Path(__file__).resolve().parent
SERVICE = "mist-mychart"
DEFAULT_ENGINE = Path.home() / "Documents/openrecord/npm-package/dist/index.js"
BRIDGE = HOME / "bridge" / "bridge.mjs"
NAME_RE = re.compile(r"^[a-z0-9][a-z0-9_-]{0,31}$")
SECRET_KINDS = ("passkey", "password", "totp", "session", "fhir", "fhirsecret")


class MyChartError(Exception):
    """A failure the CLI reports as one line, with no traceback."""


def unattended() -> bool:
    return os.environ.get("MIST_UNATTENDED") == "1"


def data_dir() -> Path:
    override = os.environ.get("MYCHART_DATA_DIR")
    path = Path(override) if override else HOME / "data"
    path.mkdir(parents=True, exist_ok=True, mode=0o700)
    return path


def engine_path() -> Path:
    return Path(os.environ.get("MYCHART_ENGINE") or DEFAULT_ENGINE)


def node_bin() -> str:
    # launchd's PATH has no Homebrew, so fall back to its fixed location.
    found = shutil.which("node")
    if found:
        return found
    for candidate in ("/opt/homebrew/bin/node", "/usr/local/bin/node"):
        if Path(candidate).exists():
            return candidate
    raise MyChartError("node is not installed (brew install node)")


def write_json_atomic(path: Path, data: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    fd, tmp = tempfile.mkstemp(dir=path.parent, prefix=f".{path.name}.")
    try:
        with os.fdopen(fd, "w") as fh:
            json.dump(data, fh, indent=2, sort_keys=True)
            fh.write("\n")
        os.chmod(tmp, 0o600)
        os.replace(tmp, path)
    except BaseException:
        Path(tmp).unlink(missing_ok=True)
        raise


# ── Accounts ────────────────────────────────────────────────────────────────


@dataclass
class Account:
    name: str
    host: str
    label: str = ""
    username: str = ""
    auth: str = "passkey"  # passkey | password | totp
    fhir_base: str = ""
    enabled: bool = True
    added: str = ""
    extra: dict[str, Any] = field(default_factory=dict)

    def to_json(self) -> dict[str, Any]:
        out = {
            "host": self.host,
            "label": self.label,
            "username": self.username,
            "auth": self.auth,
            "fhir_base": self.fhir_base,
            "enabled": self.enabled,
            "added": self.added,
        }
        out.update(self.extra)
        return out


KNOWN_FIELDS = {"host", "label", "username", "auth", "fhir_base", "enabled", "added"}


def accounts_path() -> Path:
    return data_dir() / "accounts.json"


def normalize_host(host: str) -> str:
    host = host.strip().lower()
    host = re.sub(r"^https?://", "", host)
    return host.split("/", 1)[0]


def load_accounts() -> dict[str, Account]:
    path = accounts_path()
    if not path.exists():
        return {}
    raw = json.loads(path.read_text())
    out: dict[str, Account] = {}
    for name, entry in (raw.get("accounts") or {}).items():
        extra = {k: v for k, v in entry.items() if k not in KNOWN_FIELDS}
        out[name] = Account(
            name=name,
            host=entry["host"],
            label=entry.get("label", ""),
            username=entry.get("username", ""),
            auth=entry.get("auth", "passkey"),
            fhir_base=entry.get("fhir_base", ""),
            enabled=entry.get("enabled", True),
            added=entry.get("added", ""),
            extra=extra,
        )
    return out


def save_accounts(accounts: dict[str, Account]) -> None:
    payload = {"version": 1, "accounts": {n: a.to_json() for n, a in sorted(accounts.items())}}
    write_json_atomic(accounts_path(), payload)


def get_account(name: str) -> Account:
    accounts = load_accounts()
    if name not in accounts:
        known = ", ".join(sorted(accounts)) or "none yet"
        raise MyChartError(f"no account named {name!r} (known: {known}). Add one with: mychart accounts add")
    return accounts[name]


def select_accounts(name: str | None) -> list[Account]:
    """One account by name, or every enabled account for None / 'all'."""
    if name and name != "all":
        return [get_account(name)]
    accounts = [a for a in load_accounts().values() if a.enabled]
    if not accounts:
        raise MyChartError("no accounts yet. Add one with: mychart accounts add <name> --host <host>")
    return sorted(accounts, key=lambda a: a.name)


def add_account(name: str, host: str, *, label: str = "", username: str = "", fhir_base: str = "") -> Account:
    if not NAME_RE.match(name):
        raise MyChartError("account names are lowercase letters, digits, - and _ (max 32), for example: clinic")
    accounts = load_accounts()
    if name in accounts:
        raise MyChartError(f"account {name!r} exists. Use: mychart accounts set {name} ...")
    account = Account(
        name=name,
        host=normalize_host(host),
        label=label,
        username=username,
        fhir_base=fhir_base.rstrip("/"),
        added=time.strftime("%Y-%m-%d"),
    )
    accounts[name] = account
    save_accounts(accounts)
    return account


def update_account(name: str, **changes: Any) -> Account:
    accounts = load_accounts()
    if name not in accounts:
        raise MyChartError(f"no account named {name!r}")
    account = accounts[name]
    for key, value in changes.items():
        if value is None:
            continue
        if key == "host":
            value = normalize_host(value)
        if key == "fhir_base":
            value = value.rstrip("/")
        if key in KNOWN_FIELDS:
            setattr(account, key, value)
        else:
            account.extra[key] = value
    save_accounts(accounts)
    return account


def remove_account(name: str) -> None:
    accounts = load_accounts()
    if name not in accounts:
        raise MyChartError(f"no account named {name!r}")
    del accounts[name]
    save_accounts(accounts)
    for kind in SECRET_KINDS:
        keychain_delete(f"{name}:{kind}")


# ── Keychain ────────────────────────────────────────────────────────────────
# Items are written through `security -i` on stdin so the value never shows in
# a process list. Values are base64 so no character can break the command
# line that `security -i` parses. An item created by /usr/bin/security is
# readable by /usr/bin/security without a prompt, so a launchd sync works
# whatever Python version runs it.


def _keychain_service() -> str:
    return os.environ.get("MYCHART_KEYCHAIN_SERVICE", SERVICE)


def keychain_get(key: str) -> str | None:
    proc = subprocess.run(
        ["/usr/bin/security", "find-generic-password", "-s", _keychain_service(), "-a", key, "-w"],
        capture_output=True,
        text=True,
    )
    if proc.returncode != 0:
        return None
    try:
        return base64.b64decode(proc.stdout.strip()).decode()
    except ValueError:
        return None


def keychain_set(key: str, value: str) -> None:
    encoded = base64.b64encode(value.encode()).decode()
    service = _keychain_service()
    command = (
        f'add-generic-password -U -s {service} -a {key} -l "{service} {key}" '
        f'-D "MyChart CLI secret" -w {encoded}\n'
    )
    proc = subprocess.run(["/usr/bin/security", "-i"], input=command, capture_output=True, text=True)
    if proc.returncode != 0 or keychain_get(key) != value:
        raise MyChartError(f"could not save {key} to the Keychain (security rc={proc.returncode})")


def keychain_delete(key: str) -> bool:
    proc = subprocess.run(
        ["/usr/bin/security", "delete-generic-password", "-s", _keychain_service(), "-a", key],
        capture_output=True,
        text=True,
    )
    return proc.returncode == 0


def secret(account: str, kind: str) -> str | None:
    return keychain_get(f"{account}:{kind}")


def set_secret(account: str, kind: str, value: str) -> None:
    keychain_set(f"{account}:{kind}", value)


# ── Engine bridge ───────────────────────────────────────────────────────────


@dataclass
class BridgeResult:
    rc: int
    events: list[dict[str, Any]]

    def of(self, kind: str) -> list[dict[str, Any]]:
        return [e for e in self.events if e.get("event") == kind]

    @property
    def actions(self) -> list[dict[str, Any]]:
        return self.of("action")

    @property
    def login(self) -> dict[str, Any] | None:
        found = self.of("login")
        return found[-1] if found else None

    @property
    def fatal(self) -> str | None:
        found = self.of("fatal")
        return json.dumps(found[-1].get("error")) if found else None


def bridge_log_path() -> Path:
    path = data_dir() / "logs"
    path.mkdir(parents=True, exist_ok=True, mode=0o700)
    return path / "bridge.log"


def call_bridge(
    request: dict[str, Any],
    *,
    on_event: Callable[[dict[str, Any]], dict[str, Any] | None] | None = None,
    timeout: float = 900,
    verbose: bool = False,
) -> BridgeResult:
    """Run one bridge op. on_event sees each event as it arrives; a dict it
    returns is written back to the bridge (the answer to a prompt)."""
    engine = engine_path()
    if not engine.exists():
        raise MyChartError(f"engine not built: {engine} is missing. See mychart/README.md (Engine).")
    env = dict(os.environ)
    env["MYCHART_ENGINE"] = str(engine)
    env["MYCHART_CLI_TELEMETRY_DISABLED"] = "1"
    log = open(bridge_log_path(), "a")
    log.write(f"\n=== {time.strftime('%Y-%m-%d %H:%M:%S')} op={request.get('op')} "
              f"host={(request.get('account') or {}).get('host', '-')}\n")
    log.flush()
    proc = subprocess.Popen(
        [node_bin(), str(BRIDGE)],
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=sys.stderr if verbose else log,
        text=True,
        env=env,
        cwd=str(data_dir()),
    )
    assert proc.stdin is not None and proc.stdout is not None
    events: list[dict[str, Any]] = []
    deadline = time.monotonic() + timeout
    try:
        proc.stdin.write(json.dumps(request) + "\n")
        proc.stdin.flush()
        for line in proc.stdout:
            line = line.strip()
            if not line:
                continue
            try:
                event = json.loads(line)
            except json.JSONDecodeError:
                log.write(f"[non-protocol stdout] {line[:300]}\n")
                continue
            events.append(event)
            if on_event is not None:
                reply = on_event(event)
                if reply is not None:
                    proc.stdin.write(json.dumps(reply) + "\n")
                    proc.stdin.flush()
            if event.get("event") == "done" or time.monotonic() > deadline:
                break
        try:
            proc.stdin.close()
        except BrokenPipeError:
            pass
        rc = proc.wait(timeout=max(5.0, deadline - time.monotonic()))
    except subprocess.TimeoutExpired:
        proc.kill()
        rc = 124
    finally:
        log.close()
    return BridgeResult(rc=rc, events=events)


def auth_for(account: Account, *, use_session: bool = True) -> dict[str, Any]:
    auth: dict[str, Any] = {}
    passkey = secret(account.name, "passkey")
    if passkey:
        auth["passkey"] = passkey
    elif use_session:
        session = secret(account.name, "session")
        if session:
            auth["session"] = session
    password = secret(account.name, "password")
    if password and account.username:
        auth["user"] = account.username
        auth["pass"] = password
        totp = secret(account.name, "totp")
        if totp:
            auth["totp"] = totp
    return auth


def make_secret_saver(account: Account) -> Callable[[dict[str, Any]], dict[str, Any] | None]:
    """Event hook: persist credentials the moment the bridge reports them."""

    def hook(event: dict[str, Any]) -> dict[str, Any] | None:
        kind = event.get("event")
        if kind in ("passkey", "passkey_created") and event.get("credential"):
            set_secret(account.name, "passkey", event["credential"])
        elif kind == "session" and event.get("session"):
            set_secret(account.name, "session", event["session"])
        return None

    return hook


def chain(*hooks: Callable[[dict[str, Any]], dict[str, Any] | None] | None):
    def run(event: dict[str, Any]) -> dict[str, Any] | None:
        reply = None
        for hook in hooks:
            if hook is None:
                continue
            answer = hook(event)
            if answer is not None:
                reply = answer
        return reply

    return run


def run_actions(
    account: Account,
    actions: list[dict[str, Any]],
    *,
    allow_write: bool = False,
    interactive: bool = False,
    out_dir: Path | None = None,
    on_event: Callable[[dict[str, Any]], dict[str, Any] | None] | None = None,
    verbose: bool = False,
) -> BridgeResult:
    """Sign in to one account and run a list of capability actions."""
    if unattended():
        allow_write = False
        interactive = False
    auth = auth_for(account)
    if not auth:
        raise MyChartError(f"{account.name}: no saved sign-in. Run: mychart login {account.name}")
    request = {
        "op": "session",
        "account": {"host": account.host},
        "auth": auth,
        "actions": actions,
        "allow_write": allow_write,
        "interactive": interactive,
        "keep_session": True,
        "out_dir": str(out_dir or downloads_dir(account.name)),
    }
    return call_bridge(request, on_event=chain(make_secret_saver(account), on_event), verbose=verbose)


def downloads_dir(account: str) -> Path:
    path = data_dir() / "downloads" / account
    path.mkdir(parents=True, exist_ok=True, mode=0o700)
    return path


def capabilities(verbose: bool = False) -> list[dict[str, Any]]:
    result = call_bridge({"op": "capabilities"}, verbose=verbose)
    found = result.of("capabilities")
    if not found:
        raise MyChartError(f"engine did not list capabilities: {result.fatal or result.rc}")
    return found[0]["capabilities"]


def public_capability(capability_id: str, args: dict[str, Any], verbose: bool = False) -> Any:
    result = call_bridge({"op": "public", "id": capability_id, "args": args}, verbose=verbose)
    for action in result.actions:
        if action.get("ok"):
            return action.get("standard")
        raise MyChartError(f"{capability_id}: {action.get('error', {}).get('message')}")
    raise MyChartError(f"{capability_id}: no result ({result.fatal or result.rc})")


def render(capability_id: str, envelope: Any, mode: str = "concise") -> Any:
    result = call_bridge({"op": "render", "id": capability_id, "envelope": envelope, "mode": mode})
    found = result.of("render")
    if found and found[0].get("ok"):
        return found[0].get("output")
    return None
