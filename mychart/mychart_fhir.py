"""mychart FHIR lane: SMART on FHIR R4 patient access, the Cures Act way.

This is the standards-based second channel. It needs a registered app (a
client ID from the vendor's developer program, for Epic fhir.epic.com) and,
for each account, one sign-in in the browser. With offline_access and a
confidential app, the refresh token lets later pulls run unattended.

    mychart fhir find "health system name"     look up a FHIR base in Epic's directory
    mychart fhir app add epic --client-id ID [--secret-stdin] [--redirect URI]
    mychart fhir secret clinic < secret.txt    Epic issues one client secret per health system
    mychart fhir tls                           a self-signed certificate for the https://localhost callback
    mychart fhir login clinic [--app epic]      browser sign-in; saves tokens in the Keychain
    mychart fhir pull clinic                   every USCDI resource type into the store
    mychart fhir status
    mychart fhir show clinic Observation [--code 4548-4]

INVARIANTS:
- Tokens and client secrets live only in the Keychain (<account>:fhir,
  <account>:fhirsecret, app-<name>:secret). The authorization code is useless
  without the PKCE verifier, which never leaves this process.
- The state parameter must round-trip exactly, or the callback is refused.
- A pull stores each resource as a content-addressed blob; a failed search
  is recorded with its OperationOutcome and never deletes stored resources.
- Only GET requests go to the FHIR server. Nothing here writes to a chart.
"""

from __future__ import annotations

import argparse
import base64
import hashlib
import http.server
import json
import secrets
import ssl
import subprocess
import sys
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path
from typing import Any

import mychart_core as core
import mychart_store as st

USER_AGENT = "mist-mychart/1.0 (personal health record sync)"
EPIC_DIRECTORY = "https://open.epic.com/Endpoints/R4"
# Epic requires https redirect URIs in production and compares them character
# by character, so the callback listener serves TLS on a fixed loopback port.
DEFAULT_REDIRECT = "https://localhost:8443/callback"
DEFAULT_SCOPE = "launch/patient openid fhirUser offline_access patient/*.read"

# One search per line. Epic requires a category on several of these; a type
# the server rejects is recorded and skipped, never fatal.
PATIENT_SEARCHES: list[tuple[str, dict[str, str]]] = [
    ("AllergyIntolerance", {}),
    ("CarePlan", {"category": "assess-plan"}),
    ("CareTeam", {}),
    ("Condition", {"category": "problem-list-item"}),
    ("Condition", {"category": "encounter-diagnosis"}),
    ("Condition", {"category": "health-concern"}),
    ("Coverage", {}),
    ("Device", {}),
    ("DiagnosticReport", {}),
    ("DocumentReference", {"category": "clinical-note"}),
    ("Encounter", {}),
    ("Goal", {}),
    ("Immunization", {}),
    ("MedicationRequest", {}),
    ("Observation", {"category": "laboratory"}),
    ("Observation", {"category": "vital-signs"}),
    ("Observation", {"category": "social-history"}),
    ("Observation", {"category": "survey"}),
    ("Procedure", {}),
    ("ServiceRequest", {}),
    ("Specimen", {}),
]

SCHEMA = """
CREATE TABLE IF NOT EXISTS fhir_resources (
    account TEXT NOT NULL,
    type TEXT NOT NULL,
    id TEXT NOT NULL,
    last_updated TEXT,
    first_seen TEXT NOT NULL,
    fetched_at TEXT NOT NULL,
    sha TEXT NOT NULL,
    PRIMARY KEY (account, type, id)
);
CREATE TABLE IF NOT EXISTS fhir_pulls (
    id INTEGER PRIMARY KEY,
    account TEXT NOT NULL,
    started_at TEXT NOT NULL,
    finished_at TEXT,
    ok INTEGER,
    error TEXT,
    report TEXT
);
"""


# ── HTTP ────────────────────────────────────────────────────────────────────


class FhirError(core.MyChartError):
    pass


