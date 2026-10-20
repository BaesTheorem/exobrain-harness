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
// Bindings: KV SB; secrets INGEST_TOKEN, VIEW_KEY, ESPN_CREDENTIALS, GH_TOKEN,
// APNS_KEY, APNS_KEY_ID, APNS_TEAM_ID; vars APNS_TOPIC (the app bundle id),
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

// ---------- the short summary (widget) and the Live Activity ----------

const lastName = n => n.split(" ").slice(-1)[0];
function names(rows) {
  const n = rows.map(r => lastName(r.name));
  return n.length > 2 ? `${n.length} players` : n.join(" and ");
}

function summary(st) {
  const v = st.views[st.mine], me = v.me, op = v.opp;
  const rm = me.rows.filter(r => r.rem > 0), ro = op.rows.filter(r => r.rem > 0);
  const final = !rm.length && !ro.length;
  const live = [...me.rows, ...op.rows].some(r => r.state === "live");
  const gap = Math.round((op.actual - me.actual) * 100) / 100;
  let line;
  if (final) line = me.actual >= op.actual ? `Won by ${(-gap).toFixed(2)}` : `Lost by ${gap.toFixed(2)}`;
  else if (rm.length && ro.length) line = `${names(rm)} vs ${names(ro)}`;
  else line = `${names(rm.length ? rm : ro)} still to play`;
  return { week: st.week, meName: me.team, oppName: op.team, meScore: me.actual, oppScore: op.actual,
           p: Math.round(v.win.p * 1000) / 1000, line, live, final, updated: Math.floor(Date.now() / 1000) };
}

