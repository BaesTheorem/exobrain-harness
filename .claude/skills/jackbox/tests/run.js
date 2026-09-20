// Offline tests for the jackbox autopilot: probe + module detection against DOM fixtures, the
// Last Lash multi-pick, the lobby guard, drawing via pipelined CDP input (with a benchmark
// against per-point page.mouse), and the prompt parsers. No API calls: ctx.ai is a stub.
// Run: bin/jackbox test   (or node tests/run.js)
const path = require('path');
const fs = require('fs');
const { chromium } = require(require.resolve('playwright-core', { paths: [path.join(__dirname, '..', 'scripts')] }));
const { probe } = require('../scripts/lib/probe');
const { clickAt } = require('../scripts/lib/browser');
const draw = require('../scripts/lib/draw');
const humor = require('../scripts/lib/humor');
const quiplash = require('../scripts/games/quiplash');
const teeko = require('../scripts/games/teeko');
const generic = require('../scripts/games/generic');

const FIX = f => 'file://' + path.join(__dirname, 'fixtures', f);
const CHROME = '/Applications/Google Chrome.app/Contents/MacOS/Google Chrome';
const shellDir = path.join(process.env.HOME, 'Library/Caches/ms-playwright');
const shells = fs.existsSync(shellDir) ? fs.readdirSync(shellDir).filter(d => d.startsWith('chromium_headless_shell')).sort() : [];
let exe = CHROME;
if (shells.length) {
  const d = path.join(shellDir, shells[shells.length - 1]);
  const sub = fs.readdirSync(d).find(n => n.startsWith('chrome-headless-shell'));
  const cand = sub && path.join(d, sub, 'chrome-headless-shell');
  if (cand && fs.existsSync(cand)) exe = cand;   // true headless shell: no window, no flash
}

let pass = 0, fail = 0;
const ok = (cond, msg) => { if (cond) { pass++; console.log('  ok  ' + msg); } else { fail++; console.log('  FAIL ' + msg); } };

const PLAN = { concept: 'test smiley', strokes: [
  { color: 'black', points: [[0.3, 0.3], [0.35, 0.28], [0.4, 0.3]] },
  { color: 'red', points: [[0.6, 0.3], [0.65, 0.28], [0.7, 0.3]] },
  { color: 'black', points: [[0.3, 0.6], [0.4, 0.7], [0.5, 0.72], [0.6, 0.7], [0.7, 0.6]] },
] };
const stubAI = {
  answer: async () => 'A cupholder shaped like the middle class',
  judge: async () => 1,
  rank: async (q, opts) => opts.map((_, i) => i).reverse(),
  slogans: async n => Array.from({ length: n }, (_, i) => `Slogan ${i}`),
  design: async () => PLAN,
  visionPick: async () => 1,
};

