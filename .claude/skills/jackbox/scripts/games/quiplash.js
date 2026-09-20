// Quiplash 2 (and anything sharing its controller ids). Text in, text votes, ranked Last Lash.
// NEVER touches #quiplash-submit-safetyquip: the Safety Quip is half points.
const humor = require('../lib/humor');
const { fillAndSubmit, castTextVote } = require('../lib/actions');

const mem = { answered: new Map(), lastAnswerAt: 0, lastVoteSig: '' };

const isQuip = s => /quiplash/i.test(s);

function match(st) {
  return st.inputs.some(i => isQuip(i.id)) || st.buttons.some(b => isQuip(b.id + ' ' + b.cls)) || st.voteEls.some(v => isQuip(v.id + ' ' + v.cls));
}

async function tick(ctx, st) {
  const votes = st.voteEls.filter(v => /vote-button/i.test(v.cls) && !v.disabled && v.txt.length > 0);
  if (votes.length >= 2) {
    const sig = votes.map(v => v.txt).sort().join('||');
    if (sig !== mem.lastVoteSig) {
      mem.lastVoteSig = sig;
      const question = humor.cleanPrompt(st.text, [ctx.playerName, ...votes.map(v => v.txt)]);
      await castTextVote(ctx, 'quiplash', question, votes);
    }
    return true;
  }

  const input = st.inputs.find(i => i.id === 'quiplash-answer-input');
  const submit = st.buttons.find(b => b.id === 'quiplash-submit-answer' && !b.disabled);
  if (input && submit) {
    const prompt = humor.cleanPrompt(st.text, [ctx.playerName]);
    if (!prompt || mem.answered.has(prompt) || Date.now() - mem.lastAnswerAt < 15000) return true;
    mem.answered.set(prompt, null); mem.lastAnswerAt = Date.now();
    const t0 = Date.now();
    let ans, model = 'api';
    try { ans = await ctx.ai.answer(prompt); }
    catch (e) { ans = humor.fallbackAnswer(); model = 'fallback'; ctx.log(`answer API fail, fallback: ${e.message.split('\n')[0]}`); }
    if (input.maxlength) ans = ans.slice(0, input.maxlength);
    try {
      await fillAndSubmit(ctx, input, submit, ans);
      mem.answered.set(prompt, ans);
      ctx.record({ type: 'answer', game: 'quiplash', prompt, answer: ans, source: model, ms: Date.now() - t0 });
      ctx.log(`ANSWER [${prompt.slice(0, 80)}] -> "${ans}" (${Date.now() - t0}ms)`);
    } catch (e) { ctx.log(`submit failed: ${e.message.split('\n')[0]}`); }
    return true;
  }
  return false;
}

module.exports = { name: 'quiplash', match, tick, mem };
