// Curbside: client for the local Marketplace index. The page holds every indexed listing,
// syncs changes from the server, and filters and sorts here. The search box filters the
// index by title and also asks Facebook, whose matches join the results.
// Filter rules are mirrored in marketplace/filters.py for alerts: keep the two in step.
import * as maplibregl from "./vendor/maplibre/maplibre-gl.mjs";

const $ = (s) => document.querySelector(s);
const DEALER_MIN = 4;
const PAGE = 120;
// Facebook mixes property rentals into product searches. Category measured 2026-10-24.
const HOUSING_CATEGORIES = new Set(["1468271819871448"]);
const HOUSING_BROWSE = new Set(["propertyrentals", "propertyforsale"]);
const HOUSING_TITLE = /^\d+ beds? \d+ baths? /i;
const CONDITION = { "New": "new", "Used - Like New": "used_like_new", "Used - Good": "used_good", "Used - Fair": "used_fair" };

const DEFAULTS = {
  q: "", max_mi: 10, min: "", max: "", days: "", condition: [], categories: [],
  local_only: true, exact: false, hide_dealers: false, hide_pending: false, hide_relists: false,
  drops_only: false, sort: "near",
};
const state = structuredClone(DEFAULTS);
const all = new Map();      // id -> light row
let cursor = 0;             // server time of the last index sync
let cfg = null;
let job = null;             // the Facebook text search for state.q
let jobIds = new Set();
let shown = PAGE;
let syncTimer = null, jobTimer = null;
const cards = new Map();
let map = null;

// ------------------------------------------------------------------ helpers

const api = async (path, body) => {
  const r = await fetch(path, body === undefined ? {} :
    { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(body) });
  const j = await r.json();
  if (!r.ok) throw new Error(j.error || r.statusText);
  return j;
};
const esc = (s) => String(s ?? "").replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
const money = (n) => n == null ? "" : "$" + (Math.round(n) === n ? n.toLocaleString() : n.toFixed(2));
const priceText = (r) => (r.price === 0 ? "Free" : r.formatted || money(r.price) || "Free");

function ago(ts) {
  if (!ts) return "";
  const h = (Date.now() / 1000 - ts) / 3600;
  if (h < 1) return `${Math.max(1, Math.round(h * 60))}m`;
  if (h < 24) return `${Math.floor(h)}h`;
  const d = Math.floor(h / 24);
  return d < 60 ? `${d}d` : `${Math.floor(d / 30)}mo`;
}

function distKey(r) {
  if (r.miles != null) return r.miles;
  if (r.band_hi != null) return ((r.band_lo || 0) + r.band_hi) / 2;
  return Infinity;
}
function distLabel(r) {
  if (r.miles != null) return { text: `${r.miles < 10 ? r.miles.toFixed(1) : Math.round(r.miles)} mi`, approx: false };
  const f = (x) => (x < 10 ? x.toFixed(1) : Math.round(x));
  if (r.band_hi != null) return { text: r.band_lo ? `${f(r.band_lo)}–${f(r.band_hi)} mi` : `< ${f(r.band_hi)} mi`, approx: true };
  return { text: "?", approx: true };
}
// Delivery types: IN_PERSON, DOOR_PICKUP, PUBLIC_MEETUP, SHIPPING_ONSITE, SHIPPING_OFFSITE.
const ships = (r) => (r.delivery || []).some((d) => d.startsWith("SHIPPING"));
const shipOnly = (r) => (r.delivery || []).length > 0 && r.delivery.every((d) => d.startsWith("SHIPPING"));
const isHousing = (r) => HOUSING_CATEGORIES.has(r.category_id) || HOUSING_BROWSE.has(r.browse_cat) || HOUSING_TITLE.test(r.title || "");

// Every query word, minus a plural "s", is in the title, ignoring spaces ("book shelf").
const norm = (s) => String(s || "").toLowerCase().replace(/[^a-z0-9]/g, "");
function textMatch(title, q) {
  const hay = norm(title);
  const words = q.toLowerCase().split(/\s+/).filter((w) => w.length > 1);
  return words.length > 0 && words.every((w) => forms(norm(w)).some((f) => hay.includes(f)));
}
// The word and its singular guesses: desks -> desk, boxes -> box, shelves -> shelf.
function forms(w) {
  const out = [w];
  if (w.length > 3 && w.endsWith("ves")) out.push(w.slice(0, -3) + "f");
  if (w.length > 3 && w.endsWith("es")) out.push(w.slice(0, -2));
  if (w.length > 2 && w.endsWith("s")) out.push(w.slice(0, -1));
  return out;
}

// ------------------------------------------------------------------ filter + sort

