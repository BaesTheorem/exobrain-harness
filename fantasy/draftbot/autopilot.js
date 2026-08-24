/* MIST draft autopilot -- runs INSIDE the ESPN draft room page.
 *
 * Why in-page: a round trip out to MIST costs 20-60s. The pick clock is 30s in
 * mocks and 90s live, and bot teams pick in ~1s. Anything that waits on MIST is
 * structurally too slow, so the agent lives in the page and she supervises
 * between picks instead of during them.
 *
 * Row identification is shape-independent on purpose. The 2026-08-24 mock lost
 * pick 78 (took Jaylen Warren instead of Mike Evans) because the old code walked
 * up a FIXED number of parents from a button and then parsed the row by field
 * position. Both halves broke on ESPN's markup. Here a row is defined as the
 * largest ancestor of an action button that still contains only ONE action
 * button, which holds regardless of how many wrapper divs ESPN adds.
 *
 * Placeholders substituted by arm.py: __RANKS__, __CONFIG__
 */
(() => {
  const RANKS = __RANKS__;
  const CFG = __CONFIG__;

  if (window.__mist) {
    clearInterval(window.__mist.timer);
  }
  const M = (window.__mist = {
    log: [],
    picks: [],
    timer: null,
    busy: false,
    enabled: true,
  });

  const stamp = () => new Date().toLocaleTimeString();
  const L = (msg) => {
    M.log.push(stamp() + '  ' + msg);
    if (M.log.length > 300) M.log.shift();
  };

  const norm = (s) =>
    s
      .normalize('NFKD')
      .replace(/[’']/g, '')
      .toLowerCase()
      .replace(/\b(jr|sr|ii|iii|iv)\b/g, '')
      .replace(/[^a-z]/g, '');

  const cls = (e) =>
    String(
      e.className && e.className.baseVal !== undefined
        ? e.className.baseVal
        : e.className || ''
    );

  const isAction = (b) => /Button--(draft|queue)/i.test(cls(b));
  const isDraft = (b) => /Button--draft/i.test(cls(b));

  /* Largest ancestor still containing exactly one action button == the row. */
  const rowOf = (btn) => {
    let last = btn;
    let node = btn.parentElement;
    while (node) {
      const n = [...node.querySelectorAll('button')].filter(isAction).length;
      if (n !== 1) return last;
      last = node;
      node = node.parentElement;
    }
    return last;
  };

  const POS_RE = /^(QB|RB|WR|TE|K|D\/ST|WRCB)$/;

  const parseRow = (btn) => {
    const row = rowOf(btn);
    if (!row) return null;
    const parts = row.innerText
      .split('\n')
      .map((s) => s.trim())
      .filter(Boolean);
    if (!parts.length) return null;

    const espn = parseInt(parts[0], 10) || 999;
    let pos = (parts.find((p) => POS_RE.test(p)) || '').replace('WRCB', 'WR');

    /* Name = the ranked player whose name appears in this row. Falls back to
     * the longest non-token line so unranked players are still draftable. */
    const flat = norm(row.innerText);
    let name = null;
    let rank = null;
    for (const key in RANKS) {
      if (key.length >= 8 && flat.includes(key)) {
        if (rank === null || RANKS[key] < rank) {
          rank = RANKS[key];
          name = key;
        }
      }
    }
    const label =
      parts.find((p) => /[a-z]/.test(p) && p.length > 3 && !POS_RE.test(p)) ||
      parts[1] ||
      '?';

    return { btn, row, espn, pos, name, rank, label };
  };

  /* Limits render as one run-together string: "QB2/4RB6/8WR4/8TE2/3K1/3D/ST1/3".
   * Parse it with a single global scan. Matching each label with its own regex
   * fails on K: there is no word boundary between the "3" of TE2/3 and the K. */
  const roster = () => {
    const b = document.body.innerText;
    const counts = { QB: 0, RB: 0, WR: 0, TE: 0, K: 0, DST: 0 };
    for (const m of b.matchAll(/(QB|RB|WR|TE|K|D\/ST)(\d+)\/(\d+)/g)) {
      const key = m[1] === 'D/ST' ? 'DST' : m[1];
      counts[key] = parseInt(m[2], 10);
    }
    const g = (re) => {
      const m = b.match(re);
      return m ? parseInt(m[1], 10) : 0;
    };
    counts.total = g(/(\d+)\/\d+ Players/);
    counts.round = g(/RND (\d+) OF/);
    counts.lastRound = g(/RND \d+ OF (\d+)/);
    return counts;
  };

  /* Lower is better. null == not draftable right now. */
  const score = (p, r) => {
    const left = (r.lastRound || CFG.rounds) - r.round;
    const base = p.rank !== null ? p.rank : p.espn + CFG.unrankedPenalty;

    if (p.pos === 'D/ST') {
      if (r.DST >= 1) return null;
      return left <= CFG.dstRoundsLeft ? -1000 : null;
    }
    if (p.pos === 'K') {
      if (r.K >= 1) return null;
      return left <= CFG.kRoundsLeft ? -900 : null;
    }
    /* Required STARTING slots, not just K and D/ST. Ranking on overall board
     * position never forces a TE (they rank poorly by design) and under-rates
     * the 2nd RB once the RB pool thins, so a pure-rank bot can finish unable
     * to field a legal lineup. Reserve a pick for every unfilled starter. */
    const need = {
      RB: Math.max(0, CFG.startRB - r.RB),
      TE: Math.max(0, CFG.startTE - r.TE),
      'D/ST': Math.max(0, 1 - r.DST),
      K: Math.max(0, 1 - r.K),
    };
    const mustFill = need.RB + need.TE + need['D/ST'] + need.K;
    const picksLeft = left + 1;
    if (picksLeft <= mustFill && !need[p.pos]) return null;

    if (p.pos === 'QB' && r.QB >= CFG.maxQB) return null;
    if (p.pos === 'TE' && r.TE >= CFG.maxTE) return null;
    if (p.pos === 'RB' && r.RB >= CFG.maxRB) return null;
    if (p.pos === 'WR' && r.WR >= CFG.maxWR) return null;

    /* Best-player-available for the first few rounds. The roster-shape bonus
     * exists to stop the RB6/WR4 ending we got on 2026-08-24, which is a
     * late-round failure. Applying it at 1.01 would reorder the top of the
     * board, where consensus rank is the most reliable signal we have. */
    let s = base;
    if (r.round > CFG.bpaRounds) {
      if (p.pos === 'WR' && r.WR < CFG.wantWR) s -= CFG.wrBonus;
      if (p.pos === 'RB' && r.RB < CFG.wantRB) s -= CFG.rbBonus;
    }
    return s;
  };

  const clickConfirm = () => {
    document.querySelectorAll('button').forEach((b) => {
      const t = (b.innerText || '').trim().toUpperCase();
      if (/^(CONFIRM|YES|DRAFT PLAYER|OK)$/.test(t) && b.offsetParent !== null) {
        b.click();
      }
    });
  };

  const tick = () => {
    if (M.busy || !M.enabled) return;

    const drafts = [...document.querySelectorAll('button')].filter(isDraft);

    /* ESPN silently ignores queue clicks until the draft is live, so the queue
     * cannot be preloaded. Fill it once the clock starts -- it is the
     * zero-latency floor if the autopilot ever misses a turn. Only ever while
     * we are NOT on the clock: drafting outranks stocking the backup. */
    if (!drafts.length) {
      if (!M.queueDone && !/--:--/.test(document.body.innerText)) {
        M.queueDone = true;
        M.busy = true;
        M.fillQueue(CFG.queueDepth)
          .then((r) => {
            L('auto-queue added ' + r.added);
            if (!r.added) M.queueDone = false; /* not live yet; retry */
            M.busy = false;
          })
          .catch((e) => {
            L('auto-queue ERR ' + e.message);
            M.queueDone = false;
            M.busy = false;
          });
      }
      return; /* not our turn */
    }

    M.busy = true;
    try {
      const r = roster();
      const before = r.total;
      const cands = drafts
        .map(parseRow)
        .filter(Boolean)
        .map((p) => ({ p, s: score(p, r) }))
        .filter((x) => x.s !== null)
        .sort((a, b) => a.s - b.s);

      if (!cands.length) {
        L('NO CANDIDATE (round ' + r.round + ', ' + drafts.length + ' buttons)');
        M.busy = false;
        return;
      }

      const win = cands[0];
      const label = win.p.label + ' [' + win.p.pos + ']';
      win.p.btn.click();
      L('CLICK ' + label + ' rank=' + win.p.rank + ' espn=' + win.p.espn + ' score=' + win.s);

      setTimeout(() => {
        clickConfirm();
        setTimeout(() => {
          const after = roster();
          const grew = after.total > before;
          L(
            (grew ? 'OK   ' : 'FAIL ') +
              label +
              '  roster ' +
              before +
              '->' +
              after.total +
              '  (QB' + after.QB + ' RB' + after.RB + ' WR' + after.WR +
              ' TE' + after.TE + ' K' + after.K + ' DST' + after.DST + ')'
          );
          if (grew) M.picks.push({ at: stamp(), player: win.p.label, pos: win.p.pos });
          M.busy = false;
        }, CFG.verifyDelay);
      }, CFG.confirmDelay);
    } catch (e) {
      L('ERR ' + e.message);
      M.busy = false;
    }
  };

  /* Fill the queue as the zero-latency floor: if the clock ever beats the
   * autopilot, ESPN drafts from here instead of from its own rankings. */
  /* Returns what ACTUALLY landed in the queue, not what we tried to click.
   * ESPN silently ignores queue clicks before the draft starts, and the old
   * version reported its own intent as success. */
  const queueRows = () =>
    (document.querySelectorAll('table')[0] || { innerText: '' }).innerText
      .split('\n')
      .map((s) => s.trim())
      .filter((s) => /^[A-Z]\.\s|^[A-Z][a-z]+ /.test(s));

  M.fillQueue = async (depth) => {
    const r = roster();
    const cands = [...document.querySelectorAll('button')]
      .filter((b) => /Button--queue/i.test(cls(b)))
      .map(parseRow)
      .filter(Boolean)
      .map((p) => ({ p, s: score(p, r) }))
      .filter((x) => x.s !== null)
      .sort((a, b) => a.s - b.s)
      .slice(0, depth);

    const before = queueRows().length;
    for (const c of cands) {
      c.p.btn.click();
      await new Promise((res) => setTimeout(res, 240));
    }
    await new Promise((res) => setTimeout(res, 800));
    const after = queueRows();
    const added = after.length - before;
    L('QUEUE fill: tried ' + cands.length + ', added ' + added);
    return {
      tried: cands.map((c) => c.p.label),
      added: added,
      queueNow: after.slice(0, 40),
      ok: added > 0,
    };
  };

  M.clearQueue = () => {
    const rm = [...document.querySelectorAll('button')].filter((b) =>
      /btn-undo/i.test(cls(b))
    );
    rm.forEach((b, i) => setTimeout(() => b.click(), i * 180));
    L('QUEUE clear -> ' + rm.length + ' removed');
    return rm.length;
  };

  M.status = () => {
    const r = roster();
    return {
      round: r.round + '/' + r.lastRound,
      counts: 'QB' + r.QB + ' RB' + r.RB + ' WR' + r.WR + ' TE' + r.TE + ' K' + r.K + ' DST' + r.DST,
      total: r.total,
      enabled: M.enabled,
      picks: M.picks,
      log: M.log.slice(-12),
    };
  };

  M.timer = setInterval(tick, CFG.pollMs);
  L('ARMED  poll=' + CFG.pollMs + 'ms  ranked=' + Object.keys(RANKS).length);
  return 'ARMED';
})();