(async () => {
  const browser = await chromium.launch({ executablePath: exe, headless: true, args: ['--mute-audio'] });
  const context = await browser.newContext({ viewport: { width: 520, height: 900 } });
  const page = await context.newPage();
  const cdp = await context.newCDPSession(page);
  const logs = [], records = [];
  const ctx = { page, cdp, ai: stubAI, playerName: 'AlexsClaude', log: m => logs.push(m), record: r => records.push(r), probe: () => probe(page) };
  const load = async f => { await page.goto(FIX(f)); await page.waitForLoadState('load'); return probe(page); };

  console.log('parsers');
  ok(humor.cleanPrompt('AlexsClaude\n42\nThe worst thing\nSEND\nANSWER HERE') === 'The worst thing', 'cleanPrompt strips name, timer, controls');
  ok(humor.extractAnswer('Thinking...\nFINAL: "A cupholder shaped like the middle class."') === 'A cupholder shaped like the middle class', 'extractAnswer handles FINAL: + quotes + period');
  ok(humor.extractAnswer('A very long answer that keeps going well past the forty five character limit here').length <= 45, 'extractAnswer trims to 45 at a word boundary');
  ok(humor.parseArray('Here:\n["a","b"]').length === 2, 'parseArray tolerates prose');

  console.log('quiplash: answer phase');
  let st = await load('quiplash-answer.html');
  ok(quiplash.match(st), 'matches by ids');
  ok(!teeko.match(st), 'teeko does not match');
  ok(await quiplash.tick(ctx, st), 'tick handled');
  let sub = await page.evaluate(() => ({ sub: window.__sub, safety: window.__safety }));
  ok(sub.sub === 'A cupholder shaped like the middle class', 'submitted the answer via #quiplash-submit-answer');
  ok(!sub.safety, 'never touched the Safety Quip');
  ok(records.find(r => r.type === 'answer' && r.prompt === 'The worst thing inside a burrito' || (r.type === 'answer' && /burrito/.test(r.prompt))), 'recorded the answer with the cleaned prompt');
  ok(!(await quiplash.tick(ctx, st)) || (await page.evaluate(() => window.__sub)) === 'A cupholder shaped like the middle class', 'does not re-answer the same prompt');

  console.log('quiplash: 2-way vote');
  st = await load('quiplash-vote.html');
  ok(st.voteEls.length === 2, 'probe sees 2 vote buttons');
  await quiplash.tick(ctx, st);
  let clicks = await page.evaluate(() => window.__clicks);
  ok(clicks.length === 1 && clicks[0] === 'A "surprise" party', 'clicked judge pick B (quotes in text are fine)');

  console.log('quiplash: Last Lash (6 options, ranked, multi-pick)');
  st = await load('quiplash-lastlash.html');
  ok(st.voteEls.length === 6, 'probe sees 6 vote buttons');
  await quiplash.tick(ctx, st);
  clicks = await page.evaluate(() => window.__clicks);
  ok(clicks.length === 3, `clicked 3 picks while choices stayed on screen (got ${clicks.length})`);
  ok(clicks[0] === 'Titanic 2: Ice Harder', 'first click = top of ranking');

  console.log('teeko: draw phase');
  st = await load('teeko-draw.html');
  ok(teeko.match(st), 'matches by #awshirt-submitdrawing + canvas');
  ok(st.canvas && st.canvas.blank === true, 'blank canvas detected');
  await teeko.tick(ctx, st);
  await page.waitForTimeout(200);
  let ev = await page.evaluate(() => ({ ...window.__ev, submitted: window.__submitted, color: window.__color }));
  ok(ev.down === 3 && ev.up === 3, `3 strokes reached the canvas (down=${ev.down} up=${ev.up})`);
  ok(ev.move > 20, `interpolated moves reached the canvas (${ev.move})`);
  ok(ev.trusted === 3, 'events are trusted (real CDP input)');
  ok(ev.color === 'black', 'palette swatch clicked by nearest color (last was black)');
  ok(ev.submitted === true, 'submitted the drawing');
  st = await probe(page);
  ok(st.canvas.blank === false, 'canvas no longer blank after drawing');

  console.log('teeko: text vote');
  st = await load('teeko-vote-text.html');
  ok(teeko.match(st), 'matches by awshirt vote class');
  await teeko.tick(ctx, st);
  clicks = await page.evaluate(() => window.__clicks);
  ok(clicks.length === 1 && clicks[0] === 'Live Laugh Litigate', 'clicked judge pick B');

  console.log('generic: guards + fallbacks');
  st = await load('lobby.html');
  ok(!quiplash.match(st) && !teeko.match(st), 'no specific module claims the lobby');
  ok(!(await generic.tick(ctx, st)), 'generic declines the lobby');
  clicks = await page.evaluate(() => window.__clicks);
  ok(clicks.length === 0, 'never clicked Everyone\'s in / Skip / Continue');
  st = await load('generic-answer.html');
  ok(await generic.tick(ctx, st), 'generic answers a lone prompt');
  ok((await page.evaluate(() => window.__sub)) === 'A cupholder shaped like the middle class', 'generic submitted');
  st = await load('generic-vote.html');
  ok(await generic.tick(ctx, st), 'generic votes among 3 same-class choices');
  clicks = await page.evaluate(() => window.__clicks);
  ok(clicks.length === 1 && clicks[0] === 'The moon is a rental', 'generic clicked the top-ranked choice once');

  console.log('drawing benchmark (same plan, 3 runs each)');
  st = await load('teeko-draw.html');
  const rect = st.canvas;
  const seq = async () => { for (const s of PLAN.strokes) {
    const pts = draw.interpolate(rect, s.points);
    await page.mouse.move(pts[0][0], pts[0][1]); await page.mouse.down();
    for (let i = 1; i < pts.length; i++) await page.mouse.move(pts[i][0], pts[i][1]);
    await page.mouse.up(); } };
  const pipe = async () => { for (const s of PLAN.strokes) await draw.drawStroke(cdp, rect, s.points); };
  const time = async fn => { const t = Date.now(); for (let i = 0; i < 3; i++) await fn(); return Math.round((Date.now() - t) / 3); };
  const tSeq = await time(seq), tPipe = await time(pipe);
  const moves = draw.interpolate(rect, PLAN.strokes[2].points).length;
  console.log(`  per-point page.mouse: ${tSeq}ms/plan   pipelined CDP: ${tPipe}ms/plan   (${PLAN.strokes.length} strokes, longest ${moves} points)`);
  ok(tPipe <= tSeq, 'pipelined is not slower than per-point');

  await browser.close();
  console.log(`\n${pass} passed, ${fail} failed`);
  process.exit(fail ? 1 : 0);
})().catch(e => { console.error('TEST CRASH', e); process.exit(1); });
