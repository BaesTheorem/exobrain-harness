/* Study Bible PWA: split-screen reader for the Skeptic's Annotated
   Bible and Book of Mormon, with highlights, notes, and backup. */
'use strict';

const CATS = {
  a: 'Absurdity', i: 'Injustice', v: 'Cruelty & Violence', int: 'Intolerance',
  c: 'Contradiction', sci: 'Science & History', f: 'Family Values',
  interp: 'Interpretation', pr: 'Prophecy', w: 'Women', l: 'Language',
  s: 'Sex', h: 'Homosexuality', pol: 'Politics', g: 'Good Stuff',
  plag: 'Plagiarism', b: 'Boring', ejat: 'Every Jot & Tittle',
};

const GIST_FILENAME = 'study-bible-backup.json';

let manifest = null;
let panes = [];
let activePane = 0;
let selected = null;          // {key, ref, text}
const bookCache = new Map();  // "corpus/slug" -> book json
const ann = new Map();        // verse key -> record

const state = loadState();

function loadState() {
  const defaults = {
    split: false,
    theme: 'auto',
    fontSize: 17,
    panes: [
      { corpus: 'bible', slug: 'gen', chapter: 1, notes: true },
      { corpus: 'bom', slug: '1ne', chapter: 1, notes: true },
    ],
  };
  try {
    return Object.assign(defaults, JSON.parse(localStorage.getItem('sb-state') || '{}'));
  } catch { return defaults; }
}
function saveState() {
  state.panes = panes.map(p => ({ corpus: p.corpus, slug: p.slug, chapter: p.chapter, notes: p.notes }));
  localStorage.setItem('sb-state', JSON.stringify(state));
}

/* ------------------------------------------------ IndexedDB ------ */

const idb = {
  db: null,
  open() {
    return new Promise((resolve, reject) => {
      const req = indexedDB.open('study-bible', 1);
      req.onupgradeneeded = () => {
        req.result.createObjectStore('verses', { keyPath: 'key' });
      };
      req.onsuccess = () => { this.db = req.result; resolve(); };
      req.onerror = () => reject(req.error);
    });
  },
  tx(mode) { return this.db.transaction('verses', mode).objectStore('verses'); },
  getAll() {
    return new Promise((resolve, reject) => {
      const req = this.tx('readonly').getAll();
      req.onsuccess = () => resolve(req.result);
      req.onerror = () => reject(req.error);
    });
  },
  put(rec) {
    return new Promise((resolve, reject) => {
      const req = this.tx('readwrite').put(rec);
      req.onsuccess = () => resolve();
      req.onerror = () => reject(req.error);
    });
  },
};

async function loadAnnotations() {
  (await idb.getAll()).forEach(r => ann.set(r.key, r));
}

function annFor(key) {
  const r = ann.get(key);
  return (r && !r.deleted) ? r : null;
}

async function updateAnn(key, changes, meta) {
  let rec = ann.get(key) || { key };
  rec = Object.assign(rec, meta || {}, changes, { updatedAt: Date.now() });
  rec.deleted = !rec.hl && !rec.note;
  ann.set(key, rec);
  await idb.put(rec);
  refreshVerse(key);
  scheduleSync();
}

/* ------------------------------------------------ data loading --- */

async function fetchJSON(url) {
  const r = await fetch(url);
  if (!r.ok) throw new Error(`${url}: HTTP ${r.status}`);
  return r.json();
}

async function loadBook(corpus, slug) {
  const id = `${corpus}/${slug}`;
  if (bookCache.has(id)) return bookCache.get(id);
  const book = await fetchJSON(`data/${corpus}/${slug}.json`);
  if (bookCache.size > 8) bookCache.delete(bookCache.keys().next().value);
  bookCache.set(id, book);
  return book;
}

function bookMeta(corpus, slug) {
  const c = manifest.corpora[corpus];
  return c && c.books.find(b => b.slug === slug);
}

/* ------------------------------------------------ panes ---------- */

