#!/bin/bash
# Daily COLLECTIVE backup of everything GitHub doesn't hold, into Google Drive.
#
# One archive per run -- exobrain-collective-<timestamp>.tar.gz -- bundling three
# top-level trees:
#   1. Exobrain harness/      the whole harness folder (incl. its own gitignored
#                             data: .env, .mcp.json, processing-log.json, etc.)
#   2. Exobrain/              the full Obsidian vault (not a git repo; this is
#                             its ONLY automated backup)
#   3. repos-gitignored/<repo>/...  the gitignored files of every sibling repo
#                             under REPO_SCAN_ROOT -- the data GitHub never sees
#                             (secrets, SQLite DBs, tokens, local state). Code
#                             itself already lives on GitHub, so it's skipped.
#
# Why "collective": one tarball is one atomic restore point. Pull it down, untar,
# and the harness + vault + every repo's private data come back together.
#
# Retention: grandfather-father-son (config.sh KEEP_DAILY/WEEKLY/MONTHLY),
# applied CLOUD-SIDE via the Drive API (backup/drive-upload.py prune). A single
# archive can count toward several tiers at once, so there is exactly one
# physical copy of each kept archive. Locally, the newest uploaded archive is
# kept in the staging dir as off-cloud redundancy (BACKUP_LOCAL_KEEP).
#
# Schedule: daily at 2:00 AM via com.exobrain.backup.plist (+ RunAtLoad
# catch-up), plus com.exobrain.backup-resume.plist every 30 min to finish any
# interrupted upload as soon as the Mac is really awake.
#
# UPLOAD PATH (rewritten 2026-08-28): the archive is staged in a LOCAL dir and
# pushed through the Drive API's resumable-upload protocol by
# backup/drive-upload.py. It never touches the DriveFS mount. History: five
# separate data-loss incidents (2026-07-20 .. 2026-08-28) all traced to DriveFS
# background sync on a battery Mac that sleeps -- Drive retries a queued upload
# a few times, every retry lands in a 45s darkwake sliver with no network, and
# it then reverts the cloud file to 0 bytes and dumps the local content in
# "Lost and Found". The xattr-polling babysitter that used to live here could
# detect that but not prevent it, and a reboot killed the babysitter itself.
# A resumable API session survives all of it: the session URI is valid for
# ~a week, each chunk resumes from the last server-acked byte, and sleep,
# process death, or reboot merely pauses progress. Confirmation is the API's
# md5Checksum matching the local file, not xattr divination.
#
# Notes / constraints:
#   - Runs under /bin/bash (macOS bash 3.2): no associative arrays, no mapfile.
#   - bsdtar (libarchive) is the system tar: supports -r (append to an
#     uncompressed archive), -T (files-from), and -s (name substitution).
#   - The archive is built uncompressed in a local temp dir, verified, then
#     gzipped and moved to the staging dir only once it's known-good.
#   - The uploader is fed to python3 via stdin (never `python3 script.py`):
#     under launchd, bash in this job provably has TCC access to ~/Documents
#     (tar has read it nightly for months) but a python child may not, and the
#     stdin trick means python never opens a file under ~/Documents itself.
#     Everything python touches (staging dir, token, ledger) lives in $HOME
#     outside ~/Documents.

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
source "$SCRIPT_DIR/config.sh"

# Keep the Mac awake for the whole run: backups take hours, and system sleep
# mid-tar stalls or corrupts them ("Interrupted system call", 2026-07). Re-exec
# once under caffeinate; the guard env var prevents a loop. (On battery this is
# best-effort only -- caffeinate -s holds wake on AC power alone -- but the
# resumable upload no longer depends on staying awake.)
if [ -z "${EXOBRAIN_CAFFEINATED:-}" ] && command -v caffeinate >/dev/null 2>&1; then
    export EXOBRAIN_CAFFEINATED=1
    exec caffeinate -is "$0" "$@"
fi

