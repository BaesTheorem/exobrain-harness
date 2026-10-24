// Curbside: client for the local Marketplace index. The server crawls; this file filters,
// sorts and draws. Distance is exact once a pin is known, else the ring band from the crawl.
import * as maplibregl from "./vendor/maplibre/maplibre-gl.mjs";

const $ = (s) => document.querySelector(s);
const DEALER_MIN = 4;
// Facebook mixes property rentals into product searches. Category measured 2026-10-24.
const HOUSING_CATEGORIES = new Set(["1468271819871448"]);
const HOUSING_TITLE = /^\d+ beds? \d+ baths? /i;
const isHousing = (r) => HOUSING_CATEGORIES.has(r.category_id) || HOUSING_TITLE.test(r.title || "");

const state = {
  q: "", max_mi: 10, min: "", max: "", days: "", condition: [],
  local_only: true, exact: false, hide_dealers: false, hide_pending: false, drops_only: false, sort: "near",
};
let job = null;          // last /api/job payload
let crawledMi = 0;       // distance the current job covered
let pollTimer = null;
let home = null;
const cards = new Map(); // id -> element
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

function age(r) {
  if (!r.created) return r.listed || "";
  const h = (Date.now() / 1000 - r.created) / 3600;
  if (h < 1) return "now";
  if (h < 24) return `${Math.floor(h)}h`;
  const d = Math.floor(h / 24);
  return d < 60 ? `${d}d` : `${Math.floor(d / 30)}mo`;
}

// Distance for sorting and filtering: exact miles, or the band midpoint.
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
// Facebook stretches a query ("bookshelf" returns TVs). In title: each query word, minus a
// plural "s", appears in the title, ignoring spaces ("book shelf" matches). Descriptions are
// left out on purpose: sellers stuff them with keywords.
function exactMatch(r) {
  const hay = String(r.title || "").toLowerCase().replace(/[^a-z0-9]/g, "");
  return state.q.toLowerCase().split(/\s+/).filter((w) => w.length > 1)
    .every((w) => hay.includes(w.replace(/[^a-z0-9]/g, "").replace(/(?<=..)e?s$/, "")));
}
const shipOnly = (r) => (r.delivery || []).length > 0 && r.delivery.every((d) => d === "SHIPPING");

// ------------------------------------------------------------------ filter + sort

function visible() {
  if (!job) return [];
  const rows = job.rows.filter((r) => {
    if (r.sold || r.gone || isHousing(r)) return false;
    if (r.miles != null ? r.miles > state.max_mi : (r.band_lo || 0) >= state.max_mi) return false;
    if (state.local_only && shipOnly(r)) return false;
    if (state.local_only && r.enriched_at && r.lat == null && (r.delivery || []).includes("SHIPPING")) return false;
    if (state.hide_pending && r.pending) return false;
    if (state.hide_dealers && r.seller_volume >= DEALER_MIN) return false;
    if (state.drops_only && !(r.drop > 0)) return false;
    if (state.exact && !exactMatch(r)) return false;
    if (state.min !== "" && r.price != null && r.price < +state.min) return false;
    if (state.max !== "" && r.price != null && r.price > +state.max) return false;
    if (state.days && r.created && Date.now() / 1000 - r.created > state.days * 86400) return false;
    return true;
  });
  const by = {
    near: (a, b) => distKey(a) - distKey(b) || (b.created || 0) - (a.created || 0),
    new: (a, b) => (b.created || 0) - (a.created || 0),
    low: (a, b) => (a.price ?? 1e12) - (b.price ?? 1e12),
    high: (a, b) => (b.price ?? -1) - (a.price ?? -1),
    drop: (a, b) => (b.drop || 0) - (a.drop || 0) || distKey(a) - distKey(b),
    fb: () => 0,
  }[state.sort];
  return rows.sort(by);
}

// ------------------------------------------------------------------ cards