function visible() {
  const now = Date.now() / 1000;
  const q = state.q.trim();
  const out = [];
  for (const r of all.values()) {
    if (r.sold || r.gone || isHousing(r)) continue;
    if (q) {
      const hit = jobIds.has(r.id);
      if (!hit && !textMatch(r.title, q)) continue;
      if (state.exact && !textMatch(r.title, q)) continue;
    }
    // Distance must be known: a pin, or a ring band (pickup listings only; Facebook returns
    // shippable listings from any distance). A shippable listing waits for its pin.
    if (r.miles != null ? r.miles > state.max_mi : r.band_hi == null || (r.band_lo || 0) >= state.max_mi) continue;
    if (state.local_only && shipOnly(r)) continue;
    if (state.hide_pending && r.pending) continue;
    if (state.hide_dealers && r.seller_volume >= DEALER_MIN) continue;
    if (state.hide_relists && r.relist_count > 1) continue;
    if (state.drops_only && !(r.drop > 0)) continue;
    if (state.min !== "" && r.price != null && r.price < +state.min) continue;
    if (state.max !== "" && r.price != null && r.price > +state.max) continue;
    if (state.days && r.created && now - r.created > state.days * 86400) continue;
    const cond = CONDITION[r.condition];
    if (state.condition.length && cond && !state.condition.includes(cond)) continue;
    if (state.categories.length && r.browse_cat && !state.categories.includes(r.browse_cat)) continue;
    out.push(r);
  }
  const order = q ? new Map([...jobIds].map((id, i) => [id, i])) : new Map();
  const by = {
    near: (a, b) => distKey(a) - distKey(b) || (b.created || 0) - (a.created || 0),
    new: (a, b) => (b.created || 0) - (a.created || 0),
    low: (a, b) => (a.price ?? 1e12) - (b.price ?? 1e12),
    high: (a, b) => (b.price ?? -1) - (a.price ?? -1),
    drop: (a, b) => (b.drop || 0) - (a.drop || 0) || distKey(a) - distKey(b),
    fb: (a, b) => (order.get(a.id) ?? 1e9) - (order.get(b.id) ?? 1e9) || (b.created || 0) - (a.created || 0),
  }[state.sort];
  out.sort(by);
  // One card per relisted item: the first in sort order stands for the group.
  const seen = new Set();
  return out.filter((r) => {
    const k = r.relist_key || r.id;
    if (seen.has(k)) return false;
    seen.add(k);
    return true;
  });
}

// ------------------------------------------------------------------ cards

function tagsHTML(r) {
  const tags = [];
  if (r.drop > 0) tags.push(`<span class="tag drop">↓ ${money(r.drop)}</span>`);
  if (r.relist_count > 1) tags.push(`<span class="tag relist" title="Listed ${r.relist_count} times by this seller, first ${ago(r.relist_first)} ago">Relisted</span>`);
  if (r.photo_sellers > 1) tags.push(`<span class="tag warn" title="The same photo is in listings by ${r.photo_sellers} sellers">Shared photo</span>`);
  if (r.pending) tags.push(`<span class="tag pend">Pending</span>`);
  if (r.seller_volume >= DEALER_MIN) tags.push(`<span class="tag" title="${r.seller_volume} listings in 30 days">Dealer</span>`);
  return tags.join("");
}

function cardHTML(r) {
  const d = distLabel(r);
  const where = r.location_text || [r.city, r.state].filter(Boolean).join(", ");
  const age = r.relist_count > 1 && r.relist_first && r.relist_first < r.created - 86400
    ? `${ago(r.created)} · first ${ago(r.relist_first)} ago` : ago(r.created);
  return `<div class="ph">${r.photo ? `<img loading="lazy" src="${esc(r.photo)}" alt="">` : ""}
      <span class="dist ${d.approx ? "approx" : ""}">${esc(d.text)}</span><div class="tags">${tagsHTML(r)}</div></div>
    <div class="price">${esc(priceText(r))}${r.was ? `<span class="was">${esc(r.was)}</span>` : ""}</div>
    <div class="title">${esc(r.title)}</div>
    <div class="meta">${esc(where)} · ${esc(age)}</div>`;
}

