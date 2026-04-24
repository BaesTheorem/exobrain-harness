// Solo DM dashboard app.
// Vanilla JS, no build step. All coords are relative to the map image (0..1).

const FANDOM_WIKI_BASE = "https://forgottenrealms.fandom.com/wiki/";

const MODE_MEASURE = "measure";
const MODE_MARKER = "marker";
const MODE_MOVE = "move";
const MODE_PC = "pc";
const MODE_CALIBRATE = "calibrate";

// D&D 5e wizard ritual-tagged spells. Extend as Charles learns more.
const RITUAL_SPELLS = new Set([
  // 1st level
  "Alarm", "Comprehend Languages", "Detect Magic", "Find Familiar", "Identify",
  "Illusory Script", "Tenser's Floating Disk", "Unseen Servant",
  // 2nd level
  "Augury", "Gentle Repose", "Locate Animals or Plants", "Locate Object",
  "Magic Mouth", "Silence", "Skywrite",
  // 3rd level
  "Feign Death", "Leomund's Tiny Hut", "Meld Into Stone", "Phantom Steed",
  "Water Breathing", "Water Walk",
  // 4th level
  "Divination",
  // 5th level
  "Commune", "Commune with Nature", "Contact Other Plane", "Rary's Telepathic Bond",
]);

const state = {
  mode: MODE_MEASURE,
  measurePoints: [],
  calibratePoints: [],
  markers: [],
  pcPos: null,
  calibration: null,
  campaign: null,
  pc: null,
  session: null,
  world: null,
  // Zoom/pan state
  zoom: 1,
  panX: 0,
  panY: 0,
  // Drag state
  dragging: false,
  dragStart: null,   // {x, y, panX0, panY0}
  dragMoved: false,
  // Move-marker state: id of the marker picked up and awaiting placement
  moveSelected: null,
};

const MIN_ZOOM = 1;
const MAX_ZOOM = 16;
const ZOOM_STEP = 1.6;

// --- Helpers ---------------------------------------------------------------

const $ = (sel) => document.querySelector(sel);
const $$ = (sel) => [...document.querySelectorAll(sel)];

function el(tag, attrs = {}, ...children) {
  const isSvg = ["svg", "circle", "line", "text", "g", "title"].includes(tag);
  const e = document.createElementNS(
    isSvg ? "http://www.w3.org/2000/svg" : "http://www.w3.org/1999/xhtml",
    tag
  );
  for (const [k, v] of Object.entries(attrs)) {
    if (k === "class") e.setAttribute("class", v);
    else if (k === "text") e.textContent = v;
    else e.setAttribute(k, v);
  }
  for (const c of children) {
    if (c == null) continue;
    e.appendChild(typeof c === "string" ? document.createTextNode(c) : c);
  }
  return e;
}

async function api(path, opts = {}) {
  const r = await fetch(path, {
    ...opts,
    headers: opts.body ? { "Content-Type": "application/json", ...(opts.headers || {}) } : opts.headers,
  });
  if (!r.ok) throw new Error(`${r.status} ${r.statusText}: ${path}`);
  return r.json();
}

const mod = (score) => Math.floor((score - 10) / 2);
const signed = (n) => (n >= 0 ? `+${n}` : `${n}`);

// --- Character sheet render ------------------------------------------------

