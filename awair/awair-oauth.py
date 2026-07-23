#!/usr/bin/env python3
"""One-time Awair OAuth 2.0 login to obtain a cloud-API access token for reading
your own devices, then save it (and any refresh token) to the gitignored harness
.env. The cloud token is only needed for the historical BACKFILL; the local
5-min poller stays the free, no-rate-limit source for ongoing collection.

Flow (read off oauth-login.awair.is's bundle + confirmed token endpoint):
  authorize: https://oauth-login.awair.is/?client_id=..&redirect_uri=..&response_type=code&state=..
    -> user authorizes -> redirect to redirect_uri?code=..&state=..
  token:     POST https://oauth2.awair.is/v2/token
             grant_type=authorization_code, code, client_id, client_secret, redirect_uri

Reads AWAIR_CLIENT_ID / AWAIR_CLIENT_SECRET / AWAIR_REDIRECT_URI from .env.
Writes AWAIR_ACCESS_TOKEN (+ AWAIR_REFRESH_TOKEN / AWAIR_TOKEN_EXPIRES_IN).
"""
import http.server
import json
import secrets
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
import webbrowser
from pathlib import Path

HARNESS = Path(__file__).resolve().parent.parent
ENV = HARNESS / ".env"
AUTHORIZE = "https://oauth-login.awair.is/"
TOKEN_URL = "https://oauth2.awair.is/v2/token"
DEVICES_URL = "https://developer-apis.awair.is/v1/users/self/devices"
TIMEOUT_S = 600


def load_env():
    out = {}
    if not ENV.exists():
        return out
    for line in ENV.read_text().splitlines():
        line = line.strip()
        if line and not line.startswith("#") and "=" in line:
            k, _, v = line.partition("=")
            out[k.strip()] = v.strip()
    return out


def save_env_keys(updates):
    lines = ENV.read_text().splitlines() if ENV.exists() else []
    keys = set(updates)
    kept = [l for l in lines if (l.split("=", 1)[0] if "=" in l else None) not in keys]
    for k, v in updates.items():
        kept.append(f"{k}={v}")
    ENV.write_text("\n".join(kept) + "\n")


env = load_env()
CID = env.get("AWAIR_CLIENT_ID")
CSEC = env.get("AWAIR_CLIENT_SECRET")
RU = env.get("AWAIR_REDIRECT_URI", "http://localhost:8128/callback")
if not CID or not CSEC:
    print("FAIL: missing AWAIR_CLIENT_ID / AWAIR_CLIENT_SECRET in .env", flush=True)
    sys.exit(1)

_pr = urllib.parse.urlparse(RU)
PORT = _pr.port or 8128
CB_PATH = _pr.path or "/callback"
STATE = secrets.token_urlsafe(16)
result = {}


class Handler(http.server.BaseHTTPRequestHandler):
    def log_message(self, *a):
        pass

    def do_GET(self):
        u = urllib.parse.urlparse(self.path)
        if u.path != CB_PATH:
            self.send_response(404)
            self.end_headers()
            return
        q = urllib.parse.parse_qs(u.query)
        result["code"] = q.get("code", [None])[0]
        result["state"] = q.get("state", [None])[0]
        result["error"] = q.get("error", [None])[0]
        ok = bool(result.get("code"))
        body = (
            "Awair authorized. You can close this tab and return to MIST."
            if ok else f"Authorization failed: {result.get('error')}"
        )
        self.send_response(200)
        self.send_header("Content-Type", "text/html")
        self.end_headers()
        self.wfile.write(
            f"<html><body style='font:16px -apple-system,sans-serif;padding:48px'>"
            f"{body}</body></html>".encode()
        )


def main():
    auth_url = AUTHORIZE + "?" + urllib.parse.urlencode({
        "client_id": CID, "redirect_uri": RU,
        "response_type": "code", "state": STATE,
    })
    print("AUTH_URL: " + auth_url, flush=True)

    srv = http.server.HTTPServer(("127.0.0.1", PORT), Handler)
    srv.timeout = 1
    try:
        webbrowser.open(auth_url)
    except Exception:
        pass

    deadline = time.time() + TIMEOUT_S
    while "code" not in result and "error" not in result and time.time() < deadline:
        srv.handle_request()

    if not result.get("code"):
        print(f"FAIL: no authorization code ({result.get('error') or 'timeout'})", flush=True)
        sys.exit(2)
    if result.get("state") != STATE:
        print("FAIL: state mismatch (possible CSRF) -- aborting", flush=True)
        sys.exit(3)

    data = urllib.parse.urlencode({
        "grant_type": "authorization_code", "code": result["code"],
        "client_id": CID, "client_secret": CSEC, "redirect_uri": RU,
    }).encode()
    req = urllib.request.Request(
        TOKEN_URL, data=data, method="POST",
        headers={"Content-Type": "application/x-www-form-urlencoded"},
    )
    try:
        resp = json.loads(urllib.request.urlopen(req, timeout=20).read())
    except urllib.error.HTTPError as e:
        print(f"FAIL: token exchange HTTP {e.code}: {e.read().decode()[:200]}", flush=True)
        sys.exit(4)

    tok = resp.get("access_token") or resp.get("token")
    if not tok:
        print("FAIL: no access_token in response: " + json.dumps(resp)[:200], flush=True)
        sys.exit(5)

    updates = {"AWAIR_ACCESS_TOKEN": tok}
    if resp.get("refresh_token"):
        updates["AWAIR_REFRESH_TOKEN"] = resp["refresh_token"]
    if resp.get("expires_in"):
        updates["AWAIR_TOKEN_EXPIRES_IN"] = str(resp["expires_in"])
    save_env_keys(updates)

    vreq = urllib.request.Request(DEVICES_URL, headers={"Authorization": f"Bearer {tok}"})
    try:
        devs = json.loads(urllib.request.urlopen(vreq, timeout=20).read())
        print("SUCCESS: token saved to .env. devices: " + json.dumps(devs)[:500], flush=True)
    except urllib.error.HTTPError as e:
        print(f"SAVED token, but verify call failed HTTP {e.code}: {e.read().decode()[:200]}", flush=True)


if __name__ == "__main__":
    main()