function cardHTML(r) {
  const d = distLabel(r);
  const tags = [];
  if (r.drop > 0) tags.push(`<span class="tag drop">↓ ${money(r.drop)}</span>`);
  if (r.pending) tags.push(`<span class="tag pend">Pending</span>`);
  if (r.seller_volume >= DEALER_MIN) tags.push(`<span class="tag" title="${r.seller_volume} listings in 30 days">Dealer</span>`);
  const where = r.location_text || [r.city, r.state].filter(Boolean).join(", ");
  return `<div class="ph">${r.photo ? `<img loading="lazy" src="${esc(r.photo)}" alt="">` : ""}
      <span class="dist ${d.approx ? "approx" : ""}">${esc(d.text)}</span><div class="tags">${tags.join("")}</div></div>
    <div class="price">${esc(priceText(r))}${r.was ? `<span class="was">${esc(r.was)}</span>` : ""}</div>
    <div class="title">${esc(r.title)}</div>
    <div class="meta">${esc(where)} · ${esc(age(r))}</div>`;
}

function render() {
  const rows = visible();
  const grid = $("#grid");
  const keep = new Set(rows.map((r) => r.id));
  for (const [id, el] of cards) if (!keep.has(id)) { el.remove(); cards.delete(id); }
  rows.forEach((r, i) => {
    const sig = [r.photo, r.price, r.miles, r.band_hi, r.band_lo, r.drop, r.pending, r.seller_volume, r.location_text].join("|");
    let el = cards.get(r.id);
    if (!el) {
      el = document.createElement("article");
      el.className = "card"; el.tabIndex = 0; el.dataset.id = r.id;
      el.addEventListener("click", () => openDetail(r.id));
      el.addEventListener("keydown", (e) => { if (e.key === "Enter") openDetail(r.id); });
      el.addEventListener("mouseenter", () => highlightPin(r.id, true));
      el.addEventListener("mouseleave", () => highlightPin(r.id, false));
      cards.set(r.id, el);
    }
    if (el.dataset.sig !== sig) { el.innerHTML = cardHTML(r); el.dataset.sig = sig; }
    if (grid.children[i] !== el) grid.insertBefore(el, grid.children[i] || null);
  });
  const empty = $("#empty");
  empty.hidden = rows.length > 0 || !job;
  if (job && !rows.length) empty.textContent = job.status === "searching" ? "Searching…" : "Nothing matches these filters.";
  renderStatus(rows);
  renderPins(rows);
}

function renderStatus(rows) {
  if (!job) return;
  const all = job.rows.length;
  const located = job.rows.filter((r) => r.enriched_at).length;
  const parts = [`${rows.length} shown`, `${all} found within ${crawledMi} mi`];
  if (all) parts.push(`${located} of ${all} pinned`);
  const searching = job.status === "searching";
  if (searching) parts.unshift(`Searching ring ${Math.min(job.rings_done + 1, job.rings.length)} of ${job.rings.length}`);
  else if (located < all && job.pending) parts.push("pinning the rest");
  $("#statusText").textContent = parts.join(" · ");
  const bar = $("#bar");
  const busy = searching || (located < all && job.pending > 0);
  bar.hidden = !busy;
  const frac = searching ? job.rings_done / job.rings.length : all ? located / all : 0;
  bar.firstElementChild.style.width = `${Math.round(frac * 100)}%`;
  $("#statusWarn").textContent = [...(job.warnings || []), job.locator_error].filter(Boolean).join(" ").slice(0, 240);
}

// ------------------------------------------------------------------ search + poll

async function search() {
  if (!state.q) return;
  clearTimeout(pollTimer);
  cards.forEach((el) => el.remove()); cards.clear();
  job = { rows: [], status: "searching", rings: [1], rings_done: 0 };
  crawledMi = state.max_mi;
  render();
  const { job: id } = await api("/api/search", {
    q: state.q, max_mi: state.max_mi, min: state.min, max: state.max, days: state.days,
    condition: state.condition, local_only: state.local_only,
  });
  poll(id);
}