function renderSheet() {
  const pc = state.pc;
  if (!pc) return;
  const s = pc.sheet || {};

  $("#campaign-name").textContent = state.campaign?.name || "—";
  $("#ig-date").textContent = formatIgDate(state.world?.in_game_date);
  const today = new Date();
  $("#real-date").textContent = today.toLocaleDateString(undefined, { weekday: "short", month: "short", day: "numeric", year: "numeric" });
  $("#session").textContent = state.session
    ? `session ${state.session.number}${state.session.ended_at ? " (closed)" : " (open)"}`
    : "no session";

  $("#pc-name").textContent = pc.name || "—";
  $("#pc-sub").textContent = `${s.race || ""} ${s.class || ""}${
    s.subclass ? ` (${s.subclass})` : ""
  } · L${s.level || "?"} · ${s.background || ""}`;

  const hpMax = s.hp_max || pc.current_hp || 0;
  const hpCur = pc.current_hp ?? hpMax;
  const pct = hpMax ? Math.max(0, Math.min(100, (hpCur / hpMax) * 100)) : 0;
  $("#hp-fill").style.width = pct + "%";
  $("#hp-text").textContent = `${hpCur} / ${hpMax}${pc.temp_hp ? ` (+${pc.temp_hp} temp)` : ""}`;

  $("#ac").textContent = s.ac_with_mage_armor ?? s.ac ?? "—";
  $("#init").textContent = signed(s.initiative ?? 0);
  $("#spd").textContent = s.speed ?? "—";
  $("#pb").textContent = `+${s.proficiency_bonus ?? 0}`;

  $("#conditions").textContent = (pc.conditions || []).length
    ? pc.conditions.join(", ")
    : "none";
  $("#concentration").textContent = s.concentration || "none";
  $("#xp").textContent = `${s.xp ?? 0}${s.xp_to_next ? " / " + s.xp_to_next : ""}`;

  // Abilities
  const absBox = $("#abs");
  absBox.innerHTML = "";
  const abs = s.abilities || {};
  for (const k of ["str", "dex", "con", "int", "wis", "cha"]) {
    const score = abs[k] ?? 10;
    const m = mod(score);
    const box = el(
      "div",
      { class: "ab-box" },
      el("div", { class: "name" }, k.toUpperCase()),
      el("div", { class: "score" }, String(score)),
      el("div", { class: "mod" }, signed(m))
    );
    absBox.appendChild(box);
  }

  // Saves
  const savesEl = $("#saves");
  savesEl.innerHTML = "";
  const savesProf = new Set((s.saves_prof || []).map((x) => x.toLowerCase()));
  const saveBonuses = s.save_bonuses || {};
  for (const k of ["str", "dex", "con", "int", "wis", "cha"]) {
    const b = saveBonuses[k] ?? mod(abs[k] ?? 10);
    const li = el(
      "li",
      {},
      savesProf.has(k) ? "● " : "○ ",
      el("strong", {}, k.toUpperCase()),
      " " + signed(b)
    );
    savesEl.appendChild(li);
  }

  // Skills
  const skillsEl = $("#skills");
  skillsEl.innerHTML = "";
  const skillBonuses = s.skill_bonuses || {};
  const profSkills = new Set((s.skills_prof || []).map((x) => x.toLowerCase()));
  // Show proficient first, then others
  const all = Object.entries(skillBonuses).sort((a, b) => {
    const ap = profSkills.has(a[0].toLowerCase()) ? 0 : 1;
    const bp = profSkills.has(b[0].toLowerCase()) ? 0 : 1;
    if (ap !== bp) return ap - bp;
    return b[1] - a[1];
  });
  for (const [name, bonus] of all) {
    if (!profSkills.has(name.toLowerCase())) continue;
    const li = el(
      "li",
      {},
      el("strong", {}, signed(bonus)),
      " " + name
    );
    skillsEl.appendChild(li);
  }

  // Spell DC / slots
  $("#spell-dc-line").textContent = `DC ${s.spell_save_dc ?? "—"}, +${
    s.spell_attack_bonus ?? "—"
  } to hit`;

  const slotsEl = $("#slots");
  slotsEl.innerHTML = "";
  const slots = s.spell_slots || {};
  for (const lvl of Object.keys(slots).sort()) {
    const { max = 0, current = 0 } = slots[lvl];
    const row = el("div", { class: "slot-row" });
    row.appendChild(el("label", {}, `L${lvl}`));
    const dots = el("div", { class: "slot-dots" });
    for (let i = 0; i < max; i++) {
      const filled = i < current;
      dots.appendChild(
        document.createElement("div")
      ).className = "slot-dot" + (filled ? " filled" : "");
    }
    row.appendChild(dots);
    row.appendChild(el("span", { class: "muted" }, `${current}/${max}`));
    slotsEl.appendChild(row);
  }

  // Fey Touched free casts + Quick Ritual tracker
  const feyEl = $("#fey-free");
  feyEl.innerHTML = "";
  const fey = s.fey_touched_free_casts_available;
  if (fey && Object.keys(fey).length) {
    feyEl.appendChild(el("div", { class: "muted", style: "font-size:10px;" }, "Free casts (1/LR)"));
    for (const [sp, n] of Object.entries(fey)) {
      const row = el("div", { class: "fey-row" });
      row.appendChild(el("span", {}, sp));
      row.appendChild(
        el("span", { class: "avail-badge" + (n > 0 ? "" : " spent") }, n > 0 ? "available" : "spent")
      );
      feyEl.appendChild(row);
    }
  }
  if (s.quick_ritual_available !== undefined) {
    const qrAvail = !!s.quick_ritual_available;
    const row = el("div", { class: "fey-row", title: "Quick Ritual — 1/LR, cast any known ritual as a normal action (no 10-minute extension)" });
    row.appendChild(el("span", {}, "Quick Ritual"));
    row.appendChild(
      el("span", { class: "avail-badge" + (qrAvail ? "" : " spent") }, qrAvail ? "available" : "spent")
    );
    feyEl.appendChild(row);
  }

  // Cantrips (always-available, no prepared status)
  const cantripsEl = $("#cantrips");
  cantripsEl.innerHTML = "";
  for (const c of s.cantrips_known || []) {
    cantripsEl.appendChild(el("li", {}, c));
  }
  // Unified spellbook with prepared indicators + ritual badges
  const preparedSet = new Set(s.spells_prepared || []);
  const sbEl = $("#spellbook");
  sbEl.innerHTML = "";
  const sb = s.spellbook || {};
  for (const lvl of Object.keys(sb).sort()) {
    const group = el("div", { class: "lvl-group" });
    group.appendChild(el("h4", {}, `Level ${lvl}`));
    const ul = el("ul", { class: "spell-list spellbook-list" });
    for (const sp of [...sb[lvl]].sort()) {
      const isPrepared = preparedSet.has(sp);
      const isRitual = RITUAL_SPELLS.has(sp);
      const li = el("li", { class: "spellbook-entry" + (isPrepared ? " prepared" : "") });
      li.appendChild(el("span", { class: "prep-dot" }, isPrepared ? "●" : "○"));
      li.appendChild(el("span", { class: "spell-name" }, sp));
      if (isRitual) li.appendChild(el("span", { class: "ritual-badge", title: "Ritual — can be cast without a slot over 10 extra minutes" }, "R"));
      ul.appendChild(li);
    }
    group.appendChild(ul);
    sbEl.appendChild(group);
  }

  // Gear / gold — with containers, drag-drop, and multi-select
  $("#gold").textContent = `${s.gold ?? 0} gp`;
  const invEl = $("#inventory");
  invEl.innerHTML = "";
  invEl.dataset.containerId = "ROOT";
  attachDropTarget(invEl);
  for (const it of s.inventory || []) {
    invEl.appendChild(renderInventoryItem(it));
  }

  // Quests
  const qEl = $("#quests");
  qEl.innerHTML = "";
  for (const q of s.active_quests || []) {
    qEl.appendChild(el("li", {}, q));
  }
}

// --- Inventory: nested containers, drag-drop, multi-select ---

const invSelection = new Set();

function renderInventoryItem(item) {
  const isContainer = !!item.container;
  const li = el("li", {
    class: "inv-item" + (isContainer ? " inv-container" : ""),
    "data-item-id": item.id || "",
    draggable: "true",
  });
  attachItemDragEvents(li, item);

  if (isContainer) {
    const details = el("details", { open: "" });
    const summary = el("summary", {});
    summary.appendChild(buildItemLabel(item, true));
    details.appendChild(summary);
    const sub = el("ul", { class: "inv-container-list" });
    sub.dataset.containerId = item.id || "";
    attachDropTarget(sub);
    for (const child of item.contents || []) {
      sub.appendChild(renderInventoryItem(child));
    }
    details.appendChild(sub);
    li.appendChild(details);
  } else {
    li.appendChild(buildItemLabel(item, false));
  }

  li.addEventListener("click", (e) => {
    const summaryEl = e.target.closest("summary");
    const isMeta = e.metaKey || e.ctrlKey;
    if (summaryEl) {
      // On a container's summary: only ⌘/Ctrl-click selects (preventing default expand/collapse).
      // Plain click on summary always expands/collapses natively.
      if (isMeta) {
        e.preventDefault();
        e.stopPropagation();
        selectItem(li, item.id, "toggle");
      }
      return;
    }
    e.stopPropagation();
    if (isMeta) {
      selectItem(li, item.id, "toggle");
    } else if (e.shiftKey) {
      // TODO: true range-select. For now behave like toggle-add.
      selectItem(li, item.id, "toggle");
    } else {
      selectItem(li, item.id, "replace");
    }
  });
  if (invSelection.has(item.id)) li.classList.add("selected");
  // Right-click context menu for item operations
  li.addEventListener("contextmenu", (e) => {
    e.preventDefault();
    e.stopPropagation();
    showInventoryContextMenu(e.pageX, e.pageY, item);
  });
  return li;
}

