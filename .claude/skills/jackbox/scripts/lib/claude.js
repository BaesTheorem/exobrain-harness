// Claude calls for the autopilots, through whichever credential exists:
//   - ANTHROPIC_API_KEY set  -> Anthropic SDK (retries, timeouts, effort control, base64 vision)
//   - otherwise              -> `claude -p` (Alex's Claude Code login; no key on this machine)
// Models: writing/drawing on Opus 5 (thinking on by default, depth via effort), text votes on
// Opus 5 at low effort (measured fastest through the CLI: ~2.6s wall, no thinking; Haiku 4.5
// there always thinks and takes 5-8s), vision votes on Sonnet 5 at low effort.
const { spawn } = require('child_process');
const fs = require('fs');
const os = require('os');
const path = require('path');
const humor = require('./humor');

const MODELS = {
  answer: process.env.JACKBOX_ANSWER_MODEL || 'claude-opus-5',
  judge: process.env.JACKBOX_JUDGE_MODEL || 'claude-opus-5',
  vision: process.env.JACKBOX_VISION_MODEL || 'claude-sonnet-5',
};
const EFFORT = process.env.JACKBOX_EFFORT || 'medium';   // low | medium | high; writing only
const PROVIDER = process.env.ANTHROPIC_API_KEY ? 'sdk' : 'cli';

// ---------- SDK provider ----------
let client = null;
function sdk() {
  if (!client) { const Anthropic = require('@anthropic-ai/sdk'); client = new Anthropic({ maxRetries: 2, timeout: 60_000 }); }
  return client;
}
async function askSdk(role, system, content, maxTokens, timeout) {
  const body = { model: MODELS[role], max_tokens: maxTokens, system, messages: [{ role: 'user', content }] };
  if (!/haiku/.test(body.model)) body.output_config = { effort: role === 'answer' ? EFFORT : 'low' };   // Haiku 4.5 rejects effort
  const res = await sdk().messages.create(body, timeout ? { timeout } : undefined);
  if (res.stop_reason === 'refusal') throw new Error('refused: ' + (res.stop_details?.category || '?'));
  return res.content.filter(b => b.type === 'text').map(b => b.text).join('').trim();
}

// ---------- claude -p provider ----------
// No MCP, no tools unless vision needs Read, neutral cwd. --bare would skip the global
// CLAUDE.md too, but it also skips keychain login, so the global instructions ride along
// (about 9k cached tokens) and the MIST kaomoji line they produce is stripped below.
let claudeBin = null;
function resolveClaude() {
  if (claudeBin) return claudeBin;
  const cands = [process.env.CLAUDE_BIN, path.join(os.homedir(), '.local', 'bin', 'claude'), '/opt/homebrew/bin/claude', '/usr/local/bin/claude'].filter(Boolean);
  claudeBin = cands.find(p => { try { fs.accessSync(p, fs.constants.X_OK); return true; } catch { return false; } });
  if (!claudeBin) throw new Error('claude CLI not found (set CLAUDE_BIN)');
  return claudeBin;
}
function askCli(role, system, prompt, timeout, { tools = [] } = {}) {
  const args = ['-p', prompt, '--system-prompt', system, '--output-format', 'json', '--model', MODELS[role],
    '--no-session-persistence', '--strict-mcp-config', '--mcp-config', '{"mcpServers":{}}',
    '--tools', tools.length ? tools.join(',') : ''];
  args.push('--effort', role === 'answer' ? EFFORT : 'low');
  const env = { ...process.env, PATH: ['/opt/homebrew/bin', '/usr/local/bin', path.join(os.homedir(), '.local', 'bin'), process.env.PATH || ''].join(':') };
  return new Promise((resolve, reject) => {
    // stdin must be closed: with it open, claude -p waits 3s for piped input before starting.
    const child = spawn(resolveClaude(), args, { cwd: '/tmp', env, stdio: ['ignore', 'pipe', 'pipe'] });
    let stdout = '', stderr = '', done = false;
    const timer = setTimeout(() => { if (!done) { done = true; child.kill('SIGKILL'); reject(new Error(`claude CLI: timeout after ${timeout || 60000}ms`)); } }, timeout || 60_000);
    child.stdout.on('data', d => { stdout += d; });
    child.stderr.on('data', d => { stderr += d; });
    child.on('error', e => { if (!done) { done = true; clearTimeout(timer); reject(new Error('claude CLI: ' + e.message)); } });
    child.on('close', code => {
      if (done) return; done = true; clearTimeout(timer);
      if (code !== 0) return reject(new Error(`claude CLI exit ${code}: ${stderr.slice(0, 200)}`));
      let data;
      try { data = JSON.parse(stdout); } catch { return reject(new Error('claude CLI: bad JSON ' + stdout.slice(0, 120))); }
      if (data.is_error) return reject(new Error('claude CLI error: ' + String(data.result).slice(0, 200)));
      resolve(stripPersona(String(data.result || '')));
    });
  });
}

