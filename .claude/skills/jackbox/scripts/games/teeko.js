// Tee K.O. (internal name "awshirt"): draw with pipelined mouse strokes, feed a pre-generated
// slogan queue, vote text-first with a vision fallback for image-only shirts.
const { drawPlan } = require('../lib/draw');
const { fillAndSubmit, castTextVote, castVisionVote, isSubmit } = require('../lib/actions');

const mem = { queue: [], fetching: false, drewThisCanvas: false, lastSlogan: 0, lastVoteSig: '' };

function refill(ctx, n) {
  if (mem.fetching) return;
  mem.fetching = true;
  ctx.ai.slogans(n).then(q => { mem.queue.push(...q); ctx.log(`slogan queue: ${mem.queue.length}`); })
    .catch(e => ctx.log('slogan gen fail ' + e.message.split('\n')[0]))
    .finally(() => { mem.fetching = false; });
}

const isShirt = s => /awshirt/i.test(s);

function match(st) {
  return st.buttons.some(b => isShirt(b.id + ' ' + b.cls)) || st.voteEls.some(v => isShirt(v.id + ' ' + v.cls)) ||
    (!!st.canvas && st.buttons.some(b => /submitdrawing/i.test(b.id)));
}

async function tick(ctx, st) {
  if (mem.queue.length < 8) refill(ctx, 30);

  const votes = st.voteEls.filter(v => !v.disabled).slice(0, 2);
  if (votes.length >= 2) {
    const [a, b] = votes;
    const sig = (a.txt || `${a.cx},${a.cy}`) + '||' + (b.txt || `${b.cx},${b.cy}`);
    if (sig !== mem.lastVoteSig) {
      mem.lastVoteSig = sig;
      if (a.txt.length > 1 && b.txt.length > 1) await castTextVote(ctx, 'teeko', 'Funnier t-shirt', votes, { maxPicks: 1 });
      else await castVisionVote(ctx, 'teeko', votes);
    }
    return true;
  }

  const submitDraw = st.buttons.find(b => b.id === 'awshirt-submitdrawing' && !b.disabled);
  if (st.canvas && submitDraw) {
    if (st.canvas.blank === true) mem.drewThisCanvas = false;
    if (!mem.drewThisCanvas) {
      mem.drewThisCanvas = true;
      const t0 = Date.now();
      try {
        const plan = await ctx.ai.design();
        const tDesign = Date.now() - t0;
        await drawPlan(ctx.cdp, ctx.page, st.canvas, plan);
        await ctx.page.click('#awshirt-submitdrawing', { timeout: 2500 });
        ctx.record({ type: 'drawing', game: 'teeko', concept: plan.concept, strokes: plan.strokes.length, designMs: tDesign, ms: Date.now() - t0 });
        ctx.log(`DREW "${plan.concept}" (${plan.strokes.length} strokes, design ${tDesign}ms, total ${Date.now() - t0}ms)`);
      } catch (e) { ctx.log('draw/submit fail ' + e.message.split('\n')[0]); }
    }
    return true;
  }
  if (!st.canvas) mem.drewThisCanvas = false;

  const input = st.inputs.find(i => !/roomcode|username/i.test(i.id));
  const submit = st.buttons.find(isSubmit);
  if (input && submit) {
    if (mem.queue.length && Date.now() - mem.lastSlogan > 700) {
      const s = mem.queue.shift(); mem.lastSlogan = Date.now();
      try { await fillAndSubmit(ctx, input, submit, input.maxlength ? s.slice(0, input.maxlength) : s); ctx.record({ type: 'slogan', game: 'teeko', slogan: s }); ctx.log('SLOGAN: ' + s); }
      catch (e) { ctx.log('slogan submit fail ' + e.message.split('\n')[0]); }
    }
    return true;
  }
  return false;
}

module.exports = { name: 'teeko', match, tick, mem };
