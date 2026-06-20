#!/usr/bin/env python3
"""
alias.py — disposable email alias system for Alex.

Mints segregated, throwaway email aliases that all FORWARD INTO Alex's Gmail, so
MIST can read verification codes via the Gmail MCP and finish signups. Every alias
is tracked in a gitignored registry (which service it was for, when, status) so a
leaked/sold address is identifiable and can be burned + replaced.

Backends (schemes):
  gmail-plus  (default) alex.hedtke+<service>@gmail.com  — works instantly, no setup.
  gmail-dot             dotted variant (hides the +tag for forms that reject '+').
  addy                  addy.io API alias (true disposability) — needs ADDY_API_KEY.

Usage:
  alias.py mint <service> [--scheme gmail-plus|gmail-dot|addy] [--note "..."]
  alias.py list [--service <s>]
  alias.py note <alias> <text...>
  alias.py burn <alias>                 # mark disabled (and deactivate via API if addy)
  alias.py read <service-or-alias>      # print the Gmail search query MIST should run

Reading the verification email is MIST's job at runtime (Gmail MCP); `read` just
emits the exact `to:<alias> newer_than:1d` query to hand to search_threads.
"""
import sys, os, json, time, datetime, re

BASE_EMAIL = "alex.hedtke@gmail.com"
BASE_USER, BASE_DOMAIN = BASE_EMAIL.split("@")
HERE = os.path.dirname(os.path.abspath(__file__))
REGISTRY = os.path.join(HERE, "aliases.json")           # gitignored — personal data
SECRETS = os.path.join(HERE, "secrets.json")            # gitignored — addy.io API key etc.

def _load():
    if os.path.exists(REGISTRY):
        return json.load(open(REGISTRY))
    return []

def _save(rows):
    json.dump(rows, open(REGISTRY, "w"), indent=2)

def _slug(s):
    return re.sub(r"[^a-z0-9]+", "", s.lower())[:24] or "x"

def _today():
    return datetime.date.today().isoformat()

def _unique_tag(rows, service):
    """Clean tag per service; if the service already has a live alias, suffix -2, -3…
    (disposable: you can always mint a fresh one for the same service)."""
    base = _slug(service)
    existing = {r.get("tag") for r in rows}
    if base not in existing:
        return base
    n = 2
    while f"{base}-{n}" in existing:
        n += 1
    return f"{base}-{n}"

def mint(service, scheme="gmail-plus", note=""):
    rows = _load()
    if scheme == "gmail-plus":
        tag = _unique_tag(rows, service)
        alias = f"{BASE_USER}+{tag}@{BASE_DOMAIN}"
    elif scheme == "gmail-dot":
        # deterministic dotted variant of the username (Gmail ignores dots)
        tag = _slug(service)
        u = BASE_USER.replace(".", "")
        # insert a dot after a position derived from the service name (stable, readable)
        pos = (sum(ord(c) for c in tag) % (len(u) - 1)) + 1
        alias = f"{u[:pos]}.{u[pos:]}@{BASE_DOMAIN}"
    elif scheme == "catchall":
        # Catch-all domain (e.g. Cloudflare Email Routing *@domain -> Gmail). Any address
        # works without pre-registering, so minting is just local string + registry log.
        dom = None
        if os.path.exists(SECRETS):
            dom = json.load(open(SECRETS)).get("catchall_domain")
        if not dom:
            return ("CATCHALL_NOT_CONFIGURED: add {\"catchall_domain\":\"yourdomain.com\"} to "
                    "%s (point the domain at Cloudflare, enable Email Routing catch-all "
                    "*@domain -> %s)" % (SECRETS, BASE_EMAIL))
        tag = _unique_tag(rows, service)        # reuse the -2/-3 uniqueness logic
        alias = f"{tag}@{dom}"
    elif scheme == "addy":
        return addy_mint(service, note)
    else:
        return "BAD_SCHEME %s" % scheme
    row = {"alias": alias, "tag": tag, "service": service, "scheme": scheme,
           "created": _today(), "status": "active", "note": note}
    rows.append(row)
    _save(rows)
    return alias