function showInventoryContextMenu(x, y, item) {
  // Remove any existing menu
  const existing = document.getElementById("inv-ctx-menu");
  if (existing) existing.remove();
  const menu = el("div", { id: "inv-ctx-menu", class: "ctx-menu", style: `top:${y}px; left:${x}px;` });
  const addItem = (label, fn) => {
    const row = el("div", { class: "ctx-menu-item" }, label);
    row.addEventListener("click", async (e) => {
      e.stopPropagation();
      menu.remove();
      try { await fn(); } catch (err) { console.error(err); alert("Action failed: " + err.message); }
    });
    menu.appendChild(row);
  };
  if (!item.container) {
    addItem("Make container", async () => {
      const res = await fetch("/api/inventory/toggle-container", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ item_id: item.id, container: true }),
      });
      if (res.ok) (typeof refreshState === "function" ? refreshState() : window.location.reload());
    });
  } else {
    addItem("Un-make container (dissolve; contents move to parent)", async () => {
      if (!confirm(`Dissolve "${item.name}" as a container? Its contents will move to the parent level.`)) return;
      const res = await fetch("/api/inventory/toggle-container", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ item_id: item.id, container: false, dissolve: true }),
      });
      if (res.ok) (typeof refreshState === "function" ? refreshState() : window.location.reload());
    });
  }
  addItem("Rename…", async () => {
    const name = window.prompt("New name:", item.name);
    if (!name || !name.trim() || name.trim() === item.name) return;
    const res = await fetch("/api/inventory/rename", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ item_id: item.id, name: name.trim() }),
    });
    if (res.ok) (typeof refreshState === "function" ? refreshState() : window.location.reload());
  });
  addItem("Edit note…", async () => {
    const note = window.prompt("Note (empty to clear):", item.note || "");
    if (note === null) return;
    const res = await fetch("/api/inventory/rename", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ item_id: item.id, note: note.trim() }),
    });
    if (res.ok) (typeof refreshState === "function" ? refreshState() : window.location.reload());
  });
  addItem("Delete", async () => {
    if (!confirm(`Delete "${item.name}"? ${item.container && (item.contents||[]).length ? "All contents will also be deleted." : ""}`)) return;
    const res = await fetch("/api/inventory/delete", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ item_id: item.id }),
    });
    if (res.ok) (typeof refreshState === "function" ? refreshState() : window.location.reload());
  });
  document.body.appendChild(menu);
  // Dismiss on any outside click or escape
  const dismiss = (ev) => {
    if (!menu.contains(ev.target)) { menu.remove(); document.removeEventListener("click", dismiss); document.removeEventListener("keydown", escHandler); }
  };
  const escHandler = (ev) => { if (ev.key === "Escape") { menu.remove(); document.removeEventListener("click", dismiss); document.removeEventListener("keydown", escHandler); } };
  setTimeout(() => {
    document.addEventListener("click", dismiss);
    document.addEventListener("keydown", escHandler);
  }, 0);
}

function buildItemLabel(item, isContainer) {
  const wrap = el("span", { class: "inv-label" });
  wrap.appendChild(el("span", { class: "item-name" }, item.name || "(unnamed)"));
  if (item.qty && item.qty > 1) wrap.appendChild(el("span", { class: "qty" }, ` ×${item.qty}`));
  if (item.equipped) wrap.appendChild(el("span", { class: "equipped-badge", title: "equipped" }, "E"));
  if (item.note) wrap.appendChild(el("span", { class: "note" }, item.note));
  return wrap;
}

function selectItem(rowEl, itemId, mode) {
  if (!itemId) return;
  if (mode === "replace") {
    document.querySelectorAll(".inv-item.selected").forEach((n) => n.classList.remove("selected"));
    invSelection.clear();
    invSelection.add(itemId);
    rowEl.classList.add("selected");
  } else if (mode === "toggle") {
    if (invSelection.has(itemId)) {
      invSelection.delete(itemId);
      rowEl.classList.remove("selected");
    } else {
      invSelection.add(itemId);
      rowEl.classList.add("selected");
    }
  }
}

function attachItemDragEvents(li, item) {
  // Use IDL property for reliable draggable behavior across namespaces
  li.draggable = true;
  li.addEventListener("dragstart", (e) => {
    e.stopPropagation();
    const ids = invSelection.has(item.id) && invSelection.size > 1
      ? Array.from(invSelection)
      : [item.id];
    // Use text/plain for broadest browser compat; also set custom type as hint.
    const payload = JSON.stringify({ kind: "inv-ids", ids });
    try { e.dataTransfer.setData("text/plain", payload); } catch (_) {}
    try { e.dataTransfer.setData("application/x-inv-ids", JSON.stringify(ids)); } catch (_) {}
    e.dataTransfer.effectAllowed = "move";
    li.classList.add("dragging");
    console.log("[inv] dragstart", { ids, from: item.name });
  });
  li.addEventListener("dragend", () => li.classList.remove("dragging"));
}

function attachDropTarget(ul) {
  ul.addEventListener("dragover", (e) => {
    // Must preventDefault to allow drop. DO NOT stopPropagation — we want root
    // ul to receive events when cursor is over a root-level <li> that has no
    // drop handler of its own.
    e.preventDefault();
    e.dataTransfer.dropEffect = "move";
    ul.classList.add("drop-target");
  });
  ul.addEventListener("dragleave", (e) => {
    if (!ul.contains(e.relatedTarget)) ul.classList.remove("drop-target");
  });
  ul.addEventListener("drop", async (e) => {
    e.preventDefault();
    e.stopPropagation(); // drop fires once; stop here so root doesn't also handle it
    ul.classList.remove("drop-target");
    // Read ids — try custom type first, fall back to text/plain JSON payload
    let ids = null;
    const raw = e.dataTransfer.getData("application/x-inv-ids");
    if (raw) {
      try { ids = JSON.parse(raw); } catch (_) {}
    }
    if (!ids) {
      const plain = e.dataTransfer.getData("text/plain");
      if (plain) {
        try {
          const obj = JSON.parse(plain);
          if (obj && obj.kind === "inv-ids") ids = obj.ids;
        } catch (_) {}
      }
    }
    if (!ids || !ids.length) {
      console.warn("[inv] drop had no item ids in dataTransfer");
      return;
    }
    const targetContainerId = ul.dataset.containerId || "ROOT";
    console.log("[inv] drop", { ids, targetContainerId });
    try {
      const res = await fetch("/api/inventory/move", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ item_ids: ids, target_container_id: targetContainerId }),
      });
      if (res.ok) {
        invSelection.clear();
        if (typeof refreshState === "function") await refreshState();
        else window.location.reload();
      } else {
        console.warn("[inv] move failed", res.status, await res.text());
      }
    } catch (err) {
      console.error("[inv] move error", err);
    }
  });
}