def http_json(url: str, *, data: dict[str, str] | None = None, headers: dict[str, str] | None = None,
              timeout: float = 60) -> tuple[int, Any]:
    body = urllib.parse.urlencode(data).encode() if data is not None else None
    req = urllib.request.Request(url, data=body, method="POST" if body is not None else "GET")
    req.add_header("Accept", "application/fhir+json, application/json")
    req.add_header("User-Agent", USER_AGENT)
    if body is not None:
        req.add_header("Content-Type", "application/x-www-form-urlencoded")
    for key, value in (headers or {}).items():
        req.add_header(key, value)
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            raw = resp.read()
            return resp.status, json.loads(raw) if raw else None
    except urllib.error.HTTPError as exc:
        raw = exc.read()
        try:
            return exc.code, json.loads(raw)
        except (json.JSONDecodeError, ValueError):
            return exc.code, {"error": raw.decode(errors="replace")[:500]}


# ── directory and apps ──────────────────────────────────────────────────────


def epic_directory(refresh: bool = False) -> list[dict[str, str]]:
    cache = core.data_dir() / "epic-endpoints.json"
    if cache.exists() and not refresh and time.time() - cache.stat().st_mtime < 7 * 86400:
        return json.loads(cache.read_text())
    status, bundle = http_json(EPIC_DIRECTORY)
    if status != 200 or not isinstance(bundle, dict):
        raise FhirError(f"Epic endpoint directory: HTTP {status}")
    rows = []
    for entry in bundle.get("entry", []):
        res = entry.get("resource", {})
        if res.get("address"):
            rows.append({"name": res.get("name", ""), "base": res["address"].rstrip("/")})
    core.write_json_atomic(cache, rows)
    return rows


def apps_path() -> Path:
    return core.data_dir() / "fhir-apps.json"


def load_apps() -> dict[str, dict[str, Any]]:
    path = apps_path()
    return json.loads(path.read_text()) if path.exists() else {}


def get_app(name: str, account: core.Account | None = None) -> dict[str, Any]:
    apps = load_apps()
    if name not in apps:
        raise FhirError(f"no FHIR app {name!r}. Add it: mychart fhir app add {name} --client-id <id>")
    app = dict(apps[name])
    app["name"] = name
    # Epic issues a separate client secret for each health system; a secret
    # saved for the account wins over one saved for the app.
    account_secret = core.secret(account.name, "fhirsecret") if account else None
    app["secret"] = account_secret or core.keychain_get(f"app-{name}:secret")
    return app


# ── SMART sign-in ───────────────────────────────────────────────────────────


def smart_config(base: str) -> dict[str, Any]:
    status, conf = http_json(f"{base}/.well-known/smart-configuration")
    if status != 200 or not isinstance(conf, dict) or "authorization_endpoint" not in conf:
        raise FhirError(f"{base}: no SMART configuration (HTTP {status})")
    return conf


def pkce_pair() -> tuple[str, str]:
    verifier = secrets.token_urlsafe(64)[:96]
    challenge = base64.urlsafe_b64encode(hashlib.sha256(verifier.encode()).digest()).rstrip(b"=").decode()
    return verifier, challenge


def basic_auth(client_id: str, secret: str) -> dict[str, str]:
    token = base64.b64encode(
        f"{urllib.parse.quote(client_id, safe='')}:{urllib.parse.quote(secret, safe='')}".encode()
    ).decode()
    return {"Authorization": f"Basic {token}"}


class _CallbackHandler(http.server.BaseHTTPRequestHandler):
    result: dict[str, str] = {}
    expected_path = "/callback"

    def do_GET(self) -> None:  # noqa: N802 (http.server API)
        parsed = urllib.parse.urlparse(self.path)
        if parsed.path != self.expected_path:
            self.send_response(404)
            self.end_headers()
            return
        params = dict(urllib.parse.parse_qsl(parsed.query))
        type(self).result.update(params)
        self.send_response(200)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.end_headers()
        message = "Signed in. You can close this tab." if "code" in params else "Sign-in did not finish."
        self.wfile.write(f"<html><body><p>{message}</p></body></html>".encode())

    def log_message(self, format: str, *args: Any) -> None:  # noqa: A002 (http.server API)
        return


def tls_paths() -> tuple[Path, Path]:
    folder = core.data_dir() / "fhir-tls"
    return folder / "localhost.pem", folder / "localhost-key.pem"


