/* Study Bible PWA: split-screen reader for the Skeptic's Annotated
   Bible and Book of Mormon, with highlights, notes, and backup.
   UI is Material Design 3 via vendor/md-bundle.js. */
'use strict';

const CATS = {
  a: 'Absurdity', i: 'Injustice', v: 'Cruelty & Violence', int: 'Intolerance',
  c: 'Contradiction', sci: 'Science & History', f: 'Family Values',
  interp: 'Interpretation', pr: 'Prophecy', w: 'Women', l: 'Language',
  s: 'Sex', h: 'Homosexuality', pol: 'Politics', g: 'Good Stuff',
  plag: 'Plagiarism', b: 'Boring', ejat: 'Every Jot & Tittle',
};

const GIST_FILENAME = 'study-bible-backup.json';
const NOTE_FLAG_SVG = '<svg class="note-flag"><use href="#i-edit"/></svg>';

let manifest = null;
let panes = [];
let activePane = 0;
// action sheet context: {mode: 'verse'|'range'|'selection', ...}
let action = null;
const bookCache = new Map();
const ann = new Map();

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
  rec.deleted = !rec.hl && !rec.note && !(rec.ranges && rec.ranges.length);
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

// nav string: "corpus/slug/chapter" or "corpus/slug/chapter:verse"
function parseNav(nav) {
  const [corpus, slug, chv] = nav.split('/');
  const [chapter, verse] = chv.split(':');
  return { corpus, slug, chapter: +chapter, verse: verse ? +verse : null };
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
    this.btnNotes = el.querySelector('.btn-notes');

    for (const [id, c] of Object.entries(manifest.corpora)) {
      this.selCorpus.add(new Option(c.name, id));
    }
    this.selCorpus.onchange = () => {
      const first = manifest.corpora[this.selCorpus.value].books[0];
      this.load(this.selCorpus.value, first.slug, first.chapters[0]);
    };
    this.selBook.onchange = () => this.load(this.corpus, this.selBook.value, 1);
    this.selChapter.onchange = () => this.load(this.corpus, this.slug, +this.selChapter.value);
    el.querySelector('.btn-prev').addEventListener('click', () => this.step(-1));
    el.querySelector('.btn-next').addEventListener('click', () => this.step(1));
    this.btnNotes.addEventListener('click', () => {
      this.notes = this.btnNotes.selected;
      this.el.classList.toggle('show-notes', this.notes);
      saveState();
    });
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
    this.btnNotes.selected = this.notes;

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
      frag.push('<div class="footnotes"><h4>SAB ENDNOTES</h4>');
      for (const fn of ch.footnotes) {
        const num = fn.id.replace(/n$/, '');
        const html = fn.html.replace(/ id="fn-[^"]*"/g, '');
        frag.push(`<div class="footnote" data-fn="${fn.id}"><span class="fn-num">${num}.</span><div>${html}</div></div>`);
      }
      frag.push('</div>');
    }

    this.body.innerHTML = frag.join('');

    // apply selection-range highlights for this chapter
    const prefix = `${this.corpus}/${this.slug}/${this.chapter}/`;
    for (const [key, rec] of ann) {
      if (!rec.deleted && rec.ranges && rec.ranges.length && key.startsWith(prefix)) {
        refreshVerse(key);
      }
    }
  }

  verseHTML(v) {
    const key = `${this.corpus}/${this.slug}/${this.chapter}/${v.v}`;
    const rec = annFor(key);
    const hl = rec && rec.hl ? ` hl-${rec.hl}` : '';
    const flag = rec && rec.note ? NOTE_FLAG_SVG : '';
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
    const sel = document.getSelection();
    if (sel && !sel.isCollapsed) return; // selection flow owns this

    const nav = e.target.closest('a[data-nav]');
    if (nav) {
      e.preventDefault();
      openPassagePreview(nav.dataset.nav);
      return;
    }
    const link = e.target.closest('a[href^="#"]');
    if (link) {
      e.preventDefault();
      const target = link.getAttribute('href').slice(1);
      if (/^\d+n$/.test(target)) {
        openFootnotePopup(this, target);
      } else if (/^\d+$/.test(target)) {
        this.jumpToVerse(+target);
      }
      return;
    }
    if (e.target.closest('a')) return;

    const rangeEl = e.target.closest('.rhl');
    if (rangeEl) {
      const verse = rangeEl.closest('.verse');
      selectRange(verse, +rangeEl.dataset.ri);
      return;
    }
    const noteEl = e.target.closest('.own-note');
    if (noteEl) {
      const verse = this.body.querySelector(`.verse[data-key="${CSS.escape(noteEl.dataset.notekey)}"]`);
      if (verse) { selectVerse(verse); openNoteDialog(); }
      return;
    }
    const verse = e.target.closest('.verse');
    if (verse && verse.closest('.chapter-body') === this.body) selectVerse(verse);
  }
}