function formatIgDate(d) {
  if (!d) return "—";
  // If the DB stored a pre-formatted string (e.g. "30 Flamerule 1491 DR, ~9am"), just return it.
  if (typeof d === "string") return d;
  const months = [
    "Hammer","Alturiak","Ches","Tarsakh","Mirtul","Kythorn",
    "Flamerule","Eleasis","Eleint","Marpenoth","Uktar","Nightal"
  ];
  const fests = {31:"Midwinter",122:"Greengrass",213:"Midsummer",274:"Highharvestide",335:"Feast of the Moon"};
  const doy = d.day_of_year;
  const year = d.year;
  const time = d.time || "";
  if (fests[doy]) return `${fests[doy]} ${year} DR, ${time}`;
  let walk = 0;
  for (let i = 0; i < 12; i++) {
    const start = walk + 1, end = walk + 30;
    if (doy >= start && doy <= end) {
      return `${doy - walk} ${months[i]} ${year} DR, ${time}`;
    }
    walk += 30;
    if ((walk + 1) in fests) walk += 1;
  }
  return `day ${doy} of ${year} DR`;
}

// --- Map rendering ---------------------------------------------------------

function overlay() {
  return $("#map-overlay");
}

function mapImg() {
  return $("#map-img");
}

// Compute and cache the pre-transform "base" size of the map.
// #map-inner is explicitly sized here so the transform origin, overlay
// alignment, and zoom math all agree.
function sizeOverlay() {
  const img = mapImg();
  const ov = overlay();
  const container = document.getElementById("map-container");
  const inner = document.getElementById("map-inner");
  if (!img.naturalWidth || !img.naturalHeight) return;

  // Fit the image to the container while preserving aspect ratio (contain).
  const cw = container.clientWidth, ch = container.clientHeight;
  const aspect = img.naturalWidth / img.naturalHeight;
  let w, h;
  if (cw / ch > aspect) {
    h = ch; w = h * aspect;
  } else {
    w = cw; h = w / aspect;
  }

  // Center #map-inner in the container at zoom=1 by stashing the baseline
  // offset (before any pan is applied) on the element itself.
  const baseLeft = (cw - w) / 2;
  const baseTop = (ch - h) / 2;
  inner.style.width = w + "px";
  inner.style.height = h + "px";
  inner.dataset.baseLeft = baseLeft;
  inner.dataset.baseTop = baseTop;

  // Overlay fills #map-inner; viewBox uses the pre-transform size in CSS px.
  ov.setAttribute("viewBox", `0 0 ${w} ${h}`);

  applyTransform();
  redrawOverlay();
}

function clickToRel(e) {
  // Normalized 0..1 image-relative coordinate regardless of zoom/pan.
  const img = mapImg();
  const rect = img.getBoundingClientRect();
  return {
    x: (e.clientX - rect.left) / rect.width,
    y: (e.clientY - rect.top) / rect.height,
  };
}

function relToPx(x, y) {
  // Pixels in the pre-transform image space (SVG coords).
  const inner = document.getElementById("map-inner");
  return { x: x * inner.offsetWidth, y: y * inner.offsetHeight };
}

function applyTransform() {
  const inner = document.getElementById("map-inner");
  // At zoom=1 with no user pan, the map should sit centered via baseLeft/Top.
  // User pan (state.panX/Y) adds on top of the centering offset.
  const bl = parseFloat(inner.dataset.baseLeft || "0");
  const bt = parseFloat(inner.dataset.baseTop || "0");
  const tx = bl + state.panX;
  const ty = bt + state.panY;
  inner.style.transform = `translate(${tx}px, ${ty}px) scale(${state.zoom})`;
  const zl = document.getElementById("zoom-level");
  if (zl) zl.textContent = state.zoom.toFixed(1) + "×";
}

function clampPan() {
  // Image is displayed at [bl+panX, bl+panX+iw] horizontally (and similarly Y).
  // The clamp has to respect the centering offset (baseLeft/Top), otherwise
  // at high zoom you can reach the left/top edge but not the right/bottom.
  const container = document.getElementById("map-container");
  const inner = document.getElementById("map-inner");
  if (!inner.offsetWidth) return;
  const cw = container.clientWidth, ch = container.clientHeight;
  const iw = inner.offsetWidth * state.zoom;
  const ih = inner.offsetHeight * state.zoom;
  const bl = parseFloat(inner.dataset.baseLeft || "0");
  const bt = parseFloat(inner.dataset.baseTop || "0");
  const bleed = 40; // px of optional overshoot past the image edge
  // X axis: when the zoomed image is wider than the viewport the user can pan
  // from "image's left edge flush with viewport left" to "right flush with right".
  if (iw >= cw) {
    const xMax = -bl + bleed;             // pan this far right → left edge visible
    const xMin = cw - bl - iw - bleed;    // pan this far left  → right edge visible
    state.panX = Math.max(xMin, Math.min(xMax, state.panX));
  } else {
    // Image fits entirely; let it wiggle a touch but not drift away.
    state.panX = Math.max(-bleed, Math.min(bleed, state.panX));
  }
  if (ih >= ch) {
    const yMax = -bt + bleed;
    const yMin = ch - bt - ih - bleed;
    state.panY = Math.max(yMin, Math.min(yMax, state.panY));
  } else {
    state.panY = Math.max(-bleed, Math.min(bleed, state.panY));
  }
}

function zoomAt(clientX, clientY, newZoom) {
  newZoom = Math.max(MIN_ZOOM, Math.min(MAX_ZOOM, newZoom));
  const container = document.getElementById("map-container");
  const inner = document.getElementById("map-inner");
  const rect = container.getBoundingClientRect();
  const bl = parseFloat(inner.dataset.baseLeft || "0");
  const bt = parseFloat(inner.dataset.baseTop || "0");
  const cx = clientX - rect.left;
  const cy = clientY - rect.top;
  // Translate container-space to world-space: subtract center-offset and user pan, divide by zoom.
  const worldX = (cx - bl - state.panX) / state.zoom;
  const worldY = (cy - bt - state.panY) / state.zoom;
  // Adjust user pan so the same world point stays under the cursor at new zoom.
  state.panX = cx - bl - worldX * newZoom;
  state.panY = cy - bt - worldY * newZoom;
  state.zoom = newZoom;
  clampPan();
  applyTransform();
  redrawOverlay(); // counter-scale marker glyphs for the new zoom
}