class Pane {
  constructor(el, idx) {
    this.el = el;
    this.idx = idx;
    const ps = state.panes[idx] || state.panes[0];
    this.corpus = ps.corpus; this.slug = ps.slug; this.chapter = ps.chapter;
    this.notes = ps.notes !== false;

    this.selCorpus = el.querySelector('.sel-corpus');
    this.selBook = el.querySelector('.sel-book');
    this.selChapter = el.querySelector('.sel-chapter');
    this.body = el.querySelector('.chapter-body');
    this.scroll = el.querySelector('.pane-scroll');

    for (const [id, c] of Object.entries(manifest.corpora)) {
      this.selCorpus.add(new Option(c.name, id));
    }
    this.selCorpus.onchange = () => {
      const first = manifest.corpora[this.selCorpus.value].books[0];
      this.load(this.selCorpus.value, first.slug, first.chapters[0]);
    };
    this.selBook.onchange = () => this.load(this.corpus, this.selBook.value, 1);
    this.selChapter.onchange = () => this.load(this.corpus, this.slug, +this.selChapter.value);
    el.querySelector('.btn-prev').onclick = () => this.step(-1);
    el.querySelector('.btn-next').onclick = () => this.step(1);
    const btnNotes = el.querySelector('.btn-notes');
    btnNotes.onclick = () => {
      this.notes = !this.notes;
      this.el.classList.toggle('show-notes', this.notes);
      btnNotes.classList.toggle('active', this.notes);
      saveState();
    };
    el.addEventListener('pointerdown', () => { activePane = this.idx; });
    this.body.addEventListener('click', e => this.onBodyClick(e));
  }

  async load(corpus, slug, chapter, verse) {
    const meta = bookMeta(corpus, slug);
    if (!meta) { toast(`${slug} is not in your local data`); return; }
    if (!meta.chapters.includes(chapter)) chapter = meta.chapters[0];
    let book;
    try { book = await loadBook(corpus, slug); }
    catch (e) { toast(`Could not load ${meta.name} (${e.message})`); return; }
    this.corpus = corpus; this.slug = slug; this.chapter = chapter;
    this.render(book);
    saveState();
    if (verse) {
      this.jumpToVerse(verse);
    } else {
      this.scroll.scrollTop = 0;
    }
  }

  step(dir) {
    const meta = bookMeta(this.corpus, this.slug);
    const i = meta.chapters.indexOf(this.chapter);
    if (i + dir >= 0 && i + dir < meta.chapters.length) {
      this.load(this.corpus, this.slug, meta.chapters[i + dir]);
      return;
    }
    const books = manifest.corpora[this.corpus].books;
    const bi = books.findIndex(b => b.slug === this.slug) + dir;
    if (bi < 0 || bi >= books.length) return;
    const nb = books[bi];
    this.load(this.corpus, nb.slug, dir > 0 ? nb.chapters[0] : nb.chapters[nb.chapters.length - 1]);
  }