let rowsNow = [];
function render() {
  rowsNow = visible();
  const rows = rowsNow.slice(0, shown);
  const grid = $("#grid");
  const keep = new Set(rows.map((r) => r.id));
  for (const [id, el] of cards) if (!keep.has(id)) { el.remove(); cards.delete(id); }
  rows.forEach((r, i) => {
    const sig = [r.photo, r.price, r.miles, r.band_hi, r.band_lo, r.drop, r.pending, r.seller_volume,
      r.location_text, r.relist_count, r.photo_sellers].join("|");
    let el = cards.get(r.id);
    if (!el) {
      el = document.createElement("article");
      el.className = "card"; el.tabIndex = 0; el.dataset.id = r.id;
      el.addEventListener("click", () => openDetail(el.dataset.id));
      el.addEventListener("keydown", (e) => { if (e.key === "Enter") openDetail(el.dataset.id); });
      el.addEventListener("mouseenter", () => highlightPin(el.dataset.id, true));
      el.addEventListener("mouseleave", () => highlightPin(el.dataset.id, false));
      cards.set(r.id, el);
    }
    if (el.dataset.sig !== sig) {
      el.innerHTML = cardHTML(r);
      el.dataset.sig = sig;
      el.querySelector("img")?.addEventListener("error", () => api("/api/pins", { ids: [r.id] }).catch(() => {}), { once: true });
    }
    if (grid.children[i] !== el) grid.insertBefore(el, grid.children[i] || null);
  });
  const more = $("#more");
  more.hidden = rowsNow.length <= shown;
  more.textContent = `Showing ${shown} of ${rowsNow.length.toLocaleString()}. Scroll for more.`;
  const empty = $("#empty");
  empty.hidden = rowsNow.length > 0;
  if (!rowsNow.length) {
    empty.textContent = !all.size ? "Building the index. Listings show here as they arrive."
      : job && job.status === "searching" ? "Searching Facebook…" : "Nothing matches these filters.";
  }
  renderStatus();
  renderPins();
  requestPinsSoon();
}

let sweepInfo = null, pendingPins = 0, locatorError = null;
function renderStatus() {
  const parts = [`${rowsNow.length.toLocaleString()} listings within ${state.max_mi} mi`];
  if (state.q) {
    if (job?.status === "searching") parts.push(`asking Facebook for “${state.q}”, ring ${Math.min(job.rings_done + 1, job.rings.length)} of ${job.rings.length}`);
    else if (job) parts.push(`${jobIds.size} from Facebook's search`);
  }
  const sw = sweepInfo || {};
  if (sw.running) parts.push(`indexing ${sw.category || ""} (${sw.done + 1} of ${sw.total}), ${sw.new} new`);
  else if (sw.finished) parts.push(`index checked ${ago(sw.finished)} ago`);
  if (pendingPins) parts.push(`${pendingPins} pins loading`);
  if (state.max_mi > (cfg?.index_mi || 25)) parts.push(`index covers ${cfg.index_mi} mi; search terms reach farther`);
  $("#statusText").textContent = parts.join(" · ");
  const bar = $("#bar");
  const busy = sw.running || job?.status === "searching";
  bar.hidden = !busy;
  if (sw.running) bar.firstElementChild.style.width = `${Math.round((sw.done / sw.total) * 100)}%`;
  else if (job?.status === "searching") bar.firstElementChild.style.width = `${Math.round((job.rings_done / job.rings.length) * 100)}%`;
  $("#statusWarn").textContent = [sw.error, ...(job?.warnings || []), locatorError].filter(Boolean).join(" ").slice(0, 240);
  $("#refreshBtn").disabled = !!sw.running;
}

// Pins load only for cards near the screen, nearest first, so the account sees few item pages.
let pinTimer = null;
function requestPinsSoon() {
  clearTimeout(pinTimer);
  pinTimer = setTimeout(() => {
    const ids = [];
    const limit = innerHeight * 2;
    for (const el of $("#grid").children) {
      const top = el.getBoundingClientRect().top;
      if (top > limit) break;
      if (top < -innerHeight) continue;
      const r = all.get(el.dataset.id);
      if (r && !r.enriched_at) ids.push(r.id);
    }
    if (ids.length) api("/api/pins", { ids: ids.slice(0, 40) }).catch(() => {});
  }, 1200);
}
addEventListener("scroll", () => {
  requestPinsSoon();
  if (innerHeight + scrollY > document.body.scrollHeight - 1200 && shown < rowsNow.length) { shown += PAGE; render(); }
}, { passive: true });

// ------------------------------------------------------------------ index sync + text search

async function sync() {
  clearTimeout(syncTimer);
  try {
    const d = await api(`/api/index?since=${cursor}`);
    for (const r of d.rows) {
      if (r.gone || r.sold) all.delete(r.id); else all.set(r.id, r);
    }
    cursor = d.now - 2;
    sweepInfo = d.sweep; pendingPins = d.pending; locatorError = d.locator_error;
    if (d.rows.length || !syncTimer) render(); else renderStatus();
    syncTimer = setTimeout(sync, sweepInfo?.running || pendingPins ? 4000 : 30000);
  } catch (e) {
    $("#statusWarn").textContent = e.message;
    syncTimer = setTimeout(sync, 10000);
  }
}

async function search() {
  clearTimeout(jobTimer);
  jobIds = new Set(); job = null;
  shown = PAGE;
  if (!state.q.trim()) { render(); return; }
  render();
  const { job: id } = await api("/api/search", {
    q: state.q, max_mi: state.max_mi, min: state.min, max: state.max, days: state.days,
    condition: state.condition, local_only: state.local_only,
  });
  pollJob(id);
}