function zoomToCenter(newZoom) {
  const container = document.getElementById("map-container");
  const rect = container.getBoundingClientRect();
  zoomAt(rect.left + rect.width / 2, rect.top + rect.height / 2, newZoom);
}

function resetZoom() {
  state.zoom = 1;
  state.panX = 0;
  state.panY = 0;
  applyTransform();
  redrawOverlay();
}

function redrawOverlay() {
  const ov = overlay();
  ov.innerHTML = "";

  // Counter-scale factor: the SVG lives inside #map-inner which is scaled by
  // state.zoom, so to keep glyphs visually constant we divide all sizes by it.
  // Bases are chosen so the visual pin is ~6px diameter at zoom 1 AND at zoom 16.
  const invZ = 1 / state.zoom;
  const r = (base) => Math.max(0.3, base * invZ);
  const fs = (base) => Math.max(4, base * invZ);
  const labelStyle = (px) => `font-size: ${px}px;`;
  // Counter-scaled stroke width. Chromium's vector-effect:non-scaling-stroke
  // is unreliable when the SVG's ancestor uses CSS transform: scale(), so at
  // high zoom strokes balloon and swallow small fills. Setting stroke-width
  // inline in scaled SVG units reliably renders at ~`base` screen pixels.
  const sw = (base) => base * invZ;

  // Markers
  for (const m of state.markers) {
    const { x, y } = relToPx(m.x, m.y);
    const g = el("g", { class: "marker-group", style: "pointer-events: auto; cursor: pointer;" });
    g.__marker = m;   // stash for pointerup-as-click detection
    // Picked-up-to-move highlight: big pulsing orange ring around the marker.
    if (state.moveSelected === m.id) {
      g.appendChild(el("circle", {
        class: "marker-selected", cx: x, cy: y, r: r(14),
        style: `stroke-width: ${sw(2.2)}px;`,
      }));
    }
    // A slightly larger filled circle behind the stroked one, so the red fill
    // stays clearly visible even when the stroke is thick relative to radius.
    g.appendChild(el("circle", {
      class: "marker-point", cx: x, cy: y, r: r(6),
      style: `stroke-width: ${sw(0.8)}px;`,
    }));
    g.appendChild(
      el("text", { class: "marker-label", x: x + 9 * invZ, y: y + 3 * invZ, style: labelStyle(fs(13)) }, (m.label || "").replace(/_/g, " "))
    );
    // Right-click deletes (browsers fire contextmenu independently of pointer events).
    g.addEventListener("contextmenu", (e) => {
      e.preventDefault();
      e.stopPropagation();
      if (confirm(`Delete marker "${m.label}"?`)) deleteMarker(m.id);
    });
    ov.appendChild(g);
  }

  // PC position — wrapped in a .marker-group so the pointerup-as-click flow
  // picks it up the same way a city marker does. Special id "__pc__" routes
  // the move through the /api/pc-position endpoint (see placeMovedMarker).
  if (state.pcPos && state.pcPos.x != null) {
    const { x, y } = relToPx(state.pcPos.x, state.pcPos.y);
    const g = el("g", { class: "marker-group pc-group", style: "pointer-events: auto; cursor: pointer;" });
    g.__marker = {
      id: "__pc__",
      isPc: true,
      label: state.pcPos.label || "Charles",
      x: state.pcPos.x,
      y: state.pcPos.y,
    };
    if (state.moveSelected === "__pc__") {
      g.appendChild(el("circle", {
        class: "marker-selected", cx: x, cy: y, r: r(14),
        style: `stroke-width: ${sw(2.2)}px;`,
      }));
    }
    g.appendChild(el("circle", {
      class: "pc-pulse", cx: x, cy: y, r: r(6),
      style: `stroke-width: ${sw(1.5)}px;`,
    }));
    g.appendChild(el("circle", {
      class: "pc-point", cx: x, cy: y, r: r(6),
      style: `stroke-width: ${sw(2)}px;`,
    }));
    g.appendChild(
      el("text", { class: "pc-label", x: x + 10 * invZ, y: y - 8 * invZ, style: labelStyle(fs(13)) }, state.pcPos.label || "Charles")
    );
    ov.appendChild(g);
  }

  // Measure points + line + label
  if (state.mode === MODE_MEASURE && state.measurePoints.length) {
    if (state.measurePoints.length === 1) {
      const { x, y } = relToPx(state.measurePoints[0].x, state.measurePoints[0].y);
      ov.appendChild(el("circle", { class: "measure-point", cx: x, cy: y, r: r(4) }));
    } else if (state.measurePoints.length >= 2) {
      const a = relToPx(state.measurePoints[0].x, state.measurePoints[0].y);
      const b = relToPx(state.measurePoints[1].x, state.measurePoints[1].y);
      ov.appendChild(el("line", { class: "measure-line", x1: a.x, y1: a.y, x2: b.x, y2: b.y }));
      ov.appendChild(el("circle", { class: "measure-point", cx: a.x, cy: a.y, r: r(4) }));
      ov.appendChild(el("circle", { class: "measure-point", cx: b.x, cy: b.y, r: r(4) }));
    }
  }

  // Calibration points + line
  if (state.mode === MODE_CALIBRATE && state.calibratePoints.length) {
    if (state.calibratePoints.length === 1) {
      const { x, y } = relToPx(state.calibratePoints[0].x, state.calibratePoints[0].y);
      ov.appendChild(el("circle", { class: "cal-point", cx: x, cy: y, r: r(5) }));
    } else if (state.calibratePoints.length >= 2) {
      const a = relToPx(state.calibratePoints[0].x, state.calibratePoints[0].y);
      const b = relToPx(state.calibratePoints[1].x, state.calibratePoints[1].y);
      ov.appendChild(el("line", { class: "cal-line", x1: a.x, y1: a.y, x2: b.x, y2: b.y }));
      ov.appendChild(el("circle", { class: "cal-point", cx: a.x, cy: a.y, r: r(5) }));
      ov.appendChild(el("circle", { class: "cal-point", cx: b.x, cy: b.y, r: r(5) }));
    }
  }
}

// --- Map interactions ------------------------------------------------------

