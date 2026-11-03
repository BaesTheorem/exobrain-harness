import { afterEach, beforeEach, describe, expect, it, vi } from 'vitest';
import { mkdtempSync, readFileSync, writeFileSync } from 'fs';
import os from 'os';
import path from 'path';

const dir = mkdtempSync(path.join(os.tmpdir(), 'ghealth-'));
const TOKEN = path.join(dir, 'token.json');
process.env.GOOGLE_HEALTH_TOKEN_FILE = TOKEN;
process.env.GOOGLE_OAUTH_CLIENT_ID = 'cid';
process.env.GOOGLE_OAUTH_CLIENT_SECRET = 'secret';

const auth = await import('./google-auth.js');
const gh = await import('./google-health.js');
const { periodRange } = await import('./google-tools.js');

const json = (status: number, body: unknown) =>
  new Response(JSON.stringify(body), { status, headers: { 'Content-Type': 'application/json' } });

function writeToken(expiresInMs: number, access = 'old-access') {
  writeFileSync(
    TOKEN,
    JSON.stringify({ access_token: access, refresh_token: 'refresh-1', scope: 's', token_type: 'Bearer', expires_at: new Date(Date.now() + expiresInMs).toISOString() })
  );
}

describe('dates and filters', () => {
  it('adds days across a month end and a DST change', () => {
    expect(gh.addDays('2026-10-31', 1)).toBe('2026-11-01');
    expect(gh.addDays('2026-11-01', 1)).toBe('2026-11-02');
    expect(gh.addDays('2026-03-01', -1)).toBe('2026-02-28');
  });

  it('uses the field that matches each time shape, end exclusive', () => {
    expect(gh.dateFilter(gh.dataTypeSpec('daily-resting-heart-rate'), '2026-11-01', '2026-11-02')).toBe(
      'daily_resting_heart_rate.date >= "2026-11-01" AND daily_resting_heart_rate.date < "2026-11-03"'
    );
    expect(gh.dateFilter(gh.dataTypeSpec('weight'), '2026-11-01', '2026-11-01')).toContain('weight.sample_time.civil_time < "2026-11-02"');
    expect(gh.dateFilter(gh.dataTypeSpec('steps'), '2026-11-01', '2026-11-01')).toContain('steps.interval.civil_start_time');
    expect(gh.dateFilter(gh.dataTypeSpec('exercise'), '2026-11-01', '2026-11-01')).toContain('exercise.interval.civil_start_time');
  });

  it('files sleep under the morning it ended (civil end time)', () => {
    expect(gh.dateFilter(gh.dataTypeSpec('sleep'), '2026-11-02', '2026-11-02')).toBe(
      'sleep.interval.civil_end_time >= "2026-11-02" AND sleep.interval.civil_end_time < "2026-11-03"'
    );
  });

  it('rejects an unknown data type instead of building a bad filter', () => {
    expect(() => gh.dataTypeSpec('sleeps')).toThrow(/unknown data type/);
  });

  it('turns a Fitbit period into an inclusive range ending on the date', () => {
    expect(periodRange('1d', '2026-11-02')).toEqual({ startDate: '2026-11-02', endDate: '2026-11-02' });
    expect(periodRange('7d', '2026-11-02')).toEqual({ startDate: '2026-10-27', endDate: '2026-11-02' });
    expect(periodRange('1w', '2026-11-02')).toEqual(periodRange('7d', '2026-11-02'));
  });
});