def wait_for_callback(redirect_uri: str, timeout: float) -> dict[str, str]:
    parsed = urllib.parse.urlparse(redirect_uri)
    handler = type("Handler", (_CallbackHandler,), {"result": {}, "expected_path": parsed.path or "/"})
    host = "127.0.0.1" if parsed.hostname in (None, "localhost") else parsed.hostname
    default_port = 443 if parsed.scheme == "https" else 80
    server = http.server.HTTPServer((host, parsed.port or default_port), handler)
    if parsed.scheme == "https":
        cert, key = tls_paths()
        if not cert.exists():
            server.server_close()
            raise FhirError("the https callback has no certificate yet. Run: mychart fhir tls")
        context = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
        context.load_cert_chain(str(cert), str(key))
        server.socket = context.wrap_socket(server.socket, server_side=True)
    server.timeout = 1
    thread = threading.Thread(target=lambda: _serve_until(server, handler, timeout), daemon=True)
    thread.start()
    thread.join(timeout + 2)
    server.server_close()
    return dict(handler.result)


def _serve_until(server: http.server.HTTPServer, handler: Any, timeout: float) -> None:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline and not handler.result:
        server.handle_request()


def follow_without_browser(url: str, redirect_uri: str, limit: int = 10) -> dict[str, str]:
    """For sandboxes that skip the login page: follow redirects by hand until
    one lands on the redirect URI, and read the code from it."""

    class NoRedirect(urllib.request.HTTPRedirectHandler):
        def redirect_request(self, *args: Any, **kwargs: Any) -> None:
            return None

    opener = urllib.request.build_opener(NoRedirect)
    for _ in range(limit):
        if url.startswith(redirect_uri):
            return dict(urllib.parse.parse_qsl(urllib.parse.urlparse(url).query))
        req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
        try:
            resp = opener.open(req, timeout=30)
            raise FhirError(f"sign-in page wants a person (HTTP {resp.status} at {url[:80]})")
        except urllib.error.HTTPError as exc:
            if exc.code not in (301, 302, 303, 307, 308):
                raise FhirError(f"authorize: HTTP {exc.code}") from exc
            url = urllib.parse.urljoin(url, exc.headers.get("Location", ""))
    raise FhirError("too many redirects during sign-in")


def login(account: core.Account, app: dict[str, Any], *, open_browser: bool = True, follow: bool = False,
          timeout: float = 300, consent_days: int = 0) -> dict[str, Any]:
    if not account.fhir_base:
        raise FhirError(f"{account.name} has no FHIR base. Find it: mychart fhir find <name>, "
                        f"then: mychart accounts set {account.name} --fhir-base <url>")
    conf = smart_config(account.fhir_base)
    redirect_uri = app.get("redirect_uri") or DEFAULT_REDIRECT
    verifier, challenge = pkce_pair()
    state = secrets.token_urlsafe(24)
    params = {
        "response_type": "code",
        "client_id": app["client_id"],
        "redirect_uri": redirect_uri,
        "scope": app.get("scope") or DEFAULT_SCOPE,
        "state": state,
        "aud": account.fhir_base,
        "code_challenge": challenge,
        "code_challenge_method": "S256",
    }
    url = f"{conf['authorization_endpoint']}?{urllib.parse.urlencode(params)}"
    if follow:
        callback = follow_without_browser(url, redirect_uri)
    else:
        print(f"Opening the {account.label or account.name} sign-in page in your browser.", file=sys.stderr)
        print(f"If it does not open, visit:\n{url}", file=sys.stderr)
        if open_browser:
            subprocess.run(["open", url], check=False)
        callback = wait_for_callback(redirect_uri, timeout)
    if callback.get("state") != state:
        raise FhirError("sign-in refused: the state parameter did not match")
    if "code" not in callback:
        raise FhirError(f"sign-in failed: {callback.get('error_description') or callback.get('error') or 'no code'}")
    form = {"grant_type": "authorization_code", "code": callback["code"], "redirect_uri": redirect_uri,
            "code_verifier": verifier}
    headers = {}
    if app.get("secret"):
        headers = basic_auth(app["client_id"], app["secret"])
    else:
        form["client_id"] = app["client_id"]
    status, token = http_json(conf["token_endpoint"], data=form, headers=headers)
    if status != 200 or not isinstance(token, dict) or "access_token" not in token:
        raise FhirError(f"token exchange failed: HTTP {status} {json.dumps(token)[:300]}")
    saved = {
        "app": app["name"],
        "base": account.fhir_base,
        "token_endpoint": conf["token_endpoint"],
        "access_token": token["access_token"],
        "expires_at": time.time() + float(token.get("expires_in") or 3600) - 60,
        "refresh_token": token.get("refresh_token"),
        "patient": token.get("patient"),
        "scope": token.get("scope"),
        "obtained_at": time.strftime("%Y-%m-%dT%H:%M:%S%z"),
        # The access period the patient picked on the consent screen. The
        # refresh chain stops there unless the organization allows indefinite.
        "consent_until": time.time() + consent_days * 86400 if consent_days else None,
    }
    core.set_secret(account.name, "fhir", json.dumps(saved))
    return saved


