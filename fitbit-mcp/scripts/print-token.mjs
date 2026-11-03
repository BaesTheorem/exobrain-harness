#!/usr/bin/env node
// Print a valid Google Health access token on stdout, for scripts outside this
// package (ironman's hitpoints-verify and quest-verify, fitbit-sleep-alarm).
// It uses the server's own refresh path, so there is one refresh code path and
// one token file. Exit 1: consent needed (run bin/fitbit-reauth). Exit 2: transient.
import path from 'path';
import { fileURLToPath } from 'url';

const HERE = path.dirname(fileURLToPath(import.meta.url));
try {
  process.loadEnvFile(path.resolve(HERE, '..', '..', '.env'));
} catch {
  // The variables can also come from the environment.
}
const { getAccessToken, lastAuthFailure } = await import('../build/google-auth.js');
const token = await getAccessToken();
if (token) {
  process.stdout.write(token + '\n');
  process.exit(0);
}
const why = lastAuthFailure();
console.error(`google-health-token: no token (${why}). ${why === 'transient' ? 'Try again shortly.' : 'Run fitbit-mcp/bin/fitbit-reauth.'}`);
process.exit(why === 'transient' ? 2 : 1);
