// Bridge between the mychart Python CLI and the OpenRecord engine
// (the mychart-cli library, built from a local checkout).
//
// Protocol: newline-delimited JSON.
//   stdin, line 1:   the request (see OPS below)
//   stdin, later:    answers to prompts, e.g. {"code": "123456"}
//   stdout:          one event per line, {"event": "...", ...}
//   stderr:          human-readable progress only
//
// Secrets (password, passkey, session) arrive on stdin and leave as events on
// stdout. They are never written to disk here and never put in argv or env.
// The caller (mychart_core.py) owns storage, in the macOS Keychain.
//
// INVARIANTS:
// - Every chart read checks whose record is active (assertProxyReadContext)
//   before it runs, the same guarantee as the engine's executeCapability.
// - A capability with kind "write" or "account" runs only when the request
//   says allow_write: true. The caller decides that, never this file.
// - After any passkey login, the advanced credential is emitted at once and
//   again at exit, so the stored signCount never falls behind the server.

import { createInterface } from 'node:readline';
import { mkdirSync, existsSync, writeFileSync } from 'node:fs';
import { join, extname, basename } from 'node:path';
import { format } from 'node:util';

process.env.MYCHART_CLI_TELEMETRY_DISABLED = '1';

// The engine logs every request with console.log. stdout carries the
// protocol, so all console output goes to stderr.
const toStderr = (...args) => process.stderr.write(format(...args) + '\n');
console.log = toStderr;
console.info = toStderr;
console.debug = toStderr;
console.warn = toStderr;

// A write to a pipe is asynchronous in Node, and process.exit() drops whatever
// is still queued. A sync with large envelopes lost its last events that way
// (2026-10-19, first real account). So the last line exits from its own write
// callback, which runs only after every earlier write has flushed.
function finish(rc) {
  process.stdout.write(JSON.stringify({ event: 'done', rc }) + '\n', () => process.exit(rc));
}

const ENGINE = process.env.MYCHART_ENGINE;
if (!ENGINE) {
  emit({ event: 'fatal', error: 'MYCHART_ENGINE is not set (path to npm-package/dist/index.js)' });
  finish(2);
  await new Promise(() => {});
}
const lib = await import(ENGINE);
const { MyChartClient, getCapability, CAPABILITIES, serializeCredential, deserializeCredential } = lib;

const MAX_SIGN_COUNT_BUMPS = 10;

function emit(obj) {
  process.stdout.write(JSON.stringify(obj, replacer) + '\n');
}

function log(msg) {
  process.stderr.write(`[bridge] ${msg}\n`);
}

// JSON.stringify cannot carry bytes; files are written out before emit, so a
// stray Uint8Array here is a bug. Make it visible instead of a giant array.
function replacer(_key, value) {
  if (value instanceof Uint8Array) return { __bytes__: value.length };
  if (typeof value === 'bigint') return value.toString();
  return value;
}

const rl = createInterface({ input: process.stdin, crlfDelay: Infinity });
const lines = rl[Symbol.asyncIterator]();

async function nextLine() {
  const { value, done } = await lines.next();
  if (done) return null;
  return value;
}

async function ask(event) {
  emit(event);
  const line = await nextLine();
  if (line === null) return null;
  try {
    return JSON.parse(line);
  } catch {
    return null;
  }
}

function describe(c) {
  return {
    id: c.id,
    aliases: c.aliases ?? [],
    title: c.title,
    description: c.description,
    kind: c.kind,
    group: c.group,
    params: c.params ?? [],
    lessFrequentlyUsed: Boolean(c.lessFrequentlyUsed),
    notImplemented: c.notImplemented ? String(c.notImplemented) : null,
    hasProcessor: Boolean(c.processor),
    returnsFile: Boolean(c.returnsFile),
    rendersMedia: Boolean(c.rendersMedia),
  };
}

// Write every byte array found in a result to outDir and replace it with a
// small record of where it went. Covers returnsFile payloads ({fileName,
// mimeType, bytes}) and image lists alike.
function saveBytes(value, outDir, hint, counter = { n: 0 }) {
  if (value instanceof Uint8Array) {
    mkdirSync(outDir, { recursive: true, mode: 0o700 });
    counter.n += 1;
    const name = uniquePath(outDir, `${hint || 'file'}-${counter.n}.bin`);
    writeFileSync(name, value, { mode: 0o600 });
    return { savedTo: name, size: value.length };
  }
  if (Array.isArray(value)) return value.map((v) => saveBytes(v, outDir, hint, counter));
  if (value && typeof value === 'object') {
    if (value.bytes instanceof Uint8Array && typeof value.fileName === 'string') {
      mkdirSync(outDir, { recursive: true, mode: 0o700 });
      const path = uniquePath(outDir, basename(value.fileName));
      writeFileSync(path, value.bytes, { mode: 0o600 });
      const { bytes, ...rest } = value;
      return { ...rest, savedTo: path, size: bytes.length };
    }
    const out = {};
    for (const [k, v] of Object.entries(value)) out[k] = saveBytes(v, outDir, k, counter);
    return out;
  }
  return value;
}

