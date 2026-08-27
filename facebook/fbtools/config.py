"""Paths, cookie loading, and named crawl targets. No secrets in this file."""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parent.parent
SECRETS = ROOT / "secrets"
DATA = ROOT / "data"
REPORT = ROOT / "report"
PROFILE = ROOT / ".profile"

COOKIE_FILE_CANDIDATES = [
    SECRETS / "cookies.txt",  # Netscape ("Get cookies.txt LOCALLY")
    SECRETS / "cookies.json",  # JSON array (EditThisCookie / manual)
]
# name -> feed URL. A private group/page URL is identifying, so it's a secret.
TARGETS_FILE = SECRETS / "targets.json"

# `xs` is the session secret, `c_user` the user id. Both are required to auth.
REQUIRED_COOKIES = {"c_user", "xs"}


@dataclass(frozen=True)
class Target:
    """One thing we crawl (a group, page, or profile feed), with its own data."""

    name: str

    @property
    def data(self) -> Path:
        return DATA / self.name

    @property
    def raw(self) -> Path:
        return self.data / "raw"

    @property
    def report(self) -> Path:
        return REPORT / self.name

    @property
    def cursor_file(self) -> Path:
        return self.data / "cursor.json"

    @property
    def posts_file(self) -> Path:
        return self.data / "posts.jsonl"


def _load_targets() -> dict[str, str]:
    if TARGETS_FILE.exists():
        return json.loads(TARGETS_FILE.read_text(encoding="utf-8"))
    return {}


def resolve_target(name: str, url: str | None = None) -> tuple[Target, str]:
    """Return (Target, feed URL). Saves the URL under `name` when provided."""
    targets = _load_targets()
    if url:
        targets[name] = url.strip()
        TARGETS_FILE.parent.mkdir(parents=True, exist_ok=True)
        TARGETS_FILE.write_text(json.dumps(targets, indent=2), encoding="utf-8")
    if name not in targets:
        raise SystemExit(
            f"Unknown target {name!r}. Set it once with:\n"
            f"  fb crawl {name} --url <facebook feed URL>\n"
            f"Known targets: {sorted(targets) or 'none yet'}"
        )
    return Target(name), targets[name]


def list_targets() -> dict[str, str]:
    return _load_targets()


def _from_netscape(path: Path) -> list[dict[str, Any]]:
    cookies: list[dict[str, Any]] = []
    for line in path.read_text(encoding="utf-8").splitlines():
        raw = line.rstrip("\n")
        if not raw.strip():
            continue
        # Netscape marks HttpOnly cookies with a `#HttpOnly_` domain prefix.
        # Keep those; skip only genuine comment lines.
        if raw.startswith("#HttpOnly_"):
            raw = raw[len("#HttpOnly_") :]
        elif raw.lstrip().startswith("#"):
            continue
        parts = raw.split("\t")
        if len(parts) != 7:
            continue
        domain, _flag, cpath, secure, expiry, name, value = parts
        cookies.append(
            {
                "name": name,
                "value": value,
                "domain": domain,
                "path": cpath or "/",
                "secure": secure.upper() == "TRUE",
                "expires": int(expiry) if expiry.lstrip("-").isdigit() else -1,
            }
        )
    return cookies


def _from_json(path: Path) -> list[dict[str, Any]]:
    raw = json.loads(path.read_text(encoding="utf-8"))
    items = raw["cookies"] if isinstance(raw, dict) and "cookies" in raw else raw
    cookies: list[dict[str, Any]] = []
    for c in items:
        name, value = c.get("name"), c.get("value")
        if not name or value is None:
            continue
        cookie: dict[str, Any] = {
            "name": name,
            "value": value,
            "domain": c.get("domain") or ".facebook.com",
            "path": c.get("path", "/"),
            "secure": bool(c.get("secure", True)),
        }
        exp = c.get("expirationDate") or c.get("expires")
        if isinstance(exp, (int, float)) and exp > 0:
            cookie["expires"] = int(exp)
        cookies.append(cookie)
    return cookies


def load_cookies() -> list[dict[str, Any]]:
    """Load FB cookies from whichever export format is in secrets/, as
    Playwright-shaped dicts. Raises clearly if missing or not logged in."""
    src = next((p for p in COOKIE_FILE_CANDIDATES if p.exists()), None)
    if src is None:
        raise SystemExit(
            "No cookie file found. Export facebook.com cookies to\n"
            f"  {COOKIE_FILE_CANDIDATES[0]}   (Netscape .txt), or\n"
            f"  {COOKIE_FILE_CANDIDATES[1]}   (JSON).\nSee facebook/README.md."
        )
    cookies = _from_netscape(src) if src.suffix == ".txt" else _from_json(src)
    for c in cookies:
        c.setdefault("sameSite", "Lax")
        if c.get("sameSite") not in {"Strict", "Lax", "None"}:
            c["sameSite"] = "Lax"
    missing = REQUIRED_COOKIES - {c["name"] for c in cookies}
    if missing:
        raise SystemExit(
            f"Cookie file {src.name} is missing required cookie(s): {sorted(missing)}.\n"
            "Re-export while logged in to facebook.com."
        )
    return cookies


def cookie_health() -> dict[str, Any]:
    """Cheap, side-effect-free check of the cookie file, for `fb status`."""
    src = next((p for p in COOKIE_FILE_CANDIDATES if p.exists()), None)
    if src is None:
        return {"ok": False, "reason": "no cookie file"}
    cookies = _from_netscape(src) if src.suffix == ".txt" else _from_json(src)
    names = {c["name"] for c in cookies}
    return {
        "ok": REQUIRED_COOKIES <= names,
        "source": src.name,
        "count": len(cookies),
        "has_required": sorted(REQUIRED_COOKIES & names),
        "missing": sorted(REQUIRED_COOKIES - names),
    }


def sanitize_feed_url(url: str) -> str:
    """Force chronological sort so history walks deterministically."""
    if "sorting_setting" in url:
        return url
    sep = "&" if "?" in url else "?"
    return f"{url}{sep}sorting_setting=CHRONOLOGICAL"


_GROUP_ID_RE = re.compile(r"/groups/(\d+)")


def group_id_from_url(url: str) -> str | None:
    m = _GROUP_ID_RE.search(url)
    return m.group(1) if m else None