  render(book) {
    const ch = book.chapters.find(c => c.c === this.chapter);
    this.syncSelectors(book);
    this.el.classList.toggle('show-notes', this.notes);
    this.el.querySelector('.btn-notes').classList.toggle('active', this.notes);

    const frag = [];
    frag.push(`<h2 class="chapter-title">${book.name} ${ch.c}</h2>`);
    if (ch.heading) frag.push(`<div class="chapter-heading">${ch.heading}</div>`);

    const blocks = ch.blocks;
    for (let i = 0; i < blocks.length; i++) {
      const b = blocks[i];
      if (b.t === 'summary') {
        frag.push(`<div class="row row-summary">${b.html}</div>`);
      } else if (b.t === 'marker') {
        const chips = b.cats.map(c =>
          `<span class="cat-chip cat-${c}" title="${CATS[c] || c}"></span>`).join('');
        frag.push(`<div class="row row-marker">${chips}<span>${b.ref}</span></div>`);
      } else if (b.t === 'verses') {
        const next = blocks[i + 1];
        const hasNote = next && next.t === 'note';
        frag.push(`<div class="row${hasNote ? ' has-note' : ''}">`);
        frag.push(`<div class="cell-text">${b.items.map(v => this.verseHTML(v)).join('')}</div>`);
        if (hasNote) { frag.push(`<div class="cell-note">${next.html}</div>`); i++; }
        frag.push('</div>');
      } else if (b.t === 'note') {
        frag.push(`<div class="row has-note"><div class="cell-text"></div><div class="cell-note">${b.html}</div></div>`);
      }
    }

    if (ch.footnotes && ch.footnotes.length) {
      frag.push('<div class="footnotes"><h4>Notes</h4>');
      for (const fn of ch.footnotes) {
        const num = fn.id.replace(/n$/, '');
        // strip embedded anchor ids so two panes never duplicate DOM ids
        const html = fn.html.replace(/ id="fn-[^"]*"/g, '');
        frag.push(`<div class="footnote" data-fn="${fn.id}"><span class="fn-num">${num}.</span><div>${html}</div></div>`);
      }
      frag.push('</div>');
    }

    this.body.innerHTML = frag.join('');
  }

  verseHTML(v) {
    const key = `${this.corpus}/${this.slug}/${this.chapter}/${v.v}`;
    const rec = annFor(key);
    const hl = rec && rec.hl ? ` hl-${rec.hl}` : '';
    const flag = rec && rec.note ? '<span class="note-flag">📝</span>' : '';
    const num = v.v > 0 ? `<span class="vnum">${v.v}</span>` : '';
    let out = `<p class="verse${hl}" data-key="${key}" data-v="${v.v}">` +
      `${num}${v.html}${flag}</p>`;
    if (rec && rec.note) out += `<div class="own-note" data-notekey="${key}">${escapeHTML(rec.note)}</div>`;
    return out;
  }

  jumpToVerse(v) {
    const el = this.body.querySelector(`.verse[data-v="${v}"]`);
    if (el) { el.scrollIntoView({ block: 'center' }); el.classList.add('flash'); }
  }

  syncSelectors(book) {
    this.selCorpus.value = this.corpus;
    this.selBook.innerHTML = '';
    for (const b of manifest.corpora[this.corpus].books) this.selBook.add(new Option(b.name, b.slug));
    this.selBook.value = this.slug;
    this.selChapter.innerHTML = '';
    for (const c of bookMeta(this.corpus, this.slug).chapters) this.selChapter.add(new Option(c, c));
    this.selChapter.value = this.chapter;
  }

  onBodyClick(e) {
    const nav = e.target.closest('a[data-nav]');
    if (nav) {
      e.preventDefault();
      const [corpus, slug, chapter] = nav.dataset.nav.split('/');
      this.load(corpus, slug, +chapter);
      return;
    }
    const link = e.target.closest('a[href^="#"]');
    if (link) {
      e.preventDefault();
      const target = link.getAttribute('href').slice(1);
      if (/^\d+n$/.test(target)) {
        const fn = this.body.querySelector(`.footnote[data-fn="${target}"]`);
        if (fn) { fn.scrollIntoView({ block: 'center' }); fn.classList.remove('flash'); void fn.offsetWidth; fn.classList.add('flash'); }
      } else if (/^\d+$/.test(target)) {
        this.jumpToVerse(+target);
      }
      return;
    }
    if (e.target.closest('a')) return;
    const noteEl = e.target.closest('.own-note');
    if (noteEl) {
      const verse = this.body.querySelector(`.verse[data-key="${noteEl.dataset.notekey}"]`);
      if (verse) selectVerse(verse);
      openNoteDialog();
      return;
    }
    const verse = e.target.closest('.verse');
    if (verse) selectVerse(verse);
  }
}

/* --------------------------------------------- verse selection --- */