async function pollJob(id) {
  try {
    job = await api(`/api/job/${id}`);
    jobIds = new Set(job.ids);
    await sync();   // the rows Facebook returned are in the index now
    if (job.status === "searching") jobTimer = setTimeout(() => pollJob(id), 1500);
  } catch (e) { $("#statusWarn").textContent = e.message; }
}

$("#refreshBtn").addEventListener("click", async () => {
  const d = await api("/api/sweep", { force: true });
  sweepInfo = d.sweep;
  if (!d.started) $("#statusWarn").textContent = "An index sweep is already running (here or in the watcher).";
  sync();
});

// ------------------------------------------------------------------ state <-> URL + chips

function saveHash() {
  const p = new URLSearchParams();
  for (const [k, v] of Object.entries(state)) {
    if (JSON.stringify(v) !== JSON.stringify(DEFAULTS[k])) p.set(k, Array.isArray(v) ? v.join(",") : v);
  }
  history.replaceState(null, "", "#" + p.toString());
}
function loadHash() {
  const p = new URLSearchParams(location.hash.slice(1));
  for (const k of Object.keys(state)) {
    if (!p.has(k)) continue;
    const v = p.get(k);
    if (typeof DEFAULTS[k] === "boolean") state[k] = v === "true";
    else if (Array.isArray(DEFAULTS[k])) state[k] = v ? v.split(",") : [];
    else if (typeof DEFAULTS[k] === "number") state[k] = +v;
    else state[k] = v;
  }
}

function syncControls() {
  $("#q").value = state.q;
  $("#distLabel").textContent = `${state.max_mi} mi`;
  $("#distVal").textContent = state.max_mi;
  $("#distRange").value = state.max_mi;
  $("#distHint").textContent = cfg ? `The index covers ${cfg.index_mi} mi from home. Past that, only search terms find listings.` : "";
  $("#pmin").value = state.min; $("#pmax").value = state.max;
  $("#priceLabel").textContent = state.min || state.max
    ? `${state.min ? money(+state.min) : "$0"}–${state.max ? money(+state.max) : "any"}` : "Any price";
  $("#priceChip").classList.toggle("on", !!(state.min || state.max));
  $("#daysLabel").textContent = { "": "Any time", 1: "24 hours", 7: "7 days", 30: "30 days" }[state.days] ?? `${state.days} days`;
  $("#daysChip").classList.toggle("on", !!state.days);
  const names = { new: "New", used_like_new: "Like new", used_good: "Good", used_fair: "Fair" };
  $("#condLabel").textContent = state.condition.length ? state.condition.map((c) => names[c]).join(", ") : "Any condition";
  $("#condChip").classList.toggle("on", state.condition.length > 0);
  document.querySelectorAll("#condPop input").forEach((cb) => { cb.checked = state.condition.includes(cb.value); });
  const catNames = Object.fromEntries(cfg?.categories || []);
  $("#catLabel").textContent = !state.categories.length ? "All categories"
    : state.categories.length === 1 ? catNames[state.categories[0]] || state.categories[0] : `${state.categories.length} categories`;
  $("#catChip").classList.toggle("on", state.categories.length > 0);
  document.querySelectorAll("#catList input").forEach((cb) => { cb.checked = !state.categories.length || state.categories.includes(cb.value); });
  for (const [id, key] of [["localChip", "local_only"], ["dealerChip", "hide_dealers"], ["pendingChip", "hide_pending"],
    ["relistChip", "hide_relists"], ["exactChip", "exact"], ["dropChip", "drops_only"]]) $("#" + id).classList.toggle("on", state[key]);
  $("#sort").value = state.sort;
  saveHash();
}

// Filters apply to the index here. A search term, or a distance past the index, also asks Facebook.
function changed({ ask = false } = {}) {
  syncControls();
  shown = PAGE;
  if (ask) search(); else render();
  fitMap();
}

// ------------------------------------------------------------------ popovers + controls

function placePopover(pop, anchor) {
  const r = anchor.getBoundingClientRect();
  const w = Math.max(pop.offsetWidth, 280);
  pop.style.left = `${Math.max(8, Math.min(r.left, innerWidth - w - 8))}px`;
  pop.style.top = `${r.bottom + 8}px`;
}
document.querySelectorAll("[popovertarget]").forEach((btn) => {
  const pop = document.getElementById(btn.getAttribute("popovertarget"));
  pop.addEventListener("toggle", (e) => { if (e.newState === "open") placePopover(pop, btn); });
});

let distTimer = null;
function setDistance(mi) {
  const before = state.max_mi;
  state.max_mi = mi;
  syncControls();
  clearTimeout(distTimer);
  distTimer = setTimeout(() => changed({ ask: !!state.q && mi > before && mi > (job?.params?.max_mi || 0) }), 350);
}
$("#distRange").addEventListener("input", (e) => setDistance(+e.target.value));
document.querySelectorAll("#distPop [data-mi]").forEach((b) => b.addEventListener("click", () => setDistance(+b.dataset.mi)));

