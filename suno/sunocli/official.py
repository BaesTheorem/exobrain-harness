"""Suno's official interface: the OAuth sign-in and the MCP endpoint at api.suno.com/mcp.

Suno runs an MCP server in beta for all plans (help.suno.com, "Suno MCP (Beta)"). It is
protected by OAuth 2.1: the endpoint names its authorization server in
``/.well-known/oauth-protected-resource/mcp``, that server takes public clients with PKCE and
registers them on request, and it gives a refresh token for the ``offline_access`` scope. This
module signs in once through the browser, keeps the tokens in ``secrets/oauth.json``, and
speaks JSON-RPC to the endpoint.

INVARIANTS:
- The refresh token is as good as the login while it lives: written 0600, never printed,
  never committed (``secrets/`` is gitignored).
- The sign-in is the person's own step. ``sign_in`` opens the system browser on Suno's
  consent page and waits on a loopback port. No other code in this package opens a window.
- The redirect is ``http://127.0.0.1:47616/callback``, fixed, because the server compares the
  registered redirect with the one in the request. The ``state`` value is compared before
  the code is used.
- This module never decides to spend. A tool call that costs credits or a download is gated
  by the command layer, the same as on the web lane.
- An access token is replaced when it has less than a minute left. A refresh that Suno
  refuses raises ``NotConnected``; it does not open a browser by itself.
- Suno opens this interface account by account. On 2026-11-11 its consent page told a paid
  account that connecting AI apps was not available for it yet, and sent nothing back to
  the loopback port. No account flag in ``/session/`` names the feature, so the sign-in is
  the only test. ``wait_for_code`` therefore has a short time limit and stores nothing when
  it ends.
"""

from __future__ import annotations

import base64
import hashlib
import http.server
import json
import os
import secrets as pysecrets
import subprocess
import time
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path
from typing import Any, Callable

Json = dict[str, Any]
HeaderTransport = Callable[[str, str, bytes | None, dict[str, str]], tuple[int, dict[str, str], bytes]]

HERE = Path(__file__).resolve().parent.parent  # suno/
OAUTH_PATH = HERE / "secrets" / "oauth.json"

MCP_URL = "https://api.suno.com/mcp"
RESOURCE_METADATA = "https://api.suno.com/.well-known/oauth-protected-resource/mcp"
REDIRECT_PORT = 47616
REDIRECT_URI = f"http://127.0.0.1:{REDIRECT_PORT}/callback"
PROTOCOL_VERSION = "2025-06-18"
CLIENT_INFO = {"name": "suno-cli", "version": "1.0"}
UA = "suno-cli/1.0 (+https://github.com/BaesTheorem/exobrain-harness)"


class NotConnected(RuntimeError):
    """No usable official sign-in. Run `suno connect`."""


class McpError(RuntimeError):
    """The official endpoint refused or failed a call."""

    def __init__(self, message: str, code: int | None = None, data: Any = None) -> None:
        super().__init__(message)
        self.code = code
        self.data = data


def header_transport(method: str, url: str, body: bytes | None, headers: dict[str, str]) -> tuple[int, dict[str, str], bytes]:
    req = urllib.request.Request(url, data=body, headers=headers, method=method)
    try:
        with urllib.request.urlopen(req, timeout=300) as resp:
            return resp.status, {k.lower(): v for k, v in resp.headers.items()}, resp.read()
    except urllib.error.HTTPError as err:
        return err.code, {k.lower(): v for k, v in err.headers.items()}, err.read()


# -- token store -------------------------------------------------------------------------------


def load() -> Json:
    if not OAUTH_PATH.exists():
        return {}
    try:
        return json.loads(OAUTH_PATH.read_text())
    except (OSError, ValueError):
        return {}


def save(state: Json) -> None:
    OAUTH_PATH.parent.mkdir(parents=True, exist_ok=True)
    tmp = OAUTH_PATH.with_suffix(".tmp")
    fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, "w") as fh:
        json.dump(state, fh, indent=1)
    os.replace(tmp, OAUTH_PATH)


# -- OAuth -------------------------------------------------------------------------------------


def pkce_pair() -> tuple[str, str]:
    verifier = pysecrets.token_urlsafe(64)
    digest = hashlib.sha256(verifier.encode()).digest()
    return verifier, base64.urlsafe_b64encode(digest).decode().rstrip("=")