# --- Settings (with safe fallbacks if config.sh predates these vars) ----------
KEEP_DAILY="${KEEP_DAILY:-7}"
KEEP_WEEKLY="${KEEP_WEEKLY:-4}"
KEEP_MONTHLY="${KEEP_MONTHLY:-6}"
REPO_SCAN_ROOT="${REPO_SCAN_ROOT:-$HOME/Documents}"
LOCAL_BACKUP_DIR="${LOCAL_BACKUP_DIR:-}"
if ! declare -p EXTRA_INCLUDES >/dev/null 2>&1; then EXTRA_INCLUDES=(); fi
if ! declare -p BACKUP_EXCLUDE_REPOS >/dev/null 2>&1; then BACKUP_EXCLUDE_REPOS=(); fi
BACKUP_REPO_MAX_MB="${BACKUP_REPO_MAX_MB:-2048}"
BACKUP_MIN_FREE_GB="${BACKUP_MIN_FREE_GB:-20}"
BACKUP_SYNC_TIMEOUT_MIN="${BACKUP_SYNC_TIMEOUT_MIN:-960}"
BACKUP_STAGING_DIR="${BACKUP_STAGING_DIR:-$HOME/Exobrain backup staging}"
BACKUP_LOCAL_KEEP="${BACKUP_LOCAL_KEEP:-1}"
BACKUP_DRIVE_FOLDER_NAME="${BACKUP_DRIVE_FOLDER_NAME:-Exobrain backups}"
LEDGER="$BACKUP_STAGING_DIR/uploaded.log"

TIMESTAMP=$(date +%Y%m%d_%H%M%S)
ARCHIVE_NAME="exobrain-collective-$TIMESTAMP.tar.gz"

# Regenerable junk to keep OUT of the per-repo gitignored capture. These are
# caches/builds, never irreplaceable data, and (in node_modules' case) huge.
CACHE_RE='(^|/)(\.venv|venv|node_modules|__pycache__|\.next|\.nuxt|\.parcel-cache|\.pytest_cache|\.mypy_cache|\.ruff_cache|\.gradle|\.terraform)(/|$)|\.pyc$|(^|/)\.DS_Store$'

fail() {
    echo "[$(date)] ERROR: $1" >&2
    # Clickable banner (opens the folder the failure is about) when mist-notify is
    # available; bare osascript can't carry a click target, so it's the fallback.
    if [ -x "$SCRIPT_DIR/mist-voice/bin/mist-notify" ]; then
        "$SCRIPT_DIR/mist-voice/bin/mist-notify" "$1" "Exobrain URGENT" Basso "${2:-$BACKUP_STAGING_DIR}" 2>/dev/null || true
    else
        osascript -e "display notification \"$1\" with title \"Exobrain URGENT\" sound name \"Basso\"" 2>/dev/null || true
    fi
    exit 1
}

# The uploader (see header for why stdin). Exit 75 = deadline hit with state
# kept, i.e. "made progress, resume later" -- not a data-loss failure.
run_uploader() {
    EXOBRAIN_HARNESS_DIR="$SCRIPT_DIR" \
    BACKUP_STAGING_DIR="$BACKUP_STAGING_DIR" \
    BACKUP_DRIVE_FOLDER_NAME="$BACKUP_DRIVE_FOLDER_NAME" \
    BACKUP_SYNC_TIMEOUT_MIN="$BACKUP_SYNC_TIMEOUT_MIN" \
    KEEP_DAILY="$KEEP_DAILY" KEEP_WEEKLY="$KEEP_WEEKLY" KEEP_MONTHLY="$KEEP_MONTHLY" \
    /usr/bin/python3 - "$@" < "$SCRIPT_DIR/backup/drive-upload.py"
}

mkdir -p "$BACKUP_STAGING_DIR"

# --- Single-instance lock -------------------------------------------------------
# The 2 AM job, the RunAtLoad catch-up, and the 30-min resume agent all run this
# script; only one may work at a time (two concurrent uploads of the same file
# would fight over the session state). /tmp clears on reboot, so a lock orphaned
# by a crash-without-reboot is detected by pid liveness.
LOCK_DIR="/tmp/exobrain-backup.lock"
if ! mkdir "$LOCK_DIR" 2>/dev/null; then
    OTHER_PID="$(cat "$LOCK_DIR/pid" 2>/dev/null || true)"
    if [ -n "$OTHER_PID" ] && kill -0 "$OTHER_PID" 2>/dev/null; then
        exit 0   # another instance is live; it owns the work
    fi
    rm -rf "$LOCK_DIR"
    mkdir "$LOCK_DIR" 2>/dev/null || exit 0