function selectVerse(el) {
  document.querySelectorAll('.verse.selected').forEach(v => v.classList.remove('selected'));
  el.classList.add('selected');
  const key = el.dataset.key;
  const [corpus, slug, chapter, v] = key.split('/');
  const meta = bookMeta(corpus, slug);
  const ref = `${meta ? meta.name : slug} ${chapter}:${v}`;
  selected = { key, ref, text: el.textContent.replace(/^\s*\d+\s*/, '').trim() };
  const sheet = document.getElementById('verse-actions');
  sheet.querySelector('.va-ref').textContent = ref;
  sheet.hidden = false;
}

function closeActions() {
  document.getElementById('verse-actions').hidden = true;
  document.querySelectorAll('.verse.selected').forEach(v => v.classList.remove('selected'));
  selected = null;
}

function refreshVerse(key) {
  const rec = annFor(key);
  document.querySelectorAll(`.verse[data-key="${CSS.escape(key)}"]`).forEach(el => {
    el.className = 'verse' + (rec && rec.hl ? ` hl-${rec.hl}` : '') +
      (el.classList.contains('selected') ? ' selected' : '');
    let flag = el.querySelector('.note-flag');
    if (rec && rec.note && !flag) {
      flag = document.createElement('span');
      flag.className = 'note-flag';
      flag.textContent = '📝';
      el.appendChild(flag);
    } else if ((!rec || !rec.note) && flag) flag.remove();

    let noteEl = el.nextElementSibling;
    const isNote = noteEl && noteEl.classList && noteEl.classList.contains('own-note');
    if (rec && rec.note) {
      if (!isNote) {
        noteEl = document.createElement('div');
        noteEl.className = 'own-note';
        noteEl.dataset.notekey = key;
        el.after(noteEl);
      }
      noteEl.textContent = rec.note;
    } else if (isNote) noteEl.remove();
  });
}

/* --------------------------------------------- note dialog ------- */

function openNoteDialog() {
  if (!selected) return;
  const dlg = document.getElementById('note-dialog');
  document.getElementById('note-ref').textContent = `Note on ${selected.ref}`;
  const rec = annFor(selected.key);
  document.getElementById('note-text').value = (rec && rec.note) || '';
  dlg.returnValue = 'cancel';
  dlg.showModal();
}

/* --------------------------------------------- search ------------ */

function stripTags(html) { return html.replace(/<[^>]+>/g, ''); }

async function runSearch(q, scope) {
  const status = document.getElementById('search-status');
  const out = document.getElementById('search-results');
  out.innerHTML = '';
  const needle = q.toLowerCase();
  if (needle.length < 3) { status.textContent = 'Type at least 3 characters.'; return; }
  let hits = 0;
  const MAX = 300;
  for (const [corpusId, corpus] of Object.entries(manifest.corpora)) {
    if (scope !== 'all' && scope !== corpusId) continue;
    for (const bmeta of corpus.books) {
      status.textContent = `Searching ${bmeta.name}...`;
      let book;
      try { book = await loadBook(corpusId, bmeta.slug); }
      catch { continue; }
      for (const ch of book.chapters) {
        for (const block of ch.blocks) {
          if (block.t !== 'verses') continue;
          for (const v of block.items) {
            const text = stripTags(v.html);
            const pos = text.toLowerCase().indexOf(needle);
            if (pos === -1) continue;
            hits++;
            if (hits > MAX) { status.textContent = `Stopped at ${MAX} results. Narrow the search.`; return; }
            const start = Math.max(0, pos - 40);
            const snippet = escapeHTML(text.slice(start, pos)) +
              '<mark>' + escapeHTML(text.slice(pos, pos + q.length)) + '</mark>' +
              escapeHTML(text.slice(pos + q.length, pos + q.length + 60));
            const div = document.createElement('div');
            div.className = 'result';
            div.innerHTML = `<div class="ref">${bmeta.name} ${ch.c}:${v.v}</div><div>${start > 0 ? '…' : ''}${snippet}…</div>`;
            div.onclick = () => {
              document.getElementById('search-dialog').close();
              panes[activePane].load(corpusId, bmeta.slug, ch.c, v.v);
            };
            out.appendChild(div);
          }
        }
      }
      await new Promise(r => setTimeout(r));  // keep UI responsive
    }
  }
  status.textContent = hits ? `${hits} result${hits === 1 ? '' : 's'}.` : 'No results.';
}

