// Join a Jackbox room.  Usage: node join.js <ROOMCODE> [name]
// Waits on the form instead of sleeping, reports whether the room accepted us.
const { connect } = require('./lib/browser');

// The cookie banner appears a beat after load on a fresh profile and covers the PLAY button.
async function dismissCookies(page) {
  for (let i = 0; i < 6; i++) {
    const shown = await page.evaluate(() => /we use cookies/i.test(document.body.innerText));
    if (!shown) return true;
    for (const t of ['Reject All', 'Accept All']) {
      try { await page.click(`button:has-text("${t}")`, { timeout: 700 }); break; } catch {}
    }
    await page.waitForTimeout(400);
  }
  return !(await page.evaluate(() => /we use cookies/i.test(document.body.innerText)));
}
(async () => {
  const code = (process.argv[2] || '').toUpperCase();
  const name = (process.argv[3] || 'AlexsClaude').slice(0, 12);   // <=12 chars; signals it's Alex's bot
  if (!/^[A-Z]{4}$/.test(code)) { console.error('usage: node join.js <4-letter ROOMCODE> [name]'); process.exit(1); }
  const b = await connect();
  const { page } = b;
  if (!page.url().includes('jackbox.tv') || !(await page.$('#roomcode'))) await page.goto('https://jackbox.tv/', { waitUntil: 'domcontentloaded' });
  await page.waitForSelector('#roomcode', { timeout: 10000 });
  await dismissCookies(page);
  await page.fill('#roomcode', code);
  await page.fill('#username', name);
  // jackbox.tv validates the code against its API and only then enables PLAY; a bad code shows
  // "Room not found" instead. Wait for whichever comes first.
  let ok = false, why = '';
  try {
    await page.waitForFunction(() => {
      const b = document.querySelector('#button-join');
      return (b && !b.disabled) || /room not found|not found|full|already/i.test(document.body.innerText);
    }, null, { timeout: 10000 });
  } catch { why = 'no response from room lookup'; }
  const enabled = await page.evaluate(() => { const b = document.querySelector('#button-join'); return !!b && !b.disabled; });
  if (enabled) {
    await page.click('#button-join', { timeout: 3000 });
    try { await page.waitForSelector('#button-join', { state: 'hidden', timeout: 10000 }); ok = true; } catch { why = 'PLAY clicked but the join form stayed'; }
  } else if (!why) why = 'room rejected the code';
  const txt = (await page.evaluate(() => document.body.innerText)).replace(/\s+/g, ' ').trim().slice(0, 160);
  console.log(ok ? `joined ${code} as ${name}` : `NOT joined ${code} (${why})`, '->', txt);
  await b.close();
  process.exit(ok ? 0 : 2);
})().catch(e => { console.error('ERR', e.message); process.exit(1); });
