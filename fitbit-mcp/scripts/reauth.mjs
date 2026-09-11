#!/usr/bin/env node
// Run the Fitbit OAuth consent flow on its own, without starting an MCP server.
//
// Everything else about this token renews itself: the server refreshes on a
// 5-minute skew before expiry and adopts a sibling's token rather than racing
// for the single-use refresh token. The one step no code can do is Fitbit's
// browser consent screen, which is needed when the refresh chain is actually
// broken (revoked app, changed scopes, a refresh token burned past recovery).
//
// This exists so that step does not require a Claude session: bin/fitbit-token-check
// escalates to a notification whose button runs bin/fitbit-reauth, and the flow
// happens in a browser under Alex's hands.
//
// Exits 0 once a new token is on disk, 1 on timeout or bind failure.

import { existsSync, statSync } from 'fs';
import path from 'path';
import { fileURLToPath } from 'url';
import net from 'net';

import { startAuthorizationFlow } from '../build/auth.js';

const here = path.dirname(fileURLToPath(import.meta.url));
const TOKEN_FILE = path.resolve(here, '..', '.fitbit-token.json');
const PORT = 3000;
const TIMEOUT_MS = 5 * 60 * 1000;
const POLL_MS = 1000;

/**
 * The OAuth flow binds localhost:3000 for the callback. A stale MCP server that
 * already started its own flow holds that port, and auth.ts only logs the bind
 * error, so the consent page would 404 and this would sit until timeout with no
 * useful message. Check first and say so plainly.
 */
function portInUse(port) {
  return new Promise((resolve) => {
    const probe = net
      .createServer()
      .once('error', () => resolve(true))
      .once('listening', () => probe.close(() => resolve(false)))
      .listen(port, '127.0.0.1');
  });
}

const mtimeOrZero = () => (existsSync(TOKEN_FILE) ? statSync(TOKEN_FILE).mtimeMs : 0);

if (await portInUse(PORT)) {
  console.error(
    `Port ${PORT} is already in use, so the OAuth callback cannot bind.\n` +
      'Another fitbit-mcp instance is probably already waiting for consent. ' +
      `Find it with: lsof -nP -iTCP:${PORT} -sTCP:LISTEN`
  );
  process.exit(1);
}

const before = mtimeOrZero();
startAuthorizationFlow();

const deadline = Date.now() + TIMEOUT_MS;
const timer = setInterval(() => {
  if (mtimeOrZero() > before) {
    console.error('Fitbit re-authorized. New token written.');
    clearInterval(timer);
    process.exit(0);
  }
  if (Date.now() > deadline) {
    console.error('Timed out waiting for the Fitbit callback. No token written.');
    clearInterval(timer);
    process.exit(1);
  }
}, POLL_MS);
