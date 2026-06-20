#!/usr/bin/env bash
# reset-identity.sh — wipe the OSRS client's device identity between disposable accounts.
#
# Goal: a ban on throwaway #1 must NOT link to / poison your ability to make + run
# throwaway #2 from the same Mac. The thing that links accounts on one machine is the
# client-side UID files (RuneLite/Jagex random.dat + jagexcache) — OSRS's real "machine
# identifier". Wiping them makes the next launch look like a fresh install. IP and email
# are the other two linkage vectors (rotate the VPN exit + mint a fresh alias — reminders
# printed below). Immutable hardware specs are coarse/non-unique and not a reliable ban
# vector for OSRS (no kernel anti-cheat); MAC is local-only and not seen by Jagex.
#
# Usage: reset-identity.sh [--mac]
#   --mac : also randomize the en0 MAC (paranoid mode; needs sudo; flaky on modern macOS
#           wifi and probably unnecessary since OSRS doesn't transmit your MAC).
set -uo pipefail
RL="$HOME/.runelite"

echo "==> stopping any running client"
pkill -f "net.runelite.client.RuneLite" 2>/dev/null || true
pkill -f "client_runelite.jar" 2>/dev/null || true
sleep 2

echo "==> wiping client-side UID + cache (the real per-machine identifier)"
rm -f  "$RL/random.dat" "$RL"/jagex_cl_*.dat 2>/dev/null || true
rm -rf "$RL/jagexcache" "$RL/cache" 2>/dev/null || true
echo "    removed random.dat / jagex_cl_*.dat / jagexcache / cache"
echo "    (next launch regenerates a fresh UID; game cache re-downloads, slower first login)"

if [[ "${1:-}" == "--mac" ]]; then
  IF=en0
  NEWMAC=$(printf '02:%02x:%02x:%02x:%02x:%02x' \
    $((RANDOM%256)) $((RANDOM%256)) $((RANDOM%256)) $((RANDOM%256)) $((RANDOM%256)))
  echo "==> [paranoid] spoofing $IF MAC -> $NEWMAC (sudo; wifi blips; reverts on reboot)"
  sudo ifconfig "$IF" ether "$NEWMAC" 2>/dev/null \
    && echo "    MAC now: $(ifconfig $IF | awk '/ether/{print $2}')" \
    || echo "    MAC spoof FAILED (modern macOS often blocks this — it's fine, MAC isn't sent to Jagex anyway)"
fi

cat <<'NOTE'

==> manual steps to finish a clean throwaway (NOT automatable here):
    1. VPN: switch to a FRESH exit (never one a banned account used).
    2. Email: mint a new separate-domain alias
         python3 ../../../../disposable-email/alias.py mint <svc> --scheme catchall
       (NOT gmail-plus — it normalizes to your real address.)
    3. Create the new Jagex account on that alias (MIST reads the verify mail).
    4. python3 osrs.py launch-vanilla  ->  log in the new account.

Residual risk after all this = BEHAVIORAL re-clustering (botting the same spots/patterns),
not device. That's account-level attrition, not an identity-wide ban. For total hardware
separation, run the stack on a separate device (Raspberry Pi) instead of this Mac.
NOTE