def _json_call(transport: HeaderTransport, method: str, url: str, *, form: Json | None = None,
               body: Json | None = None) -> tuple[int, Json]:
    headers = {"user-agent": UA, "accept": "application/json"}
    raw = None
    if form is not None:
        headers["content-type"] = "application/x-www-form-urlencoded"
        raw = urllib.parse.urlencode(form).encode()
    elif body is not None:
        headers["content-type"] = "application/json"
        raw = json.dumps(body).encode()
    status, _, data = transport(method, url, raw, headers)
    try:
        parsed = json.loads(data or b"{}")
    except ValueError:
        parsed = {"error_description": data.decode("utf-8", "replace")[:300]}
    return status, parsed if isinstance(parsed, dict) else {"value": parsed}


def discover(transport: HeaderTransport = header_transport) -> Json:
    """The authorization server's endpoints and the scopes the MCP resource uses."""
    status, resource = _json_call(transport, "GET", RESOURCE_METADATA)
    servers = resource.get("authorization_servers") or []
    if status != 200 or not servers:
        raise McpError(f"the MCP endpoint did not name an authorization server (HTTP {status})")
    issuer = urllib.parse.urlsplit(servers[0])
    candidates = [f"{issuer.scheme}://{issuer.netloc}/.well-known/oauth-authorization-server{issuer.path}",
                  f"{servers[0].rstrip('/')}/.well-known/oauth-authorization-server"]
    for url in candidates:
        status, meta = _json_call(transport, "GET", url)
        if status == 200 and meta.get("token_endpoint"):
            if "S256" not in (meta.get("code_challenge_methods_supported") or []):
                raise McpError("the authorization server does not offer PKCE with S256")
            meta["scopes_for_resource"] = resource.get("scopes_supported") or []
            return meta
    raise McpError("no authorization server metadata found")


def register(meta: Json, transport: HeaderTransport = header_transport) -> str:
    status, body = _json_call(transport, "POST", meta["registration_endpoint"], body={
        "client_name": "suno-cli (exobrain-harness)",
        "redirect_uris": [REDIRECT_URI],
        "grant_types": ["authorization_code", "refresh_token"],
        "response_types": ["code"],
        "token_endpoint_auth_method": "none",
    })
    if status not in (200, 201) or not body.get("client_id"):
        raise McpError(f"client registration failed (HTTP {status}): {body.get('error_description') or body}")
    return body["client_id"]


def authorize_url(meta: Json, client_id: str, challenge: str, state: str, scopes: list[str]) -> str:
    query = {"response_type": "code", "client_id": client_id, "redirect_uri": REDIRECT_URI,
             "scope": " ".join(scopes), "state": state, "code_challenge": challenge,
             "code_challenge_method": "S256", "resource": MCP_URL}
    return meta["authorization_endpoint"] + "?" + urllib.parse.urlencode(query)


def wait_for_code(state: str, timeout: float = 240) -> str:
    """Serve the loopback redirect once and return the authorization code."""
    result: Json = {}

    class Handler(http.server.BaseHTTPRequestHandler):
        def do_GET(self) -> None:  # noqa: N802 - the base class names it
            parts = urllib.parse.urlsplit(self.path)
            if parts.path != "/callback":
                self.send_response(404)
                self.end_headers()
                return
            query = dict(urllib.parse.parse_qsl(parts.query))
            ok = query.get("state") == state and "code" in query
            result.update(query if ok else {"error": query.get("error") or "state mismatch",
                                            "error_description": query.get("error_description", "")})
            page = ("Suno is connected. You can close this tab." if ok
                    else "The sign-in did not complete. Go back to the terminal.")
            self.send_response(200)
            self.send_header("content-type", "text/plain; charset=utf-8")
            self.end_headers()
            self.wfile.write(page.encode())

        def log_message(self, *args: Any) -> None:  # the code is in the request line: keep it off stderr
            return

    server = http.server.HTTPServer(("127.0.0.1", REDIRECT_PORT), Handler)
    server.timeout = 1
    deadline = time.time() + timeout
    try:
        while not result and time.time() < deadline:
            server.handle_request()
    finally:
        server.server_close()
    if not result:
        raise NotConnected("no answer from the browser before the time limit. If Suno's page said that "
                           "the connection is not available for the account, Suno has not opened the "
                           "official interface for it yet. Nothing was stored.")
    if "code" not in result:
        raise NotConnected(f"Suno did not approve the sign-in: {result.get('error')} "
                           f"{result.get('error_description', '')}".strip())
    return result["code"]


