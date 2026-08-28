#!/usr/bin/env python3
"""Google Drive API uploader for the exobrain collective backups.

Replaces the DriveFS-mount upload path (drop file in ~/My Drive, poll for the
item-id xattr, pray). DriveFS's background sync gives up after a few retries
and reverts the cloud file when the Mac sleeps through them -- five data-loss
incidents between 2026-07-20 and 2026-08-28. The Drive API's resumable upload
sessions have none of that: the session URI stays valid for about a week, each
chunk resumes from the last byte the server acknowledged, and sleep, process
death, or a reboot just pauses progress instead of destroying it.

Runs on stock /usr/bin/python3 (stdlib only). Invoked by backup-exobrain.sh via
`python3 - <args> < this-file` so the python process never has to open a file
under ~/Documents itself (TCC: bash in the launchd job provably can, python may
not; stdin sidesteps the question). Therefore __file__ must never be used.

Scope note: uses the full `drive` scope, not `drive.file`, because it must see
and prune archives the old DriveFS path created -- drive.file only sees files
this client itself uploaded.

INVARIANTS:
- Never deletes a cloud archive unless this run confirmed the newest archive's
  upload (prune is only invoked by the caller after a confirmed upload) and the
  file's name parses as an archive timestamp.
- The upload state file is removed only after the cloud md5 matches the local
  md5; a mismatch deletes the cloud file, not the local one.
- The local archive file is never deleted or modified here; the caller owns
  local retention.
- The ledger (uploaded.log) is append-only from here.

Subcommands:
  auth              one-time interactive consent -> refresh token
  upload FILE       resumable upload into the backup folder (resumes state)
  verify NAME       exit 0 iff NAME exists in the backup folder (prints id/md5)
  list              list archives in the backup folder
  prune             GFS retention over cloud archives (--daily/--weekly/--monthly)
  delete NAME       delete one file by exact name (test cleanup)
"""

from __future__ import annotations

import argparse
import datetime as dt
import hashlib
import json
import os
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

TOKEN_URL = "https://oauth2.googleapis.com/token"
AUTH_URL = "https://accounts.google.com/o/oauth2/v2/auth"
API = "https://www.googleapis.com/drive/v3"
UPLOAD_API = "https://www.googleapis.com/upload/drive/v3"
SCOPE = "https://www.googleapis.com/auth/drive"
REDIRECT_URI = "https://www.google.com"

CHUNK = 32 * 1024 * 1024  # multiple of 256 KiB, small enough for a slow uplink
ARCHIVE_PREFIX = "exobrain-collective-"
ARCHIVE_SUFFIX = ".tar.gz"

HARNESS_DIR = Path(os.environ.get("EXOBRAIN_HARNESS_DIR", str(Path.home() / "Documents/Exobrain harness")))
STAGING_DIR = Path(os.environ.get("BACKUP_STAGING_DIR", str(Path.home() / "Exobrain backup staging")))
FOLDER_NAME = os.environ.get("BACKUP_DRIVE_FOLDER_NAME", "Exobrain backups")
TOKEN_FILE = STAGING_DIR / ".drive-token.json"
LEDGER_FILE = STAGING_DIR / "uploaded.log"


def log(msg: str) -> None:
    print(f"[{dt.datetime.now():%a %b %d %H:%M:%S %Y}] {msg}", flush=True)


def load_env_file(path: Path) -> dict[str, str]:
    env: dict[str, str] = {}
    if path.exists():
        for line in path.read_text().splitlines():
            line = line.strip()
            if line and not line.startswith("#") and "=" in line:
                k, _, v = line.partition("=")
                env[k.strip()] = v.strip()
    return env


def client_creds() -> tuple[str, str]:
    env = load_env_file(HARNESS_DIR / ".env")
    cid = os.environ.get("GOOGLE_OAUTH_CLIENT_ID") or env.get("GOOGLE_OAUTH_CLIENT_ID", "")
    sec = os.environ.get("GOOGLE_OAUTH_CLIENT_SECRET") or env.get("GOOGLE_OAUTH_CLIENT_SECRET", "")
    if not cid or not sec:
        sys.exit("GOOGLE_OAUTH_CLIENT_ID / GOOGLE_OAUTH_CLIENT_SECRET missing (harness .env)")
    return cid, sec


