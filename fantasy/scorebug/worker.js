// scorebug: the live fantasy dashboard, served from Cloudflare so that it
// runs with the Mac off (fantasy/scorebug/README.md).
//
// The Mac (or a GitHub Actions runner when the Mac is away) posts a model
// snapshot to /ingest: each starter's mean, spread and pregame mixture, the
// correlations, team names and logos, the season odds. This Worker adds the
// live part on every request: ESPN's live fantasy points and the NFL game
// clocks, combined by model.js exactly as espncli.value.win_prob does.
//
// Routes: /ingest (POST, INGEST_TOKEN); /, /api/state, /logo/<id> (the view
// key, as ?k= once, then a cookie; or "Authorization: Bearer <VIEW_KEY>").
// Cron each minute: history every HISTORY_GAP_S while a game is on, and a
// GitHub dispatch of the snapshot workflow when the snapshot is stale.
// Bindings: KV SB; secrets INGEST_TOKEN, VIEW_KEY, ESPN_CREDENTIALS, GH_TOKEN;
// vars GH_REPO, GH_WORKFLOW. KV writes stay under the free tier's 1000 a day.

import { clockRemaining, winProb } from "./model.js";
import PAGE from "./page.html";

const READS = "https://lm-api-reads.fantasy.espn.com/apis/v3/games/ffl";
const NFL = "https://site.api.espn.com/apis/site/v2/sports/football/nfl/scoreboard";
const UA = "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/18.0 Safari/605.1.15";
const LIVE_TTL_MS = 8000;           // ESPN reads shared by every request in an isolate
const HISTORY_GAP_S = 120;          // about 300 KV writes on a full Sunday
const INGEST_GAP_S = 180;           // a changed snapshot is written at most this often
const STALE_PREGAME_S = 20 * 60;    // refresh the snapshot this often while kickoffs are near
const STALE_IDLE_S = 6 * 3600;
const DISPATCH_GAP_S = 20 * 60;

const json = (obj, status = 200, extra = {}) =>
  new Response(JSON.stringify(obj), { status, headers: { "content-type": "application/json", "cache-control": "no-store", ...extra } });

let memo = { at: 0, key: "", val: null };

async function espnLive(env, snap) {
  const key = `${snap.season}:${snap.week}`;
  if (memo.key === key && Date.now() - memo.at < LIVE_TTL_MS) return memo.val;
  const creds = JSON.parse(env.ESPN_CREDENTIALS);
  const cookie = `espn_s2=${creds.espn_s2}; SWID=${creds.swid || creds.SWID}`;
  const url = `${READS}/seasons/${snap.season}/segments/0/leagues/${creds.league_id}?view=mMatchupScore&view=mScoreboard&scoringPeriodId=${snap.week}`;
  const [league, nfl] = await Promise.all([
    fetch(url, { headers: { cookie, "user-agent": UA, accept: "application/json" } }).then(r => r.ok ? r.json() : Promise.reject(new Error(`ESPN league ${r.status}`))),
    fetch(`${NFL}?seasontype=2&week=${snap.week}&dates=${snap.season}`, { headers: { "user-agent": UA } }).then(r => r.ok ? r.json() : Promise.reject(new Error(`NFL scoreboard ${r.status}`))),
  ]);
  const teams = {}, players = {}, lineups = {};
  for (const m of league.schedule || []) {
    if (m.matchupPeriodId !== snap.week) continue;
    for (const k of ["home", "away"]) {
      const s = m[k];
      if (!s) continue;
      teams[s.teamId] = s.totalPointsLive ?? s.totalPoints ?? 0;
      lineups[s.teamId] = [];
      for (const e of (s.rosterForCurrentScoringPeriod || {}).entries || []) {
        players[e.playerPoolEntry.id] = e.playerPoolEntry.appliedStatTotal ?? 0;
        if (e.lineupSlotId !== 20 && e.lineupSlotId !== 21) lineups[s.teamId].push(e.playerPoolEntry.id);
      }
    }
  }
  const games = {};   // pro team abbrev -> {state, left}
  for (const e of nfl.events || []) {
    const comp = (e.competitions || [{}])[0], st = (e.status || {}).type || {};
    const left = clockRemaining(st.state, (e.status || {}).period, (e.status || {}).displayClock);
    for (const c of comp.competitors || []) {
      const ab = (c.team || {}).abbreviation;
      if (ab) games[ab] = { state: st.state, left };
    }
  }
  memo = { at: Date.now(), key, val: { teams, players, lineups, games, at: new Date().toISOString() } };
  return memo.val;
}

