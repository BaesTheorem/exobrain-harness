// Autonomous Quiplash 2 autopilot, LLM-powered humor. Runs locally in a tight loop so it
// never steals window focus and never misses fast voting windows.
//  - Writing prompts: Opus brainstorms 5 candidates, ships the funniest (<=45 chars).
//  - Voting: Sonnet picks the funnier of the two answers.
// NEVER uses the half-points "Safety Quip" — always submits a real full-points answer.
// Needs ANTHROPIC_API_KEY in env. Logs to stdout. Stop by killing the process.
const { chromium } = require('playwright');

const API_KEY = process.env.ANTHROPIC_API_KEY;
const ANSWER_MODEL = 'claude-opus-4-8';
const VOTE_MODEL = 'claude-sonnet-4-6';
const NOISE = ['ALEXSCLAUDE', 'SEND', 'SAFETY QUIP', '(HALF POINTS)', 'HALF POINTS', 'ANSWER HERE'];

const usedPrompts = new Map();
const votedKeys = new Map();
function log(m) { process.stdout.write(`[${new Date().toISOString()}] ${m}\n`); }

async function claude(model, system, user, maxTokens) {
  const res = await fetch('https://api.anthropic.com/v1/messages', {
    method: 'POST',
    headers: { 'x-api-key': API_KEY, 'anthropic-version': '2023-06-01', 'content-type': 'application/json' },
    body: JSON.stringify({ model, max_tokens: maxTokens, system, messages: [{ role: 'user', content: user }] }),
  });
  if (!res.ok) throw new Error(`API ${res.status}: ${(await res.text()).slice(0, 120)}`);
  const data = await res.json();
  return (data.content?.[0]?.text || '').trim();
}

// Comedic principles distilled from researching what wins Quiplash:
const ANSWER_SYS =
  "You are a ringer at Quiplash 2 — the player whose answers the whole room reads aloud and loses it over. " +
  "The crowd votes head-to-head, so your answer must beat the other player's. Funny wins, not clever-for-clever's-sake.\n\n" +
  "WHAT WINS (use these, don't just list them):\n" +
  "- SPECIFICITY beats generic. A vivid concrete image wins: 'Pulling a Beyoncé' > 'dancing'. Use real brand names, oddly specific numbers, named places.\n" +
  "- COMMIT TO THE ABSURD. No subtlety, no hedging. 'Cream of Existential Dread' > 'a bad flavor'.\n" +
  "- SMART-STUPID JUXTAPOSITION. Pair the highbrow with the idiotic: 'A TED Talk on the socioeconomic impact of carrots'.\n" +
  "- MISDIRECTION. The first joke everyone thinks of is dead on arrival. Skip it. Your 3rd or 4th idea is the funny one.\n" +
  "- RELATABLE DARKNESS. Shared misery lands: regret, debt, your ex, the DMV, crushing existential dread, HR.\n" +
  "- PUNCHY & FRONT-LOADED-LAST. Short. Put the funniest WORD at the very end so it lands when read aloud.\n" +
  "- A confident weird specific noun phrase usually beats a sentence.\n\n" +
  "AVOID: clichés, puns unless genuinely great, anything safe or milquetoast, explaining the joke, hashtags, emoji.\n\n" +
  "THE BAR (aim HERE, do not copy it): 'A cupholder shaped like the middle class.' " +
  "Why it's elite: a mundane object becomes a socioeconomic gut-punch — the cupholder is shrinking to nothing, like the middle class. " +
  "Surreal physical image + a topical/political truth + the devastating idea landing on the final word. " +
  "Reach for that: take an ordinary noun and weaponize it as a metaphor for something we're all quietly grim about (the economy, healthcare, aging, dating apps, work). Don't settle for merely 'quirky'.\n\n" +
  "PROCESS: Silently brainstorm 5 candidates using DIFFERENT techniques above. Then pick the single funniest one to read aloud to a room. " +
  "Output ONLY that one, on a final line prefixed exactly with 'FINAL:'. Hard limit 45 characters for the final answer. " +
  "No quotation marks, no trailing period.";

