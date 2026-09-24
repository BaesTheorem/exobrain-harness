/* MIST Studio front end. Vanilla JS over a small JSON API; the page polls
   /api/jobs while anything is queued or running. */
(() => {
  "use strict";

  const $ = (id) => document.getElementById(id);
  const qs = (sel, root = document) => root.querySelector(sel);
  const qsa = (sel, root = document) => Array.from(root.querySelectorAll(sel));

  const state = {
    meta: null, cfg: null, jobs: [], songs: [], uploads: [],
    watched: new Map(),          // jobId -> {onDone, onError}
    coverSource: null, editSource: null, refSource: null,
    analysis: null, pollTimer: null, lastLibraryFetch: 0, resultIds: [],
    sourcePickCallback: null, confirmCallback: null, lastLyrics: "",
  };

  // ---------------------------------------------------------------- utils
  const el = (tag, attrs = {}, children = []) => {
    const n = document.createElement(tag);
    for (const [k, v] of Object.entries(attrs)) {
      if (k === "class") n.className = v;
      else if (k === "text") n.textContent = v;
      else if (k === "html") n.innerHTML = v;
      else if (k.startsWith("on")) n.addEventListener(k.slice(2), v);
      else if (v !== null && v !== undefined && v !== false) n.setAttribute(k, v === true ? "" : v);
    }
    for (const c of [].concat(children)) {
      if (c === null || c === undefined || c === false) continue;
      n.append(c.nodeType ? c : document.createTextNode(String(c)));
    }
    return n;
  };

  async function api(method, url, body, isForm = false) {
    const opts = { method, headers: {} };
    if (body !== undefined) {
      if (isForm) opts.body = body;
      else { opts.headers["Content-Type"] = "application/json"; opts.body = JSON.stringify(body); }
    }
    const r = await fetch(url, opts);
    let data = null;
    try { data = await r.json(); } catch (e) { data = null; }
    if (!r.ok) throw new Error((data && data.error) || `${method} ${url} failed (${r.status})`);
    return data;
  }

  const sfxCache = {};
  function sfx(name) {
    if (!state.cfg || !state.cfg.sfx) return;
    try {
      const a = sfxCache[name] || (sfxCache[name] = new Audio(`/static/sfx/${name}.mp3`));
      a.volume = 0.35; a.currentTime = 0; a.play().catch(() => {});
    } catch (e) { /* audio is optional */ }
  }

  function toast(msg, kind = "info") {
    const s = $("snack");
    $("snackText").textContent = msg;
    $("snackIcon").textContent = kind === "error" ? "error" : kind === "ok" ? "check_circle" : "info";
    s.classList.remove("error", "ok");
    if (kind !== "info") s.classList.add(kind);
    s.classList.add("active");
    clearTimeout(s._t);
    s._t = setTimeout(() => s.classList.remove("active"), kind === "error" ? 6000 : 3200);
    if (kind === "error") sfx("error");
  }

  const fmtDur = (s) => {
    if (s === null || s === undefined || isNaN(s)) return "";
    s = Math.round(s); return `${Math.floor(s / 60)}:${String(s % 60).padStart(2, "0")}`;
  };
  const fmtAgo = (t) => {
    const d = Math.max(0, Date.now() / 1000 - t);
    if (d < 60) return "just now";
    if (d < 3600) return `${Math.floor(d / 60)} min ago`;
    if (d < 86400) return `${Math.floor(d / 3600)} h ago`;
    return new Date(t * 1000).toLocaleDateString();
  };
  const fmtCountdown = (secs) => {
    secs = Math.max(0, Math.round(secs));
    const h = Math.floor(secs / 3600), m = Math.floor((secs % 3600) / 60);
    return h ? `${h} h ${m} min` : `${m} min`;
  };

  function openDialog(id) { const d = $(id); if (!d.open) d.showModal(); }
  function closeDialog(id) { const d = $(id); if (d.open) d.close(); }

  function confirmDelete(title, text, cb) {
    $("dlgConfirmTitle").textContent = title;
    $("dlgConfirmText").textContent = text;
    state.confirmCallback = cb;
    openDialog("dlgConfirm");
  }

  // ------------------------------------------------------------- navigation
  function showPage(name) {
    qsa("#rail a[data-page]").forEach(a => a.classList.toggle("active", a.dataset.page === name));
    qsa(".page").forEach(p => p.classList.toggle("active", p.id === `page-${name}`));
    if (name === "library") refreshLibrary(true);
    if (name === "queue") renderJobs();
    if (name === "settings") fillSettings();
  }

  function showTab(name) {
    qsa("#createTabs a").forEach(a => a.classList.toggle("active", a.dataset.tab === name));
    qsa(".tabpane").forEach(p => p.classList.toggle("active", p.id === `tab-${name}`));
  }

  // ---------------------------------------------------------------- theme
  function applyTheme() {
    const cfg = state.cfg || {};
    if (typeof ui === "function") {
      try { ui("mode", cfg.theme_mode || "dark"); } catch (e) { /* beer not ready */ }
      try { ui("theme", cfg.theme_seed || "#00A6B8"); } catch (e) { /* no dynamic colors */ }
    }
    document.body.classList.toggle("pro", $("proSwitch").checked);
  }

  // --------------------------------------------------------------- selects
  function fillSelect(sel, values, current) {
    sel.innerHTML = "";
    for (const v of values) {
      const [val, label] = Array.isArray(v) ? v : [v, v];
      sel.append(el("option", { value: val, text: label }));
    }
    if (current !== undefined) sel.value = current;
  }

  const LANG_NAMES = { unknown: "auto", en: "English", es: "Spanish", fr: "French", de: "German",
    it: "Italian", pt: "Portuguese", ja: "Japanese", ko: "Korean", zh: "Mandarin", yue: "Cantonese",
    ru: "Russian", ar: "Arabic", hi: "Hindi", nl: "Dutch", sv: "Swedish", pl: "Polish", tr: "Turkish" };

  function langOptions() {
    return state.meta.languages.map(l => [l, LANG_NAMES[l] ? `${LANG_NAMES[l]} (${l})` : l]);
  }

  // ------------------------------------------------------------------ chips
  function renderChipGroups(selectId, listId) {
    const groups = Object.keys(state.meta.presets);
    fillSelect($(selectId), groups.map(g => [g, g[0].toUpperCase() + g.slice(1)]), groups[0]);
    const render = () => {
      const list = $(listId);
      list.innerHTML = "";
      const target = $(list.dataset.target);
      for (const tag of state.meta.presets[$(selectId).value]) {
        const on = target.value.toLowerCase().includes(tag.toLowerCase());
        list.append(el("button", { class: "chip" + (on ? " on" : ""), text: tag, type: "button",
          onclick: () => { toggleTag(target, tag); render(); sfx("press"); } }));
      }
    };
    $(selectId).addEventListener("change", render);
    $($(listId).dataset.target).addEventListener("input", render);
    render();
  }

  function toggleTag(textarea, tag) {
    const parts = textarea.value.split(",").map(s => s.trim()).filter(Boolean);
    const i = parts.findIndex(p => p.toLowerCase() === tag.toLowerCase());
    if (i >= 0) parts.splice(i, 1); else parts.push(tag);
    textarea.value = parts.join(", ");
    textarea.dispatchEvent(new Event("input"));
  }

  function renderSectionChips() {
    const list = $("sectionChips");
    list.innerHTML = "";
    for (const tag of state.meta.section_tags) {
      list.append(el("button", { class: "chip", text: tag, type: "button", onclick: () => {
        const ta = $("lyrics");
        const before = ta.value.slice(0, ta.selectionStart || ta.value.length);
        const after = ta.value.slice(ta.selectionStart || ta.value.length);
        const sep = before && !before.endsWith("\n") ? "\n" : "";
        ta.value = `${before}${sep}${tag}\n${after}`;
        ta.focus(); sfx("press");
      } }));
    }
  }

  // ----------------------------------------------------------- pro controls
  function bindSlider(id, labelId, fmt = (v) => v) {
    const i = $(id), l = $(labelId);
    const upd = () => { l.textContent = fmt(i.value); };
    i.addEventListener("input", upd); upd();
  }

  function proFields() {
    const seedLocked = $("seedLock").checked && $("seed").value !== "";
    const p = {
      steps: +$("steps").value, guidance_scale: +$("guidance").value, shift: +$("shift").value,
      infer_method: $("inferMethod").value, audio_format: $("format").value,
      seed: seedLocked ? +$("seed").value : null, custom_timesteps: $("timesteps").value,
      use_adg: $("useAdg").checked, cfg_interval_start: +$("cfgStart").value, cfg_interval_end: +$("cfgEnd").value,
      thinking: $("thinking").checked, use_cot_metas: $("cotMetas").checked,
      use_cot_caption: $("cotCaption").checked, use_cot_language: $("cotLang").checked,
      lm_temperature: +$("lmTemp").value, lm_cfg_scale: +$("lmCfg").value, lm_top_k: +$("lmTopK").value,
      lm_top_p: +$("lmTopP").value, lm_negative_prompt: $("lmNeg").value,
      auto_score: $("autoScore").checked, auto_lrc: $("autoLrc").checked,
    };
    if (!document.body.classList.contains("pro")) {
      // Not showing pro controls: keep the model defaults except for the seed lock.
      return { seed: seedLocked ? +$("seed").value : null };
    }
    return p;
  }

  function autoArtChoice() {
    const v = $("autoArt").value;
    return v === "" ? null : v === "on";
  }

  // ------------------------------------------------------------- requests
  function requestSimple() {
    return {
      generation_mode: "simple", task: "text2music", description: $("simpleDesc").value.trim(),
      instrumental: $("simpleInstrumental").checked, vocal_language: $("simpleLang").value,
      batch_size: +$("simpleBatch").value, model: $("model").value, ...proFields(),
    };
  }

  function requestCustom() {
    return {
      generation_mode: "custom", task: "text2music", title: $("title").value.trim(),
      caption: $("caption").value.trim(), lyrics: $("lyrics").value, instrumental: $("instrumental").checked,
      vocal_language: $("lang").value, bpm: $("bpm").value || 0, key_scale: $("key").value.trim(),
      time_signature: $("timesig").value, duration: $("durationAuto").checked ? -1 : +$("duration").value,
      batch_size: +$("batch").value, model: $("model").value, ...proFields(),
    };
  }

  function requestCover() {
    const a = state.analysis || {};
    return {
      generation_mode: "custom", task: "cover", caption: $("coverCaption").value.trim(),
      lyrics: $("coverLyrics").value, instrumental: $("coverInstrumental").checked,
      vocal_language: $("coverLang").value, cover_strength: +$("coverStrength").value,
      audio_codes: ($("useCodes").checked && a.codes) ? a.codes : "",
      bpm: a.bpm || 0, key_scale: a.key_scale || "", time_signature: a.time_signature || "",
      batch_size: +$("coverBatch").value, model: $("model").value,
      title: state.coverSource ? `Cover of ${state.coverSource.name}` : "",
      ...proFields(),
    };
  }

  function requestEdit() {
    return {
      generation_mode: "custom", task: "repaint", caption: $("editCaption").value.trim(),
      lyrics: $("editLyrics").value, repaint_start: +$("repaintStart").value, repaint_end: +$("repaintEnd").value,
      batch_size: +$("editBatch").value, model: $("model").value,
      title: state.editSource ? `Repaint of ${state.editSource.name}` : "", ...proFields(),
    };
  }

  async function generate(req, source) {
    const body = { request: req, source: source || null, auto_art: autoArtChoice() };
    if (state.refSource) body.reference = { kind: state.refSource.kind, id: state.refSource.id };
    try {
      const job = await api("POST", "/api/generate", body);
      sfx("processing");
      toast(`Queued: ${job.label}`);
      watch(job, {
        onDone: async (j) => {
          sfx("complete");
          toast("Song ready", "ok");
          for (const id of (j.result && j.result.songs) || []) state.resultIds.unshift(id);
          state.resultIds = state.resultIds.slice(0, 8);
          await renderResults();
          refreshLibrary(true);
        },
        onError: (j) => showJobError(j),
      });
    } catch (e) { toast(e.message, "error"); }
  }

  function showJobError(j) {
    toast(j.error || "Failed", "error");
    if (j.error_kind === "QuotaError") {
      const box = $("quotaBox");
      box.classList.remove("hidden");
      box.innerHTML = "";
      box.append(el("h6", { text: "Free quota is spent" }),
        el("p", { class: "small-text", text: j.error }),
        el("p", { class: "small-text muted", text: j.retry_in ? `Refills in about ${fmtCountdown(j.retry_in)}.` : "" }),
        el("nav", { class: "actions" }, [
          el("button", { class: "border small", onclick: () => showPage("settings") }, [el("i", { text: "settings" }), el("span", { text: "Change backend" })]),
        ]));
    }
  }

  // ------------------------------------------------------------------ jobs
  function watch(job, handlers) {
    state.watched.set(job.id, handlers);
    state.jobs.unshift(job);
    renderJobs();
    startPolling();
  }

  function startPolling() {
    if (state.pollTimer) return;
    const tick = async () => {
      try {
        const jobs = await api("GET", "/api/jobs");
        state.jobs = jobs;
        for (const j of jobs) {
          const h = state.watched.get(j.id);
          if (!h) continue;
          if (j.status === "done") { state.watched.delete(j.id); h.onDone && h.onDone(j); }
          else if (j.status === "error" || j.status === "cancelled") { state.watched.delete(j.id); h.onError && h.onError(j); }
        }
        renderJobs();
      } catch (e) { /* server hiccup; keep polling */ }
      const active = state.jobs.some(j => j.status === "queued" || j.status === "running");
      state.pollTimer = setTimeout(tick, active ? 1500 : 6000);
    };
    state.pollTimer = setTimeout(tick, 400);
  }

  function renderJobs() {
    const active = state.jobs.filter(j => j.status === "queued" || j.status === "running").length;
    const badge = $("queueBadge");
    badge.textContent = active || "";
    badge.classList.toggle("none", !active);
    const rail = $("healthPill");
    if (active) { rail.classList.add("busy"); }
    else { rail.classList.remove("busy"); }

    const list = $("jobList");
    if (!$("page-queue").classList.contains("active")) return;
    list.innerHTML = "";
    if (!state.jobs.length) { list.append(el("p", { class: "muted", text: "No jobs yet." })); return; }
    for (const j of state.jobs) {
      const p = j.progress || {};
      let detail = "";
      if (j.status === "running") {
        const bits = [];
        if (p.stage) bits.push(p.stage);
        if (p.detail && p.detail !== p.stage) bits.push(p.detail);
        if (p.rank !== undefined && p.rank !== null && p.stage === "queued") bits.push(`position ${p.rank + 1}${p.queue_size ? ` of ${p.queue_size}` : ""}`);
        if (p.eta) bits.push(`eta ${Math.round(p.eta)} s`);
        if (p.elapsed) bits.push(`${Math.round(p.elapsed)} s elapsed`);
        detail = bits.join(" · ");
      } else if (j.status === "done") {
        detail = `finished ${fmtAgo(j.finished)}` + (j.result && j.result.songs ? ` · ${j.result.songs.length} song(s)` : "");
      } else if (j.status === "queued") {
        detail = `queued ${fmtAgo(j.created)}`;
      } else {
        detail = `${j.status} ${fmtAgo(j.finished || j.created)}`;
      }
      const row = el("div", { class: "job" }, [
        el("span", { class: `state ${j.status}`, text: j.status }),
        el("span", { class: "label", text: j.label || j.kind }),
        (j.status === "queued" || j.status === "running")
          ? el("button", { class: "transparent circle small", title: "Cancel", onclick: async () => { await api("POST", `/api/jobs/${j.id}/cancel`); } }, [el("i", { text: "close" })])
          : el("span", { class: "small-text muted", text: j.kind }),
        el("span", { class: "detail", text: detail }),
      ]);
      if (j.status === "running") row.append(el("progress", { class: "small" }));
      if (j.error) row.append(el("div", { class: "err", text: j.error }));
      list.append(row);
    }
  }

  // --------------------------------------------------------------- library
  async function refreshLibrary(force = false) {
    if (!force && Date.now() - state.lastLibraryFetch < 2000) return;
    state.lastLibraryFetch = Date.now();
    const q = encodeURIComponent($("libSearch").value.trim());
    const [songs, uploads] = await Promise.all([
      api("GET", `/api/songs?q=${q}&sort=${$("libSort").value}&fav=${$("libFav").checked ? 1 : 0}`),
      api("GET", "/api/uploads"),
    ]);
    state.songs = songs; state.uploads = uploads;
    renderLibrary(); renderUploads();
  }

  function songCard(s) {
    const art = el("div", { class: "art" }, [
      s.art ? el("img", { src: `/media/song/${s.id}/art?t=${Math.round(s.created)}`, alt: "" }) : el("i", { text: "music_note" }),
      el("span", { class: "task", text: s.task === "text2music" ? (s.mode === "simple" ? "simple" : "song") : s.task }),
    ]);
    const meta = el("div", { class: "meta" }, [
      s.duration ? el("span", { text: fmtDur(s.duration) }) : null,
      s.bpm ? el("span", { text: `${Math.round(s.bpm)} bpm` }) : null,
      s.key_scale ? el("span", { text: s.key_scale }) : null,
      s.seed ? el("span", { text: `seed ${s.seed}` }) : null,
      el("span", { text: fmtAgo(s.created) }),
    ]);
    const tools = el("div", { class: "tools" }, [
      iconBtn(s.favorite ? "favorite" : "favorite_border", s.favorite ? "Unfavorite" : "Favorite", async () => {
        await api("PATCH", `/api/songs/${s.id}`, { favorite: !s.favorite }); sfx(s.favorite ? "toggle-off" : "toggle-on"); refreshLibrary(true);
      }, s.favorite ? "fav" : ""),
      el("a", { class: "button transparent circle", href: `/media/song/${s.id}?download=1`, title: "Download" }, [el("i", { text: "download" })]),
      iconBtn("swap_horiz", "Cover this", () => { setCoverSource({ kind: "song", id: s.id, name: s.title, duration: s.duration }); showPage("create"); showTab("cover"); }),
      iconBtn("content_cut", "Repaint", () => { setEditSource({ kind: "song", id: s.id, name: s.title, duration: s.duration }); showPage("create"); showTab("edit"); }),
      iconBtn("call_split", "Split stems", () => stems("song", s.id, s.title)),
      iconBtn("image", s.art ? "Redo art" : "Make art", () => art_(s)),
      iconBtn("replay", "Reuse settings", () => reuse(s)),
      iconBtn("info", "Details", () => songDetails(s)),
      iconBtn("delete", "Delete", () => confirmDelete("Delete song?", `"${s.title}" and its files will be removed.`, async () => {
        await api("DELETE", `/api/songs/${s.id}`); toast("Deleted"); refreshLibrary(true);
      })),
    ]);
    const card = el("article", { class: "song-card no-padding" }, [
      art,
      el("div", { class: "body" }, [
        el("div", { class: "title" }, [el("span", { text: s.title || "Untitled", title: s.title })]),
        meta,
        s.caption ? el("div", { class: "caption", text: s.caption }) : null,
        el("audio", { controls: true, preload: "none", src: `/media/song/${s.id}` }),
      ]),
    ]);
    const stemsNames = Object.keys(s.stems || {});
    if (stemsNames.length) {
      card.append(el("div", { class: "stem-list" }, stemsNames.map(n => el("a", { href: `/media/song/${s.id}/stem/${n}?download=1`, text: n }))));
    }
    card.append(tools);
    return card;
  }

  function iconBtn(icon, title, onclick, cls = "") {
    return el("button", { class: `transparent circle ${cls}`, title, type: "button", onclick }, [el("i", { text: icon })]);
  }

  function renderLibrary() {
    const grid = $("songGrid");
    grid.innerHTML = "";
    $("libEmpty").classList.toggle("hidden", state.songs.length > 0);
    for (const s of state.songs) {
      grid.append(el("div", { class: "s12 m6 l4 xl3" }, [songCard(s)]));
    }
  }

  function renderUploads() {
    const list = $("uploadsList");
    list.innerHTML = "";
    $("uploadsCount").textContent = state.uploads.length || "";
    $("uploadsCount").classList.toggle("hidden", !state.uploads.length);
    if (!state.uploads.length) { list.append(el("p", { class: "muted small-text", text: "No uploads yet. Drop a file above." })); return; }
    for (const u of state.uploads) {
      const stemsNames = Object.keys(u.stems || {});
      list.append(el("div", { class: "pick" }, [
        el("i", { text: "audio_file" }),
        el("span", { class: "name", text: u.name, title: u.name }),
        el("span", { class: "dur", text: fmtDur(u.duration) }),
        el("audio", { controls: true, preload: "none", src: `/media/upload/${u.id}`, style: "height:2rem;max-width:14rem" }),
        ...stemsNames.map(n => el("a", { class: "chip small", href: `/media/upload/${u.id}/stem/${n}?download=1`, text: n })),
        iconBtn("swap_horiz", "Cover this", () => { setCoverSource({ kind: "upload", id: u.id, name: u.name, duration: u.duration }); showPage("create"); showTab("cover"); }),
        iconBtn("call_split", "Split stems", () => stems("upload", u.id, u.name)),
        iconBtn("delete", "Delete", () => confirmDelete("Delete upload?", `${u.name} will be removed.`, async () => {
          await api("DELETE", `/api/uploads/${u.id}`); refreshLibrary(true);
        })),
      ]));
    }
  }

  async function uploadFiles(files) {
    let last = null;
    for (const f of files) {
      const fd = new FormData(); fd.append("file", f);
      try { last = await api("POST", "/api/uploads", fd, true); toast(`Added ${f.name}`, "ok"); }
      catch (e) { toast(e.message, "error"); }
    }
    refreshLibrary(true);
    return last;
  }

  function stems(kind, id, name) {
    const mode = document.body.classList.contains("pro") && confirm("Four stems (vocals, drums, bass, other)? Cancel for vocals + instrumental.") ? "four" : "two";
    api("POST", kind === "song" ? `/api/songs/${id}/stems` : `/api/uploads/${id}/stems`, { mode })
      .then(job => { sfx("processing"); toast(`Splitting stems: ${name}`); watch(job, {
        onDone: () => { sfx("complete"); toast("Stems ready", "ok"); refreshLibrary(true); if (state.coverSource && state.coverSource.id === id) updateSourceStems(); },
        onError: (j) => toast(j.error, "error") }); })
      .catch(e => toast(e.message, "error"));
  }

  function art_(s) {
    const prompt = document.body.classList.contains("pro") ? (window.prompt("Art prompt (blank = automatic)", s.art_prompt || "") || "") : "";
    api("POST", `/api/songs/${s.id}/art`, { prompt })
      .then(job => { toast("Painting cover art"); watch(job, { onDone: () => { sfx("success"); refreshLibrary(true); renderResults(); }, onError: (j) => toast(j.error, "error") }); })
      .catch(e => toast(e.message, "error"));
  }

  function reuse(s) {
    const r = s.request || {};
    showPage("create");
    if (r.task === "cover") { showTab("cover"); $("coverCaption").value = r.caption || ""; $("coverLyrics").value = r.lyrics || ""; $("coverStrength").value = r.cover_strength ?? 1; $("coverStrength").dispatchEvent(new Event("input")); }
    else if (r.task === "repaint") { showTab("edit"); $("editCaption").value = r.caption || ""; $("editLyrics").value = r.lyrics || ""; $("repaintStart").value = r.repaint_start ?? 0; $("repaintEnd").value = r.repaint_end ?? -1; }
    else if (r.generation_mode === "simple") { showTab("simple"); $("simpleDesc").value = r.description || ""; $("simpleInstrumental").checked = !!r.instrumental; $("simpleLang").value = r.vocal_language || "unknown"; }
    else {
      showTab("custom");
      $("title").value = s.title || ""; $("caption").value = r.caption || ""; $("lyrics").value = r.lyrics || "";
      $("instrumental").checked = !!r.instrumental; $("lang").value = r.vocal_language || "unknown";
      $("bpm").value = r.bpm || ""; $("key").value = r.key_scale || ""; $("timesig").value = r.time_signature || "";
      const auto = !(r.duration > 0); $("durationAuto").checked = auto; $("duration").disabled = auto; if (!auto) $("duration").value = r.duration;
      $("duration").dispatchEvent(new Event("input"));
      $("batch").value = r.batch_size || 1;
    }
    if (r.model) $("model").value = r.model;
    if (r.seed !== null && r.seed !== undefined) { $("seed").value = r.seed; $("seedLock").checked = true; }
    for (const [id, key] of [["steps", "steps"], ["guidance", "guidance_scale"], ["shift", "shift"], ["lmTemp", "lm_temperature"], ["lmCfg", "lm_cfg_scale"]]) {
      if (r[key] !== undefined) { $(id).value = r[key]; $(id).dispatchEvent(new Event("input")); }
    }
    if (r.infer_method) $("inferMethod").value = r.infer_method;
    if (r.audio_format) $("format").value = r.audio_format;
    if (typeof r.thinking === "boolean") $("thinking").checked = r.thinking;
    $("caption").dispatchEvent(new Event("input")); $("coverCaption").dispatchEvent(new Event("input"));
    toast("Settings loaded into the form");
  }

  function songDetails(s) {
    $("dlgSongTitle").textContent = s.title || "Untitled";
    const body = $("dlgSongBody");
    body.innerHTML = "";
    const kv = el("dl", { class: "kv" });
    const rows = [["Task", s.task], ["Mode", s.mode], ["Model", s.model], ["Engine", s.engine], ["Seed", s.seed],
      ["Length", fmtDur(s.duration)], ["BPM", s.bpm], ["Key", s.key_scale], ["Time signature", s.time_signature],
      ["Language", s.vocal_language], ["Cover strength", s.cover_strength], ["Score", s.score], ["Created", new Date(s.created * 1000).toLocaleString()]];
    for (const [k, v] of rows) if (v !== null && v !== undefined && v !== "") kv.append(el("dt", { text: k }), el("dd", { text: String(v) }));
    body.append(el("audio", { controls: true, src: `/media/song/${s.id}`, style: "width:100%" }));
    body.append(el("div", { class: "field label border", style: "margin-top:.75rem" }, [
      el("input", { type: "text", id: "dlgSongRename", value: s.title || "", placeholder: " " }), el("label", { text: "Title" })]));
    body.append(kv);
    if (s.caption) body.append(el("p", { class: "small-text" }, [el("b", { text: "Tags: " }), s.caption]));
    if (s.description) body.append(el("p", { class: "small-text" }, [el("b", { text: "Brief: " }), s.description]));
    if (s.lyrics) body.append(el("h6", { class: "small", text: "Lyrics" }), el("div", { class: "song-lyrics", text: s.lyrics }));
    if (s.lrc) body.append(el("h6", { class: "small", text: "Timed lyrics (LRC)" }), el("div", { class: "song-lyrics", text: s.lrc }));
    if (s.details) body.append(el("h6", { class: "small", text: "Generation details" }), el("div", { class: "song-lyrics", text: s.details }));
    body.append(el("nav", { class: "actions" }, [
      el("button", { class: "border small", onclick: () => { navigator.clipboard.writeText(JSON.stringify(s.request || {}, null, 2)); toast("Request JSON copied"); } }, [el("i", { text: "content_copy" }), el("span", { text: "Copy request" })]),
      el("div", { class: "max" }),
      el("button", { onclick: async () => {
        const title = $("dlgSongRename").value.trim();
        await api("PATCH", `/api/songs/${s.id}`, { title }); closeDialog("dlgSong"); refreshLibrary(true); renderResults(); toast("Saved", "ok");
      } }, [el("i", { text: "save" }), el("span", { text: "Save" })]),
    ]));
    openDialog("dlgSong");
  }

  async function renderResults() {
    const list = $("resultList");
    if (!state.resultIds.length) return;
    list.innerHTML = "";
    for (const id of state.resultIds) {
      try {
        const s = await api("GET", `/api/songs/${id}`);
        list.append(el("div", { class: "result" }, [
          el("div", { class: "row" }, [
            s.art ? el("img", { src: `/media/song/${s.id}/art?t=${Date.now()}`, style: "width:3rem;height:3rem;object-fit:cover" }) : el("i", { text: "music_note" }),
            el("div", { class: "max" }, [el("div", { class: "title", text: s.title }), el("div", { class: "meta", text: [fmtDur(s.duration), s.seed ? `seed ${s.seed}` : "", s.task].filter(Boolean).join(" · ") })]),
            iconBtn("info", "Details", () => songDetails(s)),
            el("a", { class: "button transparent circle", href: `/media/song/${s.id}?download=1`, title: "Download" }, [el("i", { text: "download" })]),
          ]),
          el("audio", { controls: true, preload: "none", src: `/media/song/${s.id}` }),
        ]));
      } catch (e) { /* song may have been deleted */ }
    }
  }

  // ------------------------------------------------------------- sources
  function pickSource(cb) {
    state.sourcePickCallback = cb;
    const list = $("dlgSourceList");
    list.innerHTML = "";
    Promise.all([api("GET", "/api/uploads"), api("GET", "/api/songs")]).then(([uploads, songs]) => {
      if (!uploads.length && !songs.length) list.append(el("p", { class: "muted small-text", text: "Nothing yet. Upload a track first." }));
      for (const u of uploads) list.append(el("div", { class: "pick", onclick: () => { closeDialog("dlgSource"); cb({ kind: "upload", id: u.id, name: u.name, duration: u.duration, analysis: u.analysis, codes: u.codes }); } }, [
        el("i", { text: "audio_file" }), el("span", { class: "name", text: u.name }), el("span", { class: "dur", text: fmtDur(u.duration) })]));
      for (const s of songs) list.append(el("div", { class: "pick", onclick: () => { closeDialog("dlgSource"); cb({ kind: "song", id: s.id, name: s.title, duration: s.duration }); } }, [
        el("i", { text: "library_music" }), el("span", { class: "name", text: s.title }), el("span", { class: "dur", text: fmtDur(s.duration) })]));
    });
    openDialog("dlgSource");
  }

  function setCoverSource(src) {
    state.coverSource = src; state.analysis = null;
    $("coverSourceName").textContent = src ? `${src.name} (${fmtDur(src.duration)})` : "no source yet";
    $("coverSourceName").classList.toggle("muted", !src);
    const a = $("coverPreview");
    if (src) { a.src = src.kind === "upload" ? `/media/upload/${src.id}` : `/media/song/${src.id}`; a.classList.remove("hidden"); }
    else a.classList.add("hidden");
    $("btnAnalyze").disabled = !src; $("btnCoverStems").disabled = !src; $("btnCoverGenerate").disabled = !src;
    $("analysisBox").classList.add("hidden");
    if (src && src.analysis) applyAnalysis({ ...src.analysis, codes: src.codes || "" }, false);
  }

  function updateSourceStems() { /* stems show on the library page; nothing to refresh here */ }

  function applyAnalysis(a, overwrite = true) {
    state.analysis = a;
    const box = $("analysisBox");
    box.innerHTML = "";
    box.append(el("div", { html: `<b>Heard:</b> ${a.caption || "?"}` }),
      el("div", { class: "muted", text: [a.bpm ? `${Math.round(a.bpm)} bpm` : "", a.key_scale, a.time_signature ? `${a.time_signature}/4` : "", a.vocal_language && a.vocal_language !== "unknown" ? `lang ${a.vocal_language}` : "", a.codes ? "codes ready" : ""].filter(Boolean).join(" · ") }));
    box.classList.remove("hidden");
    if (overwrite || !$("coverCaption").value.trim()) $("coverCaption").value = a.caption || "";
    if (overwrite || !$("coverLyrics").value.trim()) $("coverLyrics").value = a.lyrics || "";
    if (a.vocal_language) $("coverLang").value = a.vocal_language;
    $("coverCaption").dispatchEvent(new Event("input"));
  }

  function setEditSource(src) {
    state.editSource = src;
    $("editSourceName").textContent = src ? `${src.name} (${fmtDur(src.duration)})` : "no source yet";
    $("editSourceName").classList.toggle("muted", !src);
    const a = $("editPreview");
    if (src) { a.src = src.kind === "upload" ? `/media/upload/${src.id}` : `/media/song/${src.id}`; a.classList.remove("hidden"); }
    else a.classList.add("hidden");
    $("btnEditGenerate").disabled = !src;
    if (src && src.duration) { $("repaintEnd").max = Math.ceil(src.duration); }
  }

  function setRefSource(src) {
    state.refSource = src;
    $("refSourceName").textContent = src ? `${src.name} (${fmtDur(src.duration)})` : "none";
  }

  // ------------------------------------------------------------ settings
  function fillSettings() {
    const c = state.cfg;
    qsa('input[name="backend"]').forEach(r => { r.checked = r.value === c.backend; });
    $("cfgSpace").value = c.space_id; $("cfgUseToken").checked = !!c.use_token; $("cfgApiUrl").value = c.api_url;
    $("tokenState").textContent = c.has_token ? "token found" : "no token in .env";
    fillSelect($("cfgModel"), state.meta.models, c.default_model);
    $("cfgBatch").value = c.default_batch; $("cfgAutoArt").checked = !!c.auto_art; $("cfgArtSize").value = c.art_size;
    $("cfgStems").value = c.stems_engine; $("cfgWriter").value = c.lyric_writer; $("cfgClaudeModel").value = c.claude_model;
    $("cfgSfx").checked = !!c.sfx; $("cfgMode").value = c.theme_mode; $("cfgSeed").value = c.theme_seed;
  }

  async function saveSettings() {
    const patch = {
      backend: (qs('input[name="backend"]:checked') || {}).value || "space",
      space_id: $("cfgSpace").value.trim(), use_token: $("cfgUseToken").checked, api_url: $("cfgApiUrl").value.trim(),
      default_model: $("cfgModel").value, default_batch: +$("cfgBatch").value, auto_art: $("cfgAutoArt").checked,
      art_size: +$("cfgArtSize").value, stems_engine: $("cfgStems").value, lyric_writer: $("cfgWriter").value,
      claude_model: $("cfgClaudeModel").value.trim(), sfx: $("cfgSfx").checked, theme_mode: $("cfgMode").value,
      theme_seed: $("cfgSeed").value,
    };
    state.cfg = await api("POST", "/api/config", patch);
    applyTheme(); applyDefaults(); toast("Settings saved", "ok"); sfx("success");
    checkHealth(true);
  }

  function applyDefaults() {
    const c = state.cfg;
    $("model").value = c.default_model;
    $("batch").value = c.default_batch; $("simpleBatch").value = Math.min(4, c.default_batch); $("coverBatch").value = Math.min(4, c.default_batch);
    $("lyrWriter").value = c.lyric_writer;
  }

  async function checkHealth(force = false) {
    const pill = $("healthPill"), txt = $("healthText");
    txt.textContent = "checking";
    try {
      const h = await api("GET", `/api/health${force ? "?force=1" : ""}`);
      pill.classList.toggle("ok", !!h.ok); pill.classList.toggle("bad", !h.ok);
      txt.textContent = h.engine === "space" ? (h.ok ? "space" : "space down") : h.engine === "api" ? (h.ok ? "server" : "server down") : "mock";
      pill.title = h.ok ? `${h.engine} ok` : (h.error || "backend unreachable");
      $("healthBox").textContent = JSON.stringify(h, null, 2);
      if (h.drift && h.drift.length) toast("The Space's API moved; check Settings", "error");
    } catch (e) { pill.classList.add("bad"); txt.textContent = "offline"; $("healthBox").textContent = e.message; }
  }

  // ------------------------------------------------------------ describe
  function describeThenCustom() {
    const desc = $("simpleDesc").value.trim();
    if (!desc) return toast("Describe the song first.", "error");
    api("POST", "/api/describe", { description: desc, instrumental: $("simpleInstrumental").checked, vocal_language: $("simpleLang").value })
      .then(job => { toast("Writing tags and lyrics"); watch(job, { onDone: (j) => {
        const r = j.result || {};
        $("caption").value = r.caption || ""; $("lyrics").value = r.lyrics || "";
        $("instrumental").checked = !!r.instrumental; $("lang").value = r.vocal_language || "unknown";
        $("bpm").value = r.bpm || ""; $("key").value = r.key_scale || ""; $("timesig").value = r.time_signature || "";
        if (r.duration && r.duration > 0) { $("durationAuto").checked = false; $("duration").disabled = false; $("duration").value = Math.round(r.duration); }
        $("duration").dispatchEvent(new Event("input")); $("caption").dispatchEvent(new Event("input"));
        showTab("custom"); sfx("success"); toast("Draft ready. Edit anything, then Generate.", "ok");
      }, onError: (j) => showJobError(j) }); })
      .catch(e => toast(e.message, "error"));
  }

  function enhance() {
    api("POST", "/api/enhance", { caption: $("caption").value, lyrics: $("lyrics").value, bpm: $("bpm").value || 0,
      duration: $("durationAuto").checked ? -1 : +$("duration").value, key_scale: $("key").value, time_signature: $("timesig").value })
      .then(job => { toast("Polishing with the music model"); watch(job, { onDone: (j) => {
        const r = j.result || {};
        if (r.caption) $("caption").value = r.caption; if (r.lyrics) $("lyrics").value = r.lyrics;
        if (r.bpm) $("bpm").value = Math.round(r.bpm); if (r.key_scale) $("key").value = r.key_scale; if (r.time_signature) $("timesig").value = r.time_signature;
        $("caption").dispatchEvent(new Event("input")); sfx("success"); toast("Enhanced", "ok");
      }, onError: (j) => showJobError(j) }); })
      .catch(e => toast(e.message, "error"));
  }

  function surprise() {
    api("POST", "/api/random", {}).then(job => watch(job, { onDone: (j) => {
      const r = j.result || {};
      $("simpleDesc").value = r.description || ""; $("simpleInstrumental").checked = !!r.instrumental;
      $("simpleLang").value = r.vocal_language || "unknown"; sfx("notification");
    }, onError: (j) => toast(j.error, "error") })).catch(e => toast(e.message, "error"));
  }

  function captionFromBrief() {
    const brief = window.prompt("Describe the song in a sentence; Claude turns it into style tags.", "");
    if (!brief) return;
    api("POST", "/api/caption", { description: brief }).then(job => watch(job, { onDone: (j) => {
      $("caption").value = (j.result || {}).caption || ""; $("caption").dispatchEvent(new Event("input")); sfx("success");
    }, onError: (j) => toast(j.error, "error") })).catch(e => toast(e.message, "error"));
  }

  function openLyricWriter() {
    $("lyrStyle").value = $("caption").value; $("lyrLang").value = $("lang").value === "unknown" ? "en" : $("lang").value;
    $("lyrResult").classList.add("hidden"); $("btnLyrUse").disabled = true; state.lastLyrics = "";
    openDialog("dlgLyrics");
  }

  function writeLyrics() {
    const theme = $("lyrTheme").value.trim();
    if (!theme) return toast("Give the writer a theme.", "error");
    $("btnLyrWrite").disabled = true;
    api("POST", "/api/lyrics", { theme, style: $("lyrStyle").value, language: $("lyrLang").value, structure: $("lyrStructure").value, writer: $("lyrWriter").value })
      .then(job => watch(job, { onDone: (j) => {
        $("btnLyrWrite").disabled = false;
        state.lastLyrics = (j.result || {}).lyrics || "";
        $("lyrResult").textContent = state.lastLyrics; $("lyrResult").classList.remove("hidden"); $("btnLyrUse").disabled = !state.lastLyrics; sfx("success");
      }, onError: (j) => { $("btnLyrWrite").disabled = false; showJobError(j); } }))
      .catch(e => { $("btnLyrWrite").disabled = false; toast(e.message, "error"); });
  }

  function analyzeCover() {
    const s = state.coverSource; if (!s) return;
    api("POST", "/api/analyze", { kind: s.kind, id: s.id }).then(job => { toast("Listening to the track"); watch(job, {
      onDone: (j) => { applyAnalysis(j.result || {}, true); sfx("success"); toast("Analysis done", "ok"); },
      onError: (j) => showJobError(j) }); }).catch(e => toast(e.message, "error"));
  }

  // ---------------------------------------------------------------- init
  async function init() {
    [state.meta, state.cfg] = await Promise.all([api("GET", "/api/meta"), api("GET", "/api/config")]);
    for (const id of ["simpleLang", "lang", "coverLang"]) fillSelect($(id), langOptions(), "unknown");
    fillSelect($("lyrLang"), langOptions().filter(([l]) => l !== "unknown"), "en");
    fillSelect($("model"), state.meta.models, state.cfg.default_model);
    renderChipGroups("chipGroup", "chipList");
    renderChipGroups("coverChipGroup", "coverChipList");
    renderSectionChips();
    bindSlider("steps", "stepsLabel"); bindSlider("guidance", "guidanceLabel", v => (+v).toFixed(1));
    bindSlider("shift", "shiftLabel", v => (+v).toFixed(1)); bindSlider("lmTemp", "lmTempLabel", v => (+v).toFixed(2));
    bindSlider("lmCfg", "lmCfgLabel", v => (+v).toFixed(1)); bindSlider("coverStrength", "coverStrengthLabel", v => (+v).toFixed(2));
    bindSlider("duration", "durationLabel", v => $("durationAuto").checked ? "auto" : fmtDur(+v));
    $("durationAuto").addEventListener("change", () => { $("duration").disabled = $("durationAuto").checked; $("duration").dispatchEvent(new Event("input")); });
    applyDefaults(); applyTheme();

    // navigation
    qsa("#rail a[data-page]").forEach(a => a.addEventListener("click", () => { showPage(a.dataset.page); sfx("press"); }));
    qsa("#createTabs a").forEach(a => a.addEventListener("click", () => { showTab(a.dataset.tab); sfx("press"); }));
    $("proSwitch").addEventListener("change", () => { document.body.classList.toggle("pro", $("proSwitch").checked); sfx($("proSwitch").checked ? "toggle-on" : "toggle-off"); });
    qsa("[data-close]").forEach(b => b.addEventListener("click", () => closeDialog(b.dataset.close)));
    $("btnConfirmOk").addEventListener("click", () => { closeDialog("dlgConfirm"); state.confirmCallback && state.confirmCallback(); });

    // create actions
    $("btnSurprise").addEventListener("click", surprise);
    $("btnWriteFirst").addEventListener("click", describeThenCustom);
    $("btnSimpleGenerate").addEventListener("click", () => { const r = requestSimple(); if (!r.description) return toast("Describe the song first.", "error"); generate(r); });
    $("btnGenerate").addEventListener("click", () => { const r = requestCustom(); if (!r.caption && (!r.lyrics.trim() || r.instrumental)) return toast("Add style tags or lyrics.", "error"); generate(r); });
    $("btnCoverGenerate").addEventListener("click", () => { if (!state.coverSource) return; const r = requestCover(); if (!r.caption) return toast("Give the cover some style tags.", "error"); generate(r, { kind: state.coverSource.kind, id: state.coverSource.id, name: state.coverSource.name }); });
    $("btnEditGenerate").addEventListener("click", () => { if (!state.editSource) return; const r = requestEdit(); if (!r.caption) return toast("Describe the repainted part.", "error"); generate(r, { kind: state.editSource.kind, id: state.editSource.id, name: state.editSource.name }); });
    $("btnCaptionFromBrief").addEventListener("click", captionFromBrief);
    $("btnEnhance").addEventListener("click", enhance);
    $("btnWriteLyrics").addEventListener("click", openLyricWriter);
    $("btnLyrWrite").addEventListener("click", writeLyrics);
    $("btnLyrUse").addEventListener("click", () => { $("lyrics").value = state.lastLyrics; closeDialog("dlgLyrics"); toast("Lyrics placed", "ok"); });
    $("btnPickCover").addEventListener("click", () => pickSource(setCoverSource));
    $("btnPickEdit").addEventListener("click", () => pickSource(setEditSource));
    $("btnPickRef").addEventListener("click", () => pickSource(setRefSource));
    $("btnClearRef").addEventListener("click", () => setRefSource(null));
    $("btnAnalyze").addEventListener("click", analyzeCover);
    $("btnCoverStems").addEventListener("click", () => state.coverSource && stems(state.coverSource.kind, state.coverSource.id, state.coverSource.name));
    $("dlgSourceUpload").addEventListener("click", () => { $("uploadInput").onchange = async () => { const u = await uploadFiles($("uploadInput").files); $("uploadInput").value = ""; if (u && state.sourcePickCallback) { closeDialog("dlgSource"); state.sourcePickCallback({ kind: "upload", id: u.id, name: u.name, duration: u.duration }); } }; $("uploadInput").click(); });

    // library
    $("btnUpload").addEventListener("click", () => { $("uploadInput").onchange = async () => { await uploadFiles($("uploadInput").files); $("uploadInput").value = ""; }; $("uploadInput").click(); });
    $("libSearch").addEventListener("input", () => refreshLibrary(true));
    $("libSort").addEventListener("change", () => refreshLibrary(true));
    $("libFav").addEventListener("change", () => refreshLibrary(true));
    const dz = $("dropZone");
    ["dragenter", "dragover"].forEach(ev => dz.addEventListener(ev, e => { e.preventDefault(); dz.classList.add("over"); }));
    ["dragleave", "drop"].forEach(ev => dz.addEventListener(ev, e => { e.preventDefault(); dz.classList.remove("over"); }));
    dz.addEventListener("drop", e => uploadFiles(e.dataTransfer.files));
    document.addEventListener("dragover", e => e.preventDefault());
    document.addEventListener("drop", e => { if (!dz.contains(e.target)) { e.preventDefault(); if (e.dataTransfer.files.length) { showPage("library"); uploadFiles(e.dataTransfer.files); } } });

    // queue + settings
    $("btnClearJobs").addEventListener("click", async () => { await api("POST", "/api/jobs/clear"); startPolling(); });
    $("btnSaveSettings").addEventListener("click", () => saveSettings().catch(e => toast(e.message, "error")));
    $("btnTestBackend").addEventListener("click", () => saveSettings().then(() => checkHealth(true)).catch(e => toast(e.message, "error")));

    // keyboard: cmd/ctrl+enter generates in the active tab
    document.addEventListener("keydown", e => {
      if ((e.metaKey || e.ctrlKey) && e.key === "Enter" && $("page-create").classList.contains("active")) {
        const tab = qs("#createTabs a.active").dataset.tab;
        ({ simple: "btnSimpleGenerate", custom: "btnGenerate", cover: "btnCoverGenerate", edit: "btnEditGenerate" })[tab] && $({ simple: "btnSimpleGenerate", custom: "btnGenerate", cover: "btnCoverGenerate", edit: "btnEditGenerate" }[tab]).click();
      }
    });

    checkHealth();
    startPolling();
    refreshLibrary(true);
  }

  window.addEventListener("DOMContentLoaded", () => init().catch(e => { console.error(e); toast(`Startup failed: ${e.message}`, "error"); }));
})();