/* --------------------------------------------- my study ---------- */

function bookOrderIndex() {
  const order = new Map();
  let i = 0;
  for (const corpus of Object.values(manifest.corpora)) {
    for (const b of corpus.books) order.set(b.slug, i++);
  }
  return order;
}

function renderStudyList() {
  const list = document.getElementById('study-list');
  const items = [...ann.values()].filter(r => !r.deleted);
  if (!items.length) {
    list.innerHTML = '<p class="hint">Nothing yet. Tap any verse to highlight it or add a note.</p>';
    return;
  }
  const order = bookOrderIndex();
  items.sort((a, b) => {
    const [, sa, ca, va] = a.key.split('/');
    const [, sb, cb, vb] = b.key.split('/');
    return (order.get(sa) ?? 99) - (order.get(sb) ?? 99) || ca - cb || va - vb;
  });
  list.innerHTML = '';
  for (const r of items) {
    const [corpus, slug, chapter, v] = r.key.split('/');
    const div = document.createElement('div');
    div.className = 'study-item';
    const dot = r.hl ? `<span class="dot" style="background:var(--hl-${r.hl})"></span>` : '';
    div.innerHTML = `<div class="ref">${dot}${escapeHTML(r.ref || r.key)}</div>` +
      (r.snippet ? `<div class="snippet">${escapeHTML(r.snippet)}</div>` : '') +
      (r.note ? `<div class="mynote">📝 ${escapeHTML(r.note)}</div>` : '');
    div.onclick = () => {
      document.getElementById('study-dialog').close();
      panes[activePane].load(corpus, slug, +chapter, +v);
    };
    list.appendChild(div);
  }
}

/* --------------------------------------------- backup / sync ----- */

function exportData() {
  const payload = {
    app: 'study-bible',
    exported: new Date().toISOString(),
    items: [...ann.values()],
  };
  const blob = new Blob([JSON.stringify(payload, null, 1)], { type: 'application/json' });
  const a = document.createElement('a');
  a.href = URL.createObjectURL(blob);
  a.download = `study-bible-backup-${new Date().toISOString().slice(0, 10)}.json`;
  a.click();
  URL.revokeObjectURL(a.href);
  toast('Backup downloaded');
}

async function mergeItems(items) {
  let changed = 0;
  for (const r of items || []) {
    if (!r || !r.key) continue;
    const mine = ann.get(r.key);
    if (!mine || (r.updatedAt || 0) > (mine.updatedAt || 0)) {
      ann.set(r.key, r);
      await idb.put(r);
      refreshVerse(r.key);
      changed++;
    }
  }
  return changed;
}

async function importData(file) {
  try {
    const payload = JSON.parse(await file.text());
    if (payload.app !== 'study-bible') throw new Error('not a Study Bible backup');
    const changed = await mergeItems(payload.items);
    toast(`Imported: ${changed} item${changed === 1 ? '' : 's'} updated`);
  } catch (e) {
    toast(`Import failed: ${e.message}`);
  }
}

let syncTimer = null;
function scheduleSync() {
  if (!localStorage.getItem('sb-token')) return;
  clearTimeout(syncTimer);
  syncTimer = setTimeout(() => gistSync(false), 15000);
}

function setSyncStatus(msg) {
  const el = document.getElementById('sync-status');
  if (el) el.textContent = msg;
}

async function ghFetch(token, url, opts = {}) {
  const r = await fetch(url, Object.assign({}, opts, {
    headers: Object.assign({
      Authorization: `Bearer ${token}`,
      Accept: 'application/vnd.github+json',
    }, opts.headers || {}),
  }));
  if (!r.ok) throw new Error(`GitHub ${r.status}`);
  return r.json();
}