def consent_warning(tok: dict[str, Any], days: int = 14) -> str | None:
    until = tok.get("consent_until")
    if not until:
        return None
    left = (until - time.time()) / 86400
    if left < 0:
        return "the FHIR consent period has ended; run mychart fhir login again"
    if left < days:
        return f"the FHIR consent period ends in {int(left)} days; run mychart fhir login before then"
    return None


def access_token(account: core.Account) -> dict[str, Any]:
    raw = core.secret(account.name, "fhir")
    if not raw:
        raise FhirError(f"{account.name}: no FHIR sign-in yet. Run: mychart fhir login {account.name}")
    tok = json.loads(raw)
    if time.time() < tok.get("expires_at", 0):
        return tok
    if not tok.get("refresh_token"):
        raise FhirError(f"{account.name}: the FHIR access token expired and there is no refresh token. "
                        f"Run: mychart fhir login {account.name}")
    app = get_app(tok["app"], account)
    form = {"grant_type": "refresh_token", "refresh_token": tok["refresh_token"]}
    headers = basic_auth(app["client_id"], app["secret"]) if app.get("secret") else {}
    if not app.get("secret"):
        form["client_id"] = app["client_id"]
    status, fresh = http_json(tok["token_endpoint"], data=form, headers=headers)
    if status != 200 or not isinstance(fresh, dict) or "access_token" not in fresh:
        raise FhirError(f"{account.name}: refresh failed (HTTP {status}). Run: mychart fhir login {account.name}")
    tok["access_token"] = fresh["access_token"]
    tok["expires_at"] = time.time() + float(fresh.get("expires_in") or 3600) - 60
    if fresh.get("refresh_token"):
        tok["refresh_token"] = fresh["refresh_token"]
    core.set_secret(account.name, "fhir", json.dumps(tok))
    return tok


# ── pull ────────────────────────────────────────────────────────────────────


def ensure_schema(s: st.Store) -> None:
    s.db.executescript(SCHEMA)


def search_all(base: str, token: str, rtype: str, params: dict[str, str], max_pages: int = 200) -> tuple[list[Any], list[Any]]:
    url: str | None = f"{base}/{rtype}?{urllib.parse.urlencode(params)}"
    resources: list[Any] = []
    problems: list[Any] = []
    pages = 0
    while url and pages < max_pages:
        status, bundle = http_json(url, headers={"Authorization": f"Bearer {token}"})
        pages += 1
        if status != 200 or not isinstance(bundle, dict):
            problems.append({"status": status, "detail": bundle})
            break
        for entry in bundle.get("entry", []) or []:
            res = entry.get("resource")
            if not isinstance(res, dict):
                continue
            if res.get("resourceType") == "OperationOutcome":
                problems.append(res)
            else:
                resources.append(res)
        url = next((link.get("url") for link in bundle.get("link", []) if link.get("relation") == "next"), None)
    return resources, problems