function setMode(mode) {
  state.mode = mode;
  state.measurePoints = [];
  state.calibratePoints = [];
  state.moveSelected = null;
  $$(".mode-btn").forEach((b) => b.classList.toggle("active", b.dataset.mode === mode));
  $("#map-info").textContent = {
    [MODE_MEASURE]:   "⌘-click two points to measure. Double-click zooms. Drag to pan.",
    [MODE_MARKER]:    "⌘-click to drop a custom marker.",
    [MODE_MOVE]:      "Click a marker to pick it up, then click the map to drop it. Preserves wiki + notes.",
    [MODE_PC]:        "⌘-click to set Charles's current position.",
    [MODE_CALIBRATE]: "⌘-click two points with a known real-world distance.",
  }[mode];
  resetDistanceReadout();
  redrawOverlay();
}

// Cmd+click does the mode action (measure/calibrate/marker/pc).
// Plain click on empty map = no-op. Plain click on marker = open its wiki (handled in the marker group).
function onCmdClick(e) {
  const pt = clickToRel(e);
  if (state.mode === MODE_MEASURE) {
    if (state.measurePoints.length >= 2) state.measurePoints = [];
    state.measurePoints.push(pt);
    if (state.measurePoints.length === 2) computeDistance();
    redrawOverlay();
  } else if (state.mode === MODE_CALIBRATE) {
    if (state.calibratePoints.length >= 2) state.calibratePoints = [];
    state.calibratePoints.push(pt);
    if (state.calibratePoints.length === 2) finalizeCalibration();
    redrawOverlay();
  } else if (state.mode === MODE_MARKER) {
    promptAddMarker(pt);
  } else if (state.mode === MODE_PC) {
    setPcPosition(pt);
  }
}

async function computeDistance() {
  const [p1, p2] = state.measurePoints;
  const r = await api("/api/distance", { method: "POST", body: JSON.stringify({ p1, p2 }) });
  $("#dist-rel").textContent = r.rel.toFixed(4);
  $("#dist-miles").textContent = r.miles != null ? r.miles.toFixed(1) + " mi" : "— (uncalibrated)";
  $("#dist-cart").textContent = r.days_cart != null ? r.days_cart.toFixed(1) : "—";
  $("#dist-normal").textContent = r.days_normal != null ? r.days_normal.toFixed(1) : "—";
  $("#dist-pushed").textContent = r.days_pushed != null ? r.days_pushed.toFixed(1) : "—";
}

function resetDistanceReadout() {
  for (const id of ["dist-rel", "dist-miles", "dist-cart", "dist-normal", "dist-pushed"]) {
    $("#" + id).textContent = "—";
  }
}

async function finalizeCalibration() {
  const [p1, p2] = state.calibratePoints;
  const miles = prompt(
    "Real-world distance between these two points (in miles)?\n\n" +
    "Example: Waterdeep to Baldur's Gate ≈ 420 miles on the Sword Coast."
  );
  if (!miles || isNaN(parseFloat(miles))) {
    state.calibratePoints = [];
    redrawOverlay();
    return;
  }
  const r = await api("/api/calibration", {
    method: "POST",
    body: JSON.stringify({ p1, p2, miles: parseFloat(miles) }),
  });
  state.calibration = r;
  updateCalStatus();
  state.calibratePoints = [];
  setMode(MODE_MEASURE);
}

function updateCalStatus() {
  const el = $("#cal-status");
  if (state.calibration && state.calibration.miles_per_rel) {
    el.classList.remove("muted");
    el.innerHTML =
      `Calibrated: <strong>${state.calibration.known_miles} mi</strong> between two reference points. ` +
      `Scale: ${(1 / state.calibration.miles_per_rel).toFixed(3)} relative units per mile.`;
  } else {
    el.classList.add("muted");
    el.textContent = "Uncalibrated — click 'Calibrate' and two points with a known real-world distance.";
  }
}

