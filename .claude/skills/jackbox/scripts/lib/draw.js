// Replay stroke paths as trusted mouse input with hand-drawn wobble. All events for a stroke are
// pipelined over the CDP websocket (sent without awaiting each one; CDP preserves order), so a
// stroke costs one round trip instead of one per interpolated point.
const nz = px => (Math.random() - 0.5) * px;

const COLOR_RGB = { black: [0, 0, 0], white: [255, 255, 255], red: [230, 30, 30], orange: [240, 140, 20],
  yellow: [245, 220, 30], green: [40, 180, 70], blue: [40, 90, 220], purple: [140, 50, 200], pink: [240, 110, 190], brown: [140, 80, 40] };

function interpolate(rect, points) {
  const map = p => [rect.x + p[0] * rect.w + nz(1.5), rect.y + p[1] * rect.h + nz(1.5)];
  const out = [];
  let [x, y] = map(points[0]);
  out.push([x, y]);
  for (let i = 1; i < points.length; i++) {
    const [tx, ty] = map(points[i]);
    const segs = Math.max(2, Math.round(Math.hypot(tx - x, ty - y) / 8));
    for (let s = 1; s <= segs; s++) out.push([x + (tx - x) * s / segs + nz(1.2), y + (ty - y) * s / segs + nz(1.2)]);
    x = tx; y = ty;
  }
  return out;
}

async function drawStroke(cdp, rect, points) {
  const pts = interpolate(rect, points);
  const [x0, y0] = pts[0];
  const ev = (type, x, y, extra = {}) => cdp.send('Input.dispatchMouseEvent', { type, x, y, ...extra });
  const batch = [
    ev('mouseMoved', x0, y0),
    ev('mousePressed', x0, y0, { button: 'left', buttons: 1, clickCount: 1 }),
  ];
  for (let i = 1; i < pts.length; i++) batch.push(ev('mouseMoved', pts[i][0], pts[i][1], { button: 'left', buttons: 1 }));
  const [xe, ye] = pts[pts.length - 1];
  batch.push(ev('mouseReleased', xe, ye, { button: 'left', buttons: 1, clickCount: 1 }));
  await Promise.all(batch);
}

// Click the palette swatch whose background is nearest the wanted color (Tee K.O. has no ids).
async function pickColor(page, name) {
  const want = COLOR_RGB[name] || COLOR_RGB.black;
  const handle = await page.evaluateHandle((want) => {
    const dist = (a, b) => Math.hypot(a[0] - b[0], a[1] - b[1], a[2] - b[2]);
    const parse = s => { const m = s && s.match(/rgba?\(([^)]+)\)/); if (!m) return null; const p = m[1].split(',').map(Number); return [p[0], p[1], p[2]]; };
    let best = null, bd = 1e9;
    for (const el of document.querySelectorAll('button,div,li,span')) {
      const r = el.getBoundingClientRect();
      if (r.width < 14 || r.width > 70 || r.height < 14 || r.height > 70) continue;
      const bg = parse(getComputedStyle(el).backgroundColor); if (!bg) continue;
      const d = dist(bg, want); if (d < bd) { bd = d; best = el; }
    }
    return bd < 60 ? best : null;
  }, want);
  const el = handle.asElement();
  if (el) { try { await el.click({ timeout: 700 }); } catch {} }
}

async function drawPlan(cdp, page, rect, plan) {
  let last = null;
  for (const st of plan.strokes) {
    if (st.color && st.color !== last && page) { await pickColor(page, st.color); last = st.color; }
    const pts = (st.points || []).filter(p => Array.isArray(p) && p.length === 2 && p.every(Number.isFinite));
    if (pts.length >= 2) await drawStroke(cdp, rect, pts);
  }
}

module.exports = { drawStroke, drawPlan, pickColor, interpolate, COLOR_RGB };