def pull(account: core.Account, *, types: list[str] | None = None) -> dict[str, Any]:
    tok = access_token(account)
    base = tok["base"]
    patient = tok.get("patient")
    if not patient:
        raise FhirError("the token has no patient context")
    s = st.Store(core.data_dir() / "mychart.db")
    ensure_schema(s)
    started = st.now_iso()
    cur = s.db.execute("INSERT INTO fhir_pulls(account, started_at) VALUES (?, ?)", (account.name, started))
    pull_id = cur.lastrowid
    report: dict[str, Any] = {}
    status, patient_res = http_json(f"{base}/Patient/{patient}", headers={"Authorization": f"Bearer {tok['access_token']}"})
    searches: list[tuple[str, dict[str, str], list[Any], list[Any]]] = []
    if status == 200 and isinstance(patient_res, dict):
        searches.append(("Patient", {}, [patient_res], []))
    else:
        searches.append(("Patient", {}, [], [{"status": status, "detail": patient_res}]))
    for rtype, extra in PATIENT_SEARCHES:
        if types and rtype not in types:
            continue
        resources, problems = search_all(base, tok["access_token"], rtype, {"patient": patient, **extra})
        searches.append((rtype, extra, resources, problems))
    new_total = 0
    for rtype, extra, resources, problems in searches:
        label = rtype + (f"?category={extra['category']}" if "category" in extra else "")
        new = 0
        for res in resources:
            rid = str(res.get("id") or st.sha(st.canonical(res))[:16])
            digest = s.put_blob(res)
            row = s.db.execute("SELECT sha FROM fhir_resources WHERE account=? AND type=? AND id=?",
                               (account.name, res.get("resourceType", rtype), rid)).fetchone()
            if row is None:
                new += 1
                s.db.execute(
                    "INSERT INTO fhir_resources(account, type, id, last_updated, first_seen, fetched_at, sha) "
                    "VALUES (?,?,?,?,?,?,?)",
                    (account.name, res.get("resourceType", rtype), rid, (res.get("meta") or {}).get("lastUpdated"),
                     started, started, digest))
            else:
                s.db.execute(
                    "UPDATE fhir_resources SET last_updated=?, fetched_at=?, sha=? WHERE account=? AND type=? AND id=?",
                    ((res.get("meta") or {}).get("lastUpdated"), started, digest, account.name,
                     res.get("resourceType", rtype), rid))
        new_total += new
        report[label] = {"count": len(resources), "new": new,
                         "problems": [summarize_problem(p) for p in problems][:3]}
    s.db.execute("UPDATE fhir_pulls SET finished_at=?, ok=1, report=? WHERE id=?",
                 (st.now_iso(), json.dumps(report), pull_id))
    s.commit()
    s.close()
    return {"account": account.name, "patient": patient, "new": new_total, "report": report}


def summarize_problem(problem: Any) -> str:
    if isinstance(problem, dict) and problem.get("resourceType") == "OperationOutcome":
        issues = problem.get("issue") or []
        return "; ".join(str((i.get("details") or {}).get("text") or i.get("diagnostics") or i.get("code"))
                         for i in issues)[:200]
    if isinstance(problem, dict):
        return f"HTTP {problem.get('status')}: {json.dumps(problem.get('detail'))[:160]}"
    return str(problem)[:200]


# ── commands ────────────────────────────────────────────────────────────────


def cmd_find(args: argparse.Namespace) -> int:
    rows = epic_directory(refresh=args.refresh)
    words = args.query.lower().split()
    hits = [r for r in rows if all(w in r["name"].lower() or w in r["base"].lower() for w in words)]
    for r in hits[: args.limit]:
        print(f"{r['name']}\n    {r['base']}")
    if not hits:
        print("No match in Epic's directory. Non-Epic systems publish their own FHIR base; set it by hand.")
    return 0


def cmd_app_add(args: argparse.Namespace) -> int:
    apps = load_apps()
    apps[args.name] = {
        "client_id": args.client_id,
        "redirect_uri": args.redirect or DEFAULT_REDIRECT,
        "scope": args.scope or DEFAULT_SCOPE,
        "note": args.note or "",
    }
    core.write_json_atomic(apps_path(), apps)
    if args.secret_stdin:
        secret = sys.stdin.readline().strip()
        if secret:
            core.keychain_set(f"app-{args.name}:secret", secret)
            print("Saved the client secret in the Keychain.")
    print(f"Saved FHIR app {args.name} (redirect {apps[args.name]['redirect_uri']}).")
    return 0