async function poll(id) {
  try {
    job = await api(`/api/job/${id}`);
    crawledMi = job.params.max_mi;
    render();
    const pinned = job.rows.every((r) => r.enriched_at);
    if (job.status === "searching" || (!pinned && job.pending > 0)) {
      pollTimer = setTimeout(() => poll(id), job.status === "searching" ? 1200 : 2500);
    }
  } catch (e) {
    $("#statusWarn").textContent = e.message;
  }
}

// ------------------------------------------------------------------ state <-> URL + chips

function saveHash() {
  const p = new URLSearchParams();
  for (const [k, v] of Object.entries(state)) {
    if (Array.isArray(v) ? v.length : v !== "" && v !== false) p.set(k, Array.isArray(v) ? v.join(",") : v);
  }
  history.replaceState(null, "", "#" + p.toString());
}
function loadHash() {
  const p = new URLSearchParams(location.hash.slice(1));
  for (const k of Object.keys(state)) {
    if (!p.has(k)) continue;
    const v = p.get(k);
    if (typeof state[k] === "boolean") state[k] = v === "true";
    else if (Array.isArray(state[k])) state[k] = v ? v.split(",") : [];
    else if (typeof state[k] === "number") state[k] = +v;
    else state[k] = v;
  }
  if (!p.has("local_only") && p.toString()) state.local_only = false;
}

function syncControls() {
  $("#q").value = state.q;
  $("#distLabel").textContent = `${state.max_mi} mi`;
  $("#distVal").textContent = state.max_mi;
  $("#distRange").value = state.max_mi;
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
  $("#localChip").classList.toggle("on", state.local_only);
  $("#dealerChip").classList.toggle("on", state.hide_dealers);
  $("#pendingChip").classList.toggle("on", state.hide_pending);
  $("#dropChip").classList.toggle("on", state.drops_only);
  $("#exactChip").classList.toggle("on", state.exact);
  $("#sort").value = state.sort;
  saveHash();
}

// Server-side filters change what Facebook returns, so they start a new crawl.
// Client-side filters only redraw. A distance inside the crawled radius only redraws.
function changed({ recrawl = false } = {}) {
  syncControls();
  if (recrawl && state.q) search(); else { render(); fitMap(); }
}

// ------------------------------------------------------------------ popovers

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
  state.max_mi = mi;
  syncControls();
  clearTimeout(distTimer);
  distTimer = setTimeout(() => changed({ recrawl: mi > crawledMi }), 350);
}
$("#distRange").addEventListener("input", (e) => setDistance(+e.target.value));
document.querySelectorAll("#distPop [data-mi]").forEach((b) => b.addEventListener("click", () => setDistance(+b.dataset.mi)));

let priceTimer = null;
const priceInput = () => {
  state.min = $("#pmin").value; state.max = $("#pmax").value;
  clearTimeout(priceTimer);
  priceTimer = setTimeout(() => changed({ recrawl: true }), 700);
};
$("#pmin").addEventListener("input", priceInput);
$("#pmax").addEventListener("input", priceInput);
document.querySelectorAll("#pricePop [data-max]").forEach((b) => b.addEventListener("click", () => {
  state.min = ""; state.max = b.dataset.max; changed({ recrawl: true }); $("#pricePop").hidePopover();
}));
document.querySelectorAll("#daysPop [data-days]").forEach((b) => b.addEventListener("click", () => {
  state.days = b.dataset.days; changed({ recrawl: true }); $("#daysPop").hidePopover();
}));
document.querySelectorAll("#condPop input").forEach((cb) => cb.addEventListener("change", () => {
  state.condition = [...document.querySelectorAll("#condPop input:checked")].map((x) => x.value);
  changed({ recrawl: true });
}));
$("#localChip").addEventListener("click", () => { state.local_only = !state.local_only; changed({ recrawl: true }); });
$("#dealerChip").addEventListener("click", () => { state.hide_dealers = !state.hide_dealers; changed(); });
$("#pendingChip").addEventListener("click", () => { state.hide_pending = !state.hide_pending; changed(); });
$("#exactChip").addEventListener("click", () => { state.exact = !state.exact; changed(); });
$("#dropChip").addEventListener("click", () => { state.drops_only = !state.drops_only; changed(); });
$("#sort").addEventListener("change", (e) => { state.sort = e.target.value; changed(); });
$("#searchForm").addEventListener("submit", (e) => {
  e.preventDefault();
  state.q = $("#q").value.trim();
  $("#q").blur();
  changed({ recrawl: true });
});

