// fantasy-hub: the cloud side of the fantasy watchers (fantasy/cloud/README.md).
//
// The Mac posts a heartbeat every 15 minutes from lineup-watch. When the
// heartbeat is older than STALE_S, the cron below starts the GitHub Actions
// fallback (lineup-watch --fix and roster-watch on a runner), and the cloud
// Claude routines go ahead instead of skipping. The hub also holds what those
// cloud runs need from the Mac: the ESPN cookies (a secret), the playbook and
// skill text (mirrored by the Mac when they change), and a queue of Season
// log bullets the Mac merges back into the playbook when it is up again.
//
// Every route except /status needs "Authorization: Bearer <HUB_TOKEN>".
// Bindings: KV namespace HUB; secrets HUB_TOKEN, ESPN_CREDENTIALS (JSON),
// DISCORD_BOT_TOKEN, DISCORD_NOTIFY_CHAT_ID, GH_TOKEN; vars GH_REPO, GH_WORKFLOW.

const STALE_S = 35 * 60;          // two missed heartbeats plus slack
const DISPATCH_GAP_S = 10 * 60;   // never start the fallback more often than this
const BLOBS = new Set(["playbook", "skill", "watchlist"]);

const json = (obj, status = 200) =>
  new Response(JSON.stringify(obj), { status, headers: { "content-type": "application/json" } });

async function macState(env) {
  const last = Number(await env.HUB.get("mac:last")) || 0;
  const age = Math.floor(Date.now() / 1000) - last;
  return { mac_last: last ? new Date(last * 1000).toISOString() : null, age_s: last ? age : null, stale: !last || age > STALE_S };
}

async function discord(env, text) {
  if (!env.DISCORD_BOT_TOKEN || !env.DISCORD_NOTIFY_CHAT_ID) return false;
  const r = await fetch(`https://discord.com/api/v10/channels/${env.DISCORD_NOTIFY_CHAT_ID}/messages`, {
    method: "POST",
    headers: { Authorization: `Bot ${env.DISCORD_BOT_TOKEN}`, "content-type": "application/json",
               "User-Agent": "DiscordBot (https://exobrain.local, 1.0)" },
    body: JSON.stringify({ content: text.slice(0, 1990), allowed_mentions: { parse: [] } }),
  });
  return r.ok;
}

async function dispatch(env, reason) {
  const r = await fetch(`https://api.github.com/repos/${env.GH_REPO}/actions/workflows/${env.GH_WORKFLOW}/dispatches`, {
    method: "POST",
    headers: { Authorization: `Bearer ${env.GH_TOKEN}`, Accept: "application/vnd.github+json",
               "User-Agent": "fantasy-hub", "content-type": "application/json" },
    body: JSON.stringify({ ref: "main", inputs: { reason } }),
  });
  return r.status;
}

async function tick(env) {
  const s = await macState(env);
  const now = Math.floor(Date.now() / 1000);
  const mode = await env.HUB.get("mode");          // "cloud" while the Mac is away
  if (!s.stale) {
    if (mode === "cloud") {
      await env.HUB.put("mode", "mac");
      await discord(env, "(◠▽◠) Fantasy watchers: the Mac is back. The cloud fallback is off again.");
    }
    return { action: "none", ...s };
  }
  if (mode !== "cloud") {
    await env.HUB.put("mode", "cloud");
    const since = s.mac_last ? `since ${s.mac_last}` : "(no heartbeat yet)";
    await discord(env, `(o.o) Fantasy watchers: no Mac heartbeat ${since}. The cloud fallback is on: lineup and roster checks run on GitHub Actions every 15 minutes, and the cloud MIST routines run in place of the Mac ones.`);
  }
  const lastDispatch = Number(await env.HUB.get("dispatch:last")) || 0;
  if (now - lastDispatch < DISPATCH_GAP_S) return { action: "wait", ...s };
  const status = await dispatch(env, `mac heartbeat ${s.age_s ?? "never"}s old`);
  if (status === 204) await env.HUB.put("dispatch:last", String(now));
  else await discord(env, `(ó﹏ò) Fantasy cloud fallback: GitHub refused the workflow dispatch (HTTP ${status}). Lineup checks are not running.`);
  return { action: "dispatch", status, ...s };
}

