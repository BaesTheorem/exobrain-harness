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
# Retention: grandfather-father-son (config.sh KEEP_DAILY/WEEKLY/MONTHLY). A
# single archive can count toward several tiers at once, so there is exactly one
# physical copy of each kept archive -- no duplication on Drive.
#
# Schedule: daily at 2:00 AM via com.exobrain.backup.plist (+ RunAtLoad catch-up).
#
# Notes / constraints:
#   - Runs under /bin/bash (macOS bash 3.2): no associative arrays, no mapfile.
#   - bsdtar (libarchive) is the system tar: supports -r (append to an
#     uncompressed archive), -T (files-from), and -s (name substitution).
#   - The archive is built uncompressed in a local temp dir (fast, keeps Drive
#     from syncing a half-written file), verified, then gzipped and moved to
#     Drive only once it's known-good.
#   - Landing the file in the Drive folder is not the same as the backup
#     existing. The run blocks (still caffeinated) until Drive stamps the
#     com.google.drivefs.item-id xattr confirming the upload, and treats a
#     timeout as a failed backup: rescue the bytes locally, alert, skip the
#     prune. Before this, five runs between 2026-07-20 and 2026-08-07 reported
#     "Backup complete." while Drive had reverted the archive to 0 bytes.

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
source "$SCRIPT_DIR/config.sh"

# Keep the Mac awake for the whole run: backups take hours, and system sleep
# mid-tar stalls or corrupts them ("Interrupted system call", 2026-07). Re-exec
# once under caffeinate; the guard env var prevents a loop.
if [ -z "${EXOBRAIN_CAFFEINATED:-}" ] && command -v caffeinate >/dev/null 2>&1; then
    export EXOBRAIN_CAFFEINATED=1
    exec caffeinate -is "$0" "$@"
fi

# --- Settings (with safe fallbacks if config.sh predates these vars) ----------
BACKUP_DIR="${BACKUP_DIR:-$HOME/My Drive/Exobrain backups}"
KEEP_DAILY="${KEEP_DAILY:-7}"
KEEP_WEEKLY="${KEEP_WEEKLY:-4}"
KEEP_MONTHLY="${KEEP_MONTHLY:-6}"
REPO_SCAN_ROOT="${REPO_SCAN_ROOT:-$HOME/Documents}"
LOCAL_BACKUP_DIR="${LOCAL_BACKUP_DIR:-}"
# EXTRA_INCLUDES is an array in config.sh; default to empty if config predates it.
if ! declare -p EXTRA_INCLUDES >/dev/null 2>&1; then EXTRA_INCLUDES=(); fi
if ! declare -p BACKUP_EXCLUDE_REPOS >/dev/null 2>&1; then BACKUP_EXCLUDE_REPOS=(); fi
BACKUP_REPO_MAX_MB="${BACKUP_REPO_MAX_MB:-2048}"
BACKUP_MIN_FREE_GB="${BACKUP_MIN_FREE_GB:-20}"
BACKUP_SYNC_TIMEOUT_MIN="${BACKUP_SYNC_TIMEOUT_MIN:-45}"
BACKUP_RESCUE_DIR="${BACKUP_RESCUE_DIR:-$HOME/Exobrain backup rescue}"

# Google Drive stamps this xattr on a file once its content upload has actually
# landed in the cloud -- the value is the real Drive file id. Absent means the
# bytes are still local-only. Verified 2026-08-10: a fresh 40MB file had no
# xattr for 18s while uploading and gained it the moment the upload completed,
# and across eight archives the only one missing it was the one Drive had
# reverted to 0 bytes. Do NOT substitute file size here: the mount reports the
# local size for a file whose cloud copy is an empty husk, which is exactly how
# the 08-07 loss went unnoticed.
DRIVE_SYNCED_XATTR='com.google.drivefs.item-id#S'
drive_item_id() { xattr -p "$DRIVE_SYNCED_XATTR" "$1" 2>/dev/null; }