function extractFinal(text) {
  const m = text.match(/FINAL:\s*(.+)\s*$/im);
  let a = (m ? m[1] : text.split('\n').filter(Boolean).pop() || '').trim();
  a = a.replace(/^["'`]|["'`.]+$/g, '').replace(/\s+/g, ' ').trim();
  if (a.length > 45) {
    // Trim to a clean word boundary, never mid-word, to avoid broken-looking cuts.
    let cut = a.slice(0, 45);
    const sp = cut.lastIndexOf(' ');
    if (sp > 20) cut = cut.slice(0, sp);
    a = cut.replace(/[\s,;:.-]+$/, '').trim();
  }
  return a;
}

async function genAnswer(prompt) {
  const raw = await claude(ANSWER_MODEL, ANSWER_SYS,
    `Prompt to answer: ${prompt}\n\nBrainstorm 5, then give your funniest as FINAL:`, 400);
  return extractFinal(raw);
}

async function pickVote(question, a, b) {
  const sys = "You judge Quiplash answers. Reply with exactly one character: A or B — whichever is funnier. Nothing else.";
  const user = `Prompt: ${question || '(unknown)'}\nA: ${a}\nB: ${b}\nFunnier?`;
  const out = (await claude(VOTE_MODEL, sys, user, 5)).toUpperCase();
  if (out.includes('A') && !out.includes('B')) return a;
  if (out.includes('B') && !out.includes('A')) return b;
  return a.length >= b.length ? a : b;
}

function clean(text) {
  let lines = text.split('\n').map(s => s.trim()).filter(Boolean);
  lines = lines.filter(l => !NOISE.some(n => l.toUpperCase() === n.toUpperCase()));
  lines = lines.filter(l => !/WHICH ONE DO YOU LIKE/i.test(l));
  return lines.join(' ').slice(0, 160);
}

(async () => {
  if (!API_KEY) { log('FATAL no ANTHROPIC_API_KEY'); process.exit(1); }
  const browser = await chromium.connectOverCDP('http://localhost:9222');
  const ctx = browser.contexts()[0];
  const page = ctx.pages().find(p => p.url().includes('jackbox')) || ctx.pages()[0];
  log('Quiplash autopilot connected (answers=' + ANSWER_MODEL + ', votes=' + VOTE_MODEL + ')');

  while (true) {
    try {
      const state = await page.evaluate(() => {
        const vis = el => {
          const r = el.getBoundingClientRect(); const s = getComputedStyle(el);
          return r.width > 0 && r.height > 0 && s.visibility !== 'hidden' && s.display !== 'none' && s.opacity !== '0' && !el.disabled;
        };
        const voteBtns = [...document.querySelectorAll('button')].filter(b => vis(b) && /vote-button/.test(b.className));
        const votes = voteBtns.map(b => (b.innerText || '').trim());
        const input = document.querySelector('#quiplash-answer-input');
        const submit = document.querySelector('#quiplash-submit-answer');
        const canAnswer = !!(input && submit && vis(input) && vis(submit));
        const raw = (document.body.innerText || '');
        return { votes, canAnswer, raw };
      });

      if (state.votes.length >= 2) {
        const [a, b] = state.votes;
        const key = [a, b].slice().sort().join('||');
        if (!votedKeys.has(key)) {
          votedKeys.set(key, true); // claim immediately so we don't double-fire while awaiting API
          let choice;
          try { choice = await pickVote(clean(state.raw), a, b); }
          catch (e) { choice = a.length >= b.length ? a : b; log('vote API fail, fallback: ' + e.message); }
          try {
            await page.click(`button.quiplash2-vote-button:has-text("${choice.replace(/"/g, '\\"')}")`, { timeout: 1500 });
            log(`VOTED: ${choice}  (over: ${[a, b].filter(v => v !== choice).join(' / ')})`);
          } catch { log(`vote window closed before click: ${choice}`); }
        }
      } else if (state.canAnswer) {
        const prompt = clean(state.raw);
        if (prompt && !usedPrompts.has(prompt)) {
          usedPrompts.set(prompt, true); // claim immediately
          let ans;
          try { ans = await genAnswer(prompt); }
          catch (e) { ans = 'A deeply concerning amount of mayonnaise'; log('answer API fail, fallback: ' + e.message); }
          try {
            await page.fill('#quiplash-answer-input', ans, { timeout: 2000 });
            await page.click('#quiplash-submit-answer', { timeout: 2000 }); // never #quiplash-submit-safetyquip
            usedPrompts.set(prompt, ans);
            log(`ANSWERED [${prompt}] -> "${ans}"`);
          } catch (e) { log(`submit failed for [${prompt}]: ${e.message.split('\n')[0]}`); }
        }
      }
    } catch (e) {
      log('loop error: ' + e.message.split('\n')[0]);
    }
    await new Promise(r => setTimeout(r, 1000));
  }
})().catch(e => { log('FATAL ' + e.message); process.exit(1); });
