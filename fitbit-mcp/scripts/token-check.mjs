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
import { readFileSync, writeFileSync } from 'fs';
import path from 'path';
import { fileURLToPath } from 'url';
import dotenv from 'dotenv';

const here = path.dirname(fileURLToPath(import.meta.url));
const PKG_ROOT = path.resolve(here, '..');
const HARNESS = path.resolve(PKG_ROOT, '..');
const REAUTH = path.join(PKG_ROOT, 'bin', 'fitbit-reauth');
const NOTIFY = path.join(HARNESS, 'mist-voice', 'bin', 'mist-notify');
const STATE_FILE = path.join(PKG_ROOT, '.fitbit-check-state.json');
const LOG_FILE = path.join(
  process.env.HOME ?? '',
  'Library/Logs/exobrain/fitbit-token.log'
);

// A single inconclusive run is a blip and stays silent. Three in a row is at
// least twelve hours of never confirming the token, which is long enough that a
// broken chain could be hiding behind an outage, so say so. Re-escalate no more
// than once a day after that: the situation is already on screen.
const STALE_RUNS_BEFORE_ESCALATING = 3;
const RE_ESCALATE_AFTER_MS = 24 * 60 * 60 * 1000;

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

function readState() {
  try {
    return JSON.parse(readFileSync(STATE_FILE, 'utf8'));
  } catch {
    // Missing or corrupt state must not stop the check itself from running.
    return { consecutiveInconclusive: 0, firstInconclusiveAt: null, lastOkAt: null, lastEscalatedAt: null };
  }
}

function writeState(state) {
  try {
    writeFileSync(STATE_FILE, JSON.stringify(state, null, 2), 'utf8');
  } catch {
    // Losing the counter costs a delayed escalation, not a wrong answer.
  }
}

function hoursSince(iso) {
  if (!iso) return null;
  return Math.round((Date.now() - new Date(iso).getTime()) / 3_600_000);
}

function notify(message, subtitle, actions) {
  try {
    spawn(
      NOTIFY,
      [
        message,
        'Fitbit token',
        // Silent: the banner is the notification, and this can fire at 05:30.
        'none',
        'console',
        '--subtitle', subtitle.slice(0, 120),
        ...actions.flatMap((a) => ['--action', a]),
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
const now = new Date().toISOString();
console.log(`[${now}] ${status}: ${detail}`);

const state = readState();

if (status === OK) {
  // A success clears the slate, including any escalation already on screen.
  writeState({
    consecutiveInconclusive: 0,
    firstInconclusiveAt: null,
    lastOkAt: now,
    lastEscalatedAt: null,
  });
  process.exit(0);
}

if (status === NEEDS_REAUTH) {
  // A definite answer, so the run-counting heuristic is not involved at all.
  notify(
    'Fitbit needs re-authorization. Health data is dark until you approve it.',
    detail,
    [`Re-authorize=cmd:'${REAUTH}'`]
  );
  writeState({
    ...state,
    consecutiveInconclusive: 0,
    firstInconclusiveAt: null,
    lastEscalatedAt: now,
  });
  process.exit(1);
}

// Inconclusive: we still do not know whether the token is good. Staying quiet
// forever is how a broken chain hides behind a long outage, so count the runs.
const streak = (state.consecutiveInconclusive ?? 0) + 1;
const firstInconclusiveAt = state.firstInconclusiveAt ?? now;
const escalatedAgo = state.lastEscalatedAt
  ? Date.now() - new Date(state.lastEscalatedAt).getTime()
  : Infinity;

let lastEscalatedAt = state.lastEscalatedAt ?? null;
if (streak >= STALE_RUNS_BEFORE_ESCALATING && escalatedAgo >= RE_ESCALATE_AFTER_MS) {
  const stuckFor = hoursSince(firstInconclusiveAt);
  const lastOk = hoursSince(state.lastOkAt);
  const since = lastOk === null ? 'never confirmed healthy' : `last healthy ${lastOk}h ago`;
  notify(
    `Fitbit has not checked out for ~${stuckFor}h (${streak} runs). Health data may be stale.`,
    `${since}. Latest: ${detail}`,
    // Re-auth is NOT the first move here: inconclusive means unknown, not broken.
    // The log says which it is, so open that; re-auth stays as the escape hatch.
    [`Open log=${LOG_FILE}`, `Re-authorize=cmd:'${REAUTH}'`]
  );
  lastEscalatedAt = now;
  console.log(`[${now}] escalated: ${streak} consecutive inconclusive runs`);
}

writeState({
  consecutiveInconclusive: streak,
  firstInconclusiveAt,
  lastOkAt: state.lastOkAt ?? null,
  lastEscalatedAt,
});
process.exit(2);