fi
echo $$ > "$LOCK_DIR/pid"
trap 'rm -rf "$LOCK_DIR"' EXIT

# --- Finish any interrupted upload BEFORE anything else -------------------------
# A staged archive absent from the ledger is an upload a prior run didn't finish
# (deadline, reboot). The resumable session picks up at the server-acked offset;
# if the session aged out (~1 week) the uploader starts it over. This runs before
# the freshness guard so a kickstart heals state instead of "skipping" past it,
# which is exactly how the 2026-08-28 reverted archive stayed unnoticed all day.
for f in "$BACKUP_STAGING_DIR"/exobrain-collective-*.tar.gz; do
    [ -e "$f" ] || continue
    if ! grep -qF "$(basename "$f")" "$LEDGER" 2>/dev/null; then
        echo "[$(date)] Unfinished upload from a prior run: $(basename "$f"); resuming"
        rc=0; run_uploader upload "$f" || rc=$?
        if [ "$rc" -eq 75 ]; then
            echo "[$(date)] Upload deadline hit; progress saved, a later run resumes" >&2
            exit 0
        elif [ "$rc" -ne 0 ]; then
            fail "resuming upload of $(basename "$f") failed (exit $rc); bytes safe in staging"
        fi
    fi
done

# --- Freshness guard ----------------------------------------------------------
# RunAtLoad + the resume agent fire this often; skip building a new archive if a
# CONFIRMED upload newer than 20h exists (20h < 24h so the 2 AM run is never
# suppressed). Freshness comes from the ledger of md5-verified uploads -- never
# from files sitting in a folder. The old mount-glob check counted a reverted
# husk as a fresh backup (2026-08-28) and skipped the whole day.
newest_upload_age_secs() {
    local newest="" name stamp ep now
    now=$(date +%s)
    [ -f "$LEDGER" ] || { echo ""; return; }
    while IFS=$'\t' read -r _ name _ _; do
        stamp="${name#exobrain-collective-}"
        stamp="${stamp%.tar.gz}"           # YYYYMMDD_HHMMSS
        ep=$(date -j -f "%Y%m%d_%H%M%S" "$stamp" +%s 2>/dev/null) || continue
        if [ -z "$newest" ] || [ "$ep" -gt "$newest" ]; then newest="$ep"; fi
    done < "$LEDGER"
    [ -n "$newest" ] || { echo ""; return; }
    echo $(( now - newest ))
}
AGE_SECS="$(newest_upload_age_secs)"
if [ -n "$AGE_SECS" ] && [ "$AGE_SECS" -lt 72000 ]; then
    [ -n "${BACKUP_QUIET:-}" ] || echo "[$(date)] Recent confirmed backup exists ($((AGE_SECS / 3600))h old); skipping."
    exit 0
fi

# --- Free-space preflight ------------------------------------------------------
# The archive is staged locally (tar, then its gzip) before uploading, so a full
# disk kills the run mid-write (observed 2026-07: ENOSPC at 21.6GB). Fail fast
# and loud instead; an exact pre-gzip check runs later.
AVAIL_GB=$(( $(df -k "${TMPDIR:-/tmp}" | awk 'NR==2 {print $4}') / 1048576 ))
if [ "$AVAIL_GB" -lt "$BACKUP_MIN_FREE_GB" ]; then
    fail "backup aborted: ${AVAIL_GB}GB free on staging volume, need ${BACKUP_MIN_FREE_GB}GB"
fi

# --- Build the archive in a local temp dir ------------------------------------
WORK="$(mktemp -d "${TMPDIR:-/tmp}/exobrain-backup.XXXXXX")"
trap 'rm -rf "$WORK"; rm -rf "$LOCK_DIR"' EXIT

# Every deliberate failure path here calls fail(), which logs and raises a banner.
# An *undeliberate* one (a `set -e` trip on a command nobody expected to return
# non-zero) used to exit 1 with a completely empty log, which is how a dead backup
# went unnoticed for four days. Report those with the same volume, naming the line
# so the next one takes minutes instead of an evening.
trap 'rc=$?; [ $rc -ne 0 ] && fail "backup died unexpectedly at line $LINENO (exit $rc); see backup.log"' ERR
COLLECTIVE_TAR="$WORK/collective.tar"