def _store_tokens(state: Json, tokens: Json, clock: Callable[[], float]) -> None:
    state["access_token"] = tokens["access_token"]
    state["expires_at"] = int(clock()) + int(tokens.get("expires_in") or 3600)
    if tokens.get("refresh_token"):
        state["refresh_token"] = tokens["refresh_token"]
    if tokens.get("scope"):
        state["scope"] = tokens["scope"]


def sign_in(transport: HeaderTransport = header_transport, opener: Callable[[str], None] | None = None,
            waiter: Callable[[str], str] = wait_for_code, clock: Callable[[], float] = time.time,
            persist: bool = True, state: Json | None = None) -> Json:
    """The whole browser sign-in. Returns the stored state (never print it)."""
    state = dict(state if state is not None else load())
    meta = discover(transport)
    state["token_endpoint"] = meta["token_endpoint"]
    state["revocation_endpoint"] = meta.get("revocation_endpoint")
    if not state.get("client_id"):
        state["client_id"] = register(meta, transport)
    verifier, challenge = pkce_pair()
    nonce = pysecrets.token_urlsafe(24)
    url = authorize_url(meta, state["client_id"], challenge, nonce, meta["scopes_for_resource"])
    (opener or (lambda u: subprocess.run(["open", u], check=False)))(url)
    code = waiter(nonce)
    status, tokens = _json_call(transport, "POST", meta["token_endpoint"], form={
        "grant_type": "authorization_code", "code": code, "redirect_uri": REDIRECT_URI,
        "client_id": state["client_id"], "code_verifier": verifier, "resource": MCP_URL})
    if status != 200 or not tokens.get("access_token"):
        raise NotConnected(f"Suno refused the code (HTTP {status}): "
                           f"{tokens.get('error_description') or tokens.get('error') or 'no token'}")
    _store_tokens(state, tokens, clock)
    state["connected_at"] = int(clock())
    if persist:
        save(state)
    return state


class OfficialAuth:
    """A fresh-enough access token from the stored sign-in."""

    def __init__(self, transport: HeaderTransport = header_transport, state: Json | None = None,
                 clock: Callable[[], float] = time.time, persist: bool = True) -> None:
        self.transport = transport
        self.clock = clock
        self.persist = persist
        self.state = state if state is not None else load()

    @property
    def connected(self) -> bool:
        return bool(self.state.get("refresh_token") or self.state.get("access_token"))

    def token(self, force: bool = False) -> str:
        if not self.connected:
            raise NotConnected("not connected to Suno's official interface. Run `suno connect`.")
        if not force and self.state.get("access_token") and self.clock() < self.state.get("expires_at", 0) - 60:
            return self.state["access_token"]
        if not self.state.get("refresh_token"):
            raise NotConnected("the official sign-in expired and has no refresh token. Run `suno connect`.")
        status, tokens = _json_call(self.transport, "POST", self.state["token_endpoint"], form={
            "grant_type": "refresh_token", "refresh_token": self.state["refresh_token"],
            "client_id": self.state["client_id"], "resource": MCP_URL})
        if status != 200 or not tokens.get("access_token"):
            raise NotConnected(f"Suno refused the stored sign-in (HTTP {status}). Run `suno connect`.")
        _store_tokens(self.state, tokens, self.clock)
        if self.persist:
            save(self.state)
        return self.state["access_token"]

    def disconnect(self) -> None:
        """Revoke the refresh token at Suno and delete the local copy."""
        token, endpoint = self.state.get("refresh_token"), self.state.get("revocation_endpoint")
        if token and endpoint:
            _json_call(self.transport, "POST", endpoint, form={
                "token": token, "token_type_hint": "refresh_token", "client_id": self.state.get("client_id", "")})
        self.state = {}
        if self.persist and OAUTH_PATH.exists():
            OAUTH_PATH.unlink()