const enc = new TextEncoder();
const b64url = buf => btoa(String.fromCharCode(...new Uint8Array(buf))).replace(/\+/g, "-").replace(/\//g, "_").replace(/=+$/, "");
let apnsJwt = { token: "", iat: 0 };

async function apnsToken(env) {
  const now = Math.floor(Date.now() / 1000);
  if (apnsJwt.token && now - apnsJwt.iat < 40 * 60) return apnsJwt.token;   // Apple: refresh every 20-60 min
  const pem = env.APNS_KEY.replace(/-----[^-]+-----/g, "").replace(/\s+/g, "");
  const der = Uint8Array.from(atob(pem), c => c.charCodeAt(0));
  const key = await crypto.subtle.importKey("pkcs8", der, { name: "ECDSA", namedCurve: "P-256" }, false, ["sign"]);
  const head = b64url(enc.encode(JSON.stringify({ alg: "ES256", kid: env.APNS_KEY_ID })));
  const body = b64url(enc.encode(JSON.stringify({ iss: env.APNS_TEAM_ID, iat: now })));
  const sig = await crypto.subtle.sign({ name: "ECDSA", hash: "SHA-256" }, key, enc.encode(`${head}.${body}`));
  apnsJwt = { token: `${head}.${body}.${b64url(sig)}`, iat: now };
  return apnsJwt.token;
}

async function laPush(env, dev, aps, priority) {
  const host = dev.env === "sandbox" ? "api.sandbox.push.apple.com" : "api.push.apple.com";
  const r = await fetch(`https://${host}/3/device/${dev.token}`, {
    method: "POST",
    headers: { authorization: `bearer ${await apnsToken(env)}`, "apns-topic": `${env.APNS_TOPIC}.push-type.liveactivity`,
               "apns-push-type": "liveactivity", "apns-priority": String(priority), "content-type": "application/json" },
    body: JSON.stringify({ aps: { timestamp: Math.floor(Date.now() / 1000), ...aps } }),
  });
  return { status: r.status, reason: r.ok ? "" : ((await r.json().catch(() => ({}))).reason || "") };
}

const LA_MAX_S = 7.5 * 3600;   // iOS ends an activity after 8 hours of updates

// Start the activity by push when one of our starters' games is on, update it
// on the history cadence, end it when nothing of ours is live or due today.
async function liveActivity(env, st, snap) {
  if (!env.APNS_KEY) return null;
  const la = (await env.SB.get("la", "json")) || {};
  const now = Math.floor(Date.now() / 1000);
  const rows = [...st.views[st.mine].me.rows, ...st.views[st.mine].opp.rows];
  const live = rows.some(r => r.state === "live");
  const kick = new Map(snap.views.flatMap(v => [...v.me.rows, ...v.opp.rows]).map(r => [r.id, r.kickoff]));
  const dueSoon = rows.some(r => r.state === "upcoming" && kick.get(r.id) && Date.parse(kick.get(r.id)) - Date.now() < 4 * 3600e3);
  const s = summary(st), v = st.views[st.mine];
  const state = { meScore: s.meScore, oppScore: s.oppScore, p: s.p, line: s.line, live: s.live, final: s.final, updated: s.updated };
  let out = { live, dueSoon }, dirty = false;
  if (la.update && now - (la.update.at || 0) > LA_MAX_S) { delete la.update; dirty = true; }
  if (live && !la.update && la.start && (!la.startedAt || now - la.startedAt > LA_MAX_S)) {
    out.start = await laPush(env, la.start, { event: "start", "content-state": state, "attributes-type": "ScorebugAttributes",
      attributes: { week: st.week, meName: v.me.team, oppName: v.opp.team },
      alert: { title: `Week ${st.week} is live`, body: `${Scorebug(s.p)} to win · ${s.line}` } }, 10);
    la.startedAt = now; dirty = true;
  } else if (la.update) {
    if (live || dueSoon) {
      out.update = await laPush(env, la.update, { event: "update", "content-state": state, "stale-date": now + 600 }, 5);
    } else {
      out.end = await laPush(env, la.update, { event: "end", "content-state": state, "dismissal-date": now + 3 * 3600 }, 10);
      delete la.update; dirty = true;
    }
    if ((out.update || {}).status === 410 || (out.update || {}).status === 400) { delete la.update; dirty = true; }
  }
  if (dirty) await env.SB.put("la", JSON.stringify(la));
  return out;
}
const Scorebug = p => `${Math.round(p * 100)}%`;

// ---------- ESPN Fantasy Chat (league chat and DMs) ----------
// The same endpoints as espncli/chat.py (read) and espncli/tx.py chat_send /
// chat_open (write). A send is always Alex's own tap in the app; it is
// verified like espn-tx: read the thread back, each chunk exactly once.
// People show as their team name, or initials for a member with no team,
// never a real name (espncli.client.initials).

const WRITES = "https://lm-api-writes.fantasy.espn.com/apis/v3/games/ffl";
const CHAT_VIEW = "kona_league_communication";
const CHAT_TYPES = new Set(["CHAT", "CHAT_DIRECT_MESSAGE", "CHAT_ALL_MEMBERS"]);
const MAX_CONTENT = 240;
let chatMemo = { at: 0, val: null }, teamMemo = { at: 0, val: null };

function espnAuth(env) {
  const c = JSON.parse(env.ESPN_CREDENTIALS);
  return { c, cookie: `espn_s2=${c.espn_s2}; SWID=${c.SWID || c.swid}` };
}

function splitMessage(text, limit = MAX_CONTENT) {
  text = text.trim();
  const out = [];
  while (text.length > limit) {
    const w = text.slice(0, limit);
    let cut = -1;
    for (const seam of ["\n\n", ". ", "! ", "? ", "\n", " "]) {
      const i = w.lastIndexOf(seam);
      if (i > Math.floor(limit / 3)) { cut = i + (seam === " " ? 1 : seam.length); break; }
    }
    if (cut <= 0) cut = limit;
    out.push(text.slice(0, cut).trim());
    text = text.slice(cut).trim();
  }
  if (text) out.push(text);
  return out;
}

async function leagueTeams(env, snap) {
  if (teamMemo.val && Date.now() - teamMemo.at < 10 * 60e3) return teamMemo.val;
  const { c, cookie } = espnAuth(env);
  const r = await fetch(`${READS}/seasons/${snap.season}/segments/0/leagues/${c.league_id}?view=mTeam`, { headers: { cookie, "user-agent": UA } });
  if (!r.ok) throw new Error(`ESPN teams ${r.status}`);
  const d = await r.json();
  const members = Object.fromEntries((d.members || []).map(m => [m.id, m]));
  const ini = m => { if (!m) return "?"; const s = [m.firstName, m.lastName].filter(Boolean).map(x => x[0].toUpperCase() + ".").join(""); return s || ((m.displayName || "?")[0].toUpperCase() + "."); };
  const bySwid = {}, teams = [];
  for (const t of d.teams || []) {
    const owner = t.primaryOwner || (t.owners || [])[0];
    const name = (t.name || t.abbrev || "").trim();
    if (owner) bySwid[owner] = { name, team_id: t.id };
    teams.push({ id: t.id, name, owner, mine: t.id === Number(c.team_id) });
  }
  for (const [id, m] of Object.entries(members)) if (!bySwid[id]) bySwid[id] = { name: ini(m), team_id: null };
  teamMemo = { at: Date.now(), val: { bySwid, teams, me: String(c.SWID || c.swid) } };
  return teamMemo.val;
}

async function rawTopics(env, snap) {
  const { c, cookie } = espnAuth(env);
  const r = await fetch(`${READS}/seasons/${snap.season}/segments/0/leagues/${c.league_id}/communication/topics?view=${CHAT_VIEW}`,
    { headers: { cookie, "user-agent": UA, accept: "application/json" } });
  if (!r.ok) throw new Error(`ESPN chat ${r.status}`);
  return r.json();
}

async function chatThreads(env, snap, fresh = false) {
  if (!fresh && chatMemo.val && Date.now() - chatMemo.at < LIVE_TTL_MS) return chatMemo.val;
  const [raw, T] = await Promise.all([rawTopics(env, snap), leagueTeams(env, snap)]);
  const who = s => T.bySwid[s] || { name: s ? "?" : "ESPN", team_id: null };
  const threads = [];
  for (const t of Array.isArray(raw) ? raw : []) {
    if (!CHAT_TYPES.has(t.type || "")) continue;
    const messages = (t.messages || []).filter(m => m.content != null).sort((a, b) => (a.date || 0) - (b.date || 0))
      .map(m => ({ id: m.id, date: m.date, mine: m.author === T.me, who: m.author === T.me ? "You" : who(m.author).name,
                   team_id: who(m.author).team_id, content: m.content }));
    const others = (t.viewableBy || []).filter(s => s !== T.me);
    const dm = t.type === "CHAT_DIRECT_MESSAGE";
    threads.push({ id: t.id, type: t.type, dm, title: dm ? others.map(s => who(s).name).join(", ") || "Direct message" : t.type === "CHAT_ALL_MEMBERS" ? "All members" : "League chat",
                   team_id: dm && others.length === 1 ? who(others[0]).team_id : null,
                   messages: messages.slice(-200), last: messages.length ? messages[messages.length - 1].date : 0 });
  }
  threads.sort((a, b) => (b.last || 0) - (a.last || 0));
  const val = { threads, teams: T.teams.filter(t => !t.mine).map(t => ({ id: t.id, name: t.name })), at: new Date().toISOString() };
  chatMemo = { at: Date.now(), val };
  return val;
}

async function espnPost(env, snap, path, body) {
  const { c, cookie } = espnAuth(env);
  const r = await fetch(`${WRITES}/seasons/${snap.season}/segments/0/leagues/${c.league_id}${path}`, {
    method: "POST", body: JSON.stringify(body),
    headers: { cookie, "user-agent": UA, accept: "application/json", "content-type": "application/json",
               origin: "https://fantasy.espn.com", referer: "https://fantasy.espn.com/",
               "x-fantasy-source": "kona", "x-fantasy-platform": "kona-PROD" } });
  const text = await r.text();
  if (!r.ok) throw new Error(`ESPN ${r.status}: ${text.slice(0, 300)}`);
  return text ? JSON.parse(text) : {};
}

async function chatSend(env, snap, topic, text) {
  const chunks = splitMessage(String(text || ""));
  if (!chunks.length) throw new Error("nothing to send");
  const { c } = espnAuth(env);
  const sent = [], failed = [];
  for (const chunk of chunks) {
    try { await espnPost(env, snap, `/communication/topics/${topic}/messages`, { author: String(c.SWID || c.swid), content: chunk, topicId: topic, messageTypeId: 0 }); sent.push(chunk); }
    catch (e) { failed.push({ chunk, error: String(e.message || e) }); break; }   // stop rather than scatter the rest
  }
  const back = (await chatThreads(env, snap, true)).threads.find(t => t.id === topic);
  const posted = back ? back.messages.map(m => m.content) : [];
  const missing = sent.filter(ch => posted.filter(p => p === ch).length !== 1);
  return { chunks: chunks.length, sent: sent.length, failed, verified: !failed.length && !missing.length, missing_or_duplicated: missing };
}

async function chatOpen(env, snap, teamId) {
  const T = await leagueTeams(env, snap);
  const target = T.teams.find(t => t.id === Number(teamId));
  if (!target || !target.owner) throw new Error("no such team");
  const want = [T.me, target.owner].sort().join("|");
  const find = async () => (await rawTopics(env, snap)).find(t => t.type === "CHAT_DIRECT_MESSAGE" && [...(t.viewableBy || [])].sort().join("|") === want);
  const have = await find();
  if (have) return { topic: have.id, created: false };
  const mine = T.teams.find(t => t.mine);
  try {
    const r = await espnPost(env, snap, "/communication/topics", { type: "CHAT_DIRECT_MESSAGE", viewableBy: [T.me, target.owner], subject: (mine && mine.name) || "Direct message" });
    chatMemo.at = 0;
    return { topic: r.id, created: true };
  } catch (e) {
    if (!String(e.message).includes("TOPIC_IDENTICAL_MEMBERS")) throw e;   // ESPN dedupes DM threads by membership
    const again = await find();
    if (again) return { topic: again.id, created: false };
    throw e;
  }
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
  const last = Number(await env.SB.get("hist:last")) || 0;
  const due = now - last >= HISTORY_GAP_S - 5;
  if (due) out.la = await liveActivity(env, st, snap).catch(e => ({ error: String(e) }));
  if (st.live) {
    if (due) {
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
      if (path === "/api/chat") return json(await chatThreads(env, await getSnap(env)));
      if (path === "/api/chat/send" && req.method === "POST") {
        const b = await req.json();
        if (!/^[\w-]{6,80}$/.test(b.topic || "")) return json({ error: "bad topic" }, 400);
        return json(await chatSend(env, await getSnap(env), b.topic, b.text));
      }
      if (path === "/api/chat/open" && req.method === "POST") {
        const b = await req.json();
        return json(await chatOpen(env, await getSnap(env), b.team_id));
      }
      if (path === "/api/summary") {
        const snap = await getSnap(env);
        return json(summary(compute(snap, await espnLive(env, snap))));
      }
      if (path === "/la/register" && req.method === "POST") {
        const b = await req.json();
        if (!/^[0-9a-f]{32,200}$/.test(b.token || "") || !["start", "update"].includes(b.kind)) return json({ error: "bad token" }, 400);
        const la = (await env.SB.get("la", "json")) || {};
        const dev = { token: b.token, env: b.env === "sandbox" ? "sandbox" : "production", at: Math.floor(Date.now() / 1000), activity: b.activity || null };
        if (JSON.stringify((la[b.kind] || {}).token) === JSON.stringify(dev.token)) return json({ ok: true, stored: false });
        la[b.kind] = dev;
        await env.SB.put("la", JSON.stringify(la));
        return json({ ok: true, stored: true });
      }
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