# The backup reads a live filesystem, so a file can disappear between the moment
# it lands in the file list and the moment tar reads it -- a running app doing an
# atomic write through a .tmp file is enough (mist-console's
# data/sessions.json.tmp.<pid> killed the 2026-08-11 run). bsdtar 3.5.3 has no
# --ignore-failed-read, and it exits 1 for the whole archive over that one file.
# Those files are transient partial writes; nothing is lost by skipping them.
# Tolerate exactly that error, log every skip, and still fail on anything else.
run_tar() {
    local err="$WORK/tar.err" rc=0
    tar "$@" 2>"$err" || rc=$?
    if [ "$rc" -ne 0 ] && [ -s "$err" ] \
       && ! grep -qEv 'Cannot stat: No such file or directory|Error exit delayed from previous errors\.' "$err"; then
        sed 's/^/[vanished mid-backup, skipped] /' "$err" >&2
        rc=0
    elif [ "$rc" -ne 0 ]; then
        cat "$err" >&2
    fi
    rm -f "$err"
    return "$rc"
}

HARNESS_PARENT="$(dirname "$HARNESS_DIR")"
HARNESS_BASENAME="$(basename "$HARNESS_DIR")"
VAULT_PARENT="$(dirname "$VAULT_DIR")"
VAULT_BASENAME="$(basename "$VAULT_DIR")"

# 1. Harness -- whole folder, minus runtime caches. Captures the harness's own
#    gitignored data automatically (tar doesn't honor .gitignore).
echo "[$(date)] Adding harness: $HARNESS_BASENAME"
run_tar -cf "$COLLECTIVE_TAR" \
    --exclude='__pycache__' \
    --exclude='*.pyc' \
    --exclude='.DS_Store' \
    --exclude='node_modules' \
    --exclude="$HARNESS_BASENAME/.claude/projects" \
    --exclude="$HARNESS_BASENAME/.claude/channels" \
    --exclude="$HARNESS_BASENAME/.claude/worktrees" \
    --exclude="$HARNESS_BASENAME/.claude/session-memories" \
    --exclude="$HARNESS_BASENAME/.claude/plugins" \
    -C "$HARNESS_PARENT" \
    "$HARNESS_BASENAME"

# 2. Vault -- full (it's small and lives in no git repo, so this is its only net).
echo "[$(date)] Adding vault: $VAULT_BASENAME"
run_tar -rf "$COLLECTIVE_TAR" \
    --exclude='.DS_Store' \
    -C "$VAULT_PARENT" \
    "$VAULT_BASENAME"

# 2b. Out-of-tree extras -- secrets/state that live OUTSIDE the harness, the vault,
#     and the git-repo sweep, so nothing else would catch them: the Plaud token,
#     global ~/.claude settings + the Discord bot token, and a couple of non-git
#     app auth files. Namespaced under home-extras/ so restore is unambiguous. The
#     Home Assistant history DB and junk are filtered out (huge + regenerable).
echo "[$(date)] Adding out-of-tree extras"
EXTRA_LIST="$WORK/extras.list"
(
    cd "$HOME" || exit 0
    for rel in ${EXTRA_INCLUDES[@]+"${EXTRA_INCLUDES[@]}"}; do
        [ -e "$rel" ] || continue
        if [ -d "$rel" ]; then
            find "$rel" -type f
        else
            printf '%s\n' "$rel"
        fi
    done | grep -Ev 'home-assistant_v2\.db|\.log(\.|$)|(^|/)(deps|tts|node_modules|\.venv|\.git)/|(^|/)\.DS_Store$|(^|/)__pycache__/|\.pyc$'
) > "$EXTRA_LIST" 2>/dev/null || true
if [ -s "$EXTRA_LIST" ]; then
    extra_count=$(wc -l < "$EXTRA_LIST" | tr -d ' ')
    echo "[$(date)]   + home-extras ($extra_count files)"
    run_tar -rf "$COLLECTIVE_TAR" -s "|^|home-extras/|" -C "$HOME" -T "$EXTRA_LIST"
fi