let priceTimer = null;
const priceInput = () => {
  state.min = $("#pmin").value; state.max = $("#pmax").value;
  clearTimeout(priceTimer);
  priceTimer = setTimeout(() => changed(), 300);
};
$("#pmin").addEventListener("input", priceInput);
$("#pmax").addEventListener("input", priceInput);
document.querySelectorAll("#pricePop [data-max]").forEach((b) => b.addEventListener("click", () => {
  state.min = ""; state.max = b.dataset.max; changed(); $("#pricePop").hidePopover();
}));
document.querySelectorAll("#daysPop [data-days]").forEach((b) => b.addEventListener("click", () => {
  state.days = b.dataset.days; changed(); $("#daysPop").hidePopover();
}));
document.querySelectorAll("#condPop input").forEach((cb) => cb.addEventListener("change", () => {
  state.condition = [...document.querySelectorAll("#condPop input:checked")].map((x) => x.value);
  changed();
}));
function buildCategories() {
  $("#catList").innerHTML = cfg.categories.map(([slug, label]) =>
    `<label class="check"><input type="checkbox" value="${esc(slug)}"> ${esc(label)}</label>`).join("");
  $("#catList").querySelectorAll("input").forEach((cb) => cb.addEventListener("change", () => {
    const on = [...$("#catList").querySelectorAll("input:checked")].map((x) => x.value);
    state.categories = on.length === cfg.categories.length ? [] : on;
    changed();
  }));
}
$("#catAll").addEventListener("click", () => { state.categories = []; changed(); });
$("#catNone").addEventListener("click", () => { state.categories = ["none"]; changed(); });

for (const [id, key] of [["dealerChip", "hide_dealers"], ["pendingChip", "hide_pending"], ["relistChip", "hide_relists"],
  ["exactChip", "exact"], ["dropChip", "drops_only"], ["localChip", "local_only"]]) {
  $("#" + id).addEventListener("click", () => { state[key] = !state[key]; changed(); });
}
$("#sort").addEventListener("change", (e) => { state.sort = e.target.value; changed(); });
let typeTimer = null;
$("#q").addEventListener("input", () => {
  // Typing filters the index at once; Enter also asks Facebook.
  clearTimeout(typeTimer);
  typeTimer = setTimeout(() => { state.q = $("#q").value.trim(); jobIds = new Set(); job = null; changed(); }, 200);
});
$("#searchForm").addEventListener("submit", (e) => {
  e.preventDefault();
  state.q = $("#q").value.trim();
  $("#q").blur();
  changed({ ask: true });
});

// ------------------------------------------------------------------ theme

const themeModes = ["auto", "light", "dark"];
const themeIcon = { auto: "contrast", light: "light_mode", dark: "dark_mode" };
const darkQuery = matchMedia("(prefers-color-scheme: dark)");
let themeMode = localStorage.getItem("curbside-theme") || "auto";
function applyTheme() {
  const dark = themeMode === "dark" || (themeMode === "auto" && darkQuery.matches);
  const was = document.body.classList.contains("dark");
  document.body.classList.toggle("dark", dark);
  document.body.classList.toggle("light", !dark);
  $("#themeBtn i").textContent = themeIcon[themeMode];
  $("#themeBtn").title = `Theme: ${themeMode === "auto" ? "automatic" : themeMode} (click to change)`;
  if (map && was !== dark) { map.remove(); map = null; if (document.body.classList.contains("map-open")) openMap(); }
}
$("#themeBtn").addEventListener("click", () => {
  themeMode = themeModes[(themeModes.indexOf(themeMode) + 1) % 3];
  localStorage.setItem("curbside-theme", themeMode);
  applyTheme();
});
darkQuery.addEventListener("change", applyTheme);

// ------------------------------------------------------------------ saved searches + hidden

