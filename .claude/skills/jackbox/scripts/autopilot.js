// One loop for the whole game night. Probes the controller DOM twice a second, picks the game
// module that recognizes the screen (sticky across a game's waiting screens), lets the generic
// module cover anything the specific one declined, and logs every move to a per-run JSONL.
// Usage: node autopilot.js [--game quiplash|teeko|generic] [--name AlexsClaude] [--interval 500]
const { connect, clickAt, screenshot } = require('./lib/browser');
const { probe } = require('./lib/probe');
const ai = require('./lib/claude');
const results = require('./lib/results');
const humor = require('./lib/humor');

const MODULES = [require('./games/quiplash'), require('./games/teeko')];
const generic = require('./games/generic');

const args = process.argv.slice(2);
const opt = (k, d) => { const i = args.indexOf(k); return i >= 0 ? args[i + 1] : d; };
const forced = opt('--game', null);
const interval = Number(opt('--interval', 500));
const playerName = opt('--name', 'AlexsClaude');

const log = m => process.stdout.write(`[${new Date().toISOString()}] ${m}\n`);

(async () => {
  // Credentials: the SDK path needs ANTHROPIC_API_KEY; the CLI path needs a logged-in claude binary.
  if (ai.PROVIDER === 'cli') { try { await ai.ask('judge', 'Reply with the single letter B.', 'B?', 5, { timeout: 30_000 }); } catch (e) { log('FATAL claude CLI unusable: ' + e.message.split('\n')[0]); process.exit(1); } }
  const { page, cdp } = await connect();
  const out = results.open(forced || 'auto');
  const ctx = { page, cdp, ai, playerName, log, record: out.record, probe: () => probe(page), clickAt: (x, y) => clickAt(cdp, x, y), screenshot: f => screenshot(cdp, f) };
  log(`autopilot up: provider=${ai.PROVIDER} game=${forced || 'auto'} answers=${ai.MODELS.answer}/${ai.EFFORT} judge=${ai.MODELS.judge} vision=${ai.MODELS.vision} log=${out.file}`);

  const forcedMod = forced ? [...MODULES, generic].find(m => m.name === forced) : null;
  if (forced && !forcedMod) { log(`FATAL unknown --game ${forced}`); process.exit(1); }
  let sticky = null, lastHB = 0, lastScreen = '', errors = 0;

  while (true) {
    try {
      const st = await ctx.probe();
      const detected = forcedMod || MODULES.find(m => m.match(st)) || null;
      if (detected && detected !== generic && detected !== sticky) { sticky = detected; log(`game detected: ${sticky.name}`); ctx.record({ type: 'game', game: sticky.name }); }
      const mod = detected || sticky;

      const screen = humor.cleanPrompt(st.text).slice(0, 300);
      if (screen !== lastScreen) { lastScreen = screen; ctx.record({ type: 'screen', game: mod ? mod.name : null, text: screen, inputs: st.inputs.length, buttons: st.buttons.map(b => b.txt).slice(0, 12) }); }

      let handled = false;
      if (mod) handled = await mod.tick(ctx, st);
      if (!handled && mod !== generic) handled = await generic.tick(ctx, st);

      if (Date.now() - lastHB > 8000) {
        lastHB = Date.now();
        log(`hb game=${mod ? mod.name : '-'} handled=${handled} inputs=${st.inputs.length} votes=${st.voteEls.length} canvas=${!!st.canvas} text="${screen.slice(0, 60)}"`);
      }
      errors = 0;
    } catch (e) {
      const msg = e.message.split('\n')[0];
      log('loop error: ' + msg);
      if (/Target (closed|crashed)|has been closed|Protocol error.*(closed|detached)|ECONNREFUSED/i.test(msg) && ++errors > 5) { log('FATAL browser gone'); process.exit(2); }
    }
    await new Promise(r => setTimeout(r, interval));
  }
})().catch(e => { log('FATAL ' + e.message); process.exit(1); });