/* --------------------------------------------- action sheet ------ */

function refFor(key) {
  const [corpus, slug, chapter, v] = key.split('/');
  const meta = bookMeta(corpus, slug);
  return `${meta ? meta.name : slug} ${chapter}:${v}`;
}

function showActionSheet(mode, ref) {
  const sheet = document.getElementById('verse-actions');
  sheet.querySelector('.va-ref').textContent = ref;
  sheet.querySelector('.va-mode').textContent =
    mode === 'range' ? 'highlight' : mode === 'selection' ? 'selection' : '';
  document.getElementById('va-note').hidden = mode !== 'verse';
  document.getElementById('va-remove').hidden = mode !== 'range';
  document.getElementById('va-copy').hidden = mode === 'range';
  sheet.querySelector('.hl-clear').hidden = mode !== 'verse';
  sheet.hidden = false;
}

function clearSelectedClasses() {
  document.querySelectorAll('.verse.selected').forEach(v => v.classList.remove('selected'));
}

function selectVerse(el) {
  clearSelectedClasses();
  el.classList.add('selected');
  const key = el.dataset.key;
  action = {
    mode: 'verse', key, ref: refFor(key),
    text: el.textContent.replace(/^\s*\d+\s*/, '').trim(),
  };
  showActionSheet('verse', action.ref);
}

function selectRange(verseEl, ri) {
  clearSelectedClasses();
  verseEl.classList.add('selected');
  const key = verseEl.dataset.key;
  action = { mode: 'range', key, ri, ref: refFor(key) };
  showActionSheet('range', action.ref);
}

function closeActions() {
  document.getElementById('verse-actions').hidden = true;
  clearSelectedClasses();
  action = null;
}

/* --------------------------------------------- range highlights -- */

function collectTextNodes(el) {
  const out = [];
  const walker = document.createTreeWalker(el, NodeFilter.SHOW_TEXT, {
    acceptNode(n) {
      let p = n.parentElement;
      while (p && p !== el) {
        if (p.classList.contains('vnum') || p.classList.contains('note-flag')) {
          return NodeFilter.FILTER_REJECT;
        }
        p = p.parentElement;
      }
      return NodeFilter.FILTER_ACCEPT;
    },
  });
  let n;
  while ((n = walker.nextNode())) out.push(n);
  return out;
}

function contentLength(el) {
  return collectTextNodes(el).reduce((a, n) => a + n.textContent.length, 0);
}

function absOffset(verse, container, offset) {
  const probe = document.createRange();
  probe.selectNodeContents(verse);
  try { probe.setEnd(container, offset); } catch { return null; }
  let len = probe.toString().length;
  const vnum = verse.querySelector('.vnum');
  if (vnum) len -= Math.min(len, vnum.textContent.length);
  return Math.max(0, Math.min(len, contentLength(verse)));
}

function applyRanges(el, ranges) {
  ranges.forEach((r, ri) => {
    let pos = 0;
    for (const node of collectTextNodes(el)) {
      const ns = pos, ne = pos + node.textContent.length;
      pos = ne;
      const s = Math.max(r.s, ns), e = Math.min(r.e, ne);
      if (s >= e) continue;
      const range = document.createRange();
      range.setStart(node, s - ns);
      range.setEnd(node, e - ns);
      const span = document.createElement('span');
      span.className = `rhl rhl-${r.c}`;
      span.dataset.ri = ri;
      try { range.surroundContents(span); } catch { /* skip malformed */ }
    }
  });
}

let pendingSel = null;
let selTimer = null;