function compute(snap, live) {
  const g = t => live.games[t] || { state: "none", left: 0 };
  const pts = r => (g(r.team).state === "pre" || g(r.team).state === "none") ? null : (live.players[r.id] ?? 0);
  const views = {}, stale = [];
  for (const v of snap.views) {
    const w = winProb(v, pts, t => g(t).left);
    const side = (s, off) => ({
      team_id: s.team_id, team: s.team, actual: live.teams[s.team_id] ?? 0,
      rows: s.rows.map((r, i) => {
        const st = g(r.team), p = pts(r);
        return { id: r.id, slot: r.slot, name: r.name, team: r.team, opp: r.opp, kick: r.kick, status: r.status,
                 jersey: r.jersey, bank: p ?? 0, rem: Math.round(w.rem[off + i] * 10) / 10,
                 state: st.state === "in" ? "live" : p == null ? "upcoming" : "final", left: st.state === "in" ? st.left : null };
      }),
    });
    views[v.id] = { id: v.id, win: { p: w.p, mu_me: w.mu_me, sd_me: w.sd_me, mu_opp: w.mu_opp, sd_opp: w.sd_opp, margin: w.margin, sd_diff: w.sd_diff },
                    me: side(v.me, 0), opp: side(v.opp, v.me.rows.length) };
    for (const s of [v.me, v.opp]) {
      const now = new Set(live.lineups[s.team_id] || []), had = new Set(s.rows.map(r => r.id));
      if (now.size && (now.size !== had.size || [...now].some(id => !had.has(id)))) stale.push(s.team);
    }
  }
  const isLive = Object.values(live.games).some(x => x.state === "in");
  const frac = Object.fromEntries(Object.entries(live.games).filter(([, x]) => x.state === "in").map(([k, x]) => [k, x.left]));
  const games = snap.views.map(v => ({ id: v.id, hid: v.me.team_id, aid: v.opp.team_id, h: v.me.team, a: v.opp.team,
    hs: live.teams[v.me.team_id] ?? 0, as: live.teams[v.opp.team_id] ?? 0, p: views[v.id].win.p, mine: v.id === snap.mine }));
  const team_ids = Object.fromEntries(Object.entries(snap.teams).map(([id, t]) => [t.name, Number(id)]));
  return { ok: true, at: snap.at, source: snap.source, scoresAt: live.at, week: snap.week, live: isLive, frac, mine: snap.mine,
           views, games, team_ids, season: snap.season_sim, lineup_changed: stale };
}

async function getSnap(env) {
  const s = await env.SB.get("snap", "json");
  if (!s) throw new Error("no snapshot yet: run fantasy/scorebug/snapshot.py --post");
  return s;
}

async function history(env, snap) {
  const h = (await env.SB.get(`hist:${snap.season}:${snap.week}`, "json")) || [];
  return h.map(e => ({ t: e.t, p: e.all[snap.mine]?.p, me: e.all[snap.mine]?.me, opp: e.all[snap.mine]?.opp, all: e.all }));
}

async function record(env) {
  const snap = await getSnap(env);
  const live = await espnLive(env, snap);
  const st = compute(snap, live);
  const now = Math.floor(Date.now() / 1000);
  const out = { live: st.live };
  if (st.live) {
    const last = Number(await env.SB.get("hist:last")) || 0;
    if (now - last >= HISTORY_GAP_S - 5) {
      const key = `hist:${snap.season}:${snap.week}`;
      const h = (await env.SB.get(key, "json")) || [];
      h.push({ t: new Date().toISOString(), all: Object.fromEntries(Object.values(st.views).map(v =>
        [v.id, { p: Math.round(v.win.p * 1000) / 1000, me: v.me.actual, opp: v.opp.actual }])) });
      await env.SB.put(key, JSON.stringify(h));
      await env.SB.put("hist:last", String(now));
      out.history = h.length;
    }
  }
  // Ask for a fresh snapshot when starters are still to lock soon, or a lineup changed.
  const age = now - Math.floor(Date.parse(snap.at) / 1000);
  const soon = snap.views.some(v => [...v.me.rows, ...v.opp.rows].some(r => r.kickoff && Date.parse(r.kickoff) > Date.now() && Date.parse(r.kickoff) - Date.now() < 30 * 3600e3));
  const want = st.lineup_changed.length ? 0 : soon ? STALE_PREGAME_S : STALE_IDLE_S;
  if (age > want && env.GH_TOKEN) {
    const lastD = Number(await env.SB.get("dispatch:last")) || 0;
    if (now - lastD > DISPATCH_GAP_S) {
      const r = await fetch(`https://api.github.com/repos/${env.GH_REPO}/actions/workflows/${env.GH_WORKFLOW}/dispatches`, {
        method: "POST", headers: { Authorization: `Bearer ${env.GH_TOKEN}`, Accept: "application/vnd.github+json", "User-Agent": "scorebug", "content-type": "application/json" },
        body: JSON.stringify({ ref: "main" }) });
      if (r.status === 204) await env.SB.put("dispatch:last", String(now));
      out.dispatch = r.status;
    }
  }
  return out;
}

