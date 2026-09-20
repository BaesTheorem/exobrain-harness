// Manual controller and DOM explorer. Never brings the window to front.
//   node control.js peek                    -> phase probe: text, inputs, buttons, vote elements, canvas
//   node control.js click "Text or #sel"    -> click by selector or visible text
//   node control.js fill "#sel" "value"
//   node control.js type "free text"        -> first visible text input/textarea
//   node control.js press Enter
//   node control.js dump [label]            -> save outerHTML + PNG of this phase to tmp/jackbox/dumps/
//                                              (may contain friends' names: scrub before promoting to tests/fixtures)
const fs = require('fs');
const path = require('path');
const { connect, screenshot } = require('./lib/browser');
const { probe } = require('./lib/probe');

(async () => {
  const [cmd, a1, a2] = process.argv.slice(2);
  const b = await connect();
  const { page } = b;
  if (cmd === 'click') {
    let done = false;
    if (/^[#.\[]/.test(a1)) { try { await page.click(a1, { timeout: 4000 }); done = true; } catch {} }
    if (!done) await page.click(`text=${a1}`, { timeout: 6000 });
    console.log('clicked:', a1);
  } else if (cmd === 'fill') { await page.fill(a1, a2); console.log('filled', a1); }
  else if (cmd === 'type') { await page.fill('textarea:visible, input[type=text]:visible', a1); console.log('typed'); }
  else if (cmd === 'press') { await page.keyboard.press(a1); console.log('pressed', a1); }
  else if (cmd === 'dump') {
    const dir = path.join(__dirname, '..', '..', '..', '..', 'tmp', 'jackbox', 'dumps');
    fs.mkdirSync(dir, { recursive: true });
    const stamp = new Date().toISOString().replace(/[:.]/g, '-').slice(0, 19);
    const base = path.join(dir, `${stamp}-${(a1 || 'phase').replace(/[^\w-]/g, '_')}`);
    fs.writeFileSync(base + '.html', await page.evaluate(() => document.documentElement.outerHTML));
    await screenshot(b.cdp, base + '.png');
    console.log('dumped', base + '.{html,png}');
  }
  if (cmd && cmd !== 'peek' && cmd !== 'dump') await page.waitForTimeout(800);
  const st = await probe(page);
  console.log('URL:', st.url);
  console.log('TEXT:', JSON.stringify(st.text));
  console.log('INPUTS:', JSON.stringify(st.inputs));
  console.log('BUTTONS:', JSON.stringify(st.buttons.map(({ id, cls, txt, disabled }) => ({ id, cls, txt, disabled }))));
  console.log('VOTE:', JSON.stringify(st.voteEls.map(({ id, cls, txt }) => ({ id, cls, txt }))));
  console.log('CANVAS:', JSON.stringify(st.canvas));
  await b.close();
})().catch(e => { console.error('ERR', e.message); process.exit(1); });
