# Study Bible PWA

A self-contained study app for the [Skeptic's Annotated Bible](https://www.skepticsannotatedbible.com) (KJV, all 66 books) and the Skeptic's Annotated Book of Mormon (all 15 books). Static files, no build tooling, no server-side code. Installs to a phone or desktop as a PWA and works offline once the data is cached.

## What it does

- **Split screen.** Two independent reading panes. Each picks its own collection, book, and chapter, so you can put Genesis 1 next to 1 Nephi 1, or two chapters of the same book side by side.
- **SAB annotations.** Steve Wells' verse notes, section summaries, endnotes, and category markings (Absurdity, Injustice, Contradiction, Science and History, Plagiarism, and the rest) render alongside the text. Toggle them off per pane for a plain reading view. Cross-reference links navigate inside the app; contradiction pages and other articles open on the SAB site.
- **Highlights and notes.** Tap a verse for five highlight colors and a personal note editor. Everything lands in a "My study" list with jump links.
- **Search** across both collections, or scoped to one.
- **Real backup, not just browser cache.** Highlights and notes persist in IndexedDB, and two ways out of it:
  - one-tap export/import of a JSON backup file
  - optional sync to a **private GitHub Gist**, which also keeps multiple devices on the same data (newest edit per verse wins)
- Light/dark theme, adjustable text size, keyboard-free mobile layout.

## Setup

### 1. Build the dataset

The `data/` directory is gitignored and starts empty. The scripture text (KJV and the 1830 Book of Mormon) is public domain, but the annotations are Steve Wells' copyrighted work, so the dataset is built on your machine instead of being redistributed through this repo:

```bash
python3 bible-study/build-data.py            # everything, ~20 min, stdlib only
python3 bible-study/build-data.py --sample   # 7 books, ~5 min, for a quick look
python3 bible-study/build-data.py --book gen --book 1ne   # specific books
```

Partial builds merge into the existing manifest, so you can fetch a few books now and the rest later. The scraper waits 0.4s between requests by default (`--delay` to change).

### 2. Serve it

Any static file server works. Locally:

```bash
cd bible-study && python3 -m http.server 8080
```

Then open http://localhost:8080. For phone install, put the folder behind HTTPS (Tailscale Serve, a home server, any static host) and use the browser's "Add to Home Screen". Service workers require HTTPS or localhost.

### 3. Gist sync (optional)

Settings → GitHub Gist sync. Create a token at GitHub → Settings → Developer settings with **only the gist scope**, paste it in, hit Sync now. First sync creates a private gist named `study-bible-backup.json`; every device with the token converges on the same highlights and notes. The token stays in that browser's localStorage and never touches this repo.

## Files

| File | What |
|---|---|
| `build-data.py` | Scraper/builder. Fetches skepticsannotatedbible.com, writes `data/manifest.json` plus one JSON per book. |
| `index.html`, `css/app.css`, `js/app.js` | The whole app. Vanilla JS, no dependencies. |
| `sw.js` | Service worker: offline app shell, caches scripture data as you read it. |
| `manifest.webmanifest`, `icons/` | PWA install metadata. |

## Data shape

Each book file: `{slug, name, corpus, chapters: [{c, heading, blocks, footnotes}]}`. Blocks preserve the SAB page order: `summary` (section headings), `marker` (category icons for a verse range), `verses` (KJV/BoM text with the site's category `<span>`s), `note` (Wells' plain-language notes). Footnote and cross-book links are rewritten at build time to app navigation (`data-nav`) or absolute SAB URLs.

User data lives in IndexedDB as one record per verse: `{key: "bible/gen/1/3", hl, note, ref, snippet, updatedAt}`. Records with neither highlight nor note become tombstones so deletions sync correctly.
