// Per-game JSONL log: every answer, vote, drawing, and screen change, with timings. This is the
// instrument for tuning the humor prompts later (build-eval / hillclimb need outcomes, and the
// 'screen' entries capture whatever the controller shows about results).
const fs = require('fs');
const path = require('path');

const DIR = process.env.JACKBOX_LOG_DIR || path.join(__dirname, '..', '..', '..', '..', '..', 'tmp', 'jackbox', 'games');

function open(tag = 'game') {
  fs.mkdirSync(DIR, { recursive: true });
  const stamp = new Date().toISOString().replace(/[:.]/g, '-').slice(0, 19);
  const file = path.join(DIR, `${stamp}-${tag}.jsonl`);
  const record = entry => fs.appendFileSync(file, JSON.stringify({ t: new Date().toISOString(), ...entry }) + '\n');
  return { file, record };
}

module.exports = { open, DIR };