// ------------------------------------------------------------------ saved searches + hidden

async function loadSaved() {
  const list = await api("/api/saved");
  $("#savedList").innerHTML = list.length ? list.map((s, i) =>
    `<li style="display:flex;align-items:center;gap:4px"><button class="fchip" data-i="${i}" style="flex:1;justify-content:flex-start">${esc(s.name)}</button>
     <button class="iconbtn" data-del="${esc(s.name)}" title="Delete"><i>delete</i></button></li>`).join("")
    : `<li style="color:var(--on-surface-variant);font-size:.875rem;padding-bottom:8px">None yet.</li>`;
  $("#savedList").querySelectorAll("[data-i]").forEach((b) => b.addEventListener("click", () => {
    Object.assign(state, list[+b.dataset.i].params);
    $("#savedPop").hidePopover();
    changed({ recrawl: true });
  }));
  $("#savedList").querySelectorAll("[data-del]").forEach((b) => b.addEventListener("click", async () => {
    await api("/api/saved/delete", { name: b.dataset.del }); loadSaved();
  }));
}
$("#savedPop").addEventListener("toggle", (e) => { if (e.newState === "open") loadSaved(); });
$("#saveBtn").addEventListener("click", async () => {
  if (!state.q) return;
  const name = `${state.q} · ${state.max_mi} mi${state.max ? ` · ≤ ${money(+state.max)}` : ""}`;
  await api("/api/saved", { name, params: { ...state } });
  loadSaved();
});

async function hide(kind, key, label) {
  await api("/api/hide", { kind, key, label });
  $("#detail").close();
  if (job) job.rows = job.rows.filter((r) => kind === "listing" ? r.id !== key : r.seller_id !== key);
  render();
}
$("#hiddenBtn").addEventListener("click", async () => {
  const list = await api("/api/hidden");
  const dlg = $("#hiddenDlg");
  dlg.innerHTML = `<h6 style="margin-top:0">Hidden</h6>${list.length ? `<ul style="list-style:none;padding:0">${list.map((h) =>
    `<li><span>${h.kind === "seller" ? "Seller: " : ""}${esc(h.label || h.key)}</span><button class="btn" data-k="${esc(h.kind)}" data-key="${esc(h.key)}">Unhide</button></li>`).join("")}</ul>`
    : `<p>Nothing hidden.</p>`}<div style="text-align:right"><button class="btn fill" id="hiddenClose">Done</button></div>`;
  dlg.querySelectorAll("[data-key]").forEach((b) => b.addEventListener("click", async () => {
    await api("/api/unhide", { kind: b.dataset.k, key: b.dataset.key }); b.closest("li").remove();
  }));
  $("#hiddenClose").addEventListener("click", () => { dlg.close(); if (job?.id) poll(job.id); });
  dlg.showModal();
});

// ------------------------------------------------------------------ detail

async function openDetail(id) {
  const dlg = $("#detail");
  let r = job.rows.find((x) => x.id === id);
  dlg.innerHTML = detailHTML(r, !r.enriched_at);
  wireDetail(r);
  if (!dlg.open) dlg.showModal();
  if (!r.enriched_at) {
    try {
      r = Object.assign(r, await api(`/api/item/${id}`));
      if (dlg.open) { dlg.innerHTML = detailHTML(r, false); wireDetail(r); render(); }
    } catch (e) { dlg.querySelector(".loading").textContent = e.message; }
  }
}

