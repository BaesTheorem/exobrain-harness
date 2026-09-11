#!/usr/bin/env node
// Keep the Fitbit OAuth token renewed, and escalate only when a human is needed.
//
// Renewal is already automatic inside the MCP server: it refreshes on a 5-minute
// skew before expiry and re-reads the token file rather than racing sibling
// instances for the single-use refresh token. What it cannot do is renew a token
// nothing ever asks for, or clear a genuinely broken refresh chain.
//
// This does NOT refresh out of band. It calls the very same getAccessToken() the
// server calls, in a process that reads the same token file, so the race-safe
// path (adopt a sibling's fresher token; never spend one that is already gone)
// applies unchanged. See ../FORK.md. Two things fall out of one cheap call:
//
//   * the token gets exercised on a schedule, so it is never cold when the
//     morning briefing asks for it, and
//   * a broken refresh chain surfaces as a notification instead of as a health
//     pipeline that is quietly dark all morning.
//
// Only Fitbit's browser consent screen needs Alex, and that is what the
// notification button runs (bin/fitbit-reauth).
//
// launchd must invoke this as `/opt/homebrew/bin/node <this file>` DIRECTLY, with
// no shell wrapper. A bash wrapper that execs a Homebrew interpreter is denied by
// TCC's ~/Documents gate: node dies with EPERM opening build/index.js before it
// runs a line. Verified here 2026-09-10, and the same shape as the venv-python
// case in the harness notes. The wait-for-network gate therefore lives in this
// file rather than in a shell script.
//
// Exit codes: 0 healthy, 1 re-auth needed, 2 inconclusive (transient/unknown).

import { spawn } from 'child_process';
import path from 'path';
import { fileURLToPath } from 'url';
import dotenv from 'dotenv';

const here = path.dirname(fileURLToPath(import.meta.url));
const PKG_ROOT = path.resolve(here, '..');
const HARNESS = path.resolve(PKG_ROOT, '..');
const REAUTH = path.join(PKG_ROOT, 'bin', 'fitbit-reauth');
const NOTIFY = path.join(HARNESS, 'mist-voice', 'bin', 'mist-notify');

// Secrets live in the harness .env, and auth.js reads the client id/secret at
// module load, so this has to happen before that import.
dotenv.config({ path: path.join(HARNESS, '.env') });

const { initializeAuth, getAccessToken } = await import('../build/auth.js');

const PROFILE_URL = 'https://api.fitbit.com/1/user/-/profile.json';
const OK = 'OK';
const NEEDS_REAUTH = 'NEEDS_REAUTH';
const INCONCLUSIVE = 'INCONCLUSIVE';

/**
 * launchd fires a missed calendar event the moment the Mac wakes, before Wi-Fi
 * has reassociated. Without this gate a DNS failure reads as a dead token and
 * nags Alex to re-authorize one that is perfectly fine.
 */
async function waitForNetwork(maxWaitMs = 300_000) {
  const deadline = Date.now() + maxWaitMs;
  let delay = 2_000;
  for (;;) {
    try {
      await fetch('https://api.fitbit.com/', {
        method: 'HEAD',
        signal: AbortSignal.timeout(8_000),
      });
      return true; // any HTTP answer proves DNS + TCP + TLS work
    } catch {
      if (Date.now() >= deadline) return false;
      await new Promise((r) => setTimeout(r, Math.min(delay, deadline - Date.now())));
      delay = Math.min(delay * 2, 30_000);
    }
  }
}

async function check() {
  if (!(await waitForNetwork())) {
    return [INCONCLUSIVE, 'no network; skipping rather than guessing at the token'];
  }

  await initializeAuth();

  // The refresh, if one is due, happens in here, on the shared race-safe path.
  const token = await getAccessToken();
  if (!token) {
    return [NEEDS_REAUTH, 'no usable token: the refresh chain is broken'];
  }

  let res;
  try {
    res = await fetch(PROFILE_URL, {
      headers: { Authorization: `Bearer ${token}`, Accept: 'application/json' },
      signal: AbortSignal.timeout(30_000),
    });
  } catch (err) {
    return [INCONCLUSIVE, `profile request failed: ${err.message}`];
  }

  if (res.status === 401) {
    return [NEEDS_REAUTH, 'Fitbit rejected the token (401) even after a refresh'];
  }
  if (!res.ok) {
    return [INCONCLUSIVE, `Fitbit returned HTTP ${res.status}`];
  }

  const body = await res.json().catch(() => null);
  if (!body?.user) {
    return [INCONCLUSIVE, 'profile response had no user object'];
  }
  return [OK, 'profile fetched; token is live and was refreshed if it was due'];
}

function notifyReauth(detail) {
  try {
    spawn(
      NOTIFY,
      [
        'Fitbit needs re-authorization. Health data is dark until you approve it.',
        'Fitbit token',
        // Silent: the banner is the notification, and this can fire at 05:30.
        'none',
        'console',
        '--subtitle', detail.slice(0, 120),
        '--action', `Re-authorize=cmd:'${REAUTH}'`,
        '--group', 'fitbit-token',
        // Stable id, so a repeat replaces the banner instead of stacking.
        '--id', 'fitbit-token-reauth',
        '--urgency', 'timeSensitive',
      ],
      { stdio: 'ignore', detached: true }
    ).unref();
  } catch {
    // A missing notifier must not turn a real finding into a crash.
  }
}

const [status, detail] = await check();
console.log(`[${new Date().toISOString()}] ${status}: ${detail}`);
if (status === NEEDS_REAUTH) {
  notifyReauth(detail);
  process.exit(1);
}
process.exit(status === OK ? 0 : 2);
