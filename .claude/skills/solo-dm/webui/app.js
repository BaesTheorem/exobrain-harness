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
  campaigns: [],
  toolsBaseUrl: "http://localhost:5050",
  pc: null,
  session: null,
  world: null,
  quests: [],
  events: [],
  // Calendar view state
  view: "map",                       // "map" | "calendar"
  calendarStructure: null,           // months/festivals from /api/calendar/structure
  calMonth: 0,                       // 0..11 — currently visible month index
  calYear: 1491,                     // currently visible year
  calSelectedDoy: null,              // selected day-of-year (number) within calYear
  calMonthBlurbCache: {},            // wiki_slug → {title, extract, url}
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

  renderCampaignSelect();
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

  // Long rest abilities — checkbox per max use; click to toggle spent/available
  const feyEl = $("#fey-free");
  feyEl.innerHTML = "";
  const lra = s.long_rest_abilities || [];
  if (lra.length) {
    feyEl.appendChild(el("div", { class: "muted", style: "font-size:10px;" }, "Long rest abilities"));
    for (const ab of lra) {
      const row = el("div", { class: "fey-row", title: ab.note || "" });
      row.appendChild(el("span", {}, ab.name));
      const boxes = el("span", { class: "lra-boxes" });
      const max = ab.max || 1;
      const remaining = Math.max(0, Math.min(max, ab.uses_remaining ?? max));
      for (let i = 0; i < max; i++) {
        // Checked = available; left-aligned: first `remaining` boxes checked.
        const checked = i < remaining;
        const box = el("input", {
          type: "checkbox",
          class: "lra-box",
          title: checked ? "Click to mark this use as spent" : "Click to mark this use as available",
        });
        if (checked) box.checked = true;
        box.addEventListener("change", async () => {
          // Recompute remaining from the row's checkboxes after the user toggle.
          const all = boxes.querySelectorAll(".lra-box");
          let newRemaining = 0;
          all.forEach((b) => { if (b.checked) newRemaining++; });
          try {
            await api("/api/abilities/set", {
              method: "POST",
              body: JSON.stringify({ name: ab.name, uses_remaining: newRemaining }),
            });
            await refresh();
          } catch (err) {
            console.error(err);
            await refresh();
          }
        });
        boxes.appendChild(box);
      }
      row.appendChild(boxes);
      feyEl.appendChild(row);
    }
  }

  // Ki tracker — Monk only. Slot-style dots scaled to ki.max; click sets current.
  renderKi(s);

  // Cantrips (always-available, no prepared status) — link to 5etools
  const cantripsEl = $("#cantrips");
  cantripsEl.innerHTML = "";
  for (const c of s.cantrips_known || []) {
    const li = el("li");
    li.appendChild(buildSpellLink(c));
    cantripsEl.appendChild(li);
  }
  // Unified spellbook with prepared indicators + ritual badges
  const preparedSet = new Set(s.spells_prepared || []);
  const sbEl = $("#spellbook");
  sbEl.innerHTML = "";
  const sb = s.spellbook || {};
  // Update the prepared X/Y header
  const counterEl = $("#prep-counter");
  if (counterEl) {
    const used = preparedSet.size;
    const max = s.spells_prepared_max;
    if (max != null) {
      const auto = s.spells_prepared_max_auto ? " (auto)" : "";
      const over = used > max;
      counterEl.textContent = `Prepared ${used} / ${max}${auto}`;
      counterEl.classList.toggle("over-limit", over);
      counterEl.title = over
        ? `Over the limit by ${used - max}. Click a ● to unprepare.`
        : `Click ○ to prepare, ● to unprepare. ${auto ? "Max is computed from class/level/ability mod." : ""}`;
    } else {
      counterEl.textContent = `Prepared ${used}`;
      counterEl.classList.remove("over-limit");
      counterEl.title = "Click ○ to prepare, ● to unprepare.";
    }
  }
  for (const lvl of Object.keys(sb).sort()) {
    const group = el("div", { class: "lvl-group" });
    group.appendChild(el("h4", {}, `Level ${lvl}`));
    const ul = el("ul", { class: "spell-list spellbook-list" });
    for (const sp of [...sb[lvl]].sort()) {
      const isPrepared = preparedSet.has(sp);
      const isRitual = RITUAL_SPELLS.has(sp);
      const li = el("li", { class: "spellbook-entry" + (isPrepared ? " prepared" : "") });
      const dot = el("span", {
        class: "prep-dot clickable",
        title: isPrepared ? "Click to unprepare" : "Click to prepare",
      }, isPrepared ? "●" : "○");
      dot.addEventListener("click", async (e) => {
        e.preventDefault();
        e.stopPropagation();
        try {
          await api("/api/spells/toggle-prepared", {
            method: "POST",
            body: JSON.stringify({ spell: sp }),
          });
          await refresh();
        } catch (err) {
          console.error(err);
          alert("Failed to toggle prepared: " + err.message);
        }
      });
      li.appendChild(dot);
      li.appendChild(buildSpellLink(sp));
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

  // Quests are rendered by renderQuests() — keyed off state.quests, not the sheet.
  renderQuests();
}

// --- 5etools spell links + campaign switcher ------------------------------

// Source-code map for spells whose primary printing isn't PHB. 5etools' hash
// router falls back to the alphabetical first spell on the page (Abi-Dalzim's
// Horrid Wilting) when the <name>_<source> hash doesn't resolve, so a wrong
// source suffix silently sends the user to the wrong page. Keep this list
// updated as new spells enter the spellbook.
const SPELL_SOURCES = {
  "mind sliver": "xge",
  "silvery barbs": "scc",
  "absorb elements": "xge",
  "pyrotechnics": "xge",
  "toll the dead": "xge",
  "booming blade": "tce",
  "green-flame blade": "tce",
};

function spellToolsUrl(spellName) {
  // 5etools self-hosted: spells.html#<lower-name>_<source>. Default PHB; look
  // up non-PHB spells in SPELL_SOURCES.
  const lower = (spellName || "").toLowerCase().replace(/'/g, "").trim();
  const source = SPELL_SOURCES[lower] || "phb";
  const base = (state.toolsBaseUrl || "http://localhost:5050").replace(/\/$/, "");
  return `${base}/spells.html#${encodeURIComponent(lower)}_${source}`;
}

function buildSpellLink(spellName) {
  return el("a", {
    class: "spell-name spell-link",
    href: spellToolsUrl(spellName),
    target: "_blank",
    rel: "noopener",
    title: `Open ${spellName} on 5etools`,
  }, spellName);
}

// Features page. Aggregates every readable text block on the sheet into a
// scrollable reference page: backstory, monk + subclass features, feats,
// house rules, the Unspeaking Art skill chain, the discovery/background
// feature, and the spellcasting note. Pulls from sheet keys directly so
// it works for any character — sections only render if data is present.
function renderFeatures(s) {
  const wrap = document.getElementById("features-content");
  if (!wrap) return;
  wrap.innerHTML = "";

  const h = (tag, attrs, ...kids) => el(tag, attrs || {}, ...kids);
  const sec = (title) => {
    const block = h("section", { class: "feat-block" });
    block.appendChild(h("h2", {}, title));
    return block;
  };
  const ul = (items) => {
    const list = h("ul", { class: "feat-list" });
    for (const it of items) list.appendChild(h("li", {}, it));
    return list;
  };
  const nameDesc = (name, desc) => {
    const li = h("li");
    li.appendChild(h("strong", {}, name));
    if (desc) {
      li.appendChild(document.createTextNode(" — "));
      li.appendChild(document.createTextNode(desc));
    }
    return li;
  };

  // Header (name + class line)
  const header = h("section", { class: "feat-header" });
  header.appendChild(h("h1", {}, s.name || "Character"));
  const sub = [
    s.race_flavor || s.race,
    `${s.class || ""}${s.subclass ? ` (${s.subclass})` : ""}`,
    `Level ${s.level || "?"}`,
    s.background,
  ].filter(Boolean).join(" · ");
  if (sub) header.appendChild(h("p", { class: "muted" }, sub));
  wrap.appendChild(header);

  // Backstory
  if (s.backstory) {
    const b = sec("Backstory");
    b.appendChild(h("p", {}, s.backstory));
    wrap.appendChild(b);
  }

  // Background feature / Discovery
  if (s.background_feature) {
    const b = sec("Background Feature");
    b.appendChild(h("p", {}, s.background_feature));
    wrap.appendChild(b);
  }

  // The Unspeaking Art (skill chain table)
  if (s.unspeaking_art && Array.isArray(s.unspeaking_art.tiers)) {
    const ua = s.unspeaking_art;
    const b = sec("The Unspeaking Art");
    if (ua.description) b.appendChild(h("p", {}, ua.description));
    const table = h("table", { class: "feat-table" });
    const thead = h("thead");
    const trh = h("tr");
    for (const col of ["#", "Tier", "Status", "Unlocked at", "Mechanic"]) {
      trh.appendChild(h("th", {}, col));
    }
    thead.appendChild(trh);
    table.appendChild(thead);
    const tbody = h("tbody");
    for (const t of ua.tiers) {
      const tr = h("tr", t.status === "locked" ? { class: "tier-locked" } : {});
      tr.appendChild(h("td", {}, String(t.tier)));
      tr.appendChild(h("td", {}, h("strong", {}, t.name || "")));
      tr.appendChild(h("td", {}, t.status || ""));
      tr.appendChild(h("td", {}, t.unlocked_at || ""));
      tr.appendChild(h("td", {}, t.spec || ""));
      tbody.appendChild(tr);
    }
    table.appendChild(tbody);
    b.appendChild(table);
    if (ua.ki_feedback) {
      b.appendChild(h("p", { class: "feat-note" }, h("strong", {}, "Ki feedback: "), ua.ki_feedback));
    }
    wrap.appendChild(b);
  }

  // Class features
  if (Array.isArray(s.monk_features) && s.monk_features.length) {
    const b = sec(`${s.class || "Class"} Features`);
    b.appendChild(ul(s.monk_features));
    wrap.appendChild(b);
  }

  // Subclass features
  if (Array.isArray(s.way_of_shadow_features) && s.way_of_shadow_features.length) {
    const b = sec(`${s.subclass || "Subclass"} Features`);
    b.appendChild(ul(s.way_of_shadow_features));
    wrap.appendChild(b);
  }

  // Feats
  if (Array.isArray(s.feats) && s.feats.length) {
    const b = sec("Feats");
    const list = h("ul", { class: "feat-list" });
    for (const f of s.feats) {
      const label = `${f.name}${f.source ? ` (${f.source})` : ""}`;
      list.appendChild(nameDesc(label, f.summary));
    }
    b.appendChild(list);
    wrap.appendChild(b);
  }

  // House rules
  if (Array.isArray(s.house_rules) && s.house_rules.length) {
    const b = sec("Campaign House Rules");
    b.appendChild(ul(s.house_rules));
    wrap.appendChild(b);
  }

  // Spellcasting note (Way of Shadow specifics)
  if (s.spellcasting_note) {
    const b = sec("Spellcasting Note");
    b.appendChild(h("p", {}, s.spellcasting_note));
    wrap.appendChild(b);
  }

  if (!wrap.children.length) {
    wrap.appendChild(h("p", { class: "muted" }, "No feature text on this sheet yet."));
  }
}

// Ki tracker (Monk only). Slot-style dots, click sets current to that index.
function renderKi(s) {
  const section = document.getElementById("ki-section");
  if (!section) return;
  const ki = s.ki;
  const cls = (s.class || "").toLowerCase();
  const isMonk = cls.includes("monk");
  const max = ki && Number.isFinite(ki.max) ? ki.max : 0;
  if (!isMonk || !ki || max <= 0) {
    section.hidden = true;
    return;
  }
  section.hidden = false;
  const cur = Math.max(0, Math.min(max, ki.current ?? max));
  const txt = document.getElementById("ki-text");
  if (txt) txt.textContent = `${cur} / ${max}`;
  const dots = document.getElementById("ki-dots");
  if (!dots) return;
  dots.innerHTML = "";
  for (let i = 0; i < max; i++) {
    const filled = i < cur;
    const d = document.createElement("div");
    d.className = "slot-dot clickable" + (filled ? " filled" : "");
    d.title = filled
      ? `Click to spend down to ${i} ki`
      : `Click to restore to ${i + 1} ki`;
    d.addEventListener("click", async () => {
      const next = filled ? i : i + 1;
      try {
        await api("/api/ki/set", {
          method: "POST",
          body: JSON.stringify({ current: next }),
        });
        await refresh();
      } catch (e) {
        console.error(e);
        alert("Failed to update ki: " + e.message);
      }
    });
    dots.appendChild(d);
  }
}

function renderCampaignSelect() {
  const sel = $("#campaign-select");
  if (!sel) return;
  const list = state.campaigns || [];
  const currentSlug = state.campaign?.slug || "";
  if (list.length === 0) {
    sel.innerHTML = "";
    sel.appendChild(el("option", { value: "" }, state.campaign?.name || "—"));
    sel.disabled = true;
    return;
  }
  sel.innerHTML = "";
  for (const c of list) {
    sel.appendChild(el("option", { value: c.slug }, c.name));
  }
  sel.value = currentSlug;
  sel.disabled = false;
}

async function loadCampaigns() {
  try {
    state.campaigns = await api("/api/campaigns");
  } catch (e) {
    console.warn("campaigns fetch failed", e);
    state.campaigns = [];
  }
}

async function switchCampaign(newSlug) {
  if (!newSlug || newSlug === state.campaign?.slug) return;
  try {
    await api("/api/campaign/switch", {
      method: "POST",
      body: JSON.stringify({ slug: newSlug }),
    });
    // Map data, calendar structure, etc. are all campaign-scoped — easiest
    // to reload the page so cached state isn't carrying over.
    window.location.reload();
  } catch (e) {
    console.error(e);
    alert("Failed to switch campaign: " + e.message);
  }
}

// --- Quests (DB-backed, editable) -----------------------------------------

function renderQuests() {
  const qEl = $("#quests");
  if (!qEl) return;
  qEl.innerHTML = "";
  const quests = state.quests || [];
  if (quests.length === 0) {
    qEl.appendChild(el("li", { class: "muted" }, "No active quests. Click + Quest above to add one."));
    return;
  }
  for (const q of quests) {
    qEl.appendChild(renderQuestItem(q));
  }
}

function renderQuestItem(q) {
  const li = el("li", { "data-quest-id": String(q.id) });
  const row = el("div", { class: "quest-row" });

  const name = el("span", { class: "quest-name", title: "Click to rename" }, q.name);
  name.addEventListener("click", async () => {
    const next = window.prompt("Quest name:", q.name);
    if (!next || next === q.name) return;
    await api(`/api/quests/${q.id}`, { method: "PATCH", body: JSON.stringify({ name: next }) });
    await refresh();
  });

  const status = el(
    "span",
    { class: `quest-status ${q.status}`, title: "Click to cycle status" },
    q.status
  );
  status.addEventListener("click", async () => {
    const order = ["active", "dormant", "complete", "failed"];
    const next = order[(order.indexOf(q.status) + 1) % order.length];
    await api(`/api/quests/${q.id}`, { method: "PATCH", body: JSON.stringify({ status: next }) });
    await refresh();
  });

  const del = el("button", { class: "quest-delete", title: "Delete quest" }, "×");
  del.addEventListener("click", async () => {
    if (!confirm(`Delete quest "${q.name}"?`)) return;
    await api(`/api/quests/${q.id}`, { method: "DELETE" });
    await refresh();
  });

  row.append(name, status, del);
  li.appendChild(row);

  // Beats
  const beats = q.beats || [];
  const ul = el("ul", { class: "quest-beats" });
  beats.forEach((b, idx) => {
    const beat = el("li");
    const check = el("span", { class: "beat-check" + (b.done ? " done" : ""), title: "Toggle done" }, b.done ? "✓" : "○");
    check.addEventListener("click", async () => {
      const newBeats = beats.map((x, i) => i === idx ? { ...x, done: !x.done } : x);
      await api(`/api/quests/${q.id}`, { method: "PATCH", body: JSON.stringify({ beats: newBeats }) });
      await refresh();
    });
    const text = el("span", { class: "beat-text" + (b.done ? " done" : ""), title: "Click to edit" }, b.text || "(unnamed beat)");
    text.addEventListener("click", async () => {
      const next = window.prompt("Beat:", b.text || "");
      if (next === null) return;
      let newBeats;
      if (!next.trim()) {
        newBeats = beats.filter((_, i) => i !== idx);
      } else {
        newBeats = beats.map((x, i) => i === idx ? { ...x, text: next.trim() } : x);
      }
      await api(`/api/quests/${q.id}`, { method: "PATCH", body: JSON.stringify({ beats: newBeats }) });
      await refresh();
    });
    beat.append(check, text);
    ul.appendChild(beat);
  });
  // "+ beat" affordance
  const addBeat = el("li");
  const addLabel = el("span", { class: "beat-add" }, "+ add beat");
  addLabel.addEventListener("click", async () => {
    const text = window.prompt("New beat:");
    if (!text || !text.trim()) return;
    const newBeats = [...beats, { text: text.trim(), done: false }];
    await api(`/api/quests/${q.id}`, { method: "PATCH", body: JSON.stringify({ beats: newBeats }) });
    await refresh();
  });
  addBeat.appendChild(addLabel);
  ul.appendChild(addBeat);
  li.appendChild(ul);
  return li;
}

async function createQuest() {
  const name = window.prompt("New quest name:");
  if (!name || !name.trim()) return;
  await api("/api/quests", { method: "POST", body: JSON.stringify({ name: name.trim() }) });
  await refresh();
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
  if (s.tools_5etools_base_url) state.toolsBaseUrl = s.tools_5etools_base_url;
  await loadCampaigns();
  state.pc = s.pc;
  state.session = s.session;
  state.world = s.world;
  state.markers = s.world?.map_markers || [];
  state.pcPos = s.world?.pc_position || null;
  state.calibration = s.world?.map_calibration || null;
  state.quests = s.quests || [];
  state.events = s.calendar_events || [];
  // Initialize calendar view to current in-game date the first time we get state.
  if (!state.calendarStructure) {
    try {
      state.calendarStructure = await api("/api/calendar/structure");
      const cur = state.calendarStructure.current || { year: 1491, day_of_year: 1 };
      state.calYear = cur.year;
      state.calMonth = monthIndexForDoy(cur.day_of_year);
    } catch (e) {
      console.warn("calendar structure fetch failed", e);
    }
  }
  renderSheet();
  renderMarkersList();
  updatePcPosInfo();
  updateCalStatus();
  redrawOverlay();
  if (state.view === "calendar") renderCalendar();
  renderUpcomingEvents();
}

// --- Calendar rendering ---------------------------------------------------

const FANDOM_WIKI_BASE_HARPTOS = "https://forgottenrealms.fandom.com/wiki/";

// Map a day-of-year back to a month index (0..11). Returns -1 for festival days.
function monthIndexForDoy(doy) {
  const struct = state.calendarStructure;
  if (!struct) return 0;
  const months = struct.months;
  for (let i = 0; i < months.length; i++) {
    const m = months[i];
    if (doy >= m.start_doy && doy < m.start_doy + m.days) return i;
  }
  return -1; // festival or out of range — caller handles
}

function setView(view) {
  if (view === state.view) return;
  state.view = view;
  document.body.classList.toggle("view-calendar", view === "calendar");
  document.body.classList.toggle("view-combat", view === "combat");
  document.body.classList.toggle("view-features", view === "features");
  $("#map-wrap").classList.toggle("hidden", view !== "map");
  $("#calendar-wrap").classList.toggle("hidden", view !== "calendar");
  $("#combat-wrap").classList.toggle("hidden", view !== "combat");
  const featWrap = $("#features-wrap");
  if (featWrap) featWrap.classList.toggle("hidden", view !== "features");
  $$(".view-tab").forEach((b) => b.classList.toggle("active", b.dataset.view === view));
  // Toggle side-panel sections
  $$(".side-map-only").forEach((s) => s.classList.toggle("hidden", view !== "map"));
  $$(".side-cal-only").forEach((s) => s.classList.toggle("hidden", view !== "calendar"));
  $$(".side-combat-only").forEach((s) => s.classList.toggle("hidden", view !== "combat"));
  if (view === "calendar") renderCalendar();
  else if (view === "combat") refreshCombat();
  else if (view === "map") sizeOverlay();
  else if (view === "features" && state.pc) renderFeatures(state.pc.sheet || {});
}

// ===== Combat / hex grid =================================================
// Hexes are pointy-top, offset (col, row) coords with odd-r layout.
// One hex = 5 ft. Token images come from the local 5etools server's
// /img/bestiary/tokens/<source>/<name>.webp endpoint.

const HEX_SIZE = 30;                                  // pixel radius
const HEX_W = Math.sqrt(3) * HEX_SIZE;                // pointy-top width
const HEX_H = 2 * HEX_SIZE;
const HEX_VSTEP = HEX_H * 0.75;

const combat = {
  state: null,                       // server state ({active, grid, tokens, ...})
  selectedTokenId: null,
  drag: null,                        // {tokenId, startCol, startRow, ghost}
  dragStart: null,                   // pointer client coords at down
  dragMoved: false,
  bestiaryIndex: null,               // {SOURCE: "bestiary-source.json", ...}
  bestiaryCache: {},                 // SOURCE → [monster, ...]
  pickedEnemies: [],                 // [{name, source, image_url, hp_max, ac, size}]
  searchTimer: null,
};

function hexCenter(col, row) {
  const x = HEX_W * (col + (row & 1 ? 0.5 : 0)) + HEX_W / 2;
  const y = HEX_VSTEP * row + HEX_H / 2;
  return { x, y };
}

function hexPolygon(cx, cy, size = HEX_SIZE) {
  // Pointy-top: vertices at 30°, 90°, 150°, 210°, 270°, 330°
  const pts = [];
  for (let i = 0; i < 6; i++) {
    const ang = Math.PI / 180 * (60 * i - 30);
    pts.push(`${(cx + size * Math.cos(ang)).toFixed(2)},${(cy + size * Math.sin(ang)).toFixed(2)}`);
  }
  return pts.join(" ");
}

function offsetToCube(col, row) {
  const x = col - ((row - (row & 1)) >> 1);
  const z = row;
  const y = -x - z;
  return [x, y, z];
}

function hexDistance(a, b) {
  const [ax, ay, az] = offsetToCube(a.col, a.row);
  const [bx, by, bz] = offsetToCube(b.col, b.row);
  return (Math.abs(ax - bx) + Math.abs(ay - by) + Math.abs(az - bz)) / 2;
}

function pixelToHex(px, py) {
  // Inverse of hexCenter — cube round to nearest hex.
  // Approx via offset: row from y, then col from x with odd-row shift.
  const row = Math.round((py - HEX_H / 2) / HEX_VSTEP);
  const xOffset = (row & 1) ? HEX_W / 2 : 0;
  const col = Math.round((px - HEX_W / 2 - xOffset) / HEX_W);
  return { col, row };
}

const SVG_NS = "http://www.w3.org/2000/svg";
function svgEl(tag, attrs = {}) {
  const e = document.createElementNS(SVG_NS, tag);
  for (const [k, v] of Object.entries(attrs)) {
    if (v == null) continue;
    e.setAttribute(k, String(v));
  }
  return e;
}

async function refreshCombat() {
  try {
    combat.state = await api("/api/combat");
  } catch (e) {
    combat.state = { active: false };
  }
  renderCombat();
}

function renderCombat() {
  const wrap = $("#combat-wrap");
  if (!wrap || wrap.classList.contains("hidden") && state.view !== "combat") return;
  const empty = $("#combat-empty");
  const svg = $("#combat-grid");
  const status = $("#combat-status");
  const startBtn = $("#combat-start-btn");
  const endBtn = $("#combat-end-btn");
  const addBtn = $("#combat-add-btn");

  if (!combat.state || !combat.state.active) {
    empty.classList.remove("hidden");
    svg.classList.add("hidden");
    status.textContent = "No active encounter";
    startBtn.classList.remove("hidden");
    endBtn.classList.add("hidden");
    addBtn.classList.add("hidden");
    $("#combat-roster").innerHTML = "";
    $("#combat-selected").textContent = "Click a token on the grid.";
    return;
  }

  empty.classList.add("hidden");
  svg.classList.remove("hidden");
  startBtn.classList.add("hidden");
  endBtn.classList.remove("hidden");
  addBtn.classList.remove("hidden");
  const enemyCount = combat.state.tokens.filter(t => t.kind === "enemy" && t.hp > 0).length;
  const allyCount = combat.state.tokens.filter(t => t.kind !== "enemy" && t.hp > 0).length;
  status.textContent = `Round ${combat.state.round || 1} · ${allyCount} ally, ${enemyCount} enemy`;

  drawHexGrid(svg);
  drawTokens(svg);
  renderRoster();
  renderSelectedToken();
}

function drawHexGrid(svg) {
  while (svg.firstChild) svg.removeChild(svg.firstChild);
  const { cols, rows } = combat.state.grid;
  const widthPx = HEX_W * cols + HEX_W / 2 + 4;
  const heightPx = HEX_VSTEP * (rows - 1) + HEX_H + 4;
  svg.setAttribute("viewBox", `0 0 ${widthPx} ${heightPx}`);
  svg.setAttribute("width", widthPx);
  svg.setAttribute("height", heightPx);

  const grid = svgEl("g", { class: "hex-grid" });
  for (let r = 0; r < rows; r++) {
    for (let c = 0; c < cols; c++) {
      const { x, y } = hexCenter(c, r);
      const poly = svgEl("polygon", {
        class: "hex-cell",
        points: hexPolygon(x, y),
        "data-col": c, "data-row": r,
      });
      grid.appendChild(poly);
    }
  }
  svg.appendChild(grid);
  // Layer for tokens drawn on top
  svg.appendChild(svgEl("g", { class: "hex-tokens" }));
  svg.appendChild(svgEl("g", { class: "hex-overlay" }));  // distance ring etc.

  // Click on empty hex with cmd → quick-add token
  grid.addEventListener("click", (e) => {
    if (!(e.metaKey || e.ctrlKey)) return;
    const t = e.target.closest(".hex-cell");
    if (!t) return;
    const col = parseInt(t.dataset.col, 10);
    const row = parseInt(t.dataset.row, 10);
    const name = window.prompt("Token name:");
    if (!name) return;
    addQuickToken(name, col, row);
  });
}

function drawTokens(svg) {
  const layer = svg.querySelector(".hex-tokens");
  while (layer.firstChild) layer.removeChild(layer.firstChild);
  for (const t of combat.state.tokens) {
    layer.appendChild(buildTokenNode(t));
  }
}

function buildTokenNode(t) {
  const { x, y } = hexCenter(t.col, t.row);
  const radius = HEX_SIZE * 0.85;
  const g = svgEl("g", {
    class: `token kind-${t.kind}${t.hp <= 0 ? " dead" : ""}${combat.selectedTokenId === t.id ? " selected" : ""}`,
    "data-id": t.id,
    transform: `translate(${x},${y})`,
  });
  // Background hex highlight matches kind
  g.appendChild(svgEl("polygon", {
    class: "token-hex",
    points: hexPolygon(0, 0, HEX_SIZE * 0.95),
  }));
  // Image (use clipPath via SVG circle)
  const clipId = `clip-${t.id}`;
  const defs = svgEl("defs");
  const clip = svgEl("clipPath", { id: clipId });
  clip.appendChild(svgEl("circle", { cx: 0, cy: 0, r: radius }));
  defs.appendChild(clip);
  g.appendChild(defs);

  if (t.image_url) {
    const img = svgEl("image", {
      href: t.image_url,
      x: -radius, y: -radius, width: radius * 2, height: radius * 2,
      "clip-path": `url(#${clipId})`,
      preserveAspectRatio: "xMidYMid slice",
    });
    g.appendChild(img);
  } else {
    // No-image fallback: colored circle + initial
    g.appendChild(svgEl("circle", {
      class: "token-fallback",
      r: radius, cx: 0, cy: 0,
    }));
    const initial = svgEl("text", {
      class: "token-initial",
      x: 0, y: 0,
      "text-anchor": "middle",
      "dominant-baseline": "central",
    });
    initial.textContent = (t.name || "?").charAt(0).toUpperCase();
    g.appendChild(initial);
  }
  // Outline ring (color by kind)
  g.appendChild(svgEl("circle", { class: "token-ring", r: radius, cx: 0, cy: 0 }));

  // HP bar under token
  const barW = radius * 1.8;
  const pct = t.hp_max > 0 ? Math.max(0, Math.min(1, t.hp / t.hp_max)) : 0;
  g.appendChild(svgEl("rect", {
    class: "token-hp-bg",
    x: -barW / 2, y: radius + 3, width: barW, height: 5, rx: 2,
  }));
  g.appendChild(svgEl("rect", {
    class: "token-hp-fill",
    x: -barW / 2, y: radius + 3, width: barW * pct, height: 5, rx: 2,
  }));
  // Name label
  const lbl = svgEl("text", {
    class: "token-label",
    x: 0, y: -(radius + 4),
    "text-anchor": "middle",
  });
  lbl.textContent = t.name;
  g.appendChild(lbl);

  // Drag-to-move
  g.addEventListener("pointerdown", (e) => onTokenPointerDown(e, t));
  return g;
}

function renderRoster() {
  const list = $("#combat-roster");
  list.innerHTML = "";
  // Sort by initiative desc, then name
  const sorted = [...combat.state.tokens].sort((a, b) => {
    const ai = a.initiative ?? -99;
    const bi = b.initiative ?? -99;
    if (ai !== bi) return bi - ai;
    return (a.name || "").localeCompare(b.name || "");
  });
  for (const t of sorted) {
    const li = el("li", {
      class: `combat-roster-item kind-${t.kind}${t.hp <= 0 ? " dead" : ""}${combat.selectedTokenId === t.id ? " selected" : ""}`,
      "data-id": t.id,
    });
    const dot = el("span", { class: `roster-dot kind-${t.kind}` });
    const nm = el("strong", {}, t.name);
    const hp = el("span", { class: "muted" }, ` ${t.hp}/${t.hp_max}`);
    const init = t.initiative != null ? el("span", { class: "init" }, `(${t.initiative})`) : null;
    li.appendChild(dot); li.appendChild(nm); li.appendChild(hp);
    if (init) li.appendChild(init);
    li.addEventListener("click", () => selectToken(t.id));
    list.appendChild(li);
  }
}

function renderSelectedToken() {
  const box = $("#combat-selected");
  const t = combat.state.tokens.find(x => x.id === combat.selectedTokenId);
  if (!t) {
    box.innerHTML = "Click a token on the grid.";
    box.classList.add("muted");
    return;
  }
  box.classList.remove("muted");
  box.innerHTML = "";
  box.appendChild(el("h3", {}, t.name));
  box.appendChild(el("div", { class: "muted" }, `${t.kind}${t.source ? ` · ${t.source}` : ""}`));
  // HP edit
  const hpRow = el("div", { class: "selected-row" },
    el("label", {}, "HP"),
    (() => {
      const inp = el("input", { type: "number", value: String(t.hp), min: "0", max: String(t.hp_max) });
      inp.style.width = "60px";
      inp.addEventListener("change", async () => {
        const v = parseInt(inp.value, 10);
        if (!Number.isFinite(v)) return;
        await api(`/api/combat/token/${t.id}`, {
          method: "PATCH", body: JSON.stringify({ hp: Math.max(0, Math.min(t.hp_max, v)) }),
        });
        await refreshCombat();
      });
      return inp;
    })(),
    el("span", { class: "muted" }, ` / ${t.hp_max}`)
  );
  box.appendChild(hpRow);
  box.appendChild(el("div", { class: "row" },
    el("label", {}, "AC"), el("span", {}, String(t.ac))));
  box.appendChild(el("div", { class: "row" },
    el("label", {}, "Pos"), el("span", {}, `(${t.col}, ${t.row})`)));
  // Quick damage buttons
  const dmgRow = el("div", { class: "selected-row" });
  for (const d of [-5, -1, +1, +5]) {
    const btn = el("button", {}, (d > 0 ? `+${d}` : `${d}`));
    btn.addEventListener("click", async () => {
      const newHp = Math.max(0, Math.min(t.hp_max, t.hp + d));
      await api(`/api/combat/token/${t.id}`, {
        method: "PATCH", body: JSON.stringify({ hp: newHp }),
      });
      await refreshCombat();
    });
    dmgRow.appendChild(btn);
  }
  box.appendChild(dmgRow);
  // Remove button
  const rm = el("button", { class: "danger" }, "Remove from board");
  rm.addEventListener("click", async () => {
    if (!window.confirm(`Remove ${t.name}?`)) return;
    await fetch(`/api/combat/token/${t.id}`, { method: "DELETE" });
    combat.selectedTokenId = null;
    await refreshCombat();
  });
  box.appendChild(rm);
}

function selectToken(id) {
  combat.selectedTokenId = id;
  renderCombat();
}

// ----- Drag-to-move ------------------------------------------------------

function onTokenPointerDown(e, t) {
  if (e.button !== 0) return;
  e.stopPropagation();
  combat.selectedTokenId = t.id;
  combat.drag = { tokenId: t.id, startCol: t.col, startRow: t.row };
  combat.dragStart = { x: e.clientX, y: e.clientY };
  combat.dragMoved = false;
  const svg = $("#combat-grid");
  svg.setPointerCapture && svg.setPointerCapture(e.pointerId);
  svg.addEventListener("pointermove", onCombatPointerMove);
  svg.addEventListener("pointerup", onCombatPointerUp);
  svg.addEventListener("pointercancel", onCombatPointerUp);
}

function svgPointFromEvent(svg, e) {
  const rect = svg.getBoundingClientRect();
  const vb = svg.viewBox.baseVal;
  const x = (e.clientX - rect.left) / rect.width * vb.width;
  const y = (e.clientY - rect.top) / rect.height * vb.height;
  return { x, y };
}

function onCombatPointerMove(e) {
  if (!combat.drag) return;
  const dx = e.clientX - combat.dragStart.x;
  const dy = e.clientY - combat.dragStart.y;
  if (!combat.dragMoved && Math.hypot(dx, dy) < 4) return;
  combat.dragMoved = true;
  const svg = $("#combat-grid");
  const pt = svgPointFromEvent(svg, e);
  const hex = pixelToHex(pt.x, pt.y);
  // Highlight target hex + show distance
  const overlay = svg.querySelector(".hex-overlay");
  while (overlay.firstChild) overlay.removeChild(overlay.firstChild);
  const start = { col: combat.drag.startCol, row: combat.drag.startRow };
  if (hex.col >= 0 && hex.col < combat.state.grid.cols
      && hex.row >= 0 && hex.row < combat.state.grid.rows) {
    const c = hexCenter(hex.col, hex.row);
    overlay.appendChild(svgEl("polygon", {
      class: "hex-target",
      points: hexPolygon(c.x, c.y, HEX_SIZE * 0.95),
    }));
    const dist = hexDistance(start, hex);
    const label = svgEl("text", {
      class: "hex-distance",
      x: c.x, y: c.y - HEX_SIZE - 4,
      "text-anchor": "middle",
    });
    label.textContent = `${dist * 5} ft`;
    overlay.appendChild(label);
    // Move the token visual to follow cursor
    const tokNode = svg.querySelector(`.token[data-id="${combat.drag.tokenId}"]`);
    if (tokNode) tokNode.setAttribute("transform", `translate(${c.x},${c.y})`);
  }
}

async function onCombatPointerUp(e) {
  const svg = $("#combat-grid");
  svg.removeEventListener("pointermove", onCombatPointerMove);
  svg.removeEventListener("pointerup", onCombatPointerUp);
  svg.removeEventListener("pointercancel", onCombatPointerUp);
  const overlay = svg.querySelector(".hex-overlay");
  if (overlay) while (overlay.firstChild) overlay.removeChild(overlay.firstChild);
  if (!combat.drag) return;
  if (!combat.dragMoved) {
    // Pure click: just select.
    selectToken(combat.drag.tokenId);
    combat.drag = null;
    return;
  }
  const pt = svgPointFromEvent(svg, e);
  const hex = pixelToHex(pt.x, pt.y);
  const dragId = combat.drag.tokenId;
  combat.drag = null;
  if (hex.col < 0 || hex.col >= combat.state.grid.cols
      || hex.row < 0 || hex.row >= combat.state.grid.rows) {
    await refreshCombat();
    return;
  }
  // Avoid stomping on another token's hex
  const occupied = combat.state.tokens.some(
    o => o.id !== dragId && o.col === hex.col && o.row === hex.row && o.hp > 0);
  if (occupied) {
    await refreshCombat();
    return;
  }
  await api(`/api/combat/token/${dragId}`, {
    method: "PATCH",
    body: JSON.stringify({ col: hex.col, row: hex.row }),
  });
  await refreshCombat();
}

// ----- Quick add / start dialog ----------------------------------------

async function addQuickToken(name, col, row) {
  await api("/api/combat/token", {
    method: "POST",
    body: JSON.stringify({ name, kind: "enemy", col, row, hp: 1, hp_max: 1, ac: 10, size: "M" }),
  });
  await refreshCombat();
}

async function endCombat() {
  if (!window.confirm("End the encounter? This clears the board.")) return;
  await api("/api/combat/end", { method: "POST", body: "{}" });
  combat.selectedTokenId = null;
  await refreshCombat();
}

// ----- 5etools bestiary integration ------------------------------------

function tokenUrlFor(monster) {
  if (!monster.hasToken) return null;
  const base = state.toolsBaseUrl || "http://localhost:5050";
  // Tokens live at /img/bestiary/tokens/<source>/<name>.webp.
  return `${base}/img/bestiary/tokens/${encodeURIComponent(monster.source)}/${encodeURIComponent(monster.name)}.webp`;
}

async function loadBestiaryIndex() {
  if (combat.bestiaryIndex) return combat.bestiaryIndex;
  const base = state.toolsBaseUrl || "http://localhost:5050";
  try {
    const r = await fetch(`${base}/data/bestiary/index.json`);
    if (!r.ok) throw new Error(`${r.status}`);
    combat.bestiaryIndex = await r.json();
  } catch (e) {
    console.warn("Bestiary index unreachable; check 5etools is running:", e);
    combat.bestiaryIndex = {};
  }
  return combat.bestiaryIndex;
}

async function loadBestiaryFile(source) {
  if (combat.bestiaryCache[source]) return combat.bestiaryCache[source];
  const idx = await loadBestiaryIndex();
  const file = idx[source];
  if (!file) return [];
  const base = state.toolsBaseUrl || "http://localhost:5050";
  try {
    const r = await fetch(`${base}/data/bestiary/${file}`);
    const data = await r.json();
    combat.bestiaryCache[source] = data.monster || [];
    return combat.bestiaryCache[source];
  } catch (e) {
    return [];
  }
}

// Search across the SRD-relevant sources first (MM, MPMM, VGM, MTF) for speed.
const PRIORITY_SOURCES = ["MM", "MPMM", "VGM", "MTF", "TCE", "FTD", "BMT", "MM2024"];

async function searchMonsters(query) {
  const q = (query || "").trim().toLowerCase();
  if (q.length < 2) return [];
  const idx = await loadBestiaryIndex();
  const sources = [...new Set([...PRIORITY_SOURCES, ...Object.keys(idx)])];
  const matches = [];
  for (const src of sources) {
    if (!idx[src]) continue;
    const list = await loadBestiaryFile(src);
    for (const m of list) {
      if ((m.name || "").toLowerCase().includes(q)) {
        matches.push(m);
        if (matches.length >= 25) break;
      }
    }
    if (matches.length >= 25) break;
  }
  // Rank: exact-prefix > contains, then by source priority
  matches.sort((a, b) => {
    const ap = (a.name || "").toLowerCase().startsWith(q) ? 0 : 1;
    const bp = (b.name || "").toLowerCase().startsWith(q) ? 0 : 1;
    if (ap !== bp) return ap - bp;
    return PRIORITY_SOURCES.indexOf(a.source) - PRIORITY_SOURCES.indexOf(b.source);
  });
  return matches.slice(0, 12);
}

function summarizeMonster(m) {
  const cr = typeof m.cr === "object" ? (m.cr.cr || "?") : (m.cr || "?");
  const sz = Array.isArray(m.size) ? m.size.join("/") : (m.size || "?");
  const t = typeof m.type === "object" ? m.type.type : m.type;
  return `CR ${cr} · ${sz} ${t}`;
}

function monsterMaxHp(m) {
  if (typeof m.hp === "number") return m.hp;
  if (m.hp && m.hp.average) return m.hp.average;
  return 1;
}
function monsterAc(m) {
  if (Array.isArray(m.ac) && m.ac.length) {
    const first = m.ac[0];
    return typeof first === "number" ? first : (first.ac || 10);
  }
  return 10;
}

function openStartCombatDialog() {
  combat.pickedEnemies = [];
  $("#combat-monster-search").value = "";
  $("#combat-monster-qty").value = "1";
  $("#combat-search-results").innerHTML = "";
  renderPickedEnemies();
  $("#combat-start-dialog").showModal();
  setTimeout(() => $("#combat-monster-search").focus(), 30);
}

function renderPickedEnemies() {
  const list = $("#combat-picked");
  list.innerHTML = "";
  if (!combat.pickedEnemies.length) {
    list.appendChild(el("li", { class: "muted" }, "(no enemies selected)"));
    return;
  }
  for (let i = 0; i < combat.pickedEnemies.length; i++) {
    const p = combat.pickedEnemies[i];
    const li = el("li", {});
    if (p.image_url) {
      li.appendChild(el("img", { src: p.image_url, class: "picked-thumb" }));
    }
    li.appendChild(el("span", {}, ` ${p.qty}× ${p.name} `));
    li.appendChild(el("span", { class: "muted" }, `(${p.source}, HP ${p.hp_max}, AC ${p.ac})`));
    const rm = el("button", { type: "button", class: "mini-btn" }, "×");
    rm.addEventListener("click", () => {
      combat.pickedEnemies.splice(i, 1);
      renderPickedEnemies();
    });
    li.appendChild(rm);
    list.appendChild(li);
  }
}

async function combatSearchType(query) {
  clearTimeout(combat.searchTimer);
  combat.searchTimer = setTimeout(async () => {
    const results = $("#combat-search-results");
    results.innerHTML = "";
    if (!query || query.length < 2) return;
    const matches = await searchMonsters(query);
    if (!matches.length) {
      results.appendChild(el("li", { class: "muted" }, "no matches"));
      return;
    }
    for (const m of matches) {
      const li = el("li", { class: "search-result" });
      const url = tokenUrlFor(m);
      if (url) li.appendChild(el("img", { src: url, class: "picked-thumb" }));
      li.appendChild(el("span", {}, " " + m.name));
      li.appendChild(el("span", { class: "muted" }, ` ${summarizeMonster(m)}`));
      li.addEventListener("click", () => {
        const qty = parseInt($("#combat-monster-qty").value, 10) || 1;
        combat.pickedEnemies.push({
          name: m.name,
          source: m.source,
          image_url: url,
          hp_max: monsterMaxHp(m),
          ac: monsterAc(m),
          size: Array.isArray(m.size) ? m.size[0] : (m.size || "M"),
          qty,
        });
        renderPickedEnemies();
        $("#combat-monster-search").value = "";
        results.innerHTML = "";
        $("#combat-monster-search").focus();
      });
      results.appendChild(li);
    }
  }, 150);
}

async function startCombatFromDialog() {
  const cols = parseInt($("#combat-cols").value, 10) || 20;
  const rows = parseInt($("#combat-rows").value, 10) || 14;
  const tokens = [];
  for (const e of combat.pickedEnemies) {
    for (let i = 0; i < e.qty; i++) {
      tokens.push({
        kind: "enemy",
        name: e.qty > 1 ? `${e.name} ${i + 1}` : e.name,
        source: e.source,
        image_url: e.image_url,
        hp_max: e.hp_max, hp: e.hp_max,
        ac: e.ac,
        size: e.size,
      });
    }
  }
  await api("/api/combat/start", {
    method: "POST",
    body: JSON.stringify({ cols, rows, tokens, place_pc: true }),
  });
  await refreshCombat();
}

function wireCombatEvents() {
  const sb = $("#combat-start-btn");
  if (sb) sb.addEventListener("click", openStartCombatDialog);
  const eb = $("#combat-end-btn");
  if (eb) eb.addEventListener("click", endCombat);
  const ab = $("#combat-add-btn");
  if (ab) ab.addEventListener("click", () => {
    const name = window.prompt("Token name:");
    if (!name) return;
    const cs = combat.state.grid;
    addQuickToken(name, Math.floor(cs.cols / 2), Math.floor(cs.rows / 2));
  });
  const search = $("#combat-monster-search");
  if (search) search.addEventListener("input", (e) => combatSearchType(e.target.value));
  const goBtn = $("#combat-start-go");
  if (goBtn) goBtn.addEventListener("click", (e) => {
    if (!combat.pickedEnemies.length) {
      // Allow empty for "PC only" testing — fall through.
    }
    // dialog closes itself via form submit; do start after
    setTimeout(startCombatFromDialog, 0);
  });
}

function renderCalendar() {
  const struct = state.calendarStructure;
  const grid = $("#cal-grid");
  const tendaysRow = $("#cal-tendays-row");
  const titleEl = $("#cal-title");
  const wikiLink = $("#cal-wiki-link");
  const fest = $("#cal-festival-banner");
  if (!grid || !struct) return;
  const month = struct.months[state.calMonth];
  if (!month) return;

  titleEl.textContent = `${month.name} (${month.alt_name}) · ${state.calYear} DR`;
  wikiLink.href = FANDOM_WIKI_BASE_HARPTOS + encodeURIComponent(month.wiki_slug);

  // Tenday header row (3 tendays of 10 days each → 10 columns × 3 rows)
  tendaysRow.innerHTML = "";
  for (let t = 1; t <= 3; t++) {
    const lbl = el("div", { class: "lbl" }, `Tenday ${t}`);
    tendaysRow.appendChild(lbl);
  }
  tendaysRow.style.gridTemplateColumns = "repeat(3, 1fr)";

  // Build the day grid (30 days, 10 per row → 3 rows)
  grid.innerHTML = "";
  grid.style.gridTemplateColumns = "repeat(10, 1fr)";

  const todayDoy = struct.current?.day_of_year;
  const todayYear = struct.current?.year;

  for (let day = 1; day <= 30; day++) {
    const doy = month.start_doy + (day - 1);
    const cell = el("div", {
      class: "cal-day" + (day % 10 === 0 ? " tenday-end" : ""),
      "data-doy": String(doy),
    });
    if (state.calYear === todayYear && doy === todayDoy) cell.classList.add("is-today");
    if (state.calSelectedDoy === doy) cell.classList.add("is-selected");
    cell.appendChild(el("div", { class: "num" }, String(day)));
    const evWrap = el("div", { class: "events" });
    const dayEvents = (state.events || []).filter(
      (e) => e.year === state.calYear && e.day_of_year === doy
    );
    const shown = dayEvents.slice(0, 3);
    for (const e of shown) {
      evWrap.appendChild(el("span", { class: `cal-event-chip kind-${e.kind || "event"}`, title: e.title + (e.notes ? "\n" + e.notes : "") }, e.title));
    }
    if (dayEvents.length > shown.length) {
      evWrap.appendChild(el("span", { class: "cal-event-chip more" }, `+${dayEvents.length - shown.length} more`));
    }
    cell.appendChild(evWrap);
    cell.addEventListener("click", () => selectDay(doy));
    grid.appendChild(cell);
  }

  // Festival banner (if any festival follows this month)
  fest.innerHTML = "";
  if (month.following_festival) {
    const f = month.following_festival;
    const banner = el("div", { class: "fest", "data-doy": String(f.doy) });
    banner.appendChild(el("div", { class: "fname" }, `🎉 ${f.name} — between ${month.name} and the next month`));
    const evs = el("div", { class: "events" });
    const fEvents = (state.events || []).filter((e) => e.year === state.calYear && e.day_of_year === f.doy);
    for (const e of fEvents.slice(0, 4)) {
      evs.appendChild(el("span", { class: `cal-event-chip kind-${e.kind || "event"}`, title: e.title }, e.title));
    }
    banner.appendChild(evs);
    banner.addEventListener("click", () => selectDay(f.doy));
    fest.appendChild(banner);
  }

  loadMonthBlurb(month);
  renderSelectedDay();
}

async function loadMonthBlurb(month) {
  const titleEl = $("#cal-blurb-title");
  const bodyEl = $("#cal-blurb-body");
  titleEl.textContent = `${month.name} · ${month.alt_name}`;
  if (state.calMonthBlurbCache[month.wiki_slug]) {
    const c = state.calMonthBlurbCache[month.wiki_slug];
    bodyEl.textContent = c.extract || "(no description available)";
    bodyEl.classList.toggle("muted", !c.extract);
    return;
  }
  bodyEl.textContent = "Loading from Forgotten Realms wiki…";
  bodyEl.classList.add("muted");
  try {
    const r = await api(`/api/wiki-summary?slug=${encodeURIComponent(month.wiki_slug)}`);
    state.calMonthBlurbCache[month.wiki_slug] = r;
    if (r.extract) {
      bodyEl.classList.remove("muted");
      bodyEl.textContent = r.extract;
    } else {
      bodyEl.textContent = r.error ? `(no summary available: ${r.error})` : "(no summary available)";
    }
  } catch (e) {
    bodyEl.textContent = `Failed to load wiki summary: ${e}`;
  }
}

function selectDay(doy) {
  state.calSelectedDoy = doy;
  // Re-render only highlight + side panel — full grid re-render is fine here, it's cheap.
  renderCalendar();
}

function renderSelectedDay() {
  const info = $("#cal-selected-info");
  const ul = $("#cal-selected-events");
  if (!info || !ul) return;
  ul.innerHTML = "";
  const doy = state.calSelectedDoy;
  if (doy == null) {
    info.classList.add("muted");
    info.textContent = "Click a day in the calendar to see and add events.";
    return;
  }
  const label = formatDoy(state.calYear, doy);
  info.classList.remove("muted");
  info.innerHTML = "";
  const head = el("div", {}, label);
  const addBtn = el("button", { class: "mini-btn", title: "Add event on this day" }, "+ Event");
  addBtn.addEventListener("click", () => promptAddEvent(state.calYear, doy));
  info.append(head, addBtn);

  const dayEvents = (state.events || []).filter((e) => e.year === state.calYear && e.day_of_year === doy);
  if (dayEvents.length === 0) {
    ul.appendChild(el("li", { class: "muted" }, "No events. Click + Event to add one."));
    return;
  }
  for (const e of dayEvents) {
    const li = el("li");
    li.appendChild(el("span", { class: "when" }, `${e.kind || "event"}${e.time_of_day ? " · " + e.time_of_day : ""}`));
    li.appendChild(el("span", { class: "what" }, e.title));
    if (e.notes) li.appendChild(el("span", { class: "muted" }, e.notes));
    const actions = el("div", { class: "actions" });
    const editBtn = el("button", {}, "edit");
    editBtn.addEventListener("click", async () => {
      const next = window.prompt("Title:", e.title);
      if (next === null || !next.trim() || next === e.title) return;
      await api(`/api/calendar/events/${e.id}`, { method: "PATCH", body: JSON.stringify({ title: next.trim() }) });
      await refresh();
    });
    const delBtn = el("button", {}, "delete");
    delBtn.addEventListener("click", async () => {
      if (!confirm(`Delete "${e.title}"?`)) return;
      await api(`/api/calendar/events/${e.id}`, { method: "DELETE" });
      await refresh();
    });
    actions.append(editBtn, delBtn);
    li.appendChild(actions);
    ul.appendChild(li);
  }
}

function formatDoy(year, doy) {
  const struct = state.calendarStructure;
  if (!struct) return `day ${doy}, ${year} DR`;
  const fest = struct.festivals.find((f) => f.doy === doy);
  if (fest) return `${fest.name}, ${year} DR`;
  const idx = monthIndexForDoy(doy);
  if (idx < 0) return `day ${doy}, ${year} DR`;
  const m = struct.months[idx];
  return `${doy - m.start_doy + 1} ${m.name}, ${year} DR`;
}

function renderUpcomingEvents() {
  const ul = $("#upcoming-events");
  if (!ul) return;
  ul.innerHTML = "";
  const struct = state.calendarStructure;
  const cur = struct?.current || { year: state.calYear, day_of_year: 1 };
  // Sort future events by (year, doy), take first ~10
  const upcoming = (state.events || [])
    .filter((e) => e.year > cur.year || (e.year === cur.year && e.day_of_year >= cur.day_of_year))
    .sort((a, b) => (a.year - b.year) || (a.day_of_year - b.day_of_year))
    .slice(0, 10);
  if (upcoming.length === 0) {
    ul.appendChild(el("li", { class: "muted" }, "Nothing on the calendar yet."));
    return;
  }
  for (const e of upcoming) {
    const li = el("li");
    li.appendChild(el("span", { class: "when" }, formatDoy(e.year, e.day_of_year)));
    li.appendChild(el("span", { class: "what" }, `${e.kind === "task" ? "✓ " : ""}${e.title}`));
    li.addEventListener("click", () => {
      // Jump the calendar to this date and switch to calendar view
      state.calYear = e.year;
      const idx = monthIndexForDoy(e.day_of_year);
      if (idx >= 0) state.calMonth = idx;
      state.calSelectedDoy = e.day_of_year;
      setView("calendar");
    });
    li.style.cursor = "pointer";
    ul.appendChild(li);
  }
}

async function promptAddEvent(year, doy) {
  const title = window.prompt("Event title:");
  if (!title || !title.trim()) return;
  const kindRaw = (window.prompt("Kind: event | task | quest_beat", "event") || "event").trim();
  const kind = ["event", "task", "quest_beat"].includes(kindRaw) ? kindRaw : "event";
  const notes = window.prompt("Notes (optional):", "") || "";
  await api("/api/calendar/events", {
    method: "POST",
    body: JSON.stringify({
      year, day_of_year: doy,
      title: title.trim(),
      kind,
      notes: notes.trim() || null,
    }),
  });
  await refresh();
}

function calNavMonth(delta) {
  const struct = state.calendarStructure;
  if (!struct) return;
  let m = state.calMonth + delta;
  let y = state.calYear;
  if (m < 0) { m = 11; y -= 1; }
  if (m > 11) { m = 0; y += 1; }
  state.calMonth = m;
  state.calYear = y;
  state.calSelectedDoy = null;
  renderCalendar();
}

function calJumpToToday() {
  const struct = state.calendarStructure;
  if (!struct?.current) return;
  state.calYear = struct.current.year;
  const idx = monthIndexForDoy(struct.current.day_of_year);
  if (idx >= 0) state.calMonth = idx;
  state.calSelectedDoy = struct.current.day_of_year;
  renderCalendar();
}

async function calAdvance() {
  const dayStr = window.prompt("Advance the in-game date by how many days?", "1");
  if (dayStr === null) return;
  const days = parseInt(dayStr, 10);
  if (!Number.isFinite(days)) return;
  const r = await api("/api/calendar/advance", { method: "POST", body: JSON.stringify({ days }) });
  // Re-fetch structure for the new "current"
  state.calendarStructure = await api("/api/calendar/structure");
  // Update header in-game date to the new formatted string
  $("#ig-date").textContent = r.formatted || $("#ig-date").textContent;
  await refresh();
}

function wireEvents() {
  // Campaign switcher
  const camp = $("#campaign-select");
  if (camp) camp.addEventListener("change", (e) => switchCampaign(e.target.value));

  // View tabs (Map | Calendar)
  $$(".view-tab").forEach((b) => b.addEventListener("click", () => setView(b.dataset.view)));

  // Calendar toolbar
  const cPrev = $("#cal-prev"); if (cPrev) cPrev.addEventListener("click", () => calNavMonth(-1));
  const cNext = $("#cal-next"); if (cNext) cNext.addEventListener("click", () => calNavMonth(1));
  const cToday = $("#cal-today"); if (cToday) cToday.addEventListener("click", calJumpToToday);
  const cAdd = $("#cal-add-event"); if (cAdd) cAdd.addEventListener("click", () => {
    const doy = state.calSelectedDoy ?? state.calendarStructure?.months[state.calMonth]?.start_doy ?? 1;
    promptAddEvent(state.calYear, doy);
  });
  const cAdv = $("#cal-advance"); if (cAdv) cAdv.addEventListener("click", calAdvance);

  // + Quest button
  const nqBtn = $("#new-quest-btn"); if (nqBtn) nqBtn.addEventListener("click", createQuest);

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
  wireCombatEvents();
  setMode(MODE_MEASURE);
  try {
    await refresh();
  } catch (e) {
    console.error(e);
    alert("Failed to load state. Check that the server is running and the DB exists.");
  }
})();
