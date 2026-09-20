// Summarize a game log.  Usage: node report.js [file.jsonl]   (default: newest log)
const fs = require('fs'); const path = require('path');
const { DIR } = require('./lib/results');
let file = process.argv[2];
if (!file) {
  const files = fs.existsSync(DIR) ? fs.readdirSync(DIR).filter(f => f.endsWith('.jsonl')).sort() : [];
  if (!files.length) { console.log('no game logs in', DIR); process.exit(0); }
  file = path.join(DIR, files[files.length - 1]);
}
const rows = fs.readFileSync(file, 'utf8').split('\n').filter(Boolean).map(l => JSON.parse(l));
const by = t => rows.filter(r => r.type === t);
const ms = list => list.length ? Math.round(list.reduce((a, r) => a + (r.ms || 0), 0) / list.length) : 0;
console.log(`log: ${file}\nentries: ${rows.length}  games: ${[...new Set(by('game').map(r => r.game))].join(', ') || '-'}`);
const answers = by('answer'), votes = by('vote'), draws = by('drawing'), slogans = by('slogan');
console.log(`answers: ${answers.length} (avg ${ms(answers)}ms, ${answers.filter(a => a.source === 'fallback').length} fallback)`);
for (const a of answers) console.log(`  [${(a.prompt || '').slice(0, 70)}]\n    -> "${a.answer}"  (${a.ms}ms)`);
console.log(`votes: ${votes.length} (avg ${ms(votes)}ms)`);
for (const v of votes) console.log(`  ${v.mode === 'vision' ? 'vision ' + v.pick : '"' + (v.clicked || []).join('" > "') + '"'}  of ${(v.options || []).length || 2}`);
console.log(`drawings: ${draws.length} (avg design ${draws.length ? Math.round(draws.reduce((a, r) => a + r.designMs, 0) / draws.length) : 0}ms, total ${ms(draws)}ms)   slogans: ${slogans.length}`);
console.log(`screens seen: ${by('screen').length}`);