async function promptAddMarker(pt) {
  const label = prompt("Marker label (e.g., 'Candlekeep'):");
  if (!label) return;
  const defaultSlug = label.replace(/ /g, "_").replace(/'/g, "'");
  const wikiSlug = prompt(
    `Wiki slug for forgottenrealms.fandom.com/wiki/___ ?\n(leave blank for none)`,
    defaultSlug
  );
  const kind = prompt("Kind (city, town, region, landmark, inn, poi):", "poi") || "poi";
  const m = await api("/api/markers", {
    method: "POST",
    body: JSON.stringify({ x: pt.x, y: pt.y, label, kind, wiki_slug: wikiSlug || null }),
  });
  state.markers.push({ x: pt.x, y: pt.y, label, kind, wiki_slug: wikiSlug || null, id: m.id });
  redrawOverlay();
  renderMarkersList();
}

async function placeMovedMarker(pt) {
  const id = state.moveSelected;
  if (!id) return;

  // Special case: the PC lives in /api/pc-position, not /api/markers.
  if (id === "__pc__") {
    if (!state.pcPos) { state.moveSelected = null; return; }
    const label = state.pcPos.label || "Charles";
    try {
      const r = await api("/api/pc-position", {
        method: "POST",
        body: JSON.stringify({ x: pt.x, y: pt.y, label }),
      });
      state.pcPos = r;
      $("#map-info").textContent = `Moved ${label} to (${pt.x.toFixed(3)}, ${pt.y.toFixed(3)}). Click another marker to move it, or switch modes.`;
    } catch (e) {
      $("#map-info").textContent = `Save failed: ${e}`;
      console.error(e);
    }
    state.moveSelected = null;
    redrawOverlay();
    updatePcPosInfo();
    return;
  }

  const m = state.markers.find((x) => x.id === id);
  if (!m) { state.moveSelected = null; return; }
  const oldLabel = m.label;
  m.x = pt.x; m.y = pt.y;
  try {
    await api(`/api/markers/${id}`, {
      method: "PATCH",
      body: JSON.stringify({ x: pt.x, y: pt.y }),
    });
    $("#map-info").textContent = `Moved ${oldLabel.replace(/_/g," ")} to (${pt.x.toFixed(3)}, ${pt.y.toFixed(3)}). Click another marker to move it, or switch modes.`;
  } catch (e) {
    $("#map-info").textContent = `Save failed: ${e}`;
    console.error(e);
  }
  state.moveSelected = null;
  redrawOverlay();
  renderMarkersList();
}

async function deleteMarker(id) {
  await api(`/api/markers/${id}`, { method: "DELETE" });
  state.markers = state.markers.filter((m) => m.id !== id);
  redrawOverlay();
  renderMarkersList();
}

async function setPcPosition(pt) {
  const label = prompt("PC position label:", "Charles") || "Charles";
  const r = await api("/api/pc-position", {
    method: "POST",
    body: JSON.stringify({ x: pt.x, y: pt.y, label }),
  });
  state.pcPos = r;
  redrawOverlay();
  updatePcPosInfo();
  setMode(MODE_MEASURE);
}

function updatePcPosInfo() {
  const el = $("#pc-position-info");
  if (state.pcPos && state.pcPos.x != null) {
    el.classList.remove("muted");
    el.textContent = `${state.pcPos.label}: rel(${state.pcPos.x.toFixed(3)}, ${state.pcPos.y.toFixed(3)})`;
  } else {
    el.classList.add("muted");
    el.textContent = "Not set.";
  }
}

// Open the info panel for a marker. Fetches the wiki summary lazily on first
// open (server-side caches). Homebrew notes live on the marker itself.
let currentInfoMarker = null;

async function onMarkerClick(m) {
  // In Move mode, clicking a marker picks it up (or swaps selection).
  if (state.mode === MODE_MOVE) {
    state.moveSelected = m.id;
    const shown = m.isPc ? (m.label || "Charles") : (m.label || "").replace(/_/g, " ");
    $("#map-info").textContent = `Picked up ${shown}. Click anywhere on the map to drop it. ESC cancels.`;
    redrawOverlay();
    return;
  }
  // PC has no wiki/info panel. Outside Move mode, clicking it is a no-op
  // with a small hint.
  if (m.isPc) {
    $("#map-info").textContent = `${m.label || "Charles"} — switch to Move marker to reposition.`;
    return;
  }
  currentInfoMarker = m;
  $("#marker-info-title").textContent = (m.label || "").replace(/_/g, " ");
  $("#marker-info-kind").textContent = m.kind || "";
  const sumEl = $("#marker-info-summary");
  const linkEl = $("#marker-info-link");
  const notesEl = $("#marker-info-notes");
  const statusEl = $("#marker-info-status");
  statusEl.textContent = "";
  notesEl.value = m.homebrew_notes || "";
  sumEl.textContent = "Loading…";
  sumEl.classList.add("muted");
  linkEl.textContent = "Open full wiki page →";
  linkEl.href = m.wiki_slug ? FANDOM_WIKI_BASE + encodeURI(m.wiki_slug) : "#";
  if (!m.wiki_slug) linkEl.style.display = "none"; else linkEl.style.display = "";

  $("#marker-info").classList.remove("hidden");
  $("#marker-info-scrim").classList.remove("hidden");

  if (!m.wiki_slug) {
    sumEl.textContent = "No wiki link for this marker.";
    return;
  }
  // Use prefetched cache if present (instant) — set by scripts/prefetch_wiki.py
  const cached = m.wiki_cache;
  if (cached && cached.extract) {
    sumEl.classList.remove("muted");
    sumEl.textContent = cached.extract;
    if (cached.url) linkEl.href = cached.url;
    return;
  }
  // Fall back to live fetch (caches in server memory)
  try {
    const r = await api(`/api/wiki-summary?slug=${encodeURIComponent(m.wiki_slug)}`);
    if (r.extract) {
      sumEl.classList.remove("muted");
      sumEl.textContent = r.extract;
    } else {
      sumEl.textContent = r.error ? `(no summary available: ${r.error})` : "(no summary available)";
    }
    if (r.url) linkEl.href = r.url;
  } catch (e) {
    const msg = String(e);
    if (msg.includes("404")) {
      sumEl.textContent =
        "Wiki endpoint not found on the server. The server needs to be restarted " +
        "to pick up new code — stop the dashboard (Ctrl-C) and re-launch it.";
    } else {
      sumEl.textContent = `Failed to fetch wiki summary: ${msg}`;
    }
    console.error(e);
  }
}

function closeMarkerInfo() {
  currentInfoMarker = null;
  $("#marker-info").classList.add("hidden");
  $("#marker-info-scrim").classList.add("hidden");
}

async function saveMarkerHomebrew() {
  if (!currentInfoMarker) return;
  const notes = $("#marker-info-notes").value;
  const statusEl = $("#marker-info-status");
  statusEl.textContent = "Saving…";
  try {
    await api(`/api/markers/${currentInfoMarker.id}`, {
      method: "PATCH",
      body: JSON.stringify({ homebrew_notes: notes }),
    });
    currentInfoMarker.homebrew_notes = notes;
    // Also keep the in-memory state in sync
    const m = state.markers.find((x) => x.id === currentInfoMarker.id);
    if (m) m.homebrew_notes = notes;
    statusEl.textContent = "Saved.";
    setTimeout(() => { statusEl.textContent = ""; }, 1500);
  } catch (e) {
    statusEl.textContent = "Save failed.";
    console.error(e);
  }
}

function renderMarkersList() {
  const ul = $("#markers-list");
  ul.innerHTML = "";
  const sorted = [...state.markers].sort((a, b) => (a.label || "").localeCompare(b.label || ""));
  for (const m of sorted) {
    const li = el("li", {});
    const label = el("span", { class: "label" }, m.label || "(unnamed)");
    label.style.cursor = "pointer";
    label.addEventListener("click", () => onMarkerClick(m));
    li.appendChild(label);
    const del = el("button", { class: "delete", title: "Delete marker" }, "×");
    del.addEventListener("click", () => {
      if (confirm(`Delete marker "${m.label}"?`)) deleteMarker(m.id);
    });
    li.appendChild(del);
    ul.appendChild(li);
  }
}

// --- Init ------------------------------------------------------------------

async function refresh() {
  const s = await api("/api/state");
  state.campaign = s.campaign;
  state.pc = s.pc;
  state.session = s.session;
  state.world = s.world;
  state.markers = s.world?.map_markers || [];
  state.pcPos = s.world?.pc_position || null;
  state.calibration = s.world?.map_calibration || null;
  renderSheet();
  renderMarkersList();
  updatePcPosInfo();
  updateCalStatus();
  redrawOverlay();
}

function wireEvents() {
  $$(".mode-btn").forEach((b) => b.addEventListener("click", () => setMode(b.dataset.mode)));
  $("#clear-measure").addEventListener("click", () => {
    state.measurePoints = [];
    resetDistanceReadout();
    redrawOverlay();
  });
  $("#refresh").addEventListener("click", refresh);

  // + Container button — create a new root-level container
  const ncBtn = document.getElementById("new-container-btn");
  if (ncBtn) {
    ncBtn.addEventListener("click", async () => {
      const name = window.prompt("New container name (e.g. 'Red Sheaf Room 9 stash', 'Saddlebag'):");
      if (!name || !name.trim()) return;
      const note = window.prompt("Optional note (location, context) — leave blank to skip:", "") || "";
      try {
        const res = await fetch("/api/inventory/create-container", {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ name: name.trim(), note: note.trim(), parent_id: "ROOT" }),
        });
        if (res.ok) {
          if (typeof refreshState === "function") await refreshState();
          else window.location.reload();
        } else {
          alert("Failed to create container: " + (await res.text()));
        }
      } catch (err) {
        alert("Error: " + err);
      }
    });
  }

  // Zoom controls
  $("#zoom-in").addEventListener("click", () => zoomToCenter(state.zoom * ZOOM_STEP));
  $("#zoom-out").addEventListener("click", () => zoomToCenter(state.zoom / ZOOM_STEP));
  $("#zoom-reset").addEventListener("click", resetZoom);

  const container = $("#map-container");

  // Click routing:
  //   - Drag just happened (dragMoved true): suppress.
  //   - Cmd/Ctrl held: mark point for current mode (works over markers too).
  //   - Plain click on empty map: no-op — except in MOVE mode where it
  //     drops the currently-held marker.
  container.addEventListener("click", (e) => {
    if (state.dragMoved) return;
    if (e.metaKey || e.ctrlKey) {
      e.preventDefault();
      onCmdClick(e);
      return;
    }
    // Move mode: if a marker is picked up and click is NOT on another marker,
    // drop it at the click location. (Click on a marker is handled by pointerup
    // which calls onMarkerClick, which handles the swap case.)
    if (state.mode === MODE_MOVE && state.moveSelected) {
      const onMarker = e.target && e.target.closest && e.target.closest(".marker-group");
      if (!onMarker) {
        e.preventDefault();
        placeMovedMarker(clickToRel(e));
      }
    }
  });

  // Double-click: zoom in at cursor. Shift+double-click: zoom out.
  container.addEventListener("dblclick", (e) => {
    if (e.target.closest(".marker-group")) return;
    e.preventDefault();
    const factor = e.shiftKey ? 1 / ZOOM_STEP : ZOOM_STEP;
    zoomAt(e.clientX, e.clientY, state.zoom * factor);
  });

  // Wheel: zoom at cursor.
  container.addEventListener("wheel", (e) => {
    if (!e.ctrlKey && !e.metaKey && !e.altKey) return; // don't hijack normal scroll
    e.preventDefault();
    const factor = e.deltaY < 0 ? ZOOM_STEP : 1 / ZOOM_STEP;
    zoomAt(e.clientX, e.clientY, state.zoom * factor);
  }, { passive: false });

  // Drag-to-pan. Pointer events only. Key tricks for robustness at high zoom:
  //   1. setPointerCapture on the container so subsequent pointer events fire
  //      here regardless of what's under the cursor (e.g. a scaled marker).
  //   2. While dragging, add .panning to #map-wrap which sets pointer-events:none
  //      on all marker groups — they can't intercept pointermove at all.
  //   3. Deliberately NO duplicate window-level mouse listeners — they were
  //      racing with pointer handlers at high zoom.
  let downTarget = null;
  const mapWrap = document.getElementById("map-wrap");
  container.addEventListener("pointerdown", (e) => {
    if (e.button !== 0) return;
    if (e.metaKey || e.ctrlKey) return; // cmd-click handled by the click listener
    state.dragging = true;
    state.dragMoved = false;
    state.dragStart = { x: e.clientX, y: e.clientY, panX0: state.panX, panY0: state.panY };
    downTarget = e.target;
    try { container.setPointerCapture(e.pointerId); } catch (_) {}
    container.classList.add("panning");
    mapWrap.classList.add("panning"); // disables marker hit-testing via CSS
    document.getElementById("map-inner").classList.add("dragging");
    e.preventDefault();
  });
  container.addEventListener("pointermove", (e) => {
    if (!state.dragging) return;
    const dx = e.clientX - state.dragStart.x;
    const dy = e.clientY - state.dragStart.y;
    if (Math.hypot(dx, dy) > 3) state.dragMoved = true;
    state.panX = state.dragStart.panX0 + dx;
    state.panY = state.dragStart.panY0 + dy;
    clampPan();
    applyTransform();
  });
  const endPointer = (e) => {
    if (!state.dragging) return;
    state.dragging = false;
    container.classList.remove("panning");
    mapWrap.classList.remove("panning");
    document.getElementById("map-inner").classList.remove("dragging");
    try { if (e && e.pointerId != null) container.releasePointerCapture(e.pointerId); } catch (_) {}
    // If it was a pure click (no significant movement) on a marker, open it.
    if (!state.dragMoved && downTarget) {
      const group = downTarget.closest && downTarget.closest(".marker-group");
      if (group && group.__marker) onMarkerClick(group.__marker);
    }
    downTarget = null;
    setTimeout(() => { state.dragMoved = false; }, 10);
  };
  container.addEventListener("pointerup", endPointer);
  container.addEventListener("pointercancel", endPointer);
  container.addEventListener("lostpointercapture", endPointer);
  // Belt-and-suspenders: kill any lingering native image drag.
  container.addEventListener("dragstart", (e) => e.preventDefault());

  // Escape clears in-progress measure/calibrate points OR closes info panel.
  window.addEventListener("keydown", (e) => {
    if (e.key !== "Escape") return;
    if (!$("#marker-info").classList.contains("hidden")) {
      closeMarkerInfo();
      return;
    }
    if (state.moveSelected) {
      state.moveSelected = null;
      $("#map-info").textContent = "Move cancelled.";
      redrawOverlay();
      return;
    }
    const hadPoints =
      state.measurePoints.length > 0 || state.calibratePoints.length > 0;
    if (!hadPoints) return;
    state.measurePoints = [];
    state.calibratePoints = [];
    resetDistanceReadout();
    redrawOverlay();
  });

  // Info panel wiring
  $("#marker-info-close").addEventListener("click", closeMarkerInfo);
  $("#marker-info-scrim").addEventListener("click", closeMarkerInfo);
  $("#marker-info-save").addEventListener("click", saveMarkerHomebrew);

  window.addEventListener("resize", sizeOverlay);
  const img = mapImg();
  if (img.complete) sizeOverlay();
  else img.addEventListener("load", sizeOverlay);
}

(async function init() {
  wireEvents();
  setMode(MODE_MEASURE);
  try {
    await refresh();
  } catch (e) {
    console.error(e);
    alert("Failed to load state. Check that the server is running and the DB exists.");
  }
})();