async function loadSaved() {
  const list = await api("/api/saved");
  $("#savedList").innerHTML = list.length ? list.map((s, i) =>
    `<li style="display:flex;align-items:center;gap:4px"><button class="fchip" data-i="${i}" style="flex:1;justify-content:flex-start">${esc(s.name)}</button>
     <button class="iconbtn bell ${s.alert ? "on" : ""}" data-bell="${i}" title="${s.alert ? "Discord alerts on" : "Discord alerts off"}"><i>${s.alert ? "notifications_active" : "notifications_off"}</i></button>
     <button class="iconbtn" data-del="${i}" title="Delete"><i>delete</i></button></li>`).join("")
    : `<li style="color:var(--on-surface-variant);font-size:.875rem;padding-bottom:8px">None yet.</li>`;
  $("#savedList").querySelectorAll("[data-i]").forEach((b) => b.addEventListener("click", () => {
    Object.assign(state, structuredClone(DEFAULTS), list[+b.dataset.i].params);
    $("#savedPop").hidePopover();
    changed({ ask: !!state.q });
  }));
  $("#savedList").querySelectorAll("[data-bell]").forEach((b) => b.addEventListener("click", async () => {
    const s = list[+b.dataset.bell];
    await api("/api/saved/alert", { name: s.name, on: !s.alert }); loadSaved();
  }));
  $("#savedList").querySelectorAll("[data-del]").forEach((b) => b.addEventListener("click", async () => {
    await api("/api/saved/delete", { name: list[+b.dataset.del].name }); loadSaved();
  }));
}
$("#savedPop").addEventListener("toggle", (e) => { if (e.newState === "open") loadSaved(); });
$("#hiddenBtn2").addEventListener("click", () => { $("#savedPop").hidePopover(); $("#hiddenBtn").click(); });
$("#saveBtn").addEventListener("click", async () => {
  const bits = [state.q || "Everything", `${state.max_mi} mi`];
  if (state.max) bits.push(`≤ ${money(+state.max)}`);
  if (state.categories.length) bits.push(state.categories.length === 1 ? state.categories[0] : `${state.categories.length} categories`);
  await api("/api/saved", { name: bits.join(" · "), params: { ...state }, alert: true });
  loadSaved();
});

async function hide(kind, key, label) {
  await api("/api/hide", { kind, key, label });
  $("#detail").close();
  for (const [id, r] of all) if (kind === "listing" ? id === key : r.seller_id === key) all.delete(id);
  render();
}
$("#hiddenBtn").addEventListener("click", async () => {
  const list = await api("/api/hidden");
  const dlg = $("#hiddenDlg");
  dlg.innerHTML = `<h6 style="margin-top:0">Hidden</h6>${list.length ? `<ul style="list-style:none;padding:0">${list.map((h) =>
    `<li><span>${h.kind === "seller" ? "Seller: " : ""}${esc(h.label || h.key)}</span><button class="btn" data-k="${esc(h.kind)}" data-key="${esc(h.key)}">Unhide</button></li>`).join("")}</ul>`
    : `<p>Nothing hidden.</p>`}<div style="text-align:right"><button class="btn fill" id="hiddenClose">Done</button></div>`;
  let changedAny = false;
  dlg.querySelectorAll("[data-key]").forEach((b) => b.addEventListener("click", async () => {
    await api("/api/unhide", { kind: b.dataset.k, key: b.dataset.key }); b.closest("li").remove(); changedAny = true;
  }));
  $("#hiddenClose").addEventListener("click", () => { dlg.close(); if (changedAny) { cursor = 0; sync(); } });
  dlg.showModal();
});

// ------------------------------------------------------------------ detail

async function openDetail(id) {
  const dlg = $("#detail");
  let r = all.get(id);
  if (!r) return;
  dlg.innerHTML = detailHTML(r, true);
  wireDetail(r);
  if (!dlg.open) dlg.showModal();
  try {
    r = { ...r, ...(await api(`/api/item/${id}`)) };
    const { description, photos, attributes, ...light } = r;
    all.set(id, light);
    if (dlg.open) { dlg.innerHTML = detailHTML(r, false); wireDetail(r); render(); }
    void description; void photos; void attributes;
  } catch (e) { const l = dlg.querySelector(".loading"); if (l) l.textContent = e.message; }
}

function detailHTML(r, loading) {
  const d = distLabel(r);
  const photos = r.photos?.length ? r.photos : [r.photo].filter(Boolean);
  const facts = [d.text + (d.approx ? " (range)" : " from home"), ago(r.created) + " ago", r.condition,
    ships(r) ? "Ships" : null, r.pending ? "Pending" : null].filter(Boolean);
  const attrs = Object.entries(r.attributes || {}).map(([k, v]) => `${esc(k)}: ${esc(v)}`).join(" · ");
  const joined = r.seller_joined ? `joined ${r.seller_joined.slice(0, 4)}` : "";
  const rating = r.seller_rating ? `★ ${(+r.seller_rating).toFixed(1)} (${r.seller_rating_count})` : "no ratings";
  const notes = [];
  if (r.relist_count > 1) notes.push(`<div class="note">This seller listed this item ${r.relist_count} times. The first listing is from ${ago(r.relist_first)} ago, so the item has not sold in that time.</div>`);
  if (r.photo_sellers > 1) notes.push(`<div class="note warn">The same photo is in listings by ${r.photo_sellers} sellers. It can be a stock photo, or a copied photo from a scam.</div>`);
  return `<button class="iconbtn x" id="dClose" title="Close"><i>close</i></button>
    <div class="gallery">${photos.map((p) => `<img src="${esc(p)}" alt="">`).join("")}</div>
    ${photos.length > 1 ? `<span class="tag count">${photos.length} photos, swipe</span>` : ""}
    <div class="body">
      <div class="price">${esc(priceText(r))}${r.drop > 0 ? ` <span class="tag drop">↓ ${money(r.drop)}</span>` : ""}</div>
      <h2>${esc(r.title)}</h2>
      <div style="color:var(--on-surface-variant);font-size:.9rem">${esc(r.location_text || [r.city, r.state].filter(Boolean).join(", "))}</div>
      <div class="facts">${facts.map((f) => `<span class="tag">${esc(f)}</span>`).join("")}</div>
      ${notes.join("")}
      ${loading ? `<div class="loading" style="color:var(--on-surface-variant)">Loading the full listing…</div>` : ""}
      ${attrs ? `<div style="font-size:.85rem;color:var(--on-surface-variant);margin:8px 0">${attrs}</div>` : ""}
      <div class="desc">${esc(r.description || "")}</div>
      <div class="seller"><b>${esc(r.seller || "Seller")}</b> · ${esc(rating)}${joined ? " · " + esc(joined) : ""}
        ${r.seller_volume > 1 ? `<br><span style="color:var(--on-surface-variant)">${r.seller_volume} listings seen in the last 30 days</span>` : ""}</div>
      <div class="actions">
        <a class="btn fill" href="${esc(r.url)}" target="_blank" rel="noopener noreferrer"><i>open_in_new</i>Open on Facebook</a>
        <button class="btn" id="dHide"><i>visibility_off</i>Hide listing</button>
        ${r.seller_id ? `<button class="btn" id="dHideSeller"><i>person_off</i>Hide seller</button>` : ""}
        ${r.lat != null ? `<button class="btn" id="dMap"><i>map</i>On map</button>` : ""}
      </div>
    </div>`;
}