def cmd_secret(args: argparse.Namespace) -> int:
    account = core.get_account(args.account)
    value = sys.stdin.readline().strip()
    if not value:
        raise FhirError("no secret on stdin")
    core.set_secret(account.name, "fhirsecret", value)
    print(f"Saved the FHIR client secret for {account.name} in the Keychain.")
    return 0


def cmd_tls(args: argparse.Namespace) -> int:
    cert, key = tls_paths()
    if cert.exists() and not args.force:
        print(f"Certificate exists: {cert}")
    else:
        cert.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
        openssl = "/opt/homebrew/bin/openssl" if Path("/opt/homebrew/bin/openssl").exists() else "openssl"
        proc = subprocess.run(
            [openssl, "req", "-x509", "-newkey", "rsa:2048", "-nodes", "-sha256", "-days", "825",
             "-keyout", str(key), "-out", str(cert), "-subj", "/CN=localhost",
             "-addext", "subjectAltName=DNS:localhost,IP:127.0.0.1"],
            capture_output=True, text=True)
        if proc.returncode != 0:
            raise FhirError(f"openssl failed: {proc.stderr.strip()[:300]}")
        key.chmod(0o600)
        print(f"Made a self-signed certificate for localhost: {cert}")
    print("The browser warns once when Epic sends it back to https://localhost. To remove the warning, "
          "trust the certificate (macOS asks for your password):")
    print(f'  security add-trusted-cert -r trustRoot -p ssl -k ~/Library/Keychains/login.keychain-db "{cert}"')
    return 0


def cmd_app_list(args: argparse.Namespace) -> int:
    for name, app in load_apps().items():
        has_secret = core.keychain_get(f"app-{name}:secret") is not None
        print(f"{name}: client {app['client_id'][:12]}... redirect {app['redirect_uri']} "
              f"secret {'yes' if has_secret else 'no'}")
    return 0


def cmd_login(args: argparse.Namespace) -> int:
    if core.unattended():
        raise FhirError("FHIR sign-in needs a person at the browser; it never runs unattended")
    account = core.get_account(args.account)
    app = get_app(args.app, account)
    tok = login(account, app, open_browser=not args.no_browser, follow=args.follow, consent_days=args.consent_days)
    refresh = "yes" if tok.get("refresh_token") else "no (pulls need a new sign-in after the token expires)"
    print(f"Signed in to {account.name} over FHIR. Patient {tok.get('patient')}. Refresh token: {refresh}.")
    print(f"Scopes: {tok.get('scope')}")
    return 0


def cmd_pull(args: argparse.Namespace) -> int:
    accounts = [a for a in core.select_accounts(args.account) if a.fhir_base and core.secret(a.name, "fhir")]
    if not accounts:
        raise FhirError("no account has a FHIR sign-in yet. Run: mychart fhir login <account>")
    results = []
    for account in accounts:
        try:
            results.append(pull(account, types=args.types.split(",") if args.types else None))
        except core.MyChartError as exc:
            results.append({"account": account.name, "error": str(exc)})
    if args.json:
        print(json.dumps(results, indent=2))
        return 0
    for r in results:
        if "error" in r:
            print(f"{r['account']}: {r['error']}")
            continue
        print(f"{r['account']}: patient {r['patient']}, {r['new']} new resources")
        for label, info in r["report"].items():
            problem = f"  [{info['problems'][0]}]" if info["problems"] else ""
            print(f"  {label:<40} {info['count']:>5} ({info['new']} new){problem}")
    return 0 if all("error" not in r for r in results) else 1