TIMESTAMP=$(date +%Y%m%d_%H%M%S)
ARCHIVE_NAME="exobrain-collective-$TIMESTAMP.tar.gz"
ARCHIVE_PATH="$BACKUP_DIR/$ARCHIVE_NAME"

# Regenerable junk to keep OUT of the per-repo gitignored capture. These are
# caches/builds, never irreplaceable data, and (in node_modules' case) huge.
CACHE_RE='(^|/)(\.venv|venv|node_modules|__pycache__|\.next|\.nuxt|\.parcel-cache|\.pytest_cache|\.mypy_cache|\.ruff_cache|\.gradle|\.terraform)(/|$)|\.pyc$|(^|/)\.DS_Store$'

fail() {
    echo "[$(date)] ERROR: $1" >&2
    # Clickable banner (opens the folder the failure is about) when mist-notify is
    # available; bare osascript can't carry a click target, so it's the fallback.
    if [ -x "$SCRIPT_DIR/mist-voice/bin/mist-notify" ]; then
        "$SCRIPT_DIR/mist-voice/bin/mist-notify" "$1" "Exobrain URGENT" Basso "${2:-$BACKUP_DIR}" 2>/dev/null || true
    else
        osascript -e "display notification \"$1\" with title \"Exobrain URGENT\" sound name \"Basso\"" 2>/dev/null || true
    fi
    exit 1
}

mkdir -p "$BACKUP_DIR"

# --- Freshness guard ----------------------------------------------------------
# RunAtLoad fires this on every login/boot to catch up after a power-off, but we
# don't want duplicate backups during ordinary logins. Skip if a collective
# archive newer than 20h already exists (20h < 24h so the 2 AM run is never
# suppressed).
#
# Age comes from the FILENAME timestamp, never mtime. Google Drive rewrites the
# mtime of files it re-materializes, so a stale archive can look minutes old: on
# 2026-08-10 Drive stamped the 08-07 archive with 16:12, and the 08-11 02:00 run
# read that as a 10h-old backup and skipped -- 08-11 got no backup at all.
newest_archive_age_secs() {
    local newest="" f base stamp ep now
    now=$(date +%s)
    for f in "$BACKUP_DIR"/exobrain-collective-*.tar.gz; do
        [ -e "$f" ] || continue
        base="${f##*/}"
        stamp="${base#exobrain-collective-}"
        stamp="${stamp%.tar.gz}"           # YYYYMMDD_HHMMSS
        ep=$(date -j -f "%Y%m%d_%H%M%S" "$stamp" +%s 2>/dev/null) || continue
        if [ -z "$newest" ] || [ "$ep" -gt "$newest" ]; then newest="$ep"; fi
    done
    [ -n "$newest" ] || { echo ""; return; }
    echo $(( now - newest ))
}
AGE_SECS="$(newest_archive_age_secs)"
if [ -n "$AGE_SECS" ] && [ "$AGE_SECS" -lt 72000 ]; then
    echo "[$(date)] Recent collective backup exists ($((AGE_SECS / 3600))h old); skipping."
    exit 0
fi

# --- Free-space preflight ------------------------------------------------------
# The archive is staged locally (tar, then its gzip) before moving to Drive, so
# a full disk kills the run mid-write (observed 2026-07: ENOSPC at 21.6GB). Fail
# fast and loud instead; an exact pre-gzip check runs later.
AVAIL_GB=$(( $(df -k "${TMPDIR:-/tmp}" | awk 'NR==2 {print $4}') / 1048576 ))
if [ "$AVAIL_GB" -lt "$BACKUP_MIN_FREE_GB" ]; then
    fail "backup aborted: ${AVAIL_GB}GB free on staging volume, need ${BACKUP_MIN_FREE_GB}GB"
fi

# --- Build the archive in a local temp dir ------------------------------------
WORK="$(mktemp -d "${TMPDIR:-/tmp}/exobrain-backup.XXXXXX")"
trap 'rm -rf "$WORK"' EXIT
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

