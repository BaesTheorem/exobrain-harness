#!/usr/bin/env python3
"""
niu_cloud.py -- the few NIU cloud calls the scooter CLI needs.

The BLE password that authenticates a phone to a NIU vehicle is not printed
anywhere; the app fetches it from NIU's cloud for a vehicle bound to your
account.  This module logs in the way the Android app does and pulls it:

  POST account-fk.niu.com/v3/api/oauth2/token   account, password=md5(pw), grant_type=password, scope=base, app_id
  GET  app-api-fk.niu.com/v5/scooter/list       header token: <access_token>
  GET  app-api-fk.niu.com/v5/scooter/detail/<sn>
  GET  app-api-fk.niu.com/v5/ble/bleinfo?sn=<sn>   -> bleMac, blePassword, bleAes, bleSign, bleName, bus_protocol_type

Every reply is {"status": 0, "desc": ..., "data": ...}; status != 0 is an error.
"-fk" hosts are the overseas region; the domestic region uses app-api.niu.com.

Credentials live in secrets/ (gitignored), see secrets/README.md.
"""
from __future__ import annotations

import hashlib
import json
import os
import time
import urllib.error
import urllib.parse
import urllib.request

HERE = os.path.dirname(os.path.abspath(__file__))
SECRETS = os.path.join(HERE, "secrets")
SESSION_FILE = os.path.join(SECRETS, "session.json")
SCOOTER_FILE = os.path.join(SECRETS, "scooter.json")

ACCOUNT_HOST = "https://account-fk.niu.com/"
API_HOST = "https://app-api-fk.niu.com/"
APP_IDS = ("niu_8xt1afu6", "niu_ktdrr960")  # overseas release, then domestic release
USER_AGENT = ("manager/5.12.2 (android; Pixel 8 14);lang=en-US;clientIdentifier=Overseas;"
              "timezone=America/Chicago;model=google_Pixel 8;deviceName=Pixel 8;ostype=android")


class CloudError(Exception):
    pass


def _headers(token: str | None = None, json_body: bool = False) -> dict:
    h = {"User-Agent": USER_AGENT, "X-No-Encrypt": "1", "Accept": "application/json"}
    if token:
        h["token"] = token
    if json_body:
        h["Content-Type"] = "application/json"
    return h


def _call(method: str, url: str, token: str | None = None, form: dict | None = None,
          query: dict | None = None, timeout: int = 30) -> dict:
    if query:
        url += ("&" if "?" in url else "?") + urllib.parse.urlencode(query)
    data = urllib.parse.urlencode(form).encode() if form is not None else None
    req = urllib.request.Request(url, data=data, method=method, headers=_headers(token))
    if form is not None:
        req.add_header("Content-Type", "application/x-www-form-urlencoded")
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            body = resp.read().decode("utf-8", errors="replace")
    except urllib.error.HTTPError as e:
        body = e.read().decode("utf-8", errors="replace")
        try:
            j = json.loads(body)
        except ValueError:
            raise CloudError(f"HTTP {e.code} from {url}: {body[:200]}") from None
        raise CloudError(f"HTTP {e.code}: {j.get('desc') or j.get('message') or body[:200]}") from None
    try:
        j = json.loads(body)
    except ValueError:
        raise CloudError(f"non-JSON reply from {url}: {body[:200]}") from None
    if j.get("status", 0) != 0:
        raise CloudError(f"NIU says: {j.get('desc') or j} (status {j.get('status')})")
    return j.get("data")


# ----------------------------------------------------------------------------- session

def load_json(path: str) -> dict | None:
    try:
        with open(path, encoding="utf-8") as f:
            return json.load(f)
    except FileNotFoundError:
        return None


def save_json(path: str, obj: dict) -> None:
    os.makedirs(os.path.dirname(path), exist_ok=True)
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(obj, f, indent=1, sort_keys=True)
    os.chmod(tmp, 0o600)
    os.replace(tmp, path)


def login(account: str, password: str, app_id: str | None = None) -> dict:
    """Password login; the app sends md5(password). Tries both app ids unless one is given."""
    last = None
    for aid in ([app_id] if app_id else APP_IDS):
        form = {"account": account, "password": hashlib.md5(password.encode("utf-8")).hexdigest(),
                "grant_type": "password", "scope": "base", "app_id": aid}
        try:
            data = _call("POST", ACCOUNT_HOST + "v3/api/oauth2/token", form=form)
        except CloudError as e:
            last = e
            continue
        tok = (data or {}).get("token") or {}
        if not tok.get("access_token"):
            last = CloudError(f"login reply had no token: {data}")
            continue
        sess = {"account": account, "app_id": aid, "token": tok["access_token"],
                "refresh_token": tok.get("refresh_token", ""),
                "expires_at": int(time.time()) + int(tok.get("token_expires_in") or 0),
                "user": {k: (data.get("user") or {}).get(k) for k in ("id", "name", "email", "mobile", "country_code")}}
        save_json(SESSION_FILE, sess)
        return sess
    raise last or CloudError("login failed")


def refresh(sess: dict) -> dict:
    form = {"refresh_token": sess["refresh_token"], "grant_type": "refresh_token", "scope": "base",
            "app_id": sess.get("app_id", APP_IDS[0])}
    data = _call("POST", ACCOUNT_HOST + "v3/api/oauth2/token", form=form)
    tok = (data or {}).get("token") or {}
    if not tok.get("access_token"):
        raise CloudError(f"refresh reply had no token: {data}")
    sess.update(token=tok["access_token"], refresh_token=tok.get("refresh_token", sess["refresh_token"]),
                expires_at=int(time.time()) + int(tok.get("token_expires_in") or 0))
    save_json(SESSION_FILE, sess)
    return sess


def session() -> dict:
    sess = load_json(SESSION_FILE)
    if not sess or not sess.get("token"):
        raise CloudError("not logged in; run: kqi login you@example.com")
    if sess.get("expires_at", 0) and sess["expires_at"] < time.time() + 3600 and sess.get("refresh_token"):
        try:
            sess = refresh(sess)
        except CloudError:
            pass
    return sess


# ----------------------------------------------------------------------------- vehicle data

def scooters(token: str) -> list[dict]:
    data = _call("GET", API_HOST + "v5/scooter/list", token=token)
    if isinstance(data, dict):
        data = data.get("items") or data.get("list") or []
    return data or []


def detail(token: str, sn: str) -> dict:
    return _call("GET", API_HOST + "v5/scooter/detail/" + urllib.parse.quote(sn), token=token) or {}


def bleinfo(token: str, sn: str) -> dict:
    return _call("GET", API_HOST + "v5/ble/bleinfo", token=token, query={"sn": sn}) or {}


def load_scooter() -> dict:
    sc = load_json(SCOOTER_FILE)
    if not sc or not sc.get("ble", {}).get("mac"):
        raise CloudError("no scooter credentials; run: kqi setup")
    return sc


def save_scooter(sc: dict) -> None:
    save_json(SCOOTER_FILE, sc)