def cmd_status(args: argparse.Namespace) -> int:
    s = st.Store(core.data_dir() / "mychart.db")
    ensure_schema(s)
    for account in core.load_accounts().values():
        raw = core.secret(account.name, "fhir")
        tok = json.loads(raw) if raw else None
        counts = s.db.execute("SELECT type, count(*) AS n FROM fhir_resources WHERE account=? GROUP BY type",
                              (account.name,)).fetchall()
        last = s.db.execute("SELECT finished_at FROM fhir_pulls WHERE account=? AND ok=1 ORDER BY id DESC LIMIT 1",
                            (account.name,)).fetchone()
        sign_in = "none"
        if tok:
            left = tok.get("expires_at", 0) - time.time()
            sign_in = (f"app {tok.get('app')}, access {'valid' if left > 0 else 'expired'}, "
                       f"refresh {'yes' if tok.get('refresh_token') else 'no'}")
        print(f"{account.name}: FHIR base {account.fhir_base or 'not set'}")
        print(f"  sign-in: {sign_in} | last pull: {last['finished_at'][:16] if last else 'never'}")
        warning = consent_warning(tok) if tok else None
        if warning:
            print(f"  WARNING: {warning}")
        if counts:
            print("  " + ", ".join(f"{r['type']} {r['n']}" for r in counts))
    return 0


def cmd_show(args: argparse.Namespace) -> int:
    s = st.Store(core.data_dir() / "mychart.db")
    ensure_schema(s)
    rows = s.db.execute("SELECT sha FROM fhir_resources WHERE account=? AND type=? ORDER BY last_updated DESC",
                        (args.account, args.type)).fetchall()
    resources = [s.get_blob(r["sha"]) for r in rows]
    if args.code:
        resources = [r for r in resources if args.code in json.dumps((r or {}).get("code", {}))]
    print(json.dumps(resources[: args.limit], indent=2))
    return 0


def register(sub: Any) -> None:
    p = sub.add_parser("fhir", help="SMART on FHIR R4 patient access (needs a registered app)")
    fsub = p.add_subparsers(dest="fhir_command", required=True)
    a = fsub.add_parser("find", help="find an organization's FHIR base in Epic's directory")
    a.add_argument("query")
    a.add_argument("--limit", type=int, default=15)
    a.add_argument("--refresh", action="store_true")
    a.set_defaults(func=cmd_find)
    a = fsub.add_parser("app", help="registered FHIR apps (client IDs)")
    asub = a.add_subparsers(dest="app_command", required=True)
    b = asub.add_parser("add", help="save a client ID (and secret from stdin)")
    b.add_argument("name")
    b.add_argument("--client-id", required=True)
    b.add_argument("--redirect", help=f"redirect URI registered with the app (default {DEFAULT_REDIRECT})")
    b.add_argument("--scope")
    b.add_argument("--note")
    b.add_argument("--secret-stdin", action="store_true", help="read the client secret from stdin")
    b.set_defaults(func=cmd_app_add)
    b = asub.add_parser("list")
    b.set_defaults(func=cmd_app_list)
    a = fsub.add_parser("login", help="browser sign-in for one account")
    a.add_argument("account")
    a.add_argument("--app", default="epic")
    a.add_argument("--no-browser", action="store_true", help="print the URL instead of opening it")
    a.add_argument("--follow", action="store_true", help="sandboxes only: follow redirects with no browser")
    a.add_argument("--consent-days", type=int, default=0,
                   help="the access period you picked on the consent screen, for the renewal reminder")
    a.set_defaults(func=cmd_login)
    a = fsub.add_parser("secret", help="save the client secret Epic issued for this account's health system (stdin)")
    a.add_argument("account")
    a.set_defaults(func=cmd_secret)
    a = fsub.add_parser("tls", help="make the self-signed certificate for the https://localhost callback")
    a.add_argument("--force", action="store_true")
    a.set_defaults(func=cmd_tls)
    a = fsub.add_parser("pull", help="fetch every USCDI resource type into the store")
    a.add_argument("account", nargs="?", default="all")
    a.add_argument("--types", help="comma-separated resource types")
    a.set_defaults(func=cmd_pull)
    a = fsub.add_parser("status")
    a.set_defaults(func=cmd_status)
    a = fsub.add_parser("show", help="print stored resources of one type")
    a.add_argument("account")
    a.add_argument("type")
    a.add_argument("--code", help="only resources whose code mentions this (a LOINC code, for example)")
    a.add_argument("--limit", type=int, default=50)
    a.set_defaults(func=cmd_show)