async function gistSync(manual) {
  const token = localStorage.getItem('sb-token');
  if (!token) { if (manual) toast('Add a GitHub token first'); return; }
  try {
    setSyncStatus('Syncing...');
    let gistId = localStorage.getItem('sb-gist');
    if (!gistId) {
      const gists = await ghFetch(token, 'https://api.github.com/gists?per_page=100');
      const found = gists.find(g => g.files && g.files[GIST_FILENAME]);
      if (found) gistId = found.id;
    }
    if (gistId) {
      const gist = await ghFetch(token, `https://api.github.com/gists/${gistId}`);
      const f = gist.files[GIST_FILENAME];
      if (f) {
        let content = f.content;
        if (f.truncated) content = await (await fetch(f.raw_url)).text();
        const remote = JSON.parse(content || '{}');
        await mergeItems(remote.items);
      }
    }
    const payload = JSON.stringify({
      app: 'study-bible',
      exported: new Date().toISOString(),
      items: [...ann.values()],
    }, null, 1);
    if (gistId) {
      await ghFetch(token, `https://api.github.com/gists/${gistId}`, {
        method: 'PATCH',
        body: JSON.stringify({ files: { [GIST_FILENAME]: { content: payload } } }),
      });
    } else {
      const created = await ghFetch(token, 'https://api.github.com/gists', {
        method: 'POST',
        body: JSON.stringify({
          description: 'Study Bible backup (highlights and notes)',
          public: false,
          files: { [GIST_FILENAME]: { content: payload } },
        }),
      });
      gistId = created.id;
    }
    localStorage.setItem('sb-gist', gistId);
    const when = new Date().toLocaleTimeString();
    setSyncStatus(`Synced at ${when} (gist ${gistId.slice(0, 8)}…)`);
    if (manual) toast('Synced to gist');
  } catch (e) {
    setSyncStatus(`Sync failed: ${e.message}`);
    if (manual) toast(`Sync failed: ${e.message}`);
  }
}

/* --------------------------------------------- misc UI ----------- */

function escapeHTML(s) {
  return String(s).replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;');
}

let toastTimer = null;
function toast(msg) {
  const el = document.getElementById('toast');
  el.textContent = msg;
  el.hidden = false;
  clearTimeout(toastTimer);
  toastTimer = setTimeout(() => { el.hidden = true; }, 3200);
}

function applyAppearance() {
  document.documentElement.dataset.theme = state.theme;
  document.documentElement.style.setProperty('--fs', state.fontSize + 'px');
}

function buildLegend() {
  const el = document.getElementById('legend');
  el.innerHTML = Object.entries(CATS).map(([code, name]) =>
    `<div class="legend-row"><span class="cat-chip cat-${code}"></span>${name}</div>`).join('');
}

/* --------------------------------------------- wiring ------------ */