function authed(req, env) {
  const cookie = req.headers.get("cookie") || "";
  return req.headers.get("authorization") === `Bearer ${env.VIEW_KEY}` || cookie.split(/;\s*/).includes(`sbk=${env.VIEW_KEY}`);
}

export default {
  async fetch(req, env) {
    const url = new URL(req.url);
    const path = url.pathname.replace(/\/+$/, "") || "/";
    if (path === "/ingest" && req.method === "POST") {
      if (req.headers.get("authorization") !== `Bearer ${env.INGEST_TOKEN}`) return json({ error: "unauthorized" }, 401);
      const snap = await req.json();
      const prevSig = await env.SB.get("snap:sig");
      const now = Math.floor(Date.now() / 1000), last = Number(await env.SB.get("snap:last")) || 0;
      const prev = await env.SB.get("snap", "json");
      // The season odds are a Mac file; a cloud snapshot keeps the last ones.
      if (!snap.season_sim && prev?.season_sim) snap.season_sim = prev.season_sim;
      const lineupMoved = !prev || JSON.stringify(prev.views.map(v => [v.me.rows.map(r => r.id), v.opp.rows.map(r => r.id)])) !==
                          JSON.stringify(snap.views.map(v => [v.me.rows.map(r => r.id), v.opp.rows.map(r => r.id)]));
      const body = JSON.stringify(snap), sig = JSON.stringify({ ...snap, at: null, source: null });
      if (prevSig === sig) return json({ ok: true, stored: false, reason: "unchanged" });
      if (!lineupMoved && prev && prev.week === snap.week && now - last < INGEST_GAP_S) return json({ ok: true, stored: false, reason: "too soon" });
      await env.SB.put("snap", body);
      await env.SB.put("snap:sig", sig);
      await env.SB.put("snap:last", String(now));
      return json({ ok: true, stored: true });
    }
    if (path === "/status") {
      const s = await env.SB.get("snap", "json");
      return json({ ok: !!s, snapshot_at: s?.at, source: s?.source, week: s?.week });
    }
    if (url.searchParams.get("k") === env.VIEW_KEY) {
      url.searchParams.delete("k");
      return new Response(null, { status: 302, headers: { location: url.pathname + (url.search || ""),
        "set-cookie": `sbk=${env.VIEW_KEY}; Path=/; Max-Age=31536000; HttpOnly; Secure; SameSite=Lax` } });
    }
    if (!authed(req, env)) return new Response("Scorebug: open the link with your key once.", { status: 401 });

    try {
      if (path === "/") return new Response(PAGE, { headers: { "content-type": "text/html; charset=utf-8", "cache-control": "no-store" } });
      if (path === "/api/live") return json({});
      if (path === "/api/state") {
        const snap = await getSnap(env);
        const st = compute(snap, await espnLive(env, snap));
        st.history = await history(env, snap);
        return json(st);
      }
      if (path === "/api/record" && req.method === "POST") return json(await record(env));
      const m = path.match(/^\/logo\/(\d+)$/);
      if (m) {
        const snap = await getSnap(env);
        const src = (snap.teams[m[1]] || {}).logo;
        if (!src) return new Response("no logo", { status: 404 });
        const creds = JSON.parse(env.ESPN_CREDENTIALS);
        const r = await fetch(src, { headers: { "user-agent": UA, ...(src.includes("fantasy.espn.com") ? { cookie: `espn_s2=${creds.espn_s2}; SWID=${creds.swid || creds.SWID}` } : {}) } });
        if (!r.ok) return new Response("logo fetch failed", { status: 502 });
        let ct = r.headers.get("content-type") || "image/png";
        if (ct === "image/jpg") ct = "image/jpeg";
        return new Response(r.body, { headers: { "content-type": ct, "cache-control": "private, max-age=86400" } });
      }
      return new Response("not found", { status: 404 });
    } catch (e) {
      return json({ ok: false, error: String(e.message || e) }, 500);
    }
  },

  async scheduled(_event, env, ctx) {
    ctx.waitUntil(record(env).catch(() => null));
  },
};
