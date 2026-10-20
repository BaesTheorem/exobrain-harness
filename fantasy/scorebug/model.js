// The live half of the lineup model, ported from espncli/value.py
// (row_moments, lineup_moments, win_prob). The snapshot carries every input
// that needs the full model; this file only adds the clock and live points.
// test_model.py checks it against the Python win_prob on the same inputs.

export function phi(z) {
  // Abramowitz and Stegun 7.1.26 for erf, |error| < 1.5e-7.
  const x = Math.abs(z) / Math.SQRT2, t = 1 / (1 + 0.3275911 * x);
  const y = 1 - (((((1.061405429 * t - 1.453152027) * t) + 1.421413741) * t - 0.284496736) * t + 0.254829592) * t * Math.exp(-x * x);
  return 0.5 * (1 + (z >= 0 ? y : -y));
}

const GAME_SECONDS = 3600, OT_SHARE = 0.05;

// Share of one NFL game still to play (espncli.value.clock_remaining).
export function clockRemaining(state, period, clock) {
  if (state !== "in" || !period) return 0;
  if (period > 4) return OT_SHARE;
  const [m, s] = String(clock || "0:00").split(":");
  const left = (parseInt(m, 10) || 0) * 60 + (parseInt(s, 10) || 0);
  return Math.max(0, Math.min(1, ((4 - period) * 900 + left) / GAME_SECONDS));
}

// (mean, sd) for one starter. `actual` is null until his game starts.
export function rowMoments(r, actual, left) {
  if (actual == null) return [r.pre[0], r.pre[1]];
  if (!(left > 0)) return [actual, 0];
  return [actual + left * r.mean, r.sd * Math.sqrt(left)];
}

// P(me beats opp) for one snapshot view. `pts(row)` gives a starter's live
// points or null; `frac(team)` the share of his game left.
export function winProb(view, pts, frac) {
  const rows = [...view.me.rows, ...view.opp.rows], nMe = view.me.rows.length;
  const mom = rows.map(r => rowMoments(r, pts(r), frac(r.team)));
  let muMe = 0, muOpp = 0, vMe = 0, vOpp = 0, cross = 0;
  mom.forEach(([m, s], i) => { if (i < nMe) { muMe += m; vMe += s * s; } else { muOpp += m; vOpp += s * s; } });
  for (const [i, j, rho] of view.pairs) {
    const c = rho * mom[i][1] * mom[j][1];
    if (!c) continue;
    if (i < nMe && j < nMe) vMe += 2 * c;
    else if (i >= nMe && j >= nMe) vOpp += 2 * c;
    else cross += c;
  }
  const sdMe = Math.sqrt(Math.max(vMe, 0)), sdOpp = Math.sqrt(Math.max(vOpp, 0));
  const sd = Math.sqrt(Math.max(sdMe * sdMe + sdOpp * sdOpp - 2 * cross, 0));
  const p = sd === 0 ? (muMe === muOpp ? 0.5 : muMe > muOpp ? 1 : 0) : phi((muMe - muOpp) / sd);
  return { p, mu_me: muMe, sd_me: sdMe, mu_opp: muOpp, sd_opp: sdOpp, margin: muMe - muOpp, sd_diff: sd,
           rem: mom.map(([m], i) => Math.max(0, m - (pts(rows[i]) ?? 0))) };
}