# --- token handling -----------------------------------------------------------


def read_token() -> dict[str, object]:
    if not TOKEN_FILE.exists():
        sys.exit(f"No Drive token at {TOKEN_FILE}; run the auth subcommand once first")
    return json.loads(TOKEN_FILE.read_text())


def write_token(tok: dict[str, object]) -> None:
    STAGING_DIR.mkdir(parents=True, exist_ok=True)
    tmp = TOKEN_FILE.with_suffix(".json.tmp")
    tmp.write_text(json.dumps(tok, indent=2))
    tmp.chmod(0o600)
    tmp.replace(TOKEN_FILE)


def access_token() -> str:
    """Return a valid access token, refreshing if it expires within 5 minutes."""
    tok = read_token()
    exp_raw = tok.get("expires_at", 0)
    exp = float(exp_raw) if isinstance(exp_raw, (int, float)) else 0.0
    at = str(tok.get("access_token", "") or "")
    if at and exp - time.time() > 300:
        return at
    cid, sec = client_creds()
    body = urllib.parse.urlencode(
        {
            "client_id": cid,
            "client_secret": sec,
            "refresh_token": str(tok["refresh_token"]),
            "grant_type": "refresh_token",
        }
    ).encode()
    req = urllib.request.Request(TOKEN_URL, data=body, method="POST")
    with urllib.request.urlopen(req, timeout=60) as resp:
        data = json.loads(resp.read())
    tok["access_token"] = data["access_token"]
    tok["expires_at"] = time.time() + float(data.get("expires_in", 3600))
    write_token(tok)
    return str(tok["access_token"])


# --- thin API helpers -----------------------------------------------------------


def api_json(
    method: str,
    url: str,
    *,
    body: bytes | None = None,
    content_type: str = "application/json",
    retries: int = 5,
) -> dict[str, object]:
    """JSON API call with token auth and backoff on 401/5xx/network errors."""
    delay = 2.0
    for attempt in range(retries):
        req = urllib.request.Request(url, data=body, method=method)
        req.add_header("Authorization", f"Bearer {access_token()}")
        if body is not None:
            req.add_header("Content-Type", content_type)
        try:
            with urllib.request.urlopen(req, timeout=120) as resp:
                raw = resp.read()
                return json.loads(raw) if raw.strip() else {}
        except urllib.error.HTTPError as e:
            if e.code == 401 and attempt < retries - 1:
                # stale cached access token; force a refresh on the next loop
                tok = read_token()
                tok["expires_at"] = 0
                write_token(tok)
                continue
            if e.code in (429, 500, 502, 503, 504) and attempt < retries - 1:
                time.sleep(delay)
                delay *= 2
                continue
            detail = e.read().decode(errors="replace")[:500]
            raise RuntimeError(f"{method} {url} -> HTTP {e.code}: {detail}") from e
        except (urllib.error.URLError, TimeoutError):
            if attempt < retries - 1:
                time.sleep(delay)
                delay *= 2
                continue
            raise
    raise RuntimeError("unreachable")


def find_folder_id() -> str:
    q = (
        f"name = '{FOLDER_NAME}' and mimeType = 'application/vnd.google-apps.folder' "
        "and 'root' in parents and trashed = false"
    )
    url = f"{API}/files?" + urllib.parse.urlencode({"q": q, "fields": "files(id,name)"})
    files = api_json("GET", url).get("files", [])
    if isinstance(files, list) and files:
        return str(files[0]["id"])  # type: ignore[index]
    created = api_json(
        "POST",
        f"{API}/files?fields=id",
        body=json.dumps(
            {"name": FOLDER_NAME, "mimeType": "application/vnd.google-apps.folder"}
        ).encode(),
    )
    log(f"Created Drive folder '{FOLDER_NAME}'")
    return str(created["id"])


def list_archives(folder_id: str) -> list[dict[str, object]]:
    out: list[dict[str, object]] = []
    page = ""
    while True:
        params = {
            "q": f"'{folder_id}' in parents and trashed = false",
            "fields": "nextPageToken, files(id,name,size,md5Checksum,createdTime)",
            "pageSize": "200",
        }
        if page:
            params["pageToken"] = page
        data = api_json("GET", f"{API}/files?" + urllib.parse.urlencode(params))
        files = data.get("files", [])
        if isinstance(files, list):
            out.extend(f for f in files if isinstance(f, dict))
        page = str(data.get("nextPageToken", "") or "")
        if not page:
            return out


