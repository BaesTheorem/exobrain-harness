/**
 * Thin client for the Google Health API v4 (https://health.googleapis.com/v4).
 * Source of truth for paths, filters and schemas: the discovery document at
 * https://health.googleapis.com/$discovery/rest?version=v4 (revision 20261030).
 *
 * INVARIANTS
 * - Path data type ids are kebab-case (`daily-resting-heart-rate`); filter
 *   fields are snake_case (`daily_resting_heart_rate.date`). dataTypeSpec()
 *   derives both from one id so they cannot drift apart.
 * - Each time shape has its own filter field (see the discovery `filter`
 *   description). Sleep filters on civil END time, so a night is filed under
 *   the morning it ended, the same as Fitbit's dateOfSleep.
 * - Date arguments are civil dates in the user's own time zone and are
 *   inclusive; the API ranges are closed-open, so the end is moved one day.
 */
import { setTimeout as sleep } from 'timers/promises';
import { getAccessToken, lastAuthFailure } from './google-auth.js';

export const API_BASE = 'https://health.googleapis.com/v4';
const USER_AGENT = 'exobrain-harness/1.0 (+https://github.com/BaesTheorem/exobrain-harness)';

export type TimeShape = 'sample' | 'interval' | 'daily' | 'session' | 'sleep';

/** Time shape of each data type, from the DataPoint schema in the discovery doc. */
const SHAPES: Record<string, TimeShape> = {
  'heart-rate': 'sample',
  'heart-rate-variability': 'sample',
  'oxygen-saturation': 'sample',
  'respiratory-rate-sleep-summary': 'sample',
  weight: 'sample',
  'body-fat': 'sample',
  height: 'sample',
  'vo2-max': 'sample',
  'run-vo2-max': 'sample',
  'core-body-temperature': 'sample',
  steps: 'interval',
  distance: 'interval',
  floors: 'interval',
  altitude: 'interval',
  'active-minutes': 'interval',
  'active-zone-minutes': 'interval',
  'active-energy-burned': 'interval',
  'basal-energy-burned': 'interval',
  'activity-level': 'interval',
  'sedentary-period': 'interval',
  'time-in-heart-rate-zone': 'interval',
  'hydration-log': 'interval',
  'nutrition-log': 'session',
  exercise: 'session',
  sleep: 'sleep',
  'daily-resting-heart-rate': 'daily',
  'daily-heart-rate-variability': 'daily',
  'daily-heart-rate-zones': 'daily',
  'daily-oxygen-saturation': 'daily',
  'daily-respiratory-rate': 'daily',
  'daily-sleep-temperature-derivations': 'daily',
  'daily-vo2-max': 'daily',
};

export interface DataTypeSpec {
  id: string;
  field: string;
  shape: TimeShape;
}

export function dataTypeSpec(id: string): DataTypeSpec {
  const shape = SHAPES[id];
  if (!shape) throw new Error(`unknown data type '${id}'`);
  return { id, field: id.replace(/-/g, '_'), shape };
}

/** Adds n days to a YYYY-MM-DD date without touching time zones. */
export function addDays(date: string, n: number): string {
  const d = new Date(`${date}T00:00:00Z`);
  d.setUTCDate(d.getUTCDate() + n);
  return d.toISOString().slice(0, 10);
}

/** Today's civil date on this machine (the user's own time zone). */
export function today(): string {
  const d = new Date();
  const off = d.getTimezoneOffset() * 60_000;
  return new Date(d.getTime() - off).toISOString().slice(0, 10);
}

/** AIP-160 filter that selects the civil dates [start, end] inclusive. */
export function dateFilter(spec: DataTypeSpec, start: string, end: string): string {
  const next = addDays(end, 1);
  switch (spec.shape) {
    case 'daily':
      return `${spec.field}.date >= "${start}" AND ${spec.field}.date < "${next}"`;
    case 'sample':
      return `${spec.field}.sample_time.civil_time >= "${start}" AND ${spec.field}.sample_time.civil_time < "${next}"`;
    case 'interval':
    case 'session':
      return `${spec.field}.interval.civil_start_time >= "${start}" AND ${spec.field}.interval.civil_start_time < "${next}"`;
    case 'sleep':
      return `sleep.interval.civil_end_time >= "${start}" AND sleep.interval.civil_end_time < "${next}"`;
  }
}

export class HealthApiError extends Error {
  constructor(
    public status: number,
    public body: unknown,
    public url: string
  ) {
    const reason = (body as { error?: { status?: string; message?: string } })?.error;
    super(`Google Health API ${status} ${reason?.status ?? ''}: ${reason?.message ?? JSON.stringify(body).slice(0, 300)}`);
  }
}

