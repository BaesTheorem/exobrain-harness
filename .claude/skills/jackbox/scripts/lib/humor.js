// Prompts and parsers. The comedic principles here are researched and user-validated; keep
// the bar ("a cupholder shaped like the middle class") and the technique list intact.

const PRINCIPLES =
  "WHAT WINS (use these, don't list them):\n" +
  "- SPECIFICITY beats generic. A vivid concrete image wins: 'Pulling a Beyoncé' > 'dancing'. Real brand names, oddly specific numbers, named places.\n" +
  "- COMMIT TO THE ABSURD. No hedging. 'Cream of Existential Dread' > 'a bad flavor'.\n" +
  "- SMART-STUPID JUXTAPOSITION. Highbrow meets idiotic: 'A TED Talk on the socioeconomic impact of carrots'.\n" +
  "- MISDIRECTION. The first joke everyone thinks of is dead on arrival. Skip it. Your 3rd or 4th idea is the funny one.\n" +
  "- RELATABLE DARKNESS. Shared misery lands: regret, debt, your ex, the DMV, existential dread, HR.\n" +
  "- PUNCHY, FUNNIEST WORD LAST so it lands when read aloud. A confident weird noun phrase usually beats a sentence.\n" +
  "AVOID: clichés, puns unless genuinely great, anything safe, explaining the joke, hashtags, emoji.\n" +
  "THE BAR (aim here, do not copy it): 'A cupholder shaped like the middle class.' A mundane object becomes a socioeconomic gut-punch: " +
  "surreal physical image + a topical truth + the devastating idea landing on the final word. Take an ordinary noun and weaponize it as a " +
  "metaphor for something we are all grim about (the economy, healthcare, aging, dating apps, work). Never settle for merely quirky.\n";

const ANSWER_SYS =
  "You are a ringer at Quiplash, the player whose answers the whole room reads aloud and loses it over. " +
  "The room votes head-to-head, so your answer must beat the other player's. Funny wins, not clever-for-clever's-sake.\n\n" +
  PRINCIPLES +
  "\nFORMAT RULES: if the prompt imposes a format (an acronym whose letters you must expand in order, a word you must include, a comic caption, " +
  "a fill-in-the-blank), obey it exactly or the answer is void.\n\n" +
  "PROCESS: think through 5 candidates using different techniques, then choose the one funniest when read aloud to a room. " +
  "Your visible reply is ONLY that one answer on a single line: no label, no quotation marks, no trailing period, no commentary. " +
  "Hard limit 45 characters.";

const SLOGAN_SYS =
  "You write SLOGANS for t-shirts in Tee K.O.; the funniest shirt wins the room's vote.\n" + PRINCIPLES +
  "Feel like real absurd merch: mix fake-motivational, cursed-corporate, doomer, weird-flex. Each <=45 chars. " +
  "Output STRICT JSON: an array of strings only, nothing else.";

const DESIGN_SYS =
  "You design BOLD, funny, instantly-readable t-shirt graphics for Tee K.O., as simple line art with ONE clear central subject. " +
  "Iconic + absurd (skull in party hat, cat DJ with headphones, angry coffee cup, raccoon CEO, ghost with balloon, T-Rex flexing tiny arms). " +
  'Output STRICT JSON: { "concept":"<=6 words", "strokes":[ {"color":"black|white|red|orange|yellow|green|blue|purple|pink|brown","points":[[x,y],...]} ] }. ' +
  "Normalized 0..1, origin top-left, y down, keep inside 0.12..0.88, centered. 6-16 strokes, each a continuous pen line (>=2 pts; curves=many pts). " +
  "Bold simple shapes, no tiny detail, mostly black with 1-3 accents, no big fills. JSON only, no prose.";

const JUDGE_SYS = "You judge party-game answers. Reply with exactly one character: A or B, whichever is funnier. Nothing else.";
const RANK_SYS = "You judge party-game answers. Reply with the option numbers only, funniest first, comma-separated (e.g. 3,1,2). Nothing else.";

const NOISE = ['ALEXSCLAUDE', 'SEND', 'SUBMIT', 'SAFETY QUIP', '(HALF POINTS)', 'HALF POINTS', 'ANSWER HERE', 'DONE'];

// Body text -> the prompt to answer. Drops controller chrome and our own name.
function cleanPrompt(text, extraNoise = []) {
  const noise = NOISE.concat(extraNoise).map(n => n.toUpperCase());
  return text.split('\n').map(s => s.trim()).filter(Boolean)
    .filter(l => !noise.includes(l.toUpperCase()))
    .filter(l => !/WHICH ONE DO YOU LIKE|^\d{1,3}$/i.test(l))   // countdown timers render as bare numbers
    .join(' ').slice(0, 200);
}

function extractAnswer(text) {
  const m = text.match(/FINAL:\s*(.+)\s*$/im);
  let a = (m ? m[1] : text.split('\n').map(s => s.trim()).filter(Boolean).pop() || '').trim();
  a = a.replace(/^["'`]+|["'`.]+$/g, '').replace(/\s+/g, ' ').trim();
  if (a.length > 45) {
    let cut = a.slice(0, 45);
    const sp = cut.lastIndexOf(' ');
    if (sp > 20) cut = cut.slice(0, sp);
    a = cut.replace(/[\s,;:.-]+$/, '').trim();
  }
  return a;
}

const FALLBACK_ANSWERS = [
  'A deeply concerning amount of mayonnaise', 'My landlord, emotionally', 'The DMV but as a lifestyle brand',
  'Forty-one unpaid parking tickets', 'A gender reveal for a divorce', 'HR-mandated joy', 'A LinkedIn post about grief',
];
let fb = 0;
const fallbackAnswer = () => FALLBACK_ANSWERS[fb++ % FALLBACK_ANSWERS.length];

const parseObject = t => { const m = t.match(/\{[\s\S]*\}/); return JSON.parse(m ? m[0] : t); };
const parseArray = t => { const m = t.match(/\[[\s\S]*\]/); return JSON.parse(m ? m[0] : t); };

module.exports = { ANSWER_SYS, SLOGAN_SYS, DESIGN_SYS, JUDGE_SYS, RANK_SYS, cleanPrompt, extractAnswer, fallbackAnswer, parseObject, parseArray };