def find_by_name(folder_id: str, name: str) -> dict[str, object] | None:
    for f in list_archives(folder_id):
        if f.get("name") == name:
            return f
    return None


# --- subcommands -----------------------------------------------------------------


def cmd_auth() -> None:
    cid, sec = client_creds()
    url = AUTH_URL + "?" + urllib.parse.urlencode(
        {
            "client_id": cid,
            "redirect_uri": REDIRECT_URI,
            "response_type": "code",
            "scope": SCOPE,
            "access_type": "offline",
            "prompt": "consent",
        }
    )
    print("Open this URL, approve, then paste the FULL redirected URL (google.com/?code=...):")
    print(url)
    pasted = input("Redirected URL or code: ").strip()
    code = pasted
    if "code=" in pasted:
        code = urllib.parse.parse_qs(urllib.parse.urlparse(pasted).query)["code"][0]
    body = urllib.parse.urlencode(
        {
            "client_id": cid,
            "client_secret": sec,
            "code": code,
            "grant_type": "authorization_code",
            "redirect_uri": REDIRECT_URI,
        }
    ).encode()
    req = urllib.request.Request(TOKEN_URL, data=body, method="POST")
    with urllib.request.urlopen(req, timeout=60) as resp:
        data = json.loads(resp.read())
    if "refresh_token" not in data:
        sys.exit(f"No refresh_token in response: {data}")
    write_token(
        {
            "refresh_token": data["refresh_token"],
            "access_token": data.get("access_token", ""),
            "expires_at": time.time() + float(data.get("expires_in", 0)),
            "scope": SCOPE,
            "minted_at": dt.datetime.now().isoformat(timespec="seconds"),
        }
    )
    print(f"Token saved to {TOKEN_FILE}")


def md5_file(path: Path) -> str:
    h = hashlib.md5()
    with path.open("rb") as fh:
        while chunk := fh.read(8 * 1024 * 1024):
            h.update(chunk)
    return h.hexdigest()


def start_session(folder_id: str, name: str, size: int) -> str:
    meta = json.dumps({"name": name, "parents": [folder_id]}).encode()
    req = urllib.request.Request(
        f"{UPLOAD_API}/files?uploadType=resumable&fields=id,name,md5Checksum",
        data=meta,
        method="POST",
    )
    req.add_header("Authorization", f"Bearer {access_token()}")
    req.add_header("Content-Type", "application/json")
    req.add_header("X-Upload-Content-Type", "application/gzip")
    req.add_header("X-Upload-Content-Length", str(size))
    with urllib.request.urlopen(req, timeout=120) as resp:
        loc = resp.headers.get("Location")
    if not loc:
        raise RuntimeError("resumable session: no Location header")
    return loc


def query_session_offset(session_uri: str, size: int) -> tuple[int, dict[str, object] | None]:
    """Ask the session where to resume. Returns (offset, completed-file-or-None)."""
    req = urllib.request.Request(session_uri, data=b"", method="PUT")
    req.add_header("Content-Range", f"bytes */{size}")
    try:
        with urllib.request.urlopen(req, timeout=120) as resp:
            return size, json.loads(resp.read())  # 200/201: already complete
    except urllib.error.HTTPError as e:
        if e.code == 308:
            rng = e.headers.get("Range")  # "bytes=0-N" or absent (nothing stored)
            return (int(rng.rsplit("-", 1)[1]) + 1 if rng else 0), None
        raise


def state_path(archive: Path) -> Path:
    return archive.with_name(archive.name + ".driveupload.json")