function wireDetail(r) {
  $("#dClose").addEventListener("click", () => $("#detail").close());
  $("#dHide").addEventListener("click", () => hide("listing", r.id, r.title));
  $("#dHideSeller")?.addEventListener("click", () => hide("seller", r.seller_id, r.seller));
  $("#dMap")?.addEventListener("click", () => {
    $("#detail").close(); openMap();
    map.flyTo({ center: [r.lon, r.lat], zoom: 14 }); highlightPin(r.id, true);
  });
}
$("#detail").addEventListener("click", (e) => { if (e.target.id === "detail") e.target.close(); });

// ------------------------------------------------------------------ map drawer

function circle(lat, lon, miles, n = 96) {
  const km = miles * 1.609344, pts = [];
  for (let i = 0; i <= n; i++) {
    const a = (i / n) * 2 * Math.PI;
    pts.push([lon + (km / (111.32 * Math.cos((lat * Math.PI) / 180))) * Math.cos(a), lat + (km / 110.574) * Math.sin(a)]);
  }
  return { type: "Feature", geometry: { type: "Polygon", coordinates: [pts] } };
}

function openMap() {
  document.body.classList.add("map-open");
  $("#mapBtn").classList.add("on");
  document.documentElement.style.setProperty("--top-h", `${$("#top").offsetHeight}px`);
  const home = cfg.home;
  if (!map) {
    const dark = document.body.classList.contains("dark");
    map = new maplibregl.Map({
      container: "map",
      style: `https://tiles.openfreemap.org/styles/${dark ? "dark" : "positron"}`,
      center: [home[1], home[0]], zoom: 10, attributionControl: { compact: true },
    });
    map.addControl(new maplibregl.NavigationControl({ showCompass: false }), "top-left");
    pinSig = "";
    const h = document.createElement("div"); h.className = "homepin"; h.title = "Home";
    new maplibregl.Marker({ element: h }).setLngLat([home[1], home[0]]).addTo(map);
    map.on("load", () => {
      const primary = getComputedStyle(document.body).getPropertyValue("--primary").trim();
      map.addSource("radius", { type: "geojson", data: circle(home[0], home[1], state.max_mi) });
      map.addLayer({ id: "radius-fill", type: "fill", source: "radius", paint: { "fill-color": primary, "fill-opacity": 0.06 } });
      map.addLayer({ id: "radius-line", type: "line", source: "radius", paint: { "line-color": primary, "line-width": 1.5, "line-dasharray": [2, 2] } });
      addPinLayers();
      render(); fitMap();
    });
  } else { map.resize(); pinSig = ""; render(); fitMap(); }
}
function closeMap() { document.body.classList.remove("map-open"); $("#mapBtn").classList.remove("on"); }
$("#mapBtn").addEventListener("click", () => document.body.classList.contains("map-open") ? closeMap() : openMap());
$("#mapClose").addEventListener("click", closeMap);

function fitMap() {
  if (!map || !map.isStyleLoaded()) return;
  const home = cfg.home;
  map.getSource("radius")?.setData(circle(home[0], home[1], state.max_mi));
  const km = state.max_mi * 1.609344, dLat = km / 110.574, dLon = km / (111.32 * Math.cos((home[0] * Math.PI) / 180));
  map.fitBounds([[home[1] - dLon, home[0] - dLat], [home[1] + dLon, home[0] + dLat]], { padding: 24, duration: 400 });
}