export default {
  async fetch(req, env) {
    const url = new URL(req.url);
    const path = url.pathname.replace(/\/+$/, "") || "/";
    if (path === "/status") return json({ ...(await macState(env)), mode: (await env.HUB.get("mode")) || "mac" });
    if (req.headers.get("authorization") !== `Bearer ${env.HUB_TOKEN}`) return json({ error: "unauthorized" }, 401);

    if (path === "/heartbeat" && req.method === "POST") {
      await env.HUB.put("mac:last", String(Math.floor(Date.now() / 1000)));
      const body = await req.json().catch(() => ({}));
      const pendingBundle = JSON.parse((await env.HUB.get("bundle")) || "{}");
      for (const name of BLOBS) {
        if (typeof body[name] !== "string") continue;
        if (name === "playbook" && pendingBundle.playbook) continue;  // cloud edits not applied yet
        await env.HUB.put(`blob:${name}`, body[name]);
      }
      const queued = JSON.parse((await env.HUB.get("log")) || "[]");
      return json({ ok: true, queued: queued.length });
    }
    const blob = path.match(/^\/blob\/(\w+)$/);
    if (blob && BLOBS.has(blob[1]) && req.method === "GET") {
      const v = await env.HUB.get(`blob:${blob[1]}`);
      return v === null ? json({ error: "missing" }, 404) : new Response(v, { headers: { "content-type": "text/markdown; charset=utf-8" } });
    }
    if (path === "/creds" && req.method === "GET") {
      return json({ espn: JSON.parse(env.ESPN_CREDENTIALS || "{}"), discord_bot_token: env.DISCORD_BOT_TOKEN || null,
                    discord_notify_chat_id: env.DISCORD_NOTIFY_CHAT_ID || null });
    }
    if (path === "/log" && req.method === "POST") {
      const body = await req.json().catch(() => null);
      if (!body || typeof body.text !== "string") return json({ error: "need {routine, text}" }, 400);
      const queued = JSON.parse((await env.HUB.get("log")) || "[]");
      queued.push({ at: new Date().toISOString(), routine: String(body.routine || "cloud"), kind: body.kind === "routine-log" ? "routine-log" : "season-log", text: body.text });
      await env.HUB.put("log", JSON.stringify(queued));
      return json({ ok: true, queued: queued.length });
    }
    if (path === "/log/drain" && req.method === "POST") {
      const queued = JSON.parse((await env.HUB.get("log")) || "[]");
      if (queued.length) await env.HUB.put("log", "[]");
      return json({ entries: queued });
    }
    // A cloud routine's edits (the playbook and tracked fantasy files), each
    // with the sha256 of the text it started from. The Mac applies an entry
    // only when its own copy still has that base, so a fast-forward never
    // overwrites an edit made on the Mac (bin/cloud-sync).
    if (path === "/bundle" && req.method === "POST") {
      const body = await req.json().catch(() => null);
      if (!body || typeof body.files !== "object") return json({ error: "need {routine, files}" }, 400);
      const cur = JSON.parse((await env.HUB.get("bundle")) || "{}");
      for (const [k, v] of Object.entries(body.files)) {
        // A second run on the same file keeps the first base: the Mac never saw the middle version.
        cur[k] = { base: cur[k]?.base ?? v.base, text: v.text, routine: body.routine, at: new Date().toISOString() };
        if (k === "playbook") await env.HUB.put("blob:playbook", v.text);
      }
      await env.HUB.put("bundle", JSON.stringify(cur));
      return json({ ok: true, files: Object.keys(cur) });
    }
    if (path === "/bundle/drain" && req.method === "POST") {
      const cur = JSON.parse((await env.HUB.get("bundle")) || "{}");
      if (Object.keys(cur).length) await env.HUB.put("bundle", "{}");
      return json({ files: cur });
    }
    if (path === "/notify" && req.method === "POST") {
      const body = await req.json().catch(() => ({}));
      return json({ ok: await discord(env, String(body.text || "")) });
    }
    // First caller for a key wins: one cloud run per routine per local day,
    // though the cron fires twice to cover both sides of daylight saving.
    if (path === "/once" && req.method === "POST") {
      const body = await req.json().catch(() => ({}));
      const key = `once:${String(body.key || "")}`;
      if (await env.HUB.get(key)) return json({ first: false });
      await env.HUB.put(key, new Date().toISOString(), { expirationTtl: 3 * 86400 });
      return json({ first: true });
    }
    if (path === "/tick" && req.method === "POST") return json(await tick(env));
    return json({ error: "not found" }, 404);
  },
  async scheduled(_event, env, ctx) {
    ctx.waitUntil(tick(env));
  },
};
