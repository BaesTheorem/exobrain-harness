#!/bin/bash
# auto-commit-harness.sh
#
# Nightly backstop: commit + push any pending changes in the Exobrain harness
# repo. Replaces the old `com.mist.routine.auto-commit-harness` Claude routine,
# which spent a full headless Opus session to do what this shell script does.
#
# The *smart* gitignore audit still lives in the evening-winddown routine (a real
# brain reading new files for leaked secrets). This script is only the mechanical
# safety net, so it does a CONSERVATIVE static pattern check: it auto-ignores only
# clear-cut secrets / runtime-state / OS-junk / large binaries by filename, and
# leaves anything ambiguous for winddown or the next human commit. Driven by the
# launchd agent com.exobrain.auto-commit-harness (daily 23:30).
set -e

REPO="/Users/alexhedtke/Documents/Exobrain harness"
NOTIFY="$REPO/mist-voice/bin/mist-notify"
cd "$REPO" || exit 0

# Nothing to commit -> done.
[ -z "$(git status --porcelain)" ] && exit 0

# --- Conservative static gitignore audit over untracked files -------------
IGN_ADDED=""
while IFS= read -r f; do
	[ -n "$f" ] || continue
	base="$(basename "$f")"
	hit=""
	case "$base" in
		.DS_Store|*.swp|*.swo|Thumbs.db) hit="os-junk" ;;
		.env|.env.*|*-token*|*token.json|*secret*|*secrets*|*.pem|*.key|credentials*.json) hit="secret" ;;
		*-state.json|*.db|*.sqlite|*.sqlite3) hit="runtime-state" ;;
	esac
	# Large untracked media/binaries (>5MB) don't belong in git.
	if [ -z "$hit" ] && [ -f "$f" ]; then
		sz=$(stat -f%z "$f" 2>/dev/null || echo 0)
		if [ "$sz" -gt 5242880 ]; then
			case "$base" in
				*.png|*.jpg|*.jpeg|*.gif|*.mp3|*.mp4|*.mov|*.wav|*.zip|*.pdf) hit="large-binary" ;;
			esac
		fi
	fi
	if [ -n "$hit" ]; then
		if ! grep -qxF "$f" .gitignore 2>/dev/null; then
			printf '%s\n' "$f" >> .gitignore
			IGN_ADDED="${IGN_ADDED} $f($hit)"
		fi
	fi
done < <(git status --porcelain | awk '/^\?\?/{print substr($0,4)}')

git add -A
git commit -q -m "Auto-commit: daily sync $(date '+%Y-%m-%d %H:%M')" || exit 0

# The 23:30 fire often lands on wake, before DNS is up, and the push died with
# "Could not resolve host: github.com" while the commit itself had succeeded.
# Wait for the network first. If it never comes, leave the commit sitting local
# and let tomorrow's run push it -- that is not worth an URGENT banner, which is
# reserved for a push that failed with a working network (auth, conflict, hook).
if ! "$REPO/scripts/wait-for-network.sh" github.com 300; then
	echo "$(date): committed locally, no network to push; next run will send it"
	exit 0
fi

if ! git push -q; then
	[ -x "$NOTIFY" ] && "$NOTIFY" "Nightly auto-commit push failed" "MIST URGENT" Basso "$REPO"
	exit 0
fi

# Only speak up if the static audit had to hide something.
if [ -n "$IGN_ADDED" ]; then
	[ -x "$NOTIFY" ] && "$NOTIFY" "Auto-added to .gitignore:$IGN_ADDED" "MIST" Purr "$REPO"
fi
exit 0