# --- Compress, verify, then publish to Drive ----------------------------------
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

# Move the verified, complete file onto Drive (so Drive never syncs a partial).
mv -f "$WORK/$ARCHIVE_NAME" "$ARCHIVE_PATH"
BACKUP_SIZE=$(du -h "$ARCHIVE_PATH" | cut -f1)
echo "[$(date)] Archive staged on Drive: $ARCHIVE_PATH ($BACKUP_SIZE)"

# --- Block until Google Drive confirms the upload ------------------------------
# Landing the file in the Drive folder is NOT the backup succeeding; it only
# queues an upload. We are still inside the caffeinate re-exec at this point, so
# staying here holds the Mac awake and online for the transfer instead of handing
# it back to the darkwake cycle mid-upload -- which is the whole bug.
echo "[$(date)] Waiting for Drive to confirm upload (timeout ${BACKUP_SYNC_TIMEOUT_MIN}m)..."
SYNC_DEADLINE=$(( $(date +%s) + BACKUP_SYNC_TIMEOUT_MIN * 60 ))
ITEM_ID=""
while :; do
    ITEM_ID="$(drive_item_id "$ARCHIVE_PATH")"
    [ -n "$ITEM_ID" ] && break
    [ "$(date +%s)" -ge "$SYNC_DEADLINE" ] && break
    sleep 15
done

if [ -z "$ITEM_ID" ]; then
    # Drive never took the bytes. The file sitting in the Drive folder is a husk:
    # the mount reports its full local size, but the cloud copy is empty. Rescue
    # the content off Drive before that local cache is evicted, then fail loudly
    # -- and do it BEFORE the prune below, so a doomed archive can never cause an
    # older good one to be deleted.
    echo "[$(date)] WARN: Drive did not confirm upload within ${BACKUP_SYNC_TIMEOUT_MIN}m; rescuing locally" >&2
    mkdir -p "$BACKUP_RESCUE_DIR"
    if cp "$ARCHIVE_PATH" "$BACKUP_RESCUE_DIR/$ARCHIVE_NAME.tmp" \
       && mv -f "$BACKUP_RESCUE_DIR/$ARCHIVE_NAME.tmp" "$BACKUP_RESCUE_DIR/$ARCHIVE_NAME"; then
        echo "[$(date)] Rescued to: $BACKUP_RESCUE_DIR/$ARCHIVE_NAME" >&2
        fail "backup did NOT reach Google Drive; rescued copy at $BACKUP_RESCUE_DIR" "$BACKUP_RESCUE_DIR"
    else
        rm -f "$BACKUP_RESCUE_DIR/$ARCHIVE_NAME.tmp" 2>/dev/null || true
        fail "backup did NOT reach Google Drive AND the local rescue copy failed -- today has no backup"
    fi
fi
echo "[$(date)] Upload confirmed by Drive (item $ITEM_ID)"

# --- Optional secondary copy to an off-Google destination ---------------------
# Google Drive is both the backup target AND a primary data source, so a single
# account lockout takes both at once. A copy on an external disk / other cloud
# mount breaks that single point of failure. Disabled unless LOCAL_BACKUP_DIR is
# set (config.sh). Copy via a .tmp then atomic mv so a partial is never mistaken
# for a complete archive.
if [ -n "$LOCAL_BACKUP_DIR" ]; then
    if [ -d "$LOCAL_BACKUP_DIR" ]; then
        if cp "$ARCHIVE_PATH" "$LOCAL_BACKUP_DIR/$ARCHIVE_NAME.tmp" \
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

