/**
 * Google OAuth for the Google Health API (the successor to the Fitbit Web API,
 * which Google turned off on 2026-10-30 with HTTP 410 on every endpoint).
 *
 * The client is the harness's existing Google OAuth web client
 * (GOOGLE_OAUTH_CLIENT_ID / GOOGLE_OAUTH_CLIENT_SECRET in the harness .env).
 * Its project is published "In production", so refresh tokens do not expire
 * after 7 days the way "Testing" tokens do.
 *
 * INVARIANTS
 * - Google refresh tokens are reusable, so concurrent servers do not burn each
 *   other's token. Each instance still re-reads the file before a refresh, so
 *   a re-consent written by `bin/fitbit-reauth` is adopted without a restart.
 * - A refresh response usually omits refresh_token. Keep the stored one.
 * - invalid_grant is the only answer that means "re-consent". Network errors
 *   and 5xx leave the token file alone and report a transient failure.
 */
import fs from 'fs/promises';
import { existsSync, readFileSync } from 'fs';
import path from 'path';
import { fileURLToPath } from 'url';

export const AUTH_URL = 'https://accounts.google.com/o/oauth2/v2/auth';
export const TOKEN_URL = 'https://oauth2.googleapis.com/token';
export const REDIRECT_URI = 'https://www.google.com';

export const SCOPES = [
  'profile.readonly',
  'settings.readonly',
  'sleep.readonly',
  'activity_and_fitness.readonly',
  'health_metrics_and_measurements.readonly',
  'nutrition.readonly',
].map((s) => `https://www.googleapis.com/auth/googlehealth.${s}`);

const HERE = path.dirname(fileURLToPath(import.meta.url));
export const TOKEN_FILE = process.env.GOOGLE_HEALTH_TOKEN_FILE
  ?? path.resolve(HERE, '..', '.google-health-token.json');

export interface GoogleToken {
  access_token: string;
  refresh_token: string;
  scope: string;
  token_type: string;
  expires_at: string; // ISO time
}

const SKEW_MS = 5 * 60 * 1000;

let cached: GoogleToken | null = null;
let lastFailure: 'none' | 'transient' | 'revoked' | 'missing' = 'none';

/** Why the last getAccessToken() returned null. */
export function lastAuthFailure(): typeof lastFailure {
  return lastFailure;
}

function clientCreds(): { id: string; secret: string } {
  const id = process.env.GOOGLE_OAUTH_CLIENT_ID ?? '';
  const secret = process.env.GOOGLE_OAUTH_CLIENT_SECRET ?? '';
  if (!id || !secret) {
    throw new Error('GOOGLE_OAUTH_CLIENT_ID / GOOGLE_OAUTH_CLIENT_SECRET missing from the harness .env');
  }
  return { id, secret };
}

function readTokenFile(): GoogleToken | null {
  if (!existsSync(TOKEN_FILE)) return null;
  try {
    return JSON.parse(readFileSync(TOKEN_FILE, 'utf8')) as GoogleToken;
  } catch {
    return null;
  }
}

async function writeTokenFile(tok: GoogleToken): Promise<void> {
  const tmp = `${TOKEN_FILE}.tmp`;
  await fs.writeFile(tmp, JSON.stringify(tok, null, 2), { encoding: 'utf8', mode: 0o600 });
  await fs.rename(tmp, TOKEN_FILE);
}

function fresh(tok: GoogleToken | null): boolean {
  return !!tok?.access_token && Date.parse(tok.expires_at) - Date.now() > SKEW_MS;
}

interface TokenResponse {
  access_token?: string;
  refresh_token?: string;
  expires_in?: number;
  scope?: string;
  token_type?: string;
  error?: string;
  error_description?: string;
}

async function postToken(params: Record<string, string>): Promise<{ status: number; body: TokenResponse }> {
  const { id, secret } = clientCreds();
  const res = await fetch(TOKEN_URL, {
    method: 'POST',
    headers: { 'Content-Type': 'application/x-www-form-urlencoded' },
    body: new URLSearchParams({ client_id: id, client_secret: secret, ...params }),
    signal: AbortSignal.timeout(30_000),
  });
  const body = (await res.json().catch(() => ({}))) as TokenResponse;
  return { status: res.status, body };
}

function toToken(body: TokenResponse, previousRefresh?: string): GoogleToken {
  return {
    access_token: body.access_token ?? '',
    refresh_token: body.refresh_token ?? previousRefresh ?? '',
    scope: body.scope ?? '',
    token_type: body.token_type ?? 'Bearer',
    expires_at: new Date(Date.now() + (body.expires_in ?? 3599) * 1000).toISOString(),
  };
}

/** Returns a valid access token, refreshing it when it is inside the skew window. */
export async function getAccessToken(): Promise<string | null> {
  if (cached && fresh(cached)) return cached.access_token;

  // Another instance, or a re-consent, can have written a newer token.
  const onDisk = readTokenFile();
  if (onDisk && fresh(onDisk)) {
    cached = onDisk;
    return onDisk.access_token;
  }
  if (!onDisk?.refresh_token) {
    lastFailure = 'missing';
    return null;
  }

  let result;
  try {
    result = await postToken({ grant_type: 'refresh_token', refresh_token: onDisk.refresh_token });
  } catch (err) {
    console.error(`Google token refresh failed (network): ${(err as Error).message}`);
    lastFailure = 'transient';
    return null;
  }
  if (result.status === 200 && result.body.access_token) {
    cached = toToken(result.body, onDisk.refresh_token);
    await writeTokenFile(cached);
    lastFailure = 'none';
    return cached.access_token;
  }
  const revoked = result.body.error === 'invalid_grant' || result.body.error === 'unauthorized_client';
  console.error(`Google token refresh failed: HTTP ${result.status} ${result.body.error ?? ''} ${result.body.error_description ?? ''}`);
  lastFailure = revoked ? 'revoked' : 'transient';
  return null;
}

/** Builds the consent URL. Offline access plus prompt=consent always returns a refresh token. */
export function consentUrl(): string {
  const { id } = clientCreds();
  return `${AUTH_URL}?${new URLSearchParams({
    client_id: id,
    redirect_uri: REDIRECT_URI,
    response_type: 'code',
    scope: SCOPES.join(' '),
    access_type: 'offline',
    prompt: 'consent',
    include_granted_scopes: 'true',
  })}`;
}

/** Takes the full redirected URL (https://www.google.com/?code=...) or the bare code. */
export async function exchangeCode(pasted: string): Promise<GoogleToken> {
  let code = pasted.trim();
  if (code.startsWith('http')) {
    const u = new URL(code);
    const err = u.searchParams.get('error');
    if (err) throw new Error(`consent returned error=${err}`);
    code = u.searchParams.get('code') ?? '';
  }
  if (!code) throw new Error('no authorization code in the pasted text');
  const { status, body } = await postToken({
    grant_type: 'authorization_code',
    code,
    redirect_uri: REDIRECT_URI,
  });
  if (status !== 200 || !body.access_token || !body.refresh_token) {
    throw new Error(`code exchange failed: HTTP ${status} ${body.error ?? ''} ${body.error_description ?? ''}`);
  }
  const tok = toToken(body);
  await writeTokenFile(tok);
  cached = tok;
  return tok;
}

/** Test seam: forget the in-memory token. */
export function _resetForTests(): void {
  cached = null;
  lastFailure = 'none';
}