document.addEventListener('selectionchange', () => {
  clearTimeout(selTimer);
  selTimer = setTimeout(onSelectionSettled, 250);
});

function onSelectionSettled() {
  const sel = document.getSelection();
  if (!sel || sel.isCollapsed || sel.rangeCount === 0) {
    if (action && action.mode === 'selection') closeActions();
    pendingSel = null;
    return;
  }
  const range = sel.getRangeAt(0);
  const cont = range.commonAncestorContainer;
  const el = cont.nodeType === 1 ? cont : cont.parentElement;
  const paneEl = el && el.closest && el.closest('.pane');
  if (!paneEl) return;
  const verses = [...paneEl.querySelectorAll('.chapter-body .verse')]
    .filter(v => range.intersectsNode(v));
  if (!verses.length) return;

  const parts = [];
  for (const v of verses) {
    const vr = document.createRange();
    vr.selectNodeContents(v);
    const startsBefore = range.compareBoundaryPoints(Range.START_TO_START, vr) <= 0;
    const endsAfter = range.compareBoundaryPoints(Range.END_TO_END, vr) >= 0;
    const s = startsBefore ? 0 : absOffset(v, range.startContainer, range.startOffset);
    const e = endsAfter ? contentLength(v) : absOffset(v, range.endContainer, range.endOffset);
    if (s === null || e === null || e - s < 1) continue;
    parts.push({ key: v.dataset.key, s, e, snippet: v.textContent.slice(0, 90) });
  }
  if (!parts.length) return;
  pendingSel = parts;
  const first = refFor(parts[0].key);
  const last = parts.length > 1 ? `-${parts[parts.length - 1].key.split('/')[3]}` : '';
  action = { mode: 'selection' };
  showActionSheet('selection', first + last);
}

async function applySelectionHighlight(color) {
  if (!pendingSel) return;
  for (const p of pendingSel) {
    const rec = ann.get(p.key);
    const ranges = ((rec && rec.ranges) || []).concat([{ s: p.s, e: p.e, c: color }]);
    await updateAnn(p.key, { ranges }, { ref: refFor(p.key), snippet: p.snippet });
  }
  pendingSel = null;
  document.getSelection().removeAllRanges();
  closeActions();
}

async function removeRangeHighlight(key, ri) {
  const rec = ann.get(key);
  if (!rec || !rec.ranges) return;
  const ranges = rec.ranges.filter((_, i) => i !== ri);
  await updateAnn(key, { ranges });
}

async function recolorRange(key, ri, color) {
  const rec = ann.get(key);
  if (!rec || !rec.ranges || !rec.ranges[ri]) return;
  const ranges = rec.ranges.map((r, i) => i === ri ? { ...r, c: color } : r);
  await updateAnn(key, { ranges });
}

/* --------------------------------------------- verse refresh ----- */