function uniquePath(dir, name) {
  const ext = extname(name);
  const stem = name.slice(0, name.length - ext.length) || 'file';
  let candidate = join(dir, name);
  for (let i = 2; existsSync(candidate); i++) candidate = join(dir, `${stem}-${i}${ext}`);
  return candidate;
}

function errInfo(err) {
  return {
    name: err?.name ?? 'Error',
    message: String(err?.message ?? err),
    status: err?.status,
    path: err?.path,
  };
}

// ── Sign-in ────────────────────────────────────────────────────────────────

async function connect(req) {
  const account = req.account ?? {};
  const auth = req.auth ?? {};
  const base = { hostname: account.host, protocol: account.protocol };

  // 1. A saved session, if MyChart still accepts it. It cannot renew itself,
  //    so it is only used when no passkey exists to renew with.
  if (auth.session && !auth.passkey) {
    try {
      const client = await MyChartClient.fromSerialized(auth.session);
      if (client && (await client.isSessionValid())) {
        log('using the saved session');
        return { client, method: 'session' };
      }
      client?.close();
    } catch (err) {
      log(`saved session unusable: ${errInfo(err).message}`);
    }
  }

  // 2. Passkey, with the engine CLI's counter-drift recovery: on a rejection,
  //    raise signCount one step and retry, up to MAX_SIGN_COUNT_BUMPS.
  if (auth.passkey) {
    const credential = deserializeCredential(auth.passkey);
    const start = credential.signCount;
    let result;
    for (let bump = 0; bump <= MAX_SIGN_COUNT_BUMPS; bump++) {
      credential.signCount = start + bump;
      result = await MyChartClient.connectWithPasskey({ ...base, credential });
      if (result.state !== 'invalid_login') break;
      log(`passkey rejected at signCount ${start + bump}, retrying one step higher`);
    }
    emit({ event: 'passkey', credential: serializeCredential(credential) });
    if (result.state === 'connected') return { client: result.client, method: 'passkey', credential };
    if (!auth.pass) {
      return { error: { state: result.state, message: result.error ?? `passkey login: ${result.state}` } };
    }
    log(`passkey login failed (${result.state}); trying the password`);
  }

  // 3. Username and password, with TOTP or an interactive code for 2FA.
  if (auth.user && auth.pass) {
    const result = await MyChartClient.connect({
      ...base,
      user: auth.user,
      pass: auth.pass,
      totpSecret: auth.totp || undefined,
      skipSendCode: Boolean(auth.totp),
    });
    if (result.state === 'connected') return { client: result.client, method: 'password' };
    if (result.state === 'invalid_login') return { error: { state: 'invalid_login', message: 'wrong username or password' } };
    if (result.state === 'error') return { error: { state: 'error', message: result.error ?? 'sign-in error' } };
    // need_2fa
    if (auth.totp) {
      const code = await MyChartClient.totpCode(auth.totp);
      const client = await result.complete(code, { isTOTP: true });
      return { client, method: 'password+totp' };
    }
    if (!req.interactive) {
      return { error: { state: 'need_2fa', message: 'MyChart asked for a 2FA code and this run is not interactive' } };
    }
    for (let attempt = 1; attempt <= 3; attempt++) {
      const answer = await ask({ event: 'need_2fa', delivery: result.delivery ?? null, attempt });
      const code = answer?.code ? String(answer.code).trim() : '';
      if (!code) return { error: { state: 'need_2fa', message: 'no code given' } };
      try {
        const client = await result.complete(code);
        return { client, method: 'password+code' };
      } catch (err) {
        emit({ event: 'code_rejected', attempt, message: errInfo(err).message });
      }
    }
    return { error: { state: 'need_2fa', message: 'three codes rejected' } };
  }

  return { error: { state: 'no_credentials', message: 'no session, passkey, or password for this account' } };
}

// ── Capabilities ───────────────────────────────────────────────────────────