# -- MCP ---------------------------------------------------------------------------------------


def parse_rpc(content_type: str, data: bytes, want_id: int) -> Json:
    """The JSON-RPC answer for ``want_id`` out of a JSON body or an event stream."""
    text = data.decode("utf-8", "replace")
    if "text/event-stream" in content_type:
        messages = []
        for block in text.replace("\r\n", "\n").split("\n\n"):
            payload = "\n".join(line[5:].lstrip() for line in block.split("\n") if line.startswith("data:"))
            if payload:
                try:
                    messages.append(json.loads(payload))
                except ValueError:
                    continue
    else:
        try:
            parsed = json.loads(text) if text.strip() else {}
        except ValueError as err:
            raise McpError(f"the endpoint sent text that is not JSON: {text[:200]}") from err
        messages = parsed if isinstance(parsed, list) else [parsed]
    for message in messages:
        if isinstance(message, dict) and message.get("id") == want_id:
            return message
    raise McpError("the endpoint sent no answer to the request")


class McpClient:
    def __init__(self, auth: OfficialAuth, transport: HeaderTransport = header_transport, url: str = MCP_URL) -> None:
        self.auth = auth
        self.transport = transport
        self.url = url
        self.session_id: str | None = None
        self.version: str | None = None
        self.server: Json = {}
        self._next_id = 0

    def _post(self, payload: Json) -> tuple[int, dict[str, str], bytes]:
        headers = {"authorization": f"Bearer {self.auth.token()}", "content-type": "application/json",
                   "accept": "application/json, text/event-stream", "user-agent": UA}
        if self.session_id:
            headers["mcp-session-id"] = self.session_id
        if self.version:
            headers["mcp-protocol-version"] = self.version
        return self.transport("POST", self.url, json.dumps(payload).encode(), headers)

    def request(self, method: str, params: Json | None = None) -> Any:
        self._next_id += 1
        payload: Json = {"jsonrpc": "2.0", "id": self._next_id, "method": method}
        if params is not None:
            payload["params"] = params
        status, headers, data = self._post(payload)
        if status == 401:  # the token died early: one new token, one resend
            self.auth.token(force=True)
            status, headers, data = self._post(payload)
        if status == 401:
            raise NotConnected("Suno's official endpoint refused the sign-in. Run `suno connect`.")
        if status >= 400:
            raise McpError(f"HTTP {status} from the official endpoint: {data.decode('utf-8', 'replace')[:300]}", status)
        if headers.get("mcp-session-id"):
            self.session_id = headers["mcp-session-id"]
        answer = parse_rpc(headers.get("content-type", ""), data, self._next_id)
        if "error" in answer:
            err = answer["error"] or {}
            raise McpError(str(err.get("message") or err), err.get("code"), err.get("data"))
        return answer.get("result")

    def initialize(self) -> Json:
        if self.version:
            return self.server
        result = self.request("initialize", {"protocolVersion": PROTOCOL_VERSION, "capabilities": {},
                                             "clientInfo": CLIENT_INFO}) or {}
        self.version = result.get("protocolVersion") or PROTOCOL_VERSION
        self.server = result
        self._post({"jsonrpc": "2.0", "method": "notifications/initialized"})
        return result

    def tools(self) -> list[Json]:
        self.initialize()
        out: list[Json] = []
        cursor = None
        while True:
            result = self.request("tools/list", {"cursor": cursor} if cursor else {}) or {}
            out.extend(result.get("tools") or [])
            cursor = result.get("nextCursor")
            if not cursor:
                return out

    def call(self, name: str, arguments: Json | None = None) -> Json:
        """Call one tool. Returns ``{"data": parsed-or-None, "text": str, "raw": result}``."""
        self.initialize()
        result = self.request("tools/call", {"name": name, "arguments": arguments or {}}) or {}
        text = "\n".join(str(c.get("text")) for c in result.get("content") or [] if c.get("type") == "text")
        if result.get("isError"):
            raise McpError(text or "the tool reported an error", data=result)
        data = result.get("structuredContent")
        if data is None and text:
            try:
                data = json.loads(text)
            except ValueError:
                data = None
        return {"data": data, "text": text, "raw": result}