# --- Drop husks before ranking for retention ----------------------------------
# An archive Drive reverted still sits in the folder at its full apparent size,
# so the retention tiers below would happily count it as one of the kept dailies
# and delete a real backup to make room for it. Our own archive is confirmed
# synced by now, so anything else missing the xattr is a husk from a prior run.
# Only removed once a rescue copy is known to exist -- otherwise the husk's local
# content may be the last copy of that day, so keep it and say so.
while IFS= read -r f; do
    [ "$f" = "$ARCHIVE_PATH" ] && continue
    [ -n "$(drive_item_id "$f")" ] && continue
    if [ -f "$BACKUP_RESCUE_DIR/${f##*/}" ]; then
        echo "[$(date)] Removing husk (never uploaded; rescued copy exists): $f"
        rm -f "$f"
    else
        # No rescue copy, so its local bytes may be the last copy of that day and
        # deleting it is not on the table. Rename it out of the *.tar.gz glob
        # instead: that frees the retention slot it would otherwise take from a
        # real backup, without destroying anything.
        echo "[$(date)] WARN: $f never reached Drive and has no rescue copy; parking it as .UNUPLOADED" >&2
        mv -f "$f" "$f.UNUPLOADED" 2>/dev/null || true
    fi
done < <(ls -t "$BACKUP_DIR"/exobrain-collective-*.tar.gz 2>/dev/null)

# --- Prune with grandfather-father-son retention ------------------------------
# Single-copy GFS: compute the union of archives needed by the daily, weekly,
# and monthly tiers, then delete everything else. Archives are listed newest
# first, so the first one seen for any week/month is that period's newest.
KEEP_LIST="$WORK/keep.txt"
: > "$KEEP_LIST"

# Daily: newest KEEP_DAILY archives.
ls -t "$BACKUP_DIR"/exobrain-collective-*.tar.gz 2>/dev/null \
    | head -n "$KEEP_DAILY" >> "$KEEP_LIST" || true

# Weekly / monthly: newest archive per ISO week / per calendar month.
seen_weeks=" "
seen_months=" "
wk_count=0
mo_count=0
while IFS= read -r f; do
    base="${f##*/}"
    ymd="${base#exobrain-collective-}"
    ymd="${ymd%%_*}"   # YYYYMMDD
    wk=$(date -j -f "%Y%m%d" "$ymd" "+%G-%V" 2>/dev/null) || continue
    mo=$(date -j -f "%Y%m%d" "$ymd" "+%Y-%m" 2>/dev/null) || continue
    case "$seen_weeks" in *" $wk "*) : ;; *)
        if [ "$wk_count" -lt "$KEEP_WEEKLY" ]; then
            echo "$f" >> "$KEEP_LIST"
            seen_weeks="$seen_weeks$wk "
            wk_count=$((wk_count + 1))
        fi ;;
    esac
    case "$seen_months" in *" $mo "*) : ;; *)
        if [ "$mo_count" -lt "$KEEP_MONTHLY" ]; then
            echo "$f" >> "$KEEP_LIST"
            seen_months="$seen_months$mo "
            mo_count=$((mo_count + 1))
        fi ;;
    esac
done < <(ls -t "$BACKUP_DIR"/exobrain-collective-*.tar.gz 2>/dev/null)

# Delete any collective archive not in the keep set.
while IFS= read -r f; do
    if ! grep -Fxq "$f" "$KEEP_LIST"; then
        echo "[$(date)] Pruning: $f"
        rm -f "$f"
    fi
done < <(ls -t "$BACKUP_DIR"/exobrain-collective-*.tar.gz 2>/dev/null)

# Transitional cleanup: the previous harness-only job left exobrain-harness-*
# archives. The collective archive supersedes them; keep only the newest one as
# a cushion and retire the rest. The legacy archives are all gone now, so ls
# matches nothing and exits 1; under pipefail that fails the whole pipeline and
# set -e killed the run right before "Backup complete." -- every successful
# backup reported exit 1. Guarded, same as the KEEP_DAILY ls above.
ls -t "$BACKUP_DIR"/exobrain-harness-*.tar.gz 2>/dev/null | tail -n +2 | while IFS= read -r old; do
    echo "[$(date)] Retiring legacy harness-only backup: $old"
    rm -f "$old"
done || true

echo "[$(date)] Backup complete."
