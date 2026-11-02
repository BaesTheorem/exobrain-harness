#!/usr/bin/env node
// Keep the Google Health OAuth token exercised, and escalate only when a human is needed.
//
// Since 2026-10-30 the `fitbit` MCP server reads the Google Health API v4 (the
// legacy Fitbit Web API answers HTTP 410). Google refresh tokens are reusable and,
// because the OAuth project is published "In production", do not expire after 7
// days. A refresh can still fail for good: consent revoked, password changed,
// or six months unused. This job finds that before the morning briefing does.
//
// It calls the same getAccessToken() the server calls (build/google-auth.js), then
// GET users/me/identity, so a pass proves token + API + account link together.
//
// launchd must invoke this as `/opt/homebrew/bin/node <this file>` DIRECTLY, with
// no shell wrapper (TCC's ~/Documents gate; see the harness launchd notes).
//
// Exit codes: 0 healthy, 1 re-consent needed, 2 inconclusive (transient/unknown).

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

const { getAccessToken, lastAuthFailure } = await import('../build/google-auth.js');
const { identity, HealthApiError } = await import('../build/google-health.js');
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
      await fetch('https://health.googleapis.com/', {
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

  const token = await getAccessToken();
  if (!token) {
    const why = lastAuthFailure();
    if (why === 'transient') return [INCONCLUSIVE, 'Google token endpoint failed (network or 5xx); the refresh token is unspent'];
    if (why === 'missing') return [NEEDS_REAUTH, 'no Google Health token on disk yet'];
    return [NEEDS_REAUTH, 'Google rejected the refresh token (invalid_grant): consent was revoked or expired'];
  }

  try {
    const id = await identity();
    if (!id || typeof id !== 'object') return [INCONCLUSIVE, 'identity response was empty'];
  } catch (err) {
    if (err instanceof HealthApiError) {
      if (err.status === 401) return [NEEDS_REAUTH, 'Google Health rejected a fresh access token (401)'];
      if (err.status === 400 && JSON.stringify(err.body).includes('ACCOUNT_NOT_LINKED')) {
        return [NEEDS_REAUTH, 'Google account is not linked to Google Health (ACCOUNT_NOT_LINKED): sign in to the Google Health app'];
      }
      if (err.status === 403) return [NEEDS_REAUTH, `Google Health refused access (403): ${err.message.slice(0, 160)}`];
      return [INCONCLUSIVE, `Google Health returned HTTP ${err.status}`];
    }
    return [INCONCLUSIVE, `identity request failed: ${err.message}`];
  }
  return [OK, 'identity fetched; token is live and was refreshed if it was due'];
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
        '--discord',
        '--context', `Fitbit data comes from the Google Health API v4. Re-consent: run '${REAUTH} url', have Alex approve, then '${REAUTH} code "<redirected google.com URL>"'. Log: ${LOG_FILE}`,
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
    'Fitbit data (Google Health) needs your consent again. Tap to fix it in a chat.',
    detail,
    []
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
    // Inconclusive means unknown, not broken, so the log is the first move.
    [`Open log=${LOG_FILE}`]
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
