// Generic Jackbox controller over CDP. Drives jackbox.tv WITHOUT stealing window focus.
// Use for one-off / manual interaction and for discovering a new game's DOM (peek).
// Usage:
//   node control.js peek                      -> dump page text + visible interactive elements
//   node control.js click "Text or #selector"
//   node control.js fill "#selector" "value"
//   node control.js type "free text"          -> first visible text input/textarea
//   node control.js press Enter
const { chromium } = require('playwright');

(async () => {
  const [cmd, a1, a2] = process.argv.slice(2);
  const browser = await chromium.connectOverCDP('http://localhost:9222');
  const ctx = browser.contexts()[0];
  const page = ctx.pages().find(p => p.url().includes('jackbox')) || ctx.pages()[0];
  // Intentionally do NOT bringToFront — play quietly without stealing the user's focus.

  if (cmd === 'click') {
    let done = false;
    if (/^[#.\[]/.test(a1)) { try { await page.click(a1, { timeout: 4000 }); done = true; } catch {} }
    if (!done) await page.click(`text=${a1}`, { timeout: 6000 });
    console.log('clicked:', a1);
  } else if (cmd === 'fill') {
    await page.fill(a1, a2); console.log('filled', a1);
  } else if (cmd === 'type') {
    await page.fill('textarea:visible, input[type=text]:visible', a1); console.log('typed');
  } else if (cmd === 'press') {
    await page.keyboard.press(a1); console.log('pressed', a1);
  }

  await page.waitForTimeout(a1 && cmd !== 'peek' ? 1200 : 300);
  const info = await page.evaluate(() => {
    const vis = el => {
      const r = el.getBoundingClientRect(); const s = getComputedStyle(el);
      return r.width > 0 && r.height > 0 && s.visibility !== 'hidden' && s.display !== 'none' && s.opacity !== '0';
    };
    const interactive = [...document.querySelectorAll('button, input, textarea, [role=button], a, canvas')]
      .filter(vis).map(e => ({
        tag: e.tagName.toLowerCase(), type: e.type || '', id: e.id || '',
        cls: (typeof e.className === 'string' ? e.className : '').slice(0, 40),
        txt: (e.innerText || e.value || e.placeholder || '').replace(/\s+/g, ' ').trim().slice(0, 50),
        disabled: !!e.disabled,
      }));
    return { text: document.body.innerText.replace(/\n{2,}/g, '\n').trim().slice(0, 1200), interactive };
  });
  console.log('URL:', page.url());
  console.log('TEXT:', JSON.stringify(info.text));
  console.log('INTERACTIVE:', JSON.stringify(info.interactive, null, 1));
  // best-effort screenshot (use shot.js for a guaranteed one)
  try { await page.screenshot({ path: '/tmp/jb.png', timeout: 4000 }); } catch {}
  await browser.close();
})().catch(e => { console.error('ERR', e.message); process.exit(1); });
