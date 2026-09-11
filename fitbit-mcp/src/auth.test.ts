import { describe, it, expect, vi, beforeEach } from 'vitest';

// Mutable state shared with the mock factories. vi.mock is hoisted above the
// imports, so the factories cannot close over ordinary module-level `let`
// bindings without hitting the temporal dead zone; vi.hoisted is the way in.
const h = vi.hoisted(() => ({
  // Stands in for .fitbit-token.json. null means the file does not exist.
  fileContents: null as string | null,
  refresh: vi.fn(),
  createToken: vi.fn(),
}));

vi.mock('simple-oauth2', () => ({
  AuthorizationCode: vi.fn(() => ({
    createToken: h.createToken,
    authorizeURL: vi.fn(() => 'https://example.invalid/authorize'),
  })),
}));

vi.mock('fs/promises', () => ({
  default: {
    readFile: vi.fn(async () => {
      if (h.fileContents === null) throw new Error('ENOENT');
      return h.fileContents;
    }),
    writeFile: vi.fn(async (_path: string, data: string) => {
      h.fileContents = data;
    }),
  },
}));

vi.mock('fs', () => ({
  existsSync: vi.fn(() => h.fileContents !== null),
}));

vi.mock('express', () => ({ default: vi.fn() }));
vi.mock('open', () => ({ default: vi.fn() }));
vi.mock('dotenv', () => ({ default: { config: vi.fn() } }));

const HOUR_MS = 60 * 60 * 1000;

function tokenJson(overrides: Record<string, unknown> = {}): string {
  return JSON.stringify({
    access_token: 'access-1',
    refresh_token: 'refresh-1',
    expires_in: 28800,
    expires_at: new Date(Date.now() + 8 * HOUR_MS).toISOString(),
    scope: 'profile',
    token_type: 'Bearer',
    user_id: 'USER1',
    ...overrides,
  });
}

const expired = { expires_at: new Date(Date.now() - HOUR_MS).toISOString() };

/** Fresh module instance, so the module-level token state starts empty. */
async function loadAuth() {
  vi.resetModules();
  return import('./auth.js');
}

describe('getAccessToken', () => {
  beforeEach(() => {
    vi.clearAllMocks();
    h.fileContents = null;
    h.createToken.mockImplementation(() => ({ refresh: h.refresh }));
  });

  it('returns the loaded token without refreshing when it is still fresh', async () => {
    h.fileContents = tokenJson();
    const auth = await loadAuth();
    await auth.initializeAuth();

    expect(await auth.getAccessToken()).toBe('access-1');
    expect(h.refresh).not.toHaveBeenCalled();
  });

  it('adopts a fresher token another instance wrote instead of spending its own', async () => {
    h.fileContents = tokenJson(expired);
    const auth = await loadAuth();
    await auth.initializeAuth();

    // Another server instance rotates the token before this one refreshes.
    h.fileContents = tokenJson({ access_token: 'access-2' });

    expect(await auth.getAccessToken()).toBe('access-2');
    expect(h.refresh).not.toHaveBeenCalled();
  });

  // The regression this file exists for. A lost refresh race nulls the in-memory
  // token, and that used to be permanent: every later call short-circuited to null
  // without ever re-reading the file, so the instance stayed dark until its whole
  // Claude session restarted, even though a sibling wrote a good token seconds
  // later. That is the "Fitbit dark all morning, fine by evening" failure.
  it('recovers on a later call once another instance writes a usable token', async () => {
    h.fileContents = tokenJson(expired);
    const auth = await loadAuth();
    await auth.initializeAuth();

    h.refresh.mockRejectedValueOnce(new Error('invalid_grant'));
    expect(await auth.getAccessToken()).toBeNull();

    // A sibling instance completes its own refresh and persists the result.
    h.fileContents = tokenJson({ access_token: 'access-2' });

    expect(await auth.getAccessToken()).toBe('access-2');
  });

  it('stays null while the token file is still missing', async () => {
    h.fileContents = tokenJson(expired);
    const auth = await loadAuth();
    await auth.initializeAuth();

    h.refresh.mockRejectedValueOnce(new Error('invalid_grant'));
    expect(await auth.getAccessToken()).toBeNull();

    h.fileContents = null;
    expect(await auth.getAccessToken()).toBeNull();
  });

  it('refreshes a stale token when no sibling has rotated it', async () => {
    h.fileContents = tokenJson(expired);
    const auth = await loadAuth();
    await auth.initializeAuth();

    h.refresh.mockResolvedValueOnce({
      token: JSON.parse(tokenJson({ access_token: 'access-refreshed' })),
    });

    expect(await auth.getAccessToken()).toBe('access-refreshed');
    expect(h.refresh).toHaveBeenCalledOnce();
    // The rotated token is persisted for every other instance to adopt.
    expect(JSON.parse(h.fileContents as string).access_token).toBe('access-refreshed');
  });
});