def cmd_upload(file_arg: str, deadline_min: int) -> None:
    archive = Path(file_arg)
    if not archive.is_file():
        sys.exit(f"no such file: {archive}")
    size = archive.stat().st_size
    deadline = time.time() + deadline_min * 60
    folder_id = find_folder_id()

    existing = find_by_name(folder_id, archive.name)
    local_md5 = md5_file(archive)
    if existing and existing.get("md5Checksum") == local_md5:
        log(f"Already on Drive with matching md5 (id {existing['id']}); nothing to do")
        record_ledger(archive.name, str(existing["id"]), local_md5)
        state_path(archive).unlink(missing_ok=True)
        return

    st = state_path(archive)
    session_uri = ""
    if st.exists():
        try:
            prev = json.loads(st.read_text())
            if prev.get("size") == size and prev.get("mtime") == archive.stat().st_mtime:
                session_uri = str(prev.get("session_uri", "") or "")
        except (json.JSONDecodeError, OSError):
            pass

    offset = 0
    done: dict[str, object] | None = None
    if session_uri:
        try:
            offset, done = query_session_offset(session_uri, size)
            log(f"Resuming prior session at byte {offset:,} ({offset * 100 // size}%)")
        except (urllib.error.HTTPError, urllib.error.URLError, TimeoutError):
            log("Prior session unusable; starting a fresh one")
            session_uri = ""

    if not session_uri:
        session_uri = start_session(folder_id, archive.name, size)
        st.write_text(
            json.dumps(
                {"session_uri": session_uri, "size": size, "mtime": archive.stat().st_mtime}
            )
        )
        offset = 0

    delay = 5.0
    with archive.open("rb") as fh:
        while done is None:
            if time.time() > deadline:
                log(f"Deadline reached at byte {offset:,}/{size:,}; state kept for resume")
                sys.exit(75)
            fh.seek(offset)
            chunk = fh.read(CHUNK)
            end = offset + len(chunk) - 1
            req = urllib.request.Request(session_uri, data=chunk, method="PUT")
            req.add_header("Content-Range", f"bytes {offset}-{end}/{size}")
            try:
                with urllib.request.urlopen(req, timeout=1800) as resp:
                    done = json.loads(resp.read())  # 200/201 on the final chunk
            except urllib.error.HTTPError as e:
                if e.code == 308:
                    offset = end + 1
                    delay = 5.0
                    log(f"Uploaded {offset:,}/{size:,} bytes ({offset * 100 // size}%)")
                    continue
                if e.code in (404, 410):
                    log("Session expired; restarting from byte 0")
                    session_uri = start_session(folder_id, archive.name, size)
                    st.write_text(
                        json.dumps(
                            {
                                "session_uri": session_uri,
                                "size": size,
                                "mtime": archive.stat().st_mtime,
                            }
                        )
                    )
                    offset = 0
                    continue
                if e.code in (429, 500, 502, 503, 504):
                    log(f"HTTP {e.code} on chunk; retrying in {delay:.0f}s")
                    time.sleep(min(delay, 300))
                    delay *= 2
                    continue
                raise
            except (urllib.error.URLError, TimeoutError, ConnectionError) as e:
                # offline (asleep-adjacent, wifi down): re-query the session so a
                # chunk that half-landed isn't re-sent from the wrong offset
                log(f"Network error ({e.__class__.__name__}); retrying in {delay:.0f}s")
                time.sleep(min(delay, 300))
                delay *= 2
                try:
                    offset, done = query_session_offset(session_uri, size)
                except (urllib.error.HTTPError, urllib.error.URLError, TimeoutError):
                    pass
                continue

    cloud_md5 = str(done.get("md5Checksum", "") or "")
    file_id = str(done.get("id", "") or "")
    if cloud_md5 != local_md5:
        log(f"MD5 MISMATCH: local {local_md5} vs cloud {cloud_md5}; deleting cloud copy")
        api_json("DELETE", f"{API}/files/{file_id}")
        sys.exit(1)
    record_ledger(archive.name, file_id, local_md5)
    state_path(archive).unlink(missing_ok=True)
    log(f"Upload confirmed: {archive.name} (id {file_id}, md5 {cloud_md5})")


def record_ledger(name: str, file_id: str, md5: str) -> None:
    STAGING_DIR.mkdir(parents=True, exist_ok=True)
    stamp = dt.datetime.now().isoformat(timespec="seconds")
    with LEDGER_FILE.open("a") as fh:
        fh.write(f"{stamp}\t{name}\t{file_id}\t{md5}\n")