describe('token handling', () => {
  beforeEach(() => auth._resetForTests());
  afterEach(() => vi.unstubAllGlobals());

  it('uses a fresh token from disk without a network call', async () => {
    writeToken(30 * 60_000, 'disk-access');
    const fetchMock = vi.fn();
    vi.stubGlobal('fetch', fetchMock);
    expect(await auth.getAccessToken()).toBe('disk-access');
    expect(fetchMock).not.toHaveBeenCalled();
  });

  it('refreshes inside the skew window and keeps the refresh token Google omits', async () => {
    writeToken(60_000);
    vi.stubGlobal('fetch', vi.fn().mockResolvedValue(json(200, { access_token: 'new-access', expires_in: 3599, scope: 's' })));
    expect(await auth.getAccessToken()).toBe('new-access');
    const saved = JSON.parse(readFileSync(TOKEN, 'utf8'));
    expect(saved.refresh_token).toBe('refresh-1');
    expect(saved.access_token).toBe('new-access');
  });

  it('asks for the Health scopes only on refresh (the API refuses a token with other scopes)', async () => {
    writeToken(-60_000);
    const fetchMock = vi.fn().mockResolvedValue(json(200, { access_token: 'narrow', expires_in: 3599 }));
    vi.stubGlobal('fetch', fetchMock);
    await auth.getAccessToken();
    const body = new URLSearchParams(String((fetchMock.mock.calls[0] as [string, RequestInit])[1].body));
    expect(body.get('scope')?.split(' ').sort()).toEqual([...auth.SCOPES].sort());
    expect(auth.consentUrl()).not.toContain('include_granted_scopes');
  });

  it('reports invalid_grant as revoked and a 503 as transient, leaving the file alone', async () => {
    writeToken(-60_000);
    const before = readFileSync(TOKEN, 'utf8');
    vi.stubGlobal('fetch', vi.fn().mockResolvedValue(json(400, { error: 'invalid_grant' })));
    expect(await auth.getAccessToken()).toBeNull();
    expect(auth.lastAuthFailure()).toBe('revoked');

    auth._resetForTests();
    vi.stubGlobal('fetch', vi.fn().mockResolvedValue(json(503, {})));
    expect(await auth.getAccessToken()).toBeNull();
    expect(auth.lastAuthFailure()).toBe('transient');
    expect(readFileSync(TOKEN, 'utf8')).toBe(before);
  });
});

describe('dailyRollUp', () => {
  beforeEach(() => {
    auth._resetForTests();
    writeToken(30 * 60_000);
  });
  afterEach(() => vi.unstubAllGlobals());

  it('splits a long range at the 14-day cap and sends closed-open civil ranges', async () => {
    const bodies: { range: { start: { date: object }; end: { date: object } } }[] = [];
    vi.stubGlobal(
      'fetch',
      vi.fn(async (_url: string, init: RequestInit) => {
        bodies.push(JSON.parse(String(init.body)));
        return json(200, { rollupDataPoints: [{}] });
      })
    );
    const out = await gh.dailyRollUp('heart-rate', '2026-10-01', '2026-10-20');
    expect(bodies).toHaveLength(2);
    expect(bodies[0].range.start.date).toEqual({ year: 2026, month: 10, day: 1 });
    expect(bodies[0].range.end.date).toEqual({ year: 2026, month: 10, day: 15 });
    expect(bodies[1].range.start.date).toEqual({ year: 2026, month: 10, day: 15 });
    expect(bodies[1].range.end.date).toEqual({ year: 2026, month: 10, day: 21 });
    expect(out).toHaveLength(2);
  });

  it('follows page tokens on list calls', async () => {
    const pages = [json(200, { dataPoints: [1, 2], nextPageToken: 'p2' }), json(200, { dataPoints: [3] })];
    const fetchMock = vi.fn(async () => pages.shift()!);
    vi.stubGlobal('fetch', fetchMock);
    const r = await gh.listByDates('steps', '2026-11-01', '2026-11-01');
    expect(r.dataPoints).toEqual([1, 2, 3]);
    expect(String((fetchMock.mock.calls[1] as unknown[])[0])).toContain('pageToken=p2');
  });

  it('turns an API error into a HealthApiError with the status', async () => {
    vi.stubGlobal('fetch', vi.fn().mockResolvedValue(json(400, { error: { status: 'INVALID_ARGUMENT', message: 'bad filter' } })));
    await expect(gh.listByDates('steps', '2026-11-01', '2026-11-01')).rejects.toMatchObject({ status: 400 });
  });
});
