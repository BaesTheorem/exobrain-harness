// Shared moves: fill a text input, submit, cast a 2-way or N-way vote (with multi-pick for
// ranked rounds like Last Lash), and the vision vote for image-only choices.
const { clickAt, screenshot, sleep } = require('./browser');

async function fillAndSubmit(ctx, input, submitBtn, text) {
  const sel = input.id ? `#${input.id}` : 'textarea:visible, input[type=text]:visible, input:not([type]):visible';
  await ctx.page.fill(sel, text, { timeout: 2000 });
  if (submitBtn.id) await ctx.page.click(`#${submitBtn.id}`, { timeout: 2000 });
  else await clickAt(ctx.cdp, submitBtn.cx, submitBtn.cy);
}

// options: [{txt, cx, cy}], all with text. Picks by Haiku; for N>=3 keeps clicking the next-best
// while the same choices stay on screen (ranked rounds accept up to maxPicks votes; single-vote
// rounds close after the first click, so extra clicks land on nothing).
async function castTextVote(ctx, game, question, options, { maxPicks = 3 } = {}) {
  const t0 = Date.now();
  let order;
  try {
    order = options.length === 2 ? (await ctx.ai.judge(question, options[0].txt, options[1].txt)) === 1 ? [1, 0] : [0, 1]
                                 : await ctx.ai.rank(question, options.map(o => o.txt));
  } catch (e) {
    ctx.log(`${game} vote API fail, longest wins: ${e.message.split('\n')[0]}`);
    order = options.map((o, i) => i).sort((a, b) => options[b].txt.length - options[a].txt.length);
  }
  const picks = options.length >= 3 ? Math.min(maxPicks, options.length) : 1;
  const sig = options.map(o => o.txt).sort().join('||');
  const clicked = [];
  for (let k = 0; k < picks; k++) {
    const o = options[order[k]];
    if (k > 0) {
      await sleep(450);
      const st = await ctx.probe();
      const still = st.voteEls.concat(st.buttons).filter(v => v.txt && !v.disabled).map(v => v.txt);
      if (!options.every(x => still.includes(x.txt))) break;    // single-vote round already closed
    }
    await clickAt(ctx.cdp, o.cx, o.cy);
    clicked.push(o.txt);
  }
  ctx.record({ type: 'vote', game, question, options: options.map(o => o.txt), order, clicked, ms: Date.now() - t0 });
  ctx.log(`VOTE ${game}: "${clicked.join('" > "')}"  (of ${options.length})`);
  return clicked;
}

async function castVisionVote(ctx, game, votes) {
  const t0 = Date.now();
  const [a, b] = votes;
  const png = await screenshot(ctx.cdp);
  const lr = Math.abs(a.cx - b.cx) >= Math.abs(a.cy - b.cy);
  const labelA = lr ? 'LEFT' : 'TOP', labelB = lr ? 'RIGHT' : 'BOTTOM';
  const sorted = lr ? [a, b].sort((p, q) => p.cx - q.cx) : [a, b].sort((p, q) => p.cy - q.cy);
  let idx = 0;
  try { idx = await ctx.ai.visionPick(png, labelA, labelB); }
  catch (e) { ctx.log(`${game} vision fail, picking ${labelA}: ${e.message.split('\n')[0]}`); }
  const pick = sorted[idx];
  await clickAt(ctx.cdp, pick.cx, pick.cy);
  ctx.record({ type: 'vote', game, mode: 'vision', pick: idx ? labelB : labelA, ms: Date.now() - t0 });
  ctx.log(`VOTE ${game} (vision): ${idx ? labelB : labelA}`);
}

const isSubmit = b => !b.disabled && (/submit|send|done/i.test(b.id) || /^(SEND|SUBMIT|DONE|OK)$/i.test(b.txt));

module.exports = { fillAndSubmit, castTextVote, castVisionVote, isSubmit };