function refreshVerse(key) {
  const rec = annFor(key);
  document.querySelectorAll(`.verse[data-key="${CSS.escape(key)}"]`).forEach(el => {
    if (el.closest('#ref-content')) return; // previews are static
    el.className = 'verse' + (rec && rec.hl ? ` hl-${rec.hl}` : '') +
      (el.classList.contains('selected') ? ' selected' : '');

    // unwrap old range spans, then reapply
    el.querySelectorAll('span.rhl').forEach(s => {
      const parent = s.parentNode;
      while (s.firstChild) parent.insertBefore(s.firstChild, s);
      s.remove();
    });
    el.normalize();
    if (rec && rec.ranges && rec.ranges.length) applyRanges(el, rec.ranges);

    let flag = el.querySelector('.note-flag');
    if (rec && rec.note && !flag) {
      el.insertAdjacentHTML('beforeend', NOTE_FLAG_SVG);
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
  if (!action || !action.key) return;
  const dlg = document.getElementById('note-dialog');
  document.getElementById('note-ref').textContent = `Note on ${action.ref}`;
  const rec = annFor(action.key);
  document.getElementById('note-text').value = (rec && rec.note) || '';
  dlg.show();
}

/* --------------------------------------------- popups ------------ */

function refDialogEls() {
  return {
    dlg: document.getElementById('ref-dialog'),
    title: document.getElementById('ref-title'),
    content: document.getElementById('ref-content'),
    here: document.getElementById('ref-open-here'),
    split: document.getElementById('ref-open-split'),
  };
}

async function openFootnotePopup(pane, fnid) {
  const { dlg, title, content, here, split } = refDialogEls();
  const book = await loadBook(pane.corpus, pane.slug);
  const ch = book.chapters.find(c => c.c === pane.chapter);
  const fn = (ch.footnotes || []).find(f => f.id === fnid);
  if (!fn) return;
  title.textContent = `Note ${fnid.replace(/n$/, '')} on ${book.name} ${ch.c}`;
  content.innerHTML = fn.html.replace(/ id="fn-[^"]*"/g, '');
  here.hidden = true;
  split.hidden = true;
  dlg.pendingNav = null;
  dlg.show();
}

async function openPassagePreview(nav) {
  const { dlg, title, content, here, split } = refDialogEls();
  const { corpus, slug, chapter, verse } = parseNav(nav);
  const meta = bookMeta(corpus, slug);
  if (!meta) { toast('That passage is not in your local data'); return; }
  let book;
  try { book = await loadBook(corpus, slug); }
  catch { toast('Could not load passage'); return; }
  const ch = book.chapters.find(c => c.c === chapter);
  if (!ch) return;
  title.textContent = `${book.name} ${chapter}${verse ? ':' + verse : ''}`;
  const frag = [];
  for (const b of ch.blocks) {
    if (b.t !== 'verses') continue;
    for (const v of b.items) {
      const num = v.v > 0 ? `<span class="vnum">${v.v}</span>` : '';
      frag.push(`<p class="verse" data-v="${v.v}">${num}${v.html}</p>`);
    }
  }
  content.innerHTML = frag.join('');
  here.hidden = false;
  split.hidden = false;
  dlg.pendingNav = { corpus, slug, chapter, verse };
  if (!dlg.open) dlg.show();
  setTimeout(() => {
    const target = verse && content.querySelector(`.verse[data-v="${verse}"]`);
    if (target) { target.scrollIntoView({ block: 'center' }); target.classList.add('flash'); }
    else content.scrollTop = 0;
  }, 120);
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
      await new Promise(r => setTimeout(r));
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
    list.innerHTML = '<p class="hint">Nothing yet. Tap a verse, or select some text, to highlight it or add a note.</p>';
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
    const dots = [];
    if (r.hl) dots.push(`<span class="dot" style="background:var(--hl-${r.hl})"></span>`);
    for (const rg of r.ranges || []) dots.push(`<span class="dot" style="background:var(--hl-${rg.c})"></span>`);
    div.innerHTML = `<div class="ref">${dots.join('')}${escapeHTML(r.ref || r.key)}</div>` +
      (r.snippet ? `<div class="snippet">${escapeHTML(r.snippet)}</div>` : '') +
      (r.note ? `<div class="mynote">${escapeHTML(r.note)}</div>` : '');
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
    btnSplit.selected = state.split;
  };
  btnSplit.addEventListener('click', () => {
    state.split = btnSplit.selected;
    applySplit();
    saveState();
  });
  applySplit();

  document.getElementById('btn-search').addEventListener('click', () => {
    document.getElementById('search-dialog').show();
  });
  document.getElementById('search-go').addEventListener('click', () => {
    runSearch(document.getElementById('search-input').value.trim(),
      document.getElementById('search-scope').value);
  });
  document.getElementById('search-input').addEventListener('keydown', e => {
    if (e.key === 'Enter') document.getElementById('search-go').click();
  });

  document.getElementById('btn-study').addEventListener('click', () => {
    renderStudyList();
    document.getElementById('study-dialog').show();
  });

  document.getElementById('btn-settings').addEventListener('click', () => {
    document.getElementById('set-theme').value = state.theme;
    document.getElementById('set-fontsize').value = state.fontSize;
    document.getElementById('set-token').value = localStorage.getItem('sb-token') || '';
    document.getElementById('settings-dialog').show();
  });
  document.getElementById('set-theme').addEventListener('change', e => {
    state.theme = e.target.value; applyAppearance(); saveState();
  });
  document.getElementById('set-fontsize').addEventListener('change', e => {
    state.fontSize = +e.target.value; applyAppearance(); saveState();
  });
  document.getElementById('set-token').addEventListener('change', e => {
    const v = e.target.value.trim();
    if (v) localStorage.setItem('sb-token', v); else localStorage.removeItem('sb-token');
    setSyncStatus(v ? 'Token saved. Use "Sync now" to test it.' : '');
  });
  document.getElementById('btn-sync').addEventListener('click', () => gistSync(true));
  document.getElementById('btn-sync-forget').addEventListener('click', () => {
    localStorage.removeItem('sb-token');
    localStorage.removeItem('sb-gist');
    document.getElementById('set-token').value = '';
    setSyncStatus('Token removed.');
  });

  document.getElementById('btn-export').addEventListener('click', exportData);
  document.getElementById('btn-import').addEventListener('click', () =>
    document.getElementById('import-file').click());
  document.getElementById('import-file').addEventListener('change', e => {
    if (e.target.files[0]) importData(e.target.files[0]);
    e.target.value = '';
  });

  document.querySelectorAll('[data-close]').forEach(b => {
    b.addEventListener('click', () => document.getElementById(b.dataset.close).close());
  });

  // contextual action sheet
  document.querySelectorAll('#verse-actions .hl-dot').forEach(b => {
    b.addEventListener('click', async () => {
      if (!action) return;
      const color = b.dataset.hl || null;
      if (action.mode === 'selection') {
        if (color) await applySelectionHighlight(color);
      } else if (action.mode === 'range') {
        if (color) { await recolorRange(action.key, action.ri, color); closeActions(); }
      } else {
        await updateAnn(action.key, { hl: color },
          { ref: action.ref, snippet: (action.text || '').slice(0, 90) });
        if (!color) closeActions();
      }
    });
  });
  document.getElementById('va-note').addEventListener('click', openNoteDialog);
  document.getElementById('va-remove').addEventListener('click', async () => {
    if (action && action.mode === 'range') {
      await removeRangeHighlight(action.key, action.ri);
      closeActions();
    }
  });
  document.getElementById('va-copy').addEventListener('click', async () => {
    if (!action) return;
    let text = action.text;
    if (action.mode === 'selection') text = document.getSelection().toString();
    try {
      await navigator.clipboard.writeText(`"${text}" (${action.ref || ''})`);
      toast('Copied');
    } catch { toast('Copy blocked by browser'); }
  });
  document.getElementById('va-close').addEventListener('click', closeActions);

  // note dialog
  const noteDlg = document.getElementById('note-dialog');
  document.getElementById('note-save').addEventListener('click', async () => {
    if (action && action.key) {
      const text = document.getElementById('note-text').value.trim();
      await updateAnn(action.key, { note: text || null },
        { ref: action.ref, snippet: (action.text || '').slice(0, 90) });
    }
    noteDlg.close();
  });
  document.getElementById('note-delete').addEventListener('click', async () => {
    if (action && action.key) await updateAnn(action.key, { note: null });
    noteDlg.close();
  });
  document.getElementById('note-cancel').addEventListener('click', () => noteDlg.close());

  // reference popup
  const refDlg = document.getElementById('ref-dialog');
  document.getElementById('ref-close').addEventListener('click', () => refDlg.close());
  document.getElementById('ref-open-here').addEventListener('click', () => {
    const n = refDlg.pendingNav;
    if (n) { refDlg.close(); panes[activePane].load(n.corpus, n.slug, n.chapter, n.verse); }
  });
  document.getElementById('ref-open-split').addEventListener('click', () => {
    const n = refDlg.pendingNav;
    if (!n) return;
    refDlg.close();
    if (!state.split) {
      state.split = true;
      document.getElementById('panes').className = 'split';
      document.getElementById('btn-split').selected = true;
      saveState();
    }
    const other = panes[activePane === 0 ? 1 : 0];
    other.load(n.corpus, n.slug, n.chapter, n.verse);
  });
  document.getElementById('ref-content').addEventListener('click', e => {
    const nav = e.target.closest('a[data-nav]');
    if (nav) { e.preventDefault(); openPassagePreview(nav.dataset.nav); return; }
    const link = e.target.closest('a[href^="#"]');
    if (link) e.preventDefault(); // in-popup anchors have nowhere to go
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
