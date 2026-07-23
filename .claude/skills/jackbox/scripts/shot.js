// Reliable screenshot via raw CDP. Use this instead of page.screenshot() -- Playwright's
// screenshot waits for fonts to load and HANGS on jackbox.tv. CDP captureScreenshot doesn't.
// Usage: node shot.js [outfile]   (default /tmp/jb.png).  Read the PNG with vision.
const { chromium } = require('playwright');
const fs = require('fs');
(async () => {
  const out = process.argv[2] || '/tmp/jb.png';
  const browser = await chromium.connectOverCDP('http://localhost:9222');
  const ctx = browser.contexts()[0];
  const page = ctx.pages().find(p => p.url().includes('jackbox')) || ctx.pages()[0];
  const session = await ctx.newCDPSession(page);
  const { data } = await session.send('Page.captureScreenshot', { format: 'png' });
  fs.writeFileSync(out, Buffer.from(data, 'base64'));
  console.log('saved', out);
  await browser.close();
})().catch(e => { console.error('ERR', e.message); process.exit(1); });