// Pins are one clustered GeoJSON source: Facebook snaps many listings to the same
// neighborhood point, so DOM markers pile up. Clusters show a count; points show a price.
const fid = (id) => +id % 2147483647;
function geojson(rows) {
  return { type: "FeatureCollection", features: rows.filter((r) => r.lat != null).map((r) => ({
    type: "Feature", id: fid(r.id), geometry: { type: "Point", coordinates: [r.lon, r.lat] },
    properties: { id: r.id, label: priceText(r) },
  })) };
}

function addPinLayers() {
  map.addSource("pins", { type: "geojson", data: geojson(rowsNow), cluster: true, clusterRadius: 36, clusterMaxZoom: 15 });
  const ink = getComputedStyle(document.body);
  const primary = ink.getPropertyValue("--primary").trim(), onPrimary = ink.getPropertyValue("--on-primary").trim();
  const surface = ink.getPropertyValue("--surface").trim(), onSurface = ink.getPropertyValue("--on-surface").trim();
  map.addLayer({ id: "clusters", type: "circle", source: "pins", filter: ["has", "point_count"],
    paint: { "circle-color": primary, "circle-radius": ["step", ["get", "point_count"], 14, 10, 18, 30, 24], "circle-stroke-width": 2, "circle-stroke-color": surface } });
  map.addLayer({ id: "cluster-count", type: "symbol", source: "pins", filter: ["has", "point_count"],
    layout: { "text-field": ["get", "point_count_abbreviated"], "text-font": ["Noto Sans Bold"], "text-size": 12, "text-allow-overlap": true },
    paint: { "text-color": onPrimary } });
  map.addLayer({ id: "points", type: "circle", source: "pins", filter: ["!", ["has", "point_count"]],
    paint: { "circle-color": ["case", ["boolean", ["feature-state", "hl"], false], primary, onSurface],
             "circle-radius": ["case", ["boolean", ["feature-state", "hl"], false], 8, 5], "circle-stroke-width": 2, "circle-stroke-color": surface } });
  map.addLayer({ id: "point-label", type: "symbol", source: "pins", filter: ["!", ["has", "point_count"]],
    layout: { "text-field": ["get", "label"], "text-font": ["Noto Sans Bold"], "text-size": 12, "text-offset": [0, -1.3], "text-anchor": "bottom" },
    paint: { "text-color": onSurface, "text-halo-color": surface, "text-halo-width": 2 } });

  map.on("click", "clusters", async (e) => {
    const f = e.features[0];
    const src = map.getSource("pins");
    const zoom = await src.getClusterExpansionZoom(f.properties.cluster_id);
    if (zoom <= 16) return map.easeTo({ center: f.geometry.coordinates, zoom });
    // Listings at one shared point never split: mark them in the grid instead.
    const leaves = await src.getClusterLeaves(f.properties.cluster_id, 100, 0);
    cards.forEach((el) => el.classList.remove("hl"));
    leaves.forEach((l, i) => { const el = cards.get(l.properties.id); el?.classList.add("hl"); if (!i) el?.scrollIntoView({ block: "center", behavior: "smooth" }); });
  });
  map.on("click", "points", (e) => openDetail(e.features[0].properties.id));
  for (const layer of ["clusters", "points"]) {
    map.on("mouseenter", layer, () => { map.getCanvas().style.cursor = "pointer"; });
    map.on("mouseleave", layer, () => { map.getCanvas().style.cursor = ""; });
  }
  map.on("mousemove", "points", (e) => { const id = e.features[0].properties.id; if (id !== hoverId) { highlightPin(hoverId, false); highlightPin(id, true); } });
  map.on("mouseleave", "points", () => highlightPin(hoverId, false));
}

let hoverId = null;
let pinSig = "";
function renderPins() {
  if (!map || !document.body.classList.contains("map-open") || !map.getSource("pins")) return;
  const located = rowsNow.filter((r) => r.lat != null);
  const sig = located.map((r) => r.id).join(",");
  if (sig === pinSig) return;
  pinSig = sig;
  map.getSource("pins").setData(geojson(located));
}

function highlightPin(id, on) {
  if (id == null) return;
  hoverId = on ? id : null;
  cards.get(id)?.classList.toggle("hl", on);
  if (map?.getSource("pins")) map.setFeatureState({ source: "pins", id: fid(id) }, { hl: on });
}

// ------------------------------------------------------------------ boot

(async () => {
  applyTheme();
  cfg = await api("/api/config");
  buildCategories();
  loadHash();
  syncControls();
  await sync();
  if (state.q) search();
  if (cfg.sweep_due && !cfg.sweep?.running) api("/api/sweep", {}).then((d) => { sweepInfo = d.sweep; renderStatus(); }).catch(() => {});
})();