async function runAction(client, action, req) {
  const cap = getCapability(action.id);
  if (!cap) return { id: action.id, ok: false, error: { name: 'UnknownCapability', message: `unknown capability ${action.id}` } };
  const args = { ...(action.args ?? {}) };
  const out = { id: cap.id, kind: cap.kind, args: action.args ?? {} };

  if ((cap.kind === 'write' || cap.kind === 'account') && !req.allow_write) {
    return { ...out, ok: false, error: { name: 'WriteRefused', message: `${cap.id} changes the record; the caller did not allow writes` } };
  }
  if (cap.notImplemented) return { ...out, ok: false, error: { name: 'NotImplemented', message: String(cap.notImplemented) } };

  try {
    // Envelope path: one fetch gives both what MyChart sent and the standard
    // object. The engine hides run/processor from its types, not at runtime;
    // if a future version hides them for real, fall back to runCapability.
    // An explicit output mode (raw, concise, ...) is the engine's own path.
    const canEnvelope = cap.kind === 'read' && cap.processor && typeof cap.run === 'function' && !args.mode;
    if (canEnvelope) {
      await client.assertProxyReadContext(args.patient);
      const envelope = await cap.run(client.request, args);
      const standard = cap.processor.standard(envelope);
      return action.envelope ? { ...out, ok: true, standard, envelope } : { ...out, ok: true, standard };
    }
    let result = await client.runCapability(cap.id, args);
    if (cap.returnsFile || cap.rendersMedia) result = saveBytes(result, req.out_dir || '.', cap.id);
    return { ...out, ok: true, standard: result };
  } catch (err) {
    return { ...out, ok: false, error: errInfo(err) };
  }
}

// ── Ops ────────────────────────────────────────────────────────────────────

async function opSession(req) {
  const conn = await connect(req);
  if (conn.error) {
    emit({ event: 'login', ok: false, ...conn.error });
    return 1;
  }
  const { client, method, credential } = conn;
  emit({ event: 'login', ok: true, method });
  let rc = 0;
  try {
    if (req.setup_passkey) {
      const created = await client.setupPasskey();
      if (created) emit({ event: 'passkey_created', credential: serializeCredential(created) });
      else {
        emit({ event: 'passkey_refused', message: 'MyChart did not accept a new passkey on this account' });
        rc = 1;
      }
    }
    if (req.setup_totp) {
      // Turns on authenticator-app 2FA for the account. The CLI asks for it
      // only on an explicit --method totp, because it changes how the person
      // signs in everywhere else too.
      const { secret, error } = await client.setupTotp(req.auth?.pass);
      if (secret) emit({ event: 'totp_created', secret });
      else {
        emit({ event: 'totp_refused', message: error ?? 'MyChart did not accept an authenticator' });
        rc = 1;
      }
    }
    if (req.list_passkeys) emit({ event: 'passkeys', passkeys: await client.listPasskeys() });
    for (const action of req.actions ?? []) {
      const result = await runAction(client, action, req);
      if (!result.ok) rc = 1;
      emit({ event: 'action', ...result });
    }
    if (req.keep_session) emit({ event: 'session', session: await client.serialize() });
  } finally {
    // A silent re-login during the run advanced the counter again.
    if (credential) emit({ event: 'passkey', credential: serializeCredential(credential) });
    client.close();
  }
  return rc;
}

async function opPublic(req) {
  try {
    const data = await MyChartClient.runPublicCapability(req.id, req.args ?? {});
    emit({ event: 'action', id: req.id, ok: true, standard: data });
    return 0;
  } catch (err) {
    emit({ event: 'action', id: req.id, ok: false, error: errInfo(err) });
    return 1;
  }
}

function opRender(req) {
  const cap = getCapability(req.id);
  if (!cap || !cap.processor) {
    emit({ event: 'render', ok: false, error: { message: `no processor for ${req.id}` } });
    return 1;
  }
  let standard;
  try {
    standard = cap.processor.standard(req.envelope);
  } catch (err) {
    emit({ event: 'render', ok: false, error: errInfo(err) });
    return 1;
  }
  // The engine does not export its markdown renderer, so "concise" is the
  // concise projection as an object. Models read JSON fine.
  const output = req.mode === 'concise' && standard != null ? cap.processor.concise(standard) : standard;
  emit({ event: 'render', ok: true, output });
  return 0;
}

const OPS = {
  capabilities: () => {
    emit({ event: 'capabilities', capabilities: CAPABILITIES.map(describe) });
    return 0;
  },
  public: opPublic,
  session: opSession,
  render: opRender,
};

let rc = 1;
try {
  const first = await nextLine();
  const req = first ? JSON.parse(first) : {};
  const op = OPS[req.op];
  if (!op) {
    emit({ event: 'fatal', error: `unknown op ${req.op}` });
  } else {
    rc = await op(req);
  }
} catch (err) {
  emit({ event: 'fatal', error: errInfo(err) });
}
rl.close();
finish(rc);