def addy_mint(service, note=""):
    """Create an addy.io alias via API. Requires secrets.json {"addy_api_key": "...",
    "addy_domain": "anonaddy.me"}. Aliases forward to Alex's Gmail (set in addy account)."""
    if not os.path.exists(SECRETS):
        return ("ADDY_NOT_CONFIGURED: create %s with {\"addy_api_key\":\"...\","
                "\"addy_domain\":\"anonaddy.me\"} (sign up at addy.io, set the default "
                "recipient to %s)" % (SECRETS, BASE_EMAIL))
    import urllib.request
    cfg = json.load(open(SECRETS))
    body = json.dumps({"domain": cfg.get("addy_domain", "anonaddy.me"),
                       "description": "%s (%s)" % (service, _today())}).encode()
    req = urllib.request.Request("https://app.addy.io/api/v1/aliases", data=body,
                                 headers={"Authorization": "Bearer " + cfg["addy_api_key"],
                                          "Content-Type": "application/json",
                                          "Accept": "application/json"})
    try:
        resp = json.load(urllib.request.urlopen(req, timeout=20))
        alias = resp["data"]["email"]
    except Exception as e:
        return "ADDY_ERR %s" % e
    rows = _load()
    rows.append({"alias": alias, "tag": _slug(service), "service": service, "scheme": "addy",
                 "created": _today(), "status": "active", "note": note})
    _save(rows)
    return alias

def list_aliases(service=None):
    rows = _load()
    if service:
        rows = [r for r in rows if service.lower() in r["service"].lower()]
    if not rows:
        return "(no aliases yet)"
    out = []
    for r in rows:
        flag = "" if r["status"] == "active" else " [%s]" % r["status"]
        out.append("%-34s  %-14s  %-10s  %s%s" % (
            r["alias"], r["service"], r["created"], r["scheme"], flag)
            + ("  — " + r["note"] if r.get("note") else ""))
    return "\n".join(out)

def note(alias, text):
    rows = _load()
    for r in rows:
        if r["alias"] == alias:
            r["note"] = text
            _save(rows)
            return "noted: " + alias
    return "NOT_FOUND " + alias

def burn(alias):
    rows = _load()
    for r in rows:
        if r["alias"] == alias:
            r["status"] = "burned"
            _save(rows)
            # (addy aliases can also be deactivated via API — add if/when used heavily)
            return "burned: " + alias + " (stop using it; mint a fresh one for that service)"
    return "NOT_FOUND " + alias

def read_query(target):
    """Emit the Gmail query MIST runs to fetch the latest verification mail for an alias."""
    rows = _load()
    alias = None
    for r in rows:
        if r["alias"] == target or r["tag"] == _slug(target) or target.lower() in r["service"].lower():
            alias = r["alias"]
            break
    alias = alias or target
    return 'to:%s newer_than:1d   (hand to Gmail search_threads, then get_thread FULL_CONTENT)' % alias

def main():
    a = sys.argv[1:]
    if not a:
        print(__doc__); return
    c = a[0]
    if c == "mint":
        scheme = "gmail-plus"; note_txt = ""
        rest = a[1:]
        if "--scheme" in rest:
            i = rest.index("--scheme"); scheme = rest[i + 1]; del rest[i:i + 2]
        if "--note" in rest:
            i = rest.index("--note"); note_txt = rest[i + 1]; del rest[i:i + 2]
        if not rest:
            print("usage: alias.py mint <service> [--scheme ...] [--note ...]"); return
        out = mint(rest[0], scheme, note_txt)
        print(out)
        if scheme in ("gmail-plus", "gmail-dot") and out.endswith("@" + BASE_DOMAIN):
            print("  ⚠ this NORMALIZES to %s — NOT safe for anything that might get banned"
                  " (e.g. game accounts). Use --scheme addy for a separate-domain alias that"
                  " can't poison your main email." % BASE_EMAIL)
    elif c == "list":
        print(list_aliases(a[2] if len(a) > 2 and a[1] == "--service" else None))
    elif c == "note":
        print(note(a[1], " ".join(a[2:])))
    elif c == "burn":
        print(burn(a[1]))
    elif c == "read":
        print(read_query(a[1]))
    else:
        print(__doc__)

if __name__ == "__main__":
    main()
