#!/bin/bash
# Block until the network is actually usable, or give up after a bounded wait.
#
# Why this exists: launchd fires a missed StartCalendarInterval job the moment
# the Mac wakes, and Wi-Fi has not reassociated or DNS is not answering yet.
# Every network call in the first few seconds dies with "nodename nor servname
# provided" / ENOTFOUND, the job exits nonzero, and nothing retries until the
# next day. Observed on 2026-08-05: nest-precool failed at 14:09:19 against a
# 14:09:18 wake; substack-sync failed on every late (post-wake) fire and
# succeeded on every on-time one; session-memory-consolidator died with
# ENOTFOUND on 7 nights across three weeks.
#
# Usage:  wait-for-network.sh [host] [max_wait_seconds]
#   host              hostname to probe over HTTPS (default: cloudflare.com)
#   max_wait_seconds  give up after this long (default: 300)
#
# Exits 0 as soon as a real HTTPS round trip succeeds, 1 if it never does.
# Callers should treat exit 1 as "no network, skip this run" -- it also covers
# the ProtonVPN kill-switch case, where the interface is up but nothing routes.

set -uo pipefail

HOST="${1:-cloudflare.com}"
MAX_WAIT="${2:-300}"

DEADLINE=$(( $(date +%s) + MAX_WAIT ))
DELAY=2
ATTEMPT=0

while :; do
    ATTEMPT=$((ATTEMPT + 1))
    # No -f here. We are testing DNS + TCP + TLS, not the endpoint's opinion of
    # us: -f treats any HTTP >= 400 as failure, so probing api.anthropic.com
    # (401 unauthenticated) never succeeded and the consolidator skipped itself
    # for the full 300s on a healthy network. Any HTTP response at all proves
    # the network works; curl still exits nonzero on resolve/connect/TLS failure
    # (6, 7, 35), which is exactly what we want to retry on.
    if curl -s --max-time 8 -o /dev/null "https://${HOST}"; then
        [ "$ATTEMPT" -gt 1 ] && \
            echo "[$(date '+%Y-%m-%dT%H:%M:%S%z')] network ready after ${ATTEMPT} attempts"
        exit 0
    fi

    NOW=$(date +%s)
    if [ "$NOW" -ge "$DEADLINE" ]; then
        echo "[$(date '+%Y-%m-%dT%H:%M:%S%z')] network still unreachable (${HOST}) after ${MAX_WAIT}s, ${ATTEMPT} attempts" >&2
        exit 1
    fi

    # Don't sleep past the deadline.
    REMAINING=$(( DEADLINE - NOW ))
    [ "$DELAY" -gt "$REMAINING" ] && DELAY="$REMAINING"
    sleep "$DELAY"
    DELAY=$(( DELAY * 2 ))
    [ "$DELAY" -gt 30 ] && DELAY=30
done