function detailHTML(r, loading) {
  const d = distLabel(r);
  const photos = r.photos?.length ? r.photos : [r.photo].filter(Boolean);
  const facts = [d.text + (d.approx ? " (approximate)" : " from home"), age(r) + " ago", r.condition,
    (r.delivery || []).includes("SHIPPING") ? "Ships" : null, r.pending ? "Pending" : null].filter(Boolean);
  const attrs = Object.entries(r.attributes || {}).map(([k, v]) => `${esc(k)}: ${esc(v)}`).join(" · ");
  const joined = r.seller_joined ? `joined ${r.seller_joined.slice(0, 4)}` : "";
  const rating = r.seller_rating ? `★ ${(+r.seller_rating).toFixed(1)} (${r.seller_rating_count})` : "no ratings";
  return `<button class="iconbtn x" id="dClose" title="Close"><i>close</i></button>
    <div class="gallery">${photos.map((p) => `<img src="${esc(p)}" alt="">`).join("")}</div>
    ${photos.length > 1 ? `<span class="tag count">${photos.length} photos, swipe</span>` : ""}
    <div class="body">
      <div class="price">${esc(priceText(r))}${r.drop > 0 ? ` <span class="tag drop">↓ ${money(r.drop)}</span>` : ""}</div>
      <h2>${esc(r.title)}</h2>
      <div style="color:var(--on-surface-variant);font-size:.9rem">${esc(r.location_text || [r.city, r.state].filter(Boolean).join(", "))}</div>
      <div class="facts">${facts.map((f) => `<span class="tag">${esc(f)}</span>`).join("")}</div>
      ${loading ? `<div class="loading" style="color:var(--on-surface-variant)">Loading the full listing…</div>` : ""}
      ${attrs ? `<div style="font-size:.85rem;color:var(--on-surface-variant);margin-bottom:8px">${attrs}</div>` : ""}
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
      map.addSource("radius", { type: "geojson", data: circle(home[0], home[1], state.max_mi) });
      map.addLayer({ id: "radius-fill", type: "fill", source: "radius", paint: { "fill-color": "#006b5f", "fill-opacity": 0.06 } });
      map.addLayer({ id: "radius-line", type: "line", source: "radius", paint: { "line-color": "#006b5f", "line-width": 1.5, "line-dasharray": [2, 2] } });
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
  map.getSource("radius")?.setData(circle(home[0], home[1], state.max_mi));
  const km = state.max_mi * 1.609344, dLat = km / 110.574, dLon = km / (111.32 * Math.cos((home[0] * Math.PI) / 180));
  map.fitBounds([[home[1] - dLon, home[0] - dLat], [home[1] + dLon, home[0] + dLat]], { padding: 24, duration: 400 });
}

// Pins are one clustered GeoJSON source: Facebook snaps many listings to the same
// neighborhood point, so DOM markers pile up. Clusters show a count; points show a price.
function geojson(rows) {
  return { type: "FeatureCollection", features: rows.filter((r) => r.lat != null).map((r) => ({
    type: "Feature", id: +r.id % 2147483647, geometry: { type: "Point", coordinates: [r.lon, r.lat] },
    properties: { id: r.id, label: priceText(r) },
  })) };
}

function addPinLayers() {
  map.addSource("pins", { type: "geojson", data: geojson(visible()), cluster: true, clusterRadius: 36, clusterMaxZoom: 15 });
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
function renderPins(rows) {
  if (!map || !document.body.classList.contains("map-open") || !map.getSource("pins")) return;
  const located = rows.filter((r) => r.lat != null);
  const sig = located.map((r) => r.id).join(",");
  if (sig === pinSig) return;
  pinSig = sig;
  map.getSource("pins").setData(geojson(located));
}

function highlightPin(id, on) {
  if (id == null) return;
  hoverId = on ? id : null;
  cards.get(id)?.classList.toggle("hl", on);
  if (map?.getSource("pins")) map.setFeatureState({ source: "pins", id: +id % 2147483647 }, { hl: on });
}

// ------------------------------------------------------------------ boot

(async () => {
  const dark = matchMedia("(prefers-color-scheme: dark)");
  const theme = () => { document.body.classList.toggle("dark", dark.matches); document.body.classList.toggle("light", !dark.matches); };
  theme(); dark.addEventListener("change", theme);
  const cfg = await api("/api/config");
  home = cfg.home;
  loadHash();
  syncControls();
  if (state.q) search();
  else $("#q").focus();
})();