export class NoTokenError extends Error {
  constructor(public reason: string) {
    super(
      reason === 'transient'
        ? 'Google token refresh failed (network or server error); try again shortly.'
        : 'No usable Google Health token. Run fitbit-mcp/bin/fitbit-reauth to consent.'
    );
  }
}

/** Makes one API call. Retries once on 429/5xx. Throws on any other non-2xx. */
export async function request<T>(method: 'GET' | 'POST', pathAndQuery: string, body?: unknown): Promise<T> {
  const token = await getAccessToken();
  if (!token) throw new NoTokenError(lastAuthFailure());
  const url = `${API_BASE}/${pathAndQuery.replace(/^\//, '')}`;
  for (let attempt = 0; ; attempt++) {
    const res = await fetch(url, {
      method,
      headers: {
        Authorization: `Bearer ${token}`,
        Accept: 'application/json',
        'User-Agent': USER_AGENT,
        ...(body ? { 'Content-Type': 'application/json' } : {}),
      },
      body: body ? JSON.stringify(body) : undefined,
      signal: AbortSignal.timeout(60_000),
    });
    if (res.ok) return (await res.json().catch(() => ({}))) as T;
    const errBody = await res.json().catch(async () => ({ raw: await res.text().catch(() => '') }));
    if ((res.status === 429 || res.status >= 500) && attempt < 1) {
      await sleep(2_000);
      continue;
    }
    throw new HealthApiError(res.status, errBody, url);
  }
}

export interface ListOptions {
  pageSize?: number;
  maxPoints?: number;
}

/** Lists data points that match a filter and follows page tokens. Newest first (API order). */
export async function listDataPoints(
  dataType: string,
  filter: string | null,
  { pageSize, maxPoints = 50_000 }: ListOptions = {}
): Promise<{ dataPoints: unknown[]; truncated: boolean }> {
  const out: unknown[] = [];
  let pageToken = '';
  for (;;) {
    const q = new URLSearchParams();
    if (filter) q.set('filter', filter);
    if (pageSize) q.set('pageSize', String(pageSize));
    if (pageToken) q.set('pageToken', pageToken);
    const page = await request<{ dataPoints?: unknown[]; nextPageToken?: string }>(
      'GET',
      `users/me/dataTypes/${dataType}/dataPoints?${q}`
    );
    out.push(...(page.dataPoints ?? []));
    pageToken = page.nextPageToken ?? '';
    if (!pageToken) return { dataPoints: out, truncated: false };
    if (out.length >= maxPoints) return { dataPoints: out, truncated: true };
  }
}

/** Data points for the civil dates [start, end] inclusive. */
export function listByDates(dataType: string, start: string, end: string, opts: ListOptions = {}) {
  return listDataPoints(dataType, dateFilter(dataTypeSpec(dataType), start, end), opts);
}

function civil(date: string) {
  const [year, month, day] = date.split('-').map(Number);
  return { date: { year, month, day } };
}

/**
 * Daily totals for the civil dates [start, end] inclusive. The API caps one call
 * at 90 days (14 for heart-rate, active-minutes, total-calories and
 * calories-in-heart-rate-zone), so longer ranges are split into chunks.
 */
export async function dailyRollUp(dataType: string, start: string, end: string): Promise<unknown[]> {
  const maxDays = ['heart-rate', 'active-minutes', 'total-calories', 'calories-in-heart-rate-zone'].includes(dataType)
    ? 14
    : 90;
  const out: unknown[] = [];
  for (let chunkStart = start; chunkStart <= end; chunkStart = addDays(chunkStart, maxDays)) {
    const chunkEnd = [addDays(chunkStart, maxDays - 1), end].sort()[0];
    let pageToken = '';
    do {
      const page = await request<{ rollupDataPoints?: unknown[]; nextPageToken?: string }>(
        'POST',
        `users/me/dataTypes/${dataType}/dataPoints:dailyRollUp`,
        {
          range: { start: civil(chunkStart), end: civil(addDays(chunkEnd, 1)) },
          windowSizeDays: 1,
          pageSize: 90,
          ...(pageToken ? { pageToken } : {}),
        }
      );
      out.push(...(page.rollupDataPoints ?? []));
      pageToken = page.nextPageToken ?? '';
    } while (pageToken);
  }
  return out;
}

export const identity = () => request<Record<string, unknown>>('GET', 'users/me/identity');
export const profile = () => request<Record<string, unknown>>('GET', 'users/me/profile');
export const settings = () => request<Record<string, unknown>>('GET', 'users/me/settings');
export const pairedDevices = () => request<Record<string, unknown>>('GET', 'users/me/pairedDevices');