def archive_stamp(name: str) -> dt.datetime | None:
    if not (name.startswith(ARCHIVE_PREFIX) and name.endswith(ARCHIVE_SUFFIX)):
        return None
    raw = name[len(ARCHIVE_PREFIX) : -len(ARCHIVE_SUFFIX)]
    try:
        return dt.datetime.strptime(raw, "%Y%m%d_%H%M%S")
    except ValueError:
        return None


def cmd_prune(daily: int, weekly: int, monthly: int, dry_run: bool) -> None:
    folder_id = find_folder_id()
    stamped = [
        (ts, f) for f in list_archives(folder_id) if (ts := archive_stamp(str(f.get("name", ""))))
    ]
    stamped.sort(key=lambda p: p[0], reverse=True)
    keep: set[str] = set()
    for _, f in stamped[:daily]:
        keep.add(str(f["id"]))
    seen_weeks: set[str] = set()
    seen_months: set[str] = set()
    for ts, f in stamped:
        iso = ts.isocalendar()
        wk = f"{iso.year}-{iso.week:02d}"
        mo = f"{ts.year}-{ts.month:02d}"
        if wk not in seen_weeks and len(seen_weeks) < weekly:
            keep.add(str(f["id"]))
            seen_weeks.add(wk)
        if mo not in seen_months and len(seen_months) < monthly:
            keep.add(str(f["id"]))
            seen_months.add(mo)
    for _ts, f in stamped:
        if str(f["id"]) in keep:
            continue
        log(f"Pruning cloud archive: {f['name']}" + (" (dry run)" if dry_run else ""))
        if not dry_run:
            api_json("DELETE", f"{API}/files/{f['id']}")


def cmd_list() -> None:
    folder_id = find_folder_id()
    for f in sorted(list_archives(folder_id), key=lambda x: str(x.get("name", ""))):
        size_mb = int(str(f.get("size", 0) or 0)) // (1024 * 1024)
        print(f"{f.get('name')}\t{size_mb}MB\tmd5={f.get('md5Checksum', '-')}\tid={f.get('id')}")


def cmd_verify(name: str) -> None:
    hit = find_by_name(find_folder_id(), name)
    if not hit:
        print(f"NOT ON DRIVE: {name}")
        sys.exit(1)
    print(f"{hit['name']}\tid={hit['id']}\tmd5={hit.get('md5Checksum', '-')}\tsize={hit.get('size')}")


def cmd_delete(name: str) -> None:
    hit = find_by_name(find_folder_id(), name)
    if not hit:
        sys.exit(f"not found: {name}")
    api_json("DELETE", f"{API}/files/{hit['id']}")
    print(f"deleted {name} (id {hit['id']})")


def main() -> None:
    ap = argparse.ArgumentParser(prog="drive-upload", description=__doc__)
    sub = ap.add_subparsers(dest="cmd", required=True)
    sub.add_parser("auth")
    p_up = sub.add_parser("upload")
    p_up.add_argument("file")
    p_up.add_argument(
        "--deadline-min",
        type=int,
        default=int(os.environ.get("BACKUP_SYNC_TIMEOUT_MIN", "960")),
    )
    p_pr = sub.add_parser("prune")
    p_pr.add_argument("--daily", type=int, default=int(os.environ.get("KEEP_DAILY", "3")))
    p_pr.add_argument("--weekly", type=int, default=int(os.environ.get("KEEP_WEEKLY", "4")))
    p_pr.add_argument("--monthly", type=int, default=int(os.environ.get("KEEP_MONTHLY", "6")))
    p_pr.add_argument("--dry-run", action="store_true")
    sub.add_parser("list")
    p_ve = sub.add_parser("verify")
    p_ve.add_argument("name")
    p_de = sub.add_parser("delete")
    p_de.add_argument("name")
    args = ap.parse_args()

    if args.cmd == "auth":
        cmd_auth()
    elif args.cmd == "upload":
        cmd_upload(args.file, args.deadline_min)
    elif args.cmd == "prune":
        cmd_prune(args.daily, args.weekly, args.monthly, args.dry_run)
    elif args.cmd == "list":
        cmd_list()
    elif args.cmd == "verify":
        cmd_verify(args.name)
    elif args.cmd == "delete":
        cmd_delete(args.name)


if __name__ == "__main__":
    main()
