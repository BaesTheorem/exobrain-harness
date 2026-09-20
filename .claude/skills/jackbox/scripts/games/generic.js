// Fallback for games without a module: answers a lone text prompt, votes among a group of
// same-styled choice buttons. Deliberately conservative so it never clicks lobby controls
// (Everyone's in, Skip, Continue, Ready) on the friends' behalf.
const humor = require('../lib/humor');
const { fillAndSubmit, castTextVote, isSubmit } = require('../lib/actions');

const mem = { answered: new Map(), lastAnswerAt: 0, lastVoteSig: '' };
const CONTROL = /^(start|everyone|everybody|skip|continue|ready|ok|okay|next|back|cancel|yes|no|done|send|submit|play|join|reject|accept|close|got it|let'?s go|i'?m ready)\b/i;

function choiceGroup(st) {
  const cands = st.buttons.filter(b => !b.disabled && b.txt.length > 1 && !CONTROL.test(b.txt) && !isSubmit(b));
  const groups = new Map();
  for (const b of cands) { const k = b.cls || '(none)'; if (!groups.has(k)) groups.set(k, []); groups.get(k).push(b); }
  let best = null;
  for (const [cls, list] of groups) {
    const ok = list.length >= 3 || (list.length === 2 && /vote|choice|option|answer|pick|select/i.test(cls + ' ' + list.map(b => b.id).join(' ')));
    if (ok && (!best || list.length > best.length)) best = list;
  }
  return best;
}

async function tick(ctx, st) {
  if (st.canvas) return false;
  const input = st.inputs.find(i => !/roomcode|username/i.test(i.id));
  const submit = st.buttons.find(isSubmit);
  if (input && submit) {
    const prompt = humor.cleanPrompt(st.text, [ctx.playerName]);
    if (!prompt || mem.answered.has(prompt) || Date.now() - mem.lastAnswerAt < 15000) return true;
    mem.answered.set(prompt, null); mem.lastAnswerAt = Date.now();
    const t0 = Date.now();
    let ans, source = 'api';
    try { ans = await ctx.ai.answer(prompt); } catch (e) { ans = humor.fallbackAnswer(); source = 'fallback'; ctx.log('answer API fail: ' + e.message.split('\n')[0]); }
    if (input.maxlength) ans = ans.slice(0, input.maxlength);
    try {
      await fillAndSubmit(ctx, input, submit, ans);
      mem.answered.set(prompt, ans);
      ctx.record({ type: 'answer', game: 'generic', prompt, answer: ans, source, ms: Date.now() - t0 });
      ctx.log(`ANSWER(generic) [${prompt.slice(0, 80)}] -> "${ans}"`);
    } catch (e) { ctx.log('generic submit fail ' + e.message.split('\n')[0]); }
    return true;
  }
  if (st.inputs.length === 0) {
    const group = choiceGroup(st);
    if (group) {
      const sig = group.map(b => b.txt).sort().join('||');
      if (sig !== mem.lastVoteSig) {
        mem.lastVoteSig = sig;
        const question = humor.cleanPrompt(st.text, [ctx.playerName, ...group.map(b => b.txt)]);
        await castTextVote(ctx, 'generic', question, group, { maxPicks: 1 });
      }
      return true;
    }
  }
  return false;
}

module.exports = { name: 'generic', match: () => false, tick, mem, choiceGroup };