# 3. Every sibling repo's gitignored data, namespaced under repos-gitignored/.
#    Auto-discovers repos so new ones are covered without editing this script.
#
#    Building the per-repo file list robustly takes a little care:
#      - core.quotePath=false so non-ASCII names come out as raw UTF-8 (git
#        otherwise wraps them in quotes + octal escapes, which slip past the
#        cache filter and tar -T can't read).
#      - Drop cache entries up front, then expand any kept directory to its
#        real files with `find -type f`. That structurally skips dangling
#        symlinks (e.g. a broken venv python link) that would abort tar, and
#        prunes caches nested inside an otherwise-wanted directory.
#      - List is newline-delimited (no data file here contains a newline).
echo "[$(date)] Scanning repos under: $REPO_SCAN_ROOT"
while IFS= read -r gitdir; do
    repo="$(dirname "$gitdir")"
    name="$(basename "$repo")"
    # Skip the harness (already captured whole above).
    [ "$repo" = "$HARNESS_DIR" ] && continue

    # Explicitly excluded repos (huge regenerable assets; see config.sh).
    for skip in ${BACKUP_EXCLUDE_REPOS[@]+"${BACKUP_EXCLUDE_REPOS[@]}"}; do
        if [ "$name" = "$skip" ]; then
            echo "[$(date)]   - $name SKIPPED (listed in BACKUP_EXCLUDE_REPOS)"
            continue 2
        fi
    done

    list="$WORK/$name.list"
    (
        cd "$repo" || exit 0
        git -c core.quotePath=false ls-files --others --ignored --exclude-standard 2>/dev/null \
            | grep -Ev "$CACHE_RE" \
            | while IFS= read -r e; do
                if [ -d "$e" ]; then
                    find "$e" -type d \( -name node_modules -o -name .venv -o -name venv \
                        -o -name __pycache__ -o -name '.*_cache' \) -prune \
                        -o -type f -print
                elif [ -f "$e" ]; then
                    printf '%s\n' "$e"
                fi
            done \
            | grep -Ev "$CACHE_RE"
    ) > "$list" 2>/dev/null || true
    [ -s "$list" ] || { rm -f "$list"; continue; }

    # Per-repo size cap: one repo's gitignored data ballooning (e.g. 14GB of
    # game/VM assets) must not sink the whole backup. Skips are logged loudly,
    # never silent; raise the cap or exclude the repo explicitly in config.sh.
    size_bytes=$(tr '\n' '\0' < "$list" | (cd "$repo" && xargs -0 stat -f %z 2>/dev/null) | awk '{s+=$1} END {print s+0}')
    size_mb=$(( size_bytes / 1048576 ))
    if [ "$size_mb" -gt "$BACKUP_REPO_MAX_MB" ]; then
        echo "[$(date)]   - $name SKIPPED (${size_mb}MB gitignored data over the ${BACKUP_REPO_MAX_MB}MB cap; see config.sh BACKUP_REPO_MAX_MB / BACKUP_EXCLUDE_REPOS)"
        rm -f "$list"
        continue
    fi

    count=$(wc -l < "$list" | tr -d ' ')
    echo "[$(date)]   + $name ($count files)"
    # -s prepends the namespace so repos can't collide on a shared relative path.
    run_tar -rf "$COLLECTIVE_TAR" -s "|^|repos-gitignored/$name/|" -C "$repo" -T "$list"
    rm -f "$list"
done < <(find "$REPO_SCAN_ROOT" -maxdepth 2 -type d -name .git 2>/dev/null)

# --- Compress, verify, then stage locally --------------------------------------
# Exact space check: the gzip output is strictly smaller than the tar, so free
# space >= tar size guarantees the compress step cannot hit ENOSPC.
TAR_BYTES=$(stat -f %z "$COLLECTIVE_TAR")
AVAIL_BYTES=$(( $(df -k "$WORK" | awk 'NR==2 {print $4}') * 1024 ))
if [ "$AVAIL_BYTES" -lt "$TAR_BYTES" ]; then
    fail "backup aborted before compress: need $((TAR_BYTES / 1073741824))GB free for gzip, have $((AVAIL_BYTES / 1073741824))GB"
fi
echo "[$(date)] Compressing..."
gzip -c "$COLLECTIVE_TAR" > "$WORK/$ARCHIVE_NAME"
rm -f "$COLLECTIVE_TAR"

