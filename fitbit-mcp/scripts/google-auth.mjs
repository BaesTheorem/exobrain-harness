#!/usr/bin/env node
// Google Health consent. Replaces scripts/reauth.mjs (the Fitbit flow, dead since 2026-10-30).
//
//   google-auth.mjs url              print the consent URL
//   google-auth.mjs code '<URL>'     exchange the redirected https://www.google.com/?code=... URL
//   google-auth.mjs                  interactive: open the URL, then paste the redirect
import dotenv from 'dotenv';
import path from 'path';
import readline from 'readline/promises';
import { spawn } from 'child_process';
import { fileURLToPath } from 'url';

const HERE = path.dirname(fileURLToPath(import.meta.url));
dotenv.config({ path: path.resolve(HERE, '..', '..', '.env'), quiet: true });

const { consentUrl, exchangeCode, TOKEN_FILE } = await import('../build/google-auth.js');
const { identity } = await import('../build/google-health.js');

const [cmd, arg] = process.argv.slice(2);

async function finish(pasted) {
  const tok = await exchangeCode(pasted);
  console.log(`Token saved to ${TOKEN_FILE}`);
  console.log(`Granted scopes: ${tok.scope.split(' ').map((s) => s.replace(/.*googlehealth\./, '')).join(', ')}`);
  const id = await identity();
  console.log(`Identity: ${JSON.stringify(id)}`);
}

if (cmd === 'url') {
  console.log(consentUrl());
} else if (cmd === 'code') {
  await finish(arg ?? '');
} else {
  const url = consentUrl();
  console.log('Opening the Google consent page. Approve, then paste the full redirected URL (google.com/?code=...).');
  spawn('open', [url], { stdio: 'ignore', detached: true }).unref();
  const rl = readline.createInterface({ input: process.stdin, output: process.stdout });
  const pasted = await rl.question('Redirected URL: ');
  rl.close();
  await finish(pasted);
}
