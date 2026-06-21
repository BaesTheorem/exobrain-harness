#!/bin/bash
# Daily COLLECTIVE backup of everything GitHub doesn't hold, into Google Drive.
#
# One archive per run — exobrain-collective-<timestamp>.tar.gz — bundling three
# top-level trees:
#   1. Exobrain harness/      the whole harness folder (incl. its own gitignored
#                             data: .env, .mcp.json, processing-log.json, etc.)
#   2. Exobrain/              the full Obsidian vault (not a git repo; this is
#                             its ONLY automated backup)
#   3. repos-gitignored/<repo>/...  the gitignored files of every sibling repo
#                             under REPO_SCAN_ROOT — the data GitHub never sees
#                             (secrets, SQLite DBs, tokens, local state). Code
#                             itself already lives on GitHub, so it's skipped.
#
# Why "collective": one tarball is one atomic restore point. Pull it down, untar,
# and the harness + vault + every repo's private data come back together.
#
# Retention: grandfather-father-son (config.sh KEEP_DAILY/WEEKLY/MONTHLY). A
# single archive can count toward several tiers at once, so there is exactly one
# physical copy of each kept archive — no duplication on Drive.
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

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
source "$SCRIPT_DIR/config.sh"

# --- Settings (with safe fallbacks if config.sh predates these vars) ----------
BACKUP_DIR="${BACKUP_DIR:-$HOME/My Drive/Exobrain backups}"
KEEP_DAILY="${KEEP_DAILY:-7}"
KEEP_WEEKLY="${KEEP_WEEKLY:-4}"
KEEP_MONTHLY="${KEEP_MONTHLY:-6}"
REPO_SCAN_ROOT="${REPO_SCAN_ROOT:-$HOME/Documents}"
LOCAL_BACKUP_DIR="${LOCAL_BACKUP_DIR:-}"
# EXTRA_INCLUDES is an array in config.sh; default to empty if config predates it.
if ! declare -p EXTRA_INCLUDES >/dev/null 2>&1; then EXTRA_INCLUDES=(); fi

TIMESTAMP=$(date +%Y%m%d_%H%M%S)
ARCHIVE_NAME="exobrain-collective-$TIMESTAMP.tar.gz"
ARCHIVE_PATH="$BACKUP_DIR/$ARCHIVE_NAME"

# Regenerable junk to keep OUT of the per-repo gitignored capture. These are
# caches/builds, never irreplaceable data, and (in node_modules' case) huge.
CACHE_RE='(^|/)(\.venv|venv|node_modules|__pycache__|\.next|\.nuxt|\.parcel-cache|\.pytest_cache|\.mypy_cache|\.ruff_cache|\.gradle|\.terraform)(/|$)|\.pyc$|(^|/)\.DS_Store$'

fail() {
    echo "[$(date)] ERROR: $1" >&2
    osascript -e "display notification \"$1\" with title \"Exobrain URGENT\" sound name \"Basso\"" 2>/dev/null || true
    exit 1
}

mkdir -p "$BACKUP_DIR"

# --- Freshness guard ----------------------------------------------------------
# RunAtLoad fires this on every login/boot to catch up after a power-off, but we
# don't want duplicate backups during ordinary logins. Skip if a collective
# archive newer than 20h already exists (20h < 24h so the 2 AM run is never
# suppressed). Runs in an `if` so a no-match grep doesn't trip set -e.
if find "$BACKUP_DIR" -name 'exobrain-collective-*.tar.gz' -mmin -1200 -print -quit 2>/dev/null | grep -q .; then
    echo "[$(date)] Recent collective backup exists (<20h old); skipping."
    exit 0
fi

# --- Build the archive in a local temp dir ------------------------------------
WORK="$(mktemp -d "${TMPDIR:-/tmp}/exobrain-backup.XXXXXX")"
trap 'rm -rf "$WORK"' EXIT
COLLECTIVE_TAR="$WORK/collective.tar"

HARNESS_PARENT="$(dirname "$HARNESS_DIR")"
HARNESS_BASENAME="$(basename "$HARNESS_DIR")"
VAULT_PARENT="$(dirname "$VAULT_DIR")"
VAULT_BASENAME="$(basename "$VAULT_DIR")"

# 1. Harness — whole folder, minus runtime caches. Captures the harness's own
#    gitignored data automatically (tar doesn't honor .gitignore).
echo "[$(date)] Adding harness: $HARNESS_BASENAME"
tar -cf "$COLLECTIVE_TAR" \
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

# 2. Vault — full (it's small and lives in no git repo, so this is its only net).
echo "[$(date)] Adding vault: $VAULT_BASENAME"
tar -rf "$COLLECTIVE_TAR" \
    --exclude='.DS_Store' \
    -C "$VAULT_PARENT" \
    "$VAULT_BASENAME"

# 2b. Out-of-tree extras — secrets/state that live OUTSIDE the harness, the vault,
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
    tar -rf "$COLLECTIVE_TAR" -s "|^|home-extras/|" -C "$HOME" -T "$EXTRA_LIST"
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

    count=$(wc -l < "$list" | tr -d ' ')
    echo "[$(date)]   + $name ($count files)"
    # -s prepends the namespace so repos can't collide on a shared relative path.
    tar -rf "$COLLECTIVE_TAR" -s "|^|repos-gitignored/$name/|" -C "$repo" -T "$list"
    rm -f "$list"
done < <(find "$REPO_SCAN_ROOT" -maxdepth 2 -type d -name .git 2>/dev/null)

# --- Compress, verify, then publish to Drive ----------------------------------
echo "[$(date)] Compressing..."
gzip -c "$COLLECTIVE_TAR" > "$WORK/$ARCHIVE_NAME"
rm -f "$COLLECTIVE_TAR"

[ -s "$WORK/$ARCHIVE_NAME" ] || fail "collective archive missing or empty"
tar -tzf "$WORK/$ARCHIVE_NAME" >/dev/null 2>&1 || fail "collective archive is corrupted"

# Move the verified, complete file onto Drive (so Drive never syncs a partial).
mv -f "$WORK/$ARCHIVE_NAME" "$ARCHIVE_PATH"
BACKUP_SIZE=$(du -h "$ARCHIVE_PATH" | cut -f1)
echo "[$(date)] Backup verified: $ARCHIVE_PATH ($BACKUP_SIZE)"

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
# a cushion and retire the rest.
ls -t "$BACKUP_DIR"/exobrain-harness-*.tar.gz 2>/dev/null | tail -n +2 | while IFS= read -r old; do
    echo "[$(date)] Retiring legacy harness-only backup: $old"
    rm -f "$old"
done

echo "[$(date)] Backup complete."