function wireUI() {
  const btnSplit = document.getElementById('btn-split');
  const applySplit = () => {
    document.getElementById('panes').className = state.split ? 'split' : 'single';
    btnSplit.classList.toggle('active', state.split);
  };
  btnSplit.onclick = () => { state.split = !state.split; applySplit(); saveState(); };
  applySplit();

  document.getElementById('btn-search').onclick = () => {
    document.getElementById('search-dialog').showModal();
    document.getElementById('search-input').focus();
  };
  document.getElementById('search-form').onsubmit = e => {
    e.preventDefault();
    runSearch(document.getElementById('search-input').value.trim(),
      document.getElementById('search-scope').value);
  };

  document.getElementById('btn-study').onclick = () => {
    renderStudyList();
    document.getElementById('study-dialog').showModal();
  };

  document.getElementById('btn-settings').onclick = () => {
    document.getElementById('set-theme').value = state.theme;
    document.getElementById('set-fontsize').value = state.fontSize;
    document.getElementById('set-token').value = localStorage.getItem('sb-token') || '';
    document.getElementById('settings-dialog').showModal();
  };
  document.getElementById('set-theme').onchange = e => {
    state.theme = e.target.value; applyAppearance(); saveState();
  };
  document.getElementById('set-fontsize').onchange = e => {
    state.fontSize = +e.target.value; applyAppearance(); saveState();
  };
  document.getElementById('set-token').onchange = e => {
    const v = e.target.value.trim();
    if (v) localStorage.setItem('sb-token', v); else localStorage.removeItem('sb-token');
    setSyncStatus(v ? 'Token saved. Use "Sync now" to test it.' : '');
  };
  document.getElementById('btn-sync').onclick = () => gistSync(true);
  document.getElementById('btn-sync-forget').onclick = () => {
    localStorage.removeItem('sb-token');
    localStorage.removeItem('sb-gist');
    document.getElementById('set-token').value = '';
    setSyncStatus('Token removed.');
  };

  document.getElementById('btn-export').onclick = exportData;
  document.getElementById('btn-import').onclick = () =>
    document.getElementById('import-file').click();
  document.getElementById('import-file').onchange = e => {
    if (e.target.files[0]) importData(e.target.files[0]);
    e.target.value = '';
  };

  document.querySelectorAll('.dialog-close').forEach(b => {
    b.onclick = () => document.getElementById(b.dataset.close).close();
  });

  // verse action sheet
  const sheet = document.getElementById('verse-actions');
  sheet.querySelectorAll('.hl-dot').forEach(b => {
    b.onclick = async () => {
      if (!selected) return;
      await updateAnn(selected.key, { hl: b.dataset.hl || null },
        { ref: selected.ref, snippet: selected.text.slice(0, 90) });
      if (!b.dataset.hl) closeActions();
    };
  });
  document.getElementById('va-note').onclick = openNoteDialog;
  document.getElementById('va-copy').onclick = async () => {
    if (!selected) return;
    try {
      await navigator.clipboard.writeText(`"${selected.text}" (${selected.ref})`);
      toast('Copied');
    } catch { toast('Copy blocked by browser'); }
  };
  document.getElementById('va-close').onclick = closeActions;

  const noteDlg = document.getElementById('note-dialog');
  noteDlg.addEventListener('close', async () => {
    if (!selected) return;
    if (noteDlg.returnValue === 'save') {
      const text = document.getElementById('note-text').value.trim();
      await updateAnn(selected.key, { note: text || null },
        { ref: selected.ref, snippet: selected.text.slice(0, 90) });
    } else if (noteDlg.returnValue === 'delete') {
      await updateAnn(selected.key, { note: null });
    }
  });

  document.addEventListener('keydown', e => {
    if (e.key === 'Escape') closeActions();
  });
}

/* --------------------------------------------- boot -------------- */

async function boot() {
  applyAppearance();
  try {
    manifest = await fetchJSON('data/manifest.json');
  } catch {
    document.getElementById('no-data').hidden = false;
    return;
  }
  await idb.open();
  await loadAnnotations();
  buildLegend();

  const tpl = document.getElementById('pane-template');
  const container = document.getElementById('panes');
  for (let i = 0; i < 2; i++) {
    const el = tpl.content.firstElementChild.cloneNode(true);
    container.appendChild(el);
    panes.push(new Pane(el, i));
  }
  wireUI();
  for (const p of panes) {
    let { corpus, slug, chapter } = p;
    if (!bookMeta(corpus, slug)) {
      corpus = Object.keys(manifest.corpora)[0];
      slug = manifest.corpora[corpus].books[0].slug;
      chapter = 1;
    }
    await p.load(corpus, slug, chapter);
  }
  if (localStorage.getItem('sb-token')) gistSync(false);

  if ('serviceWorker' in navigator) {
    navigator.serviceWorker.register('sw.js').catch(() => {});
  }
}

boot();
