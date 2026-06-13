// Join a Jackbox room.  Usage: node join.js <ROOMCODE> [name]
// Navigates the existing CDP Chrome to jackbox.tv, dismisses the cookie banner,
// enters the room code + player name, and clicks PLAY.
const { chromium } = require('playwright');
(async () => {
  const code = (process.argv[2] || '').toUpperCase();
  const name = process.argv[3] || 'AlexsClaude';   // <=12 chars; signals it's Alex's bot
  if (!code) { console.error('usage: node join.js <ROOMCODE> [name]'); process.exit(1); }
  const browser = await chromium.connectOverCDP('http://localhost:9222');
  const ctx = browser.contexts()[0];
  const page = ctx.pages().find(p => p.url().includes('jackbox')) || ctx.pages()[0];
  await page.goto('https://jackbox.tv/', { waitUntil: 'domcontentloaded' });
  await page.waitForTimeout(1500);
  try { await page.click('text=Reject All', { timeout: 2500 }); } catch {}
  await page.waitForTimeout(400);
  await page.fill('#roomcode', code);
  await page.fill('#username', name.slice(0, 12));
  await page.click('#button-join');
  await page.waitForTimeout(2500);
  const txt = (await page.evaluate(() => document.body.innerText)).replace(/\s+/g, ' ').trim().slice(0, 160);
  console.log('joined', code, 'as', name, '->', txt);
  await browser.close();
})().catch(e => { console.error('ERR', e.message); process.exit(1); });
