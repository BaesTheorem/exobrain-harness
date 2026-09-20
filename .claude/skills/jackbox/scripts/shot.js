// Screenshot via raw CDP (page.screenshot hangs on jackbox.tv).  Usage: node shot.js [outfile]
const { connect, screenshot } = require('./lib/browser');
(async () => {
  const out = process.argv[2] || '/tmp/jb.png';
  const b = await connect();
  await screenshot(b.cdp, out);
  console.log('saved', out);
  await b.close();
})().catch(e => { console.error('ERR', e.message); process.exit(1); });
