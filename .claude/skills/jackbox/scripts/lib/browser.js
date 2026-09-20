// Connect to the throwaway Chrome that launch.sh started. Every script connects, acts,
// and disconnects; browser.close() on a CDP connection detaches without killing Chrome,
// so the game session survives across separate tool calls.
const { chromium } = require('playwright-core');

const CDP_URL = process.env.JACKBOX_CDP || 'http://localhost:9222';

async function connect() {
  let browser;
  try {
    browser = await chromium.connectOverCDP(CDP_URL, { timeout: 5000 });
  } catch (e) {
    throw new Error(`no Chrome on ${CDP_URL} (run: jackbox launch): ${e.message.split('\n')[0]}`);
  }
  const ctx = browser.contexts()[0];
  const page = ctx.pages().find(p => p.url().includes('jackbox')) || ctx.pages()[0];
  if (!page) throw new Error('Chrome has no pages; run: jackbox launch');
  const cdp = await ctx.newCDPSession(page);
  return { browser, ctx, page, cdp, close: () => browser.close() };
}

// Raw CDP screenshot. page.screenshot() hangs on jackbox.tv waiting for fonts.
async function screenshot(cdp, outfile) {
  const { data } = await cdp.send('Page.captureScreenshot', { format: 'png' });
  if (outfile) require('fs').writeFileSync(outfile, Buffer.from(data, 'base64'));
  return data;
}

// Trusted click at viewport coordinates, pipelined over CDP (no selector parsing, so answer
// text with quotes or emoji can never break the click).
async function clickAt(cdp, x, y) {
  const base = { x, y, button: 'left', clickCount: 1 };
  await Promise.all([
    cdp.send('Input.dispatchMouseEvent', { type: 'mouseMoved', x, y }),
    cdp.send('Input.dispatchMouseEvent', { type: 'mousePressed', ...base }),
    cdp.send('Input.dispatchMouseEvent', { type: 'mouseReleased', ...base }),
  ]);
}

const sleep = ms => new Promise(r => setTimeout(r, ms));

module.exports = { connect, screenshot, clickAt, sleep, CDP_URL };
