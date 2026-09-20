// One page.evaluate per tick returns everything the game modules need to decide a phase.
function probeInPage() {
  const vis = el => {
    const r = el.getBoundingClientRect(); const s = getComputedStyle(el);
    return r.width > 0 && r.height > 0 && s.visibility !== 'hidden' && s.display !== 'none' && s.opacity !== '0';
  };
  const box = el => { const r = el.getBoundingClientRect(); return { cx: r.x + r.width / 2, cy: r.y + r.height / 2, area: r.width * r.height }; };
  const cls = el => (typeof el.className === 'string' ? el.className : '');

  const buttons = [...document.querySelectorAll('button,[role=button]')].filter(vis).map(b => ({
    id: b.id || '', cls: cls(b).slice(0, 80), txt: (b.innerText || '').replace(/\s+/g, ' ').trim().slice(0, 120),
    disabled: !!b.disabled, ...box(b),
  }));
  const inputs = [...document.querySelectorAll('input[type=text],input:not([type]),textarea')].filter(vis).map(i => ({
    id: i.id || '', placeholder: i.placeholder || '', maxlength: i.maxLength > 0 ? i.maxLength : null, value: i.value || '',
  }));
  // vote-ish things: buttons/images/divs whose id or class mentions vote (Tee K.O. uses divs with images)
  const voteEls = [...document.querySelectorAll('button,[role=button],img,div')].filter(el => vis(el) && /vote/i.test(el.id + ' ' + cls(el)))
    .map(el => ({ id: el.id || '', cls: cls(el).slice(0, 80), txt: (el.innerText || '').replace(/\s+/g, ' ').trim().slice(0, 120),
      disabled: !!el.disabled, ...box(el) }))
    .filter(v => v.area > 3000);

  let canvas = null;
  const canvasEl = [...document.querySelectorAll('canvas')].find(c => { const r = c.getBoundingClientRect(); return r.width > 150 && r.height > 150; });
  if (canvasEl) {
    const r = canvasEl.getBoundingClientRect();
    canvas = { x: r.x, y: r.y, w: r.width, h: r.height, blank: null };
    try {
      const cx = canvasEl.getContext('2d');
      if (cx) {
        const id = cx.getImageData(0, 0, Math.min(canvasEl.width, 400), Math.min(canvasEl.height, 400)).data;
        let dark = 0, n = 0;
        for (let i = 0; i < id.length; i += 4 * 80) { n++; if (id[i + 3] > 0 && (id[i] < 240 || id[i + 1] < 240 || id[i + 2] < 240)) dark++; }
        canvas.blank = (dark / n) < 0.01;
      }
    } catch (e) { canvas.blank = null; }
  }
  return {
    url: location.href,
    text: (document.body.innerText || '').replace(/\n{2,}/g, '\n').trim().slice(0, 1200),
    buttons, inputs, voteEls, canvas,
  };
}

async function probe(page) { return page.evaluate(probeInPage); }

module.exports = { probe, probeInPage };
