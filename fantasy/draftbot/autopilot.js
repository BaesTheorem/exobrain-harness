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
 * Scoring is value over replacement, not overall board rank. Rank compares a
 * player to the whole field; a pick is actually decided by how much better he is
 * than the man you could have at his own position anyway. Ranking on the field
 * is why the 2026-08-24 mock took a QB in round 4 and never took a tight end.
 * VALUES carries a precomputed vor per player (see ../vor.py).
 *
 * arm.py substitutes two placeholder tokens below (the value table and the
 * config). They are deliberately not named in this comment: the substitution is
 * a plain string replace, so a token spelled out here gets the whole value blob
 * injected into it too, doubling the payload.
 */
(() => {
  const VALUES = __VALUES__;
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

  const isQueue = (b) => /Button--queue/i.test(cls(b));

  const POS_RE = /^(QB|RB|WR|TE|K|D\/ST|WRCB)$/;

  /* Every player row that is in the DOM, whether or not it is on screen.
   *
   * This is THE thing that has to be right. ESPN's fixed-data-table keeps all
   * ~200 available players in the DOM but only gives a layout box to the dozen
   * currently scrolled into view, and `innerText` returns '' for any element
   * without one. Reading innerText therefore made the bot score a pool of 1 to
   * 19 players and treat it as the whole board: on 2026-08-24 it took the only
   * candidate it could see at 1.01, then spent round 6 on a 19-VOR receiver.
   * `textContent` does not care about layout, so it sees all of them.
   *
   * Names come straight off the row's own player anchor, so there is no
   * substring scanning across a blob of page text and no way to resolve a row
   * to some other player standing next to it -- which is how pick 78 of the
   * first mock drafted Jaylen Warren while logging "Mike Evans". */
  const ROW_SEL = '.fixedDataTableRowLayout_rowWrapper';
  const txt = (el) => ((el && el.textContent) || '').trim();

  const cellMatching = (row, re) => {
    for (const el of row.querySelectorAll('span,div,td')) {
      const t = txt(el);
      if (re.test(t)) return t;
    }
    return '';
  };

  const candidates = (want) => {
    const out = [];
    for (const row of document.querySelectorAll(ROW_SEL)) {
      const label = txt(row.querySelector('.player-news'));
      if (!label) continue;
      const btn = [...row.querySelectorAll('button')].filter(isAction).find(want);
      if (!btn) continue;
      const v = VALUES[norm(label)] || null;
      out.push({
        btn,
        row,
        label,
        v,
        pos: v ? v.pos : cellMatching(row, POS_RE).replace('WRCB', 'WR'),
        bye: v ? v.bye : 0,
        espn: parseInt(cellMatching(row, /^\d{1,3}$/), 10) || 999,
      });
    }
    return out;
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
    counts.pick = g(/ON THE CLOCK: PICK (\d+)/);
    counts.lastRound = g(/RND \d+ OF (\d+)/);
    return counts;
  };

  /* Bye weeks already on the roster, read from the roster panel's BYE column.
   * Byes are a within-tier tiebreak, never a reason to reach past a tier. */
  const myByes = () => {
    const b = document.body.innerText;
    const end = b.indexOf('Roster Limits');
    const counts = {};
    if (end < 0) return counts;
    const start = b.lastIndexOf('POS', end);
    if (start < 0) return counts;
    const lines = b
      .slice(start, end)
      .split('\n')
      .map((x) => x.trim())
      .filter(Boolean);
    for (let i = 0; i < lines.length - 2; i++) {
      if (!/^(QB|RB|WR|TE|FLEX|D\/ST|K|BE|IR)$/.test(lines[i])) continue;
      const nm = lines[i + 1];
      const by = lines[i + 2];
      if (nm && nm !== 'Empty' && /^\d+$/.test(by)) {
        const w = parseInt(by, 10);
        counts[w] = (counts[w] || 0) + 1;
      }
    }
    return counts;
  };

  const CAP = { QB: 'maxQB', RB: 'maxRB', WR: 'maxWR', TE: 'maxTE' };

  /* The roster panel's team dropdown is the one select carrying exactly the
   * league's teams, and its selected option is Alex's. That gives both the team
   * count and which seat is his without hardcoding either. */
  const leagueInfo = () => {
    const sel = [...document.querySelectorAll('select')].find(
      (x) =>
        x.options.length >= 4 &&
        ![...x.options].some((o) =>
          /All Pos\.|All NFL Teams|All Rounds|Projected|Season|seconds|minutes/.test(
            o.text
          )
        )
    );
    if (!sel) return null;
    const mine = [...sel.options].find((o) => o.value === sel.value);
    return { teams: sel.options.length, myTeam: mine ? mine.text : null };
  };

  /* The horizon: the next pick at which the board will actually have changed.
   *
   * Snake order, derived from where this pick falls rather than from a
   * configured slot, because the league randomizes the slot an hour before the
   * draft.
   *
   * Consecutive picks of Alex's own are skipped. At the turn he owns both sides
   * of it, so nobody drafts in between and passing on a player costs nothing --
   * every candidate correctly scores about zero, which makes the first pick of
   * the pair a coin flip. What he is really choosing there is the PAIR, so both
   * halves are scored against the next turn where other teams get to pick. */
  const nextPickNumber = (r, teams) => {
    if (!r.pick || !r.round || !teams) return Infinity;
    const inRound = r.pick - (r.round - 1) * teams;
    const slot = r.round % 2 === 1 ? inRound : teams - inRound + 1;
    if (slot < 1 || slot > teams) return Infinity;
    const last = r.lastRound || CFG.rounds;

    const mine = [];
    for (let rd = r.round + 1; rd <= last; rd++) {
      const n = (rd - 1) * teams + (rd % 2 === 1 ? slot : teams - slot + 1);
      if (n > r.pick) mine.push(n);
    }
    let prev = r.pick;
    for (const n of mine) {
      if (n > prev + 1) return n; /* other teams pick before this one */
      prev = n;
    }
    return Infinity; /* every remaining pick is his own, or none are left */
  };

  /* Value over NEXT AVAILABLE rather than over replacement.
   *
   * Replacement level says what a player is worth. It does not say what the
   * PICK is worth, because a pick's real cost is the player it gives up. If the
   * second-best quarterback will still be sitting there in four rounds, taking
   * the best one now buys only the gap between them, not his whole value over a
   * replacement QB. Scoring on value over replacement is why the 1.01 mock spent
   * pick 27 on Josh Allen.
   *
   * The floor never drops below replacement, because a replacement-level player
   * is available for nothing by definition. */
  const nextAvailable = (board, nextPick) => {
    const bags = {};
    for (const c of board) {
      if (!c.v || !c.pos) continue;
      if (!(c.v.adp > nextPick + CFG.adpCushion)) continue; /* likely gone */
      (bags[c.pos] = bags[c.pos] || []).push({ name: c.label, vor: c.v.vor });
    }
    for (const k in bags) bags[k].sort((a, b) => b.vor - a.vor);
    return bags;
  };

  /* What passing on this player actually gets you at the next turn.
   *
   * He must be excluded from his own floor. When a player IS the best survivor
   * at his position -- which is exactly what happens at a position the room is
   * ignoring -- comparing him to himself scores him at zero and buries the best
   * available man on the board. Passing on him gets you the NEXT one down. */
  const floorFor = (p, floors) => {
    const bag = floors && floors[p.pos];
    if (!bag || !bag.length) return 0;
    const alt = bag.find((x) => x.name !== p.label);
    return Math.max(0, alt ? alt.vor : 0);
  };

  /* Lower is better. null == not draftable right now. */
  const score = (p, r, byes, floors) => {
    const left = (r.lastRound || CFG.rounds) - r.round;
    const vor = p.v ? p.v.vor : -30 - p.espn * 0.05;

    /* K and D/ST go in the last two rounds and are then streamed: both have the
     * worst weekly projection accuracy of any position, so paying earlier buys
     * noise. Offsetting by value still picks the BEST one -- a flat constant
     * left every defense tied, which quietly handed the choice to whatever order
     * ESPN happened to render. */
    if (p.pos === 'D/ST') {
      if (r.DST >= 1) return null;
      return left <= CFG.dstRoundsLeft ? -1000 - vor : null;
    }
    if (p.pos === 'K') {
      if (r.K >= 1) return null;
      return left <= CFG.kRoundsLeft ? -900 - vor : null;
    }

    /* Reserve a pick for every unfilled STARTING slot. Value over replacement
     * fixes the old "never drafts a TE" failure on its own, but this still has
     * to hold or a run on the last kickers can leave the lineup illegal. */
    const need = {
      RB: Math.max(0, CFG.startRB - r.RB),
      TE: Math.max(0, CFG.startTE - r.TE),
      'D/ST': Math.max(0, 1 - r.DST),
      K: Math.max(0, 1 - r.K),
    };
    const mustFill = need.RB + need.TE + need['D/ST'] + need.K;
    if (left + 1 <= mustFill && !need[p.pos]) return null;

    if (CAP[p.pos] && r[p.pos] >= CFG[CAP[p.pos]]) return null;

    /* Unvalued players sit below replacement, ordered by ESPN's own rank, so
     * they are only ever taken when nothing valued is legal. */
    const floor = floorFor(p, floors);
    let s = -(vor - floor);

    /* Bye spreading, while the starting nine are still being filled. Week 8 is
     * free: the league has 13 teams, so one sits idle each week and Alex's idle
     * week is 8. A player on a Week 8 bye costs him no game he could lose. */
    if (r.total < CFG.starters && p.bye) {
      if (p.bye === CFG.freeBye) s -= CFG.freeByeBonus;
      else s += CFG.byeStackPenalty * (byes[p.bye] || 0);
    }
    return s;
  };

  const wait = (ms) => new Promise((res) => setTimeout(res, ms));

  /* ESPN's list is windowed: about 32 rows exist in the DOM at a time out of
   * ~190 available, and the window follows the scroll position. Scoring only
   * the window means the best player on the board is invisible unless somebody
   * happens to have scrolled there, and it means a kicker -- ranked past 200 --
   * can never be seen at all, so the last round finds NO CANDIDATE.
   *
   * The fix is ESPN's own position filter. Filtering to one position and
   * scrolling to the top puts that position's best available players inside the
   * window by construction, so scanning position by position gives a board that
   * is complete where it matters, at every position, for one dropdown change
   * each. */
  const listMain = () =>
    document.querySelector('.fixedDataTableLayout_main') ||
    document.querySelector('.fixedDataTableLayout_rowsContainer');

  const posSelect = () =>
    [...document.querySelectorAll('select')].find((sel) =>
      [...sel.options].some((o) => o.text === 'All Pos.')
    );

  const setPosFilter = (label) => {
    const sel = posSelect();
    if (!sel) return false;
    const opt = [...sel.options].find((o) => o.text === label);
    if (!opt) return false;
    const setter = Object.getOwnPropertyDescriptor(
      window.HTMLSelectElement.prototype,
      'value'
    ).set;
    setter.call(sel, opt.value);
    sel.dispatchEvent(new Event('change', { bubbles: true }));
    return true;
  };

  const scrollListTop = async () => {
    const main = listMain();
    if (!main) return;
    let last = null;
    for (let i = 0; i < CFG.scrollSteps; i++) {
      main.dispatchEvent(
        new WheelEvent('wheel', { deltaY: -4000, bubbles: true, cancelable: true })
      );
      await wait(CFG.scrollDelay);
      const first = (candidates(() => true)[0] || {}).label || '';
      if (first && first === last) return; /* window stopped moving: at the top */
      last = first;
    }
  };

  /* One filtered, scrolled-to-top sweep per position we are still allowed to
   * draft. Returns the union, keyed by name so a player seen twice counts once. */
  const scanBoard = async (want, positions) => {
    const found = new Map();
    for (const pos of positions) {
      if (!setPosFilter(pos)) continue;
      await wait(CFG.filterDelay);
      await scrollListTop();
      for (const c of candidates(want)) {
        if (!found.has(c.label)) found.set(c.label, Object.assign({ filter: pos }, c));
      }
    }
    return [...found.values()];
  };

  /* Buttons go stale when the window recycles rows, so a winner chosen during
   * the scan cannot simply be clicked. Go back to where he was and find him
   * again by name. */
  const relocate = async (want, cand) => {
    if (!setPosFilter(cand.filter)) return null;
    await wait(CFG.filterDelay);
    await scrollListTop();
    return candidates(want).find((c) => c.label === cand.label) || null;
  };

  /* Which positions are worth a sweep: the ones a pick could legally go to. */
  const openPositions = (r) => {
    const left = (r.lastRound || CFG.rounds) - r.round;
    const out = [];
    if (r.QB < CFG.maxQB) out.push('QB');
    if (r.RB < CFG.maxRB) out.push('RB');
    if (r.WR < CFG.maxWR) out.push('WR');
    if (r.TE < CFG.maxTE) out.push('TE');
    if (r.DST < 1 && left <= CFG.dstRoundsLeft) out.push('D/ST');
    if (r.K < 1 && left <= CFG.kRoundsLeft) out.push('K');
    return out;
  };

  const clickConfirm = () => {
    document.querySelectorAll('button').forEach((b) => {
      const t = (b.innerText || '').trim().toUpperCase();
      if (/^(CONFIRM|YES|DRAFT PLAYER|OK)$/.test(t) && b.offsetParent !== null) {
        b.click();
      }
    });
  };

  const onTheClock = () =>
    [...document.querySelectorAll('button')].some(isDraft);

  const makePick = async () => {
    const r = roster();
    const byes = myByes();
    const before = r.total;

    const board = await scanBoard(isDraft, openPositions(r));
    const info = leagueInfo();
    const nextPick = nextPickNumber(r, info && info.teams);
    const floors = nextAvailable(board, nextPick);
    const cands = board
      .map((p) => ({ p, s: score(p, r, byes, floors) }))
      .filter((x) => x.s !== null)
      .sort((a, b) => a.s - b.s);

    if (!cands.length) {
      L('NO CANDIDATE (round ' + r.round + ', scanned ' + board.length + ')');
      return;
    }

    const win = cands[0];
    const label = win.p.label + ' [' + win.p.pos + ']';
    const live = await relocate(isDraft, win.p);
    if (!live) {
      L('LOST ROW ' + label + ' after scan -- retrying next tick');
      return;
    }

    live.btn.click();
    L(
      'CLICK ' + label +
        ' vor=' + (win.p.v ? win.p.v.vor : 'n/a') +
        ' floor=' + floorFor(win.p, floors).toFixed(1) +
        ' vona=' + (-win.s).toFixed(1) +
        ' adp=' + (win.p.v ? win.p.v.adp : '?') +
        ' next=' + (nextPick === Infinity ? 'none' : nextPick) +
        ' bye=' + win.p.bye +
        ' board=' + board.length
    );

    await wait(CFG.confirmDelay);
    clickConfirm();
    await wait(CFG.verifyDelay);

    /* Verify the ROSTER grew, never that a click fired. Two shipped bugs
     * reported intent: a pick logged one player while drafting another, and a
     * queue filler reported 21 adds against zero accepted. */
    const after = roster();
    const grew = after.total > before;
    L(
      (grew ? 'OK   ' : 'FAIL ') + label +
        '  roster ' + before + '->' + after.total +
        '  (QB' + after.QB + ' RB' + after.RB + ' WR' + after.WR +
        ' TE' + after.TE + ' K' + after.K + ' DST' + after.DST + ')'
    );
    if (grew) M.picks.push({ at: stamp(), player: win.p.label, pos: win.p.pos });
    setPosFilter('All Pos.');
  };

  const tick = () => {
    if (M.busy || !M.enabled) return;

    /* ESPN silently ignores queue clicks until the draft is live, so the queue
     * cannot be preloaded. Fill it once the clock starts -- it is the
     * zero-latency floor if the autopilot ever misses a turn. Only ever while
     * we are NOT on the clock: drafting outranks stocking the backup. */
    if (!onTheClock()) {
      if (!M.queueDone && !/--:--/.test(document.body.innerText)) {
        M.queueDone = true;
        M.busy = true;
        M.fillQueue(CFG.queueDepth)
          .then((res) => {
            L('auto-queue added ' + res.added);
            if (!res.added) M.queueDone = false; /* not live yet; retry */
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
    makePick()
      .catch((e) => L('ERR ' + e.message))
      .finally(() => {
        M.busy = false;
      });
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

  /* Queue the best few at each open position. This clicks inside each sweep
   * rather than scanning first and relocating per player: relocation costs a
   * filter change and a scroll each, which is fine for the ONE pick that
   * matters and absurd thirty times over. */
  M.fillQueue = async (depth) => {
    const r = roster();
    const byes = myByes();
    const positions = openPositions(r);
    const info = leagueInfo();
    const nextPick = nextPickNumber(r, info && info.teams);
    let floors = {};
    const perPos = Math.max(2, Math.ceil(depth / Math.max(1, positions.length)));
    const before = queueRows().length;
    const tried = [];

    for (const pos of positions) {
      if (!setPosFilter(pos)) continue;
      await wait(CFG.filterDelay);
      await scrollListTop();
      const here = candidates(isQueue);
      floors = Object.assign(floors, nextAvailable(here, nextPick));
      const best = here
        .map((c) => ({ p: c, s: score(c, r, byes, floors) }))
        .filter((x) => x.s !== null)
        .sort((a, b) => a.s - b.s)
        .slice(0, perPos);
      for (const c of best) {
        c.p.btn.click();
        tried.push(c.p.label);
        await wait(200);
      }
    }
    setPosFilter('All Pos.');
    await wait(600);

    const after = queueRows();
    const added = after.length - before;
    L('QUEUE fill: tried ' + tried.length + ', added ' + added);
    return { tried, added, queueNow: after.slice(0, 40), ok: added > 0 };
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

  /* Exposed so the scoring can be exercised against fixtures from outside the
     page. A check whose failure mode is a silent zero needs a positive control. */
  M.score = score;
  M.candidates = candidates;
  M.scanBoard = scanBoard;
  M.openPositions = openPositions;
  M.nextAvailable = nextAvailable;
  M.floorFor = floorFor;
  M.nextPickNumber = nextPickNumber;
  M.leagueInfo = leagueInfo;
  M.myByes = myByes;
  M.roster = roster;
  M.values = VALUES;

  M.timer = setInterval(tick, CFG.pollMs);
  L('ARMED  poll=' + CFG.pollMs + 'ms  valued=' + Object.keys(VALUES).length);
  return 'ARMED';
})();