// The global CLAUDE.md makes every reply open with a kaomoji on its own line; drop it.
function stripPersona(text) {
  const lines = text.trim().split('\n');
  while (lines.length > 1 && /^\s*\(.{1,8}\)\s*$/.test(lines[0])) lines.shift();
  return lines.join('\n').trim();
}

async function ask(role, system, content, maxTokens, { timeout } = {}) {
  if (PROVIDER === 'sdk') return askSdk(role, system, content, maxTokens, timeout);
  return askCli(role, system, content, timeout);
}

// ---- the judgment calls the games need ----

async function answer(prompt) {
  const raw = await ask('answer', humor.ANSWER_SYS, `Prompt to answer: ${prompt}`, 8000, { timeout: 45_000 });
  return humor.extractAnswer(raw);
}

async function slogans(n) {
  const raw = await ask('answer', humor.SLOGAN_SYS, `Write ${n} distinct genuinely funny t-shirt slogans. JSON array only.`, 8000, { timeout: 90_000 });
  return humor.parseArray(raw).map(s => String(s).replace(/^["'`]|["'`]$/g, '').trim()).filter(Boolean).map(s => s.slice(0, 45));
}

async function design() {
  const raw = await ask('answer', humor.DESIGN_SYS, 'Design one bold funny t-shirt graphic. JSON only.', 12000, { timeout: 90_000 });
  const plan = humor.parseObject(raw);
  plan.strokes = (plan.strokes || []).filter(s => Array.isArray(s.points) && s.points.length >= 2);
  return plan;
}

// Pairwise: returns 0 or 1.
async function judge(question, a, b) {
  const out = (await ask('judge', humor.JUDGE_SYS, `Prompt: ${question || '(unknown)'}\nA: ${a}\nB: ${b}\nFunnier?`, 5, { timeout: 15_000 })).toUpperCase();
  return (out.includes('B') && !out.includes('A')) ? 1 : 0;
}

// Ranking (Last Lash and any N-way vote): indices best-first, always a full permutation.
async function rank(question, options) {
  const list = options.map((o, i) => `${i + 1}. ${o}`).join('\n');
  const out = await ask('judge', humor.RANK_SYS, `Prompt: ${question || '(unknown)'}\n${list}\nRank them, funniest first:`, 40, { timeout: 15_000 });
  const seen = new Set(); const order = [];
  for (const m of out.matchAll(/\d+/g)) { const i = Number(m[0]) - 1; if (i >= 0 && i < options.length && !seen.has(i)) { seen.add(i); order.push(i); } }
  for (let i = 0; i < options.length; i++) if (!seen.has(i)) order.push(i);
  return order;
}

// Vision: which of two on-screen entries is funnier. Returns 0 or 1.
async function visionPick(pngBase64, labelA, labelB) {
  const system = `You judge a party-game battle between two entries. Reply with exactly one word: ${labelA} or ${labelB}, whichever is funnier or better.`;
  let out;
  if (PROVIDER === 'sdk') {
    out = await askSdk('vision', system,
      [{ type: 'image', source: { type: 'base64', media_type: 'image/png', data: pngBase64 } },
       { type: 'text', text: `Which is funnier: ${labelA} or ${labelB}? One word.` }], 5, 20_000);
  } else {
    const file = path.join(os.tmpdir(), `jb-vision-${Date.now()}.png`);
    fs.writeFileSync(file, Buffer.from(pngBase64, 'base64'));
    try { out = await askCli('vision', system, `Read the image at ${file} (it shows two entries). Which is funnier: ${labelA} or ${labelB}? Reply with that one word only.`, 30_000, { tools: ['Read'] }); }
    finally { try { fs.unlinkSync(file); } catch {} }
  }
  return out.toUpperCase().includes(labelB) ? 1 : 0;
}

module.exports = { MODELS, EFFORT, PROVIDER, ask, answer, slogans, design, judge, rank, visionPick };