[ -s "$WORK/$ARCHIVE_NAME" ] || fail "collective archive missing or empty"
tar -tzf "$WORK/$ARCHIVE_NAME" >/dev/null 2>&1 || fail "collective archive is corrupted"

STAGED="$BACKUP_STAGING_DIR/$ARCHIVE_NAME"
mv -f "$WORK/$ARCHIVE_NAME" "$STAGED"
BACKUP_SIZE=$(du -h "$STAGED" | cut -f1)
echo "[$(date)] Archive staged locally: $STAGED ($BACKUP_SIZE)"

# --- Upload via the Drive API ---------------------------------------------------
# Chunked resumable upload; confirmation is the API returning an md5Checksum that
# matches the local file. Exit 75 means the per-run deadline passed with the
# session state saved -- the resume agent (or the next 2 AM run) continues from
# the last acked byte, so this is a pause, not a failure. The staged local file
# IS the rescue copy; nothing is deleted until the cloud md5 matches.
echo "[$(date)] Uploading to Drive folder '$BACKUP_DRIVE_FOLDER_NAME' (deadline ${BACKUP_SYNC_TIMEOUT_MIN}m)..."
rc=0; run_uploader upload "$STAGED" || rc=$?
if [ "$rc" -eq 75 ]; then
    echo "[$(date)] Upload deadline hit; progress saved, a later run resumes" >&2
    exit 0
elif [ "$rc" -ne 0 ]; then
    fail "upload of $ARCHIVE_NAME failed (exit $rc); bytes safe in $BACKUP_STAGING_DIR"
fi

# --- Optional secondary copy to an off-Google destination ---------------------
# Google Drive is both the backup target AND a primary data source, so a single
# account lockout takes both at once. A copy on an external disk / other cloud
# mount breaks that single point of failure. Disabled unless LOCAL_BACKUP_DIR is
# set (config.sh). Copy via a .tmp then atomic mv so a partial is never mistaken
# for a complete archive.
if [ -n "$LOCAL_BACKUP_DIR" ]; then
    if [ -d "$LOCAL_BACKUP_DIR" ]; then
        if cp "$STAGED" "$LOCAL_BACKUP_DIR/$ARCHIVE_NAME.tmp" \
           && mv -f "$LOCAL_BACKUP_DIR/$ARCHIVE_NAME.tmp" "$LOCAL_BACKUP_DIR/$ARCHIVE_NAME"; then
            echo "[$(date)] Secondary copy: $LOCAL_BACKUP_DIR/$ARCHIVE_NAME"
        else
            echo "[$(date)] WARN: secondary copy to $LOCAL_BACKUP_DIR failed" >&2
            rm -f "$LOCAL_BACKUP_DIR/$ARCHIVE_NAME.tmp" 2>/dev/null || true
        fi
    else
        echo "[$(date)] WARN: LOCAL_BACKUP_DIR set but not present: $LOCAL_BACKUP_DIR (skipping)" >&2
    fi
fi

# --- Retention ------------------------------------------------------------------
# Cloud: grandfather-father-son via the API (covers archives from the old DriveFS
# path too -- same folder, and the uploader uses the full drive scope so it sees
# them). Local: keep the newest BACKUP_LOCAL_KEEP uploaded archives in staging as
# off-cloud redundancy; never delete a staged archive absent from the ledger.
run_uploader prune --daily "$KEEP_DAILY" --weekly "$KEEP_WEEKLY" --monthly "$KEEP_MONTHLY"

kept=0
while IFS= read -r f; do
    if ! grep -qF "$(basename "$f")" "$LEDGER" 2>/dev/null; then
        continue   # not confirmed uploaded; keep unconditionally
    fi
    kept=$((kept + 1))
    if [ "$kept" -gt "$BACKUP_LOCAL_KEEP" ]; then
        echo "[$(date)] Dropping older local staged copy (confirmed on Drive): ${f##*/}"
        rm -f "$f" "$f.driveupload.json"
    fi
done < <(ls -t "$BACKUP_STAGING_DIR"/exobrain-collective-*.tar.gz 2>/dev/null)

echo "[$(date)] Backup complete."
