// wire.js: the league log for the Scorebug Wire tab, normalized in the Worker.
//
// The same function as espncli/league_log.py `normalize()`, so the Worker can
// show every team's moves with the Mac off. test_wire.py runs both on one
// fetch and fails on any difference: change both or neither.
//
// Sources (league_log.py has the measurements): the activity feed (every add,
// drop, trade and lineup move for every team), mTransactions2 (failed and
// canceled claims, votes, declines, offers), mPendingTransactions (our claims
// and offers, and other teams' trades in their veto review).

export const FEED = {
  178: ["add", "fa"], 180: ["add", "waiver"],
  179: ["drop", null], 239: ["drop", null], 181: ["drop", "waiver"], 245: ["drop", "trade"],
  188: ["lineup", null], 224: ["trade_accepted", null], 244: ["trade", null],
};
const VOTES = { TRADE_UPHOLD: "uphold", TRADE_VETO: "veto" };
const SLOT = { 0: "QB", 2: "RB", 4: "WR", 6: "TE", 16: "D/ST", 17: "K", 20: "BE", 21: "IR", 23: "FLEX" };

export function feedFilter(limit = 1000, offset = 0) {
  return { topics: { filterType: { value: ["ACTIVITY_TRANSACTIONS"] }, limit, limitPerMessageSet: { value: 50 }, offset,
    sortMessageDate: { sortPriority: 1, sortAsc: false }, sortFor: { sortPriority: 2, sortAsc: false },
    filterIncludeMessageTypeIds: { value: Object.keys(FEED).map(Number).sort((a, b) => a - b) } } };
}

export function weekOf(ms, starts) {
  if (ms == null || !starts || !starts.length) return null;
  let w = 0;
  starts.forEach((s, i) => { if (ms >= s) w = i + 1; });
  return w;
}

const team = (m, keys, known) => {
  for (const k of keys) { const v = m[k]; if (Number.isInteger(v) && known.has(v)) return v; }
  return null;
};
const cmp = (a, b) => (a < b ? -1 : a > b ? 1 : 0);

export function normalize(raw, teams, me, starts) {
  const known = new Set(teams), events = [], seen = new Set();
  for (const t of raw.topics || []) {
    const auto = !(t.creationInfo || {}).platform;
    for (const m of t.messages || []) {
      const mt = m.messageTypeId;
      if (!Object.hasOwn(FEED, mt) || seen.has(m.id)) continue;
      seen.add(m.id);
      const [kind, how] = FEED[mt];
      const at = m.date || t.date || null;
      let tm, other = null, detail = null;
      if (kind === "add") tm = team(m, ["to", "for", "from"], known);
      else if (kind === "lineup") { tm = team(m, ["for"], known); detail = `${SLOT[m.from] ?? "?"}>${SLOT[m.to] ?? "?"}`; }
      else if (kind === "trade" || kind === "trade_accepted") { tm = team(m, ["from"], known); other = team(m, ["to"], known); }
      else if (mt === 245) tm = team(m, ["from", "for", "to"], known);
      else tm = team(m, ["for", "from", "to"], known);
      if (tm == null) continue;
      events.push({ id: m.id, at, week: weekOf(at, starts), team_id: tm, kind, how, player_id: m.targetId ?? null,
                    other_team_id: other, detail, src: "feed", auto });
    }
  }
  const rows = new Map();
  for (const x of raw.transactions || []) if (x.id) rows.set(x.id, x);
  for (const x of rows.values()) {
    const typ = x.type || "", st = x.status || "", items = x.items || [];
    const base = { id: x.id, at: x.processDate || x.proposedDate || null, week: x.scoringPeriodId ?? null, team_id: x.teamId ?? null,
                   how: null, other_team_id: null, detail: null, src: "tx", auto: !String(x.memberId || "").startsWith("{") };
    if (typ === "WAIVER" && !["EXECUTED", "PENDING", ""].includes(st)) {
      const add = items.find(i => i.type === "ADD") || {}, drop = items.find(i => i.type === "DROP");
      events.push({ ...base, kind: st === "CANCELED" ? "claim_canceled" : "claim_failed", how: "waiver",
                    player_id: add.playerId ?? null, detail: st !== "CANCELED" ? st.replace("FAILED_", "").toLowerCase() : null,
                    drop_id: drop ? (drop.playerId ?? null) : null });
    } else if (Object.hasOwn(VOTES, typ)) {
      events.push({ ...base, kind: "vote", player_id: null, detail: VOTES[typ], related: x.relatedTransactionId ?? null });
    } else if (typ === "TRADE_DECLINE") {
      events.push({ ...base, kind: "offer_declined", player_id: null, related: x.relatedTransactionId ?? null });
    } else if (typ === "TRADE_PROPOSAL" && ["CANCELED", "EXECUTED", "PENDING"].includes(st)) {
      const parties = [...new Set(items.flatMap(i => ["fromTeamId", "toTeamId"].map(k => i[k]))
        .filter(v => Number.isInteger(v) && known.has(v)))].sort((a, b) => a - b);
      if (st === "PENDING" && !parties.includes(me)) continue;
      const other = parties.find(p => p !== x.teamId) ?? null;
      // ESPN never updates an offer's original row (it stays PENDING after the
      // offer ends), so it reads "proposed"; the pending list says what is open.
      const detail = x.memberId === "TradeTaskProcessor" ? "expired" : st === "PENDING" ? "proposed" : st.toLowerCase();
      events.push({ ...base, kind: "offer", player_id: null, other_team_id: other, detail,
                    at: x.proposedDate ?? null, related: x.relatedTransactionId ?? null,
                    items: items.filter(i => i.type === "TRADE").map(i => ({ player_id: i.playerId ?? null, from: i.fromTeamId ?? null, to: i.toTeamId ?? null })) });
    }
  }
  events.sort((a, b) => (b.at || 0) - (a.at || 0) || cmp(a.id, b.id));
  const pending = [];
  for (const p of raw.pending || []) {
    const items = p.items || [], typ = p.type || "";
    const parties = new Set(items.flatMap(i => [i.fromTeamId, i.toTeamId]));
    let direction;
    if (p.teamId === me) direction = "out";
    else if (parties.has(me)) direction = "in";
    else if (typ.startsWith("TRADE")) direction = "league";
    else continue;
    pending.push({ id: p.id ?? null, type: typ, status: p.status ?? null, team_id: p.teamId ?? null, direction,
                   process_at: p.processDate ?? null, expires_at: p.expirationDate ?? null, proposed_at: p.proposedDate ?? null,
                   order: p.subOrder ?? null,
                   items: items.map(i => ({ type: i.type ?? null, player_id: i.playerId ?? null, from: i.fromTeamId ?? null, to: i.toTeamId ?? null })) });
  }
  const rank = { out: 0, in: 1, league: 2 };   // ours, then offers to us, then trades in review
  const key = p => [rank[p.direction], p.order != null ? p.order : 99, p.process_at || 0];
  pending.sort((a, b) => { const x = key(a), y = key(b); return x[0] - y[0] || x[1] - y[1] || x[2] - y[2]; });
  return { events, pending };
}
