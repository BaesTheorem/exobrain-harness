# Bookmarklets

A single static page of draggable `javascript:` bookmarklets. Open it and drag a
button onto the bookmarks bar:

```
open "/Users/alexhedtke/Documents/Exobrain harness/bookmarklets/index.html"
```

There is no server. `index.html` is self-contained and works from `file://`.

## What's here

| Bookmark | Does |
| --- | --- |
| 🕰️ Wayback | Opens the newest Wayback Machine snapshot of the current page in a new tab. On an already-archived page it opens that URL's capture calendar instead, so you can pick a different date. |
| 💾 Archive This | Submits the current page to Wayback's Save Page Now. |

The latest-snapshot trick is `https://web.archive.org/web/2/<url>`: a partial
timestamp makes Wayback 302 to the nearest capture, and `2` rounds to the newest
one. The calendar view is `https://web.archive.org/web/*/<url>`.

## Adding one

Append a `<section>` and one entry in the `BM` object at the bottom of
`index.html`. The `javascript:` string lives in JS rather than in the `href`
attribute so quoting and escaping survive editing; the page assigns it to the
link and prints it in the collapsed Source block.

Bookmarklets have no host, so browsers do not fetch a favicon for them. Until
the tool below writes an icon, the emoji at the start of a name is the only
identifier on the bar. The tool also uses that emoji as the default icon. After
`apply`, the emoji in a name only repeats the icon, so you can remove it. You
can also remove the full name for an icon-only button. The manifest finds each
bookmarklet by part of its code, so the icon stays.

## Favicons for bookmarklets

Chrome picks a bookmark's icon by looking the bookmark's URL up in the profile's
`Favicons` database (`icon_mapping.page_url`, then `favicons`, then
`favicon_bitmaps`). A `javascript:` URL is never visited, so no page ever
supplies an icon and the bar shows the default globe. `bin/bookmarklet-favicon`
writes those rows itself, keyed by the exact URL string in the `Bookmarks` file,
which is the string Chrome looks up. The bookmarklets stay native `javascript:`
URLs, so nothing about how they run changes (the Web Store extensions that offer
this rewrite the bookmark to a `data:` URL and navigate away and back).

```
bin/bookmarklet-favicon list                 # every bookmarklet, its planned icon, the current state
bin/bookmarklet-favicon preview              # the planned icons on a mock bookmarks bar, plus each bitmap magnified
bin/bookmarklet-favicon apply --dry-run      # the plan, applied to a copy; Chrome can stay open
bin/bookmarklet-favicon apply --quit         # quit Chrome, write the icons, relaunch with the tabs
bin/bookmarklet-favicon check                # Chrome's own favicon service confirms each icon at 16 and 32 px
bin/bookmarklet-favicon apply --browser brave --quit
```

The tool uses the first source in this sequence that gives an icon:

1. An entry in `icons.json` with `match` text that is part of the bookmarklet's
   code, for example the address of the app that it calls. This entry stays
   correct after a rename, after you remove the name, and after a new version of
   the code.
2. An entry by bookmark name, compared with emoji and symbols removed.
3. The emoji that the name starts with.
4. A one-letter badge.

Steps 3 and 4 only fill in a missing icon. They do not replace an icon that is
there, so a bookmarklet without a manifest entry keeps its icon after a rename.
An entry is a spec, or `{"icon": spec, "match": text}`. Specs: `emoji:🕰️`, `symbol:history` (Material
Symbols Outlined on a rounded square, `bg=`/`fg=`/`fill=`/`wght=`/`opsz=`
options), `text:W`, `file:/path.svg`, `like:https://web.archive.org/` (the icon
the profile already holds for that site), `url:https://site/` (fetched from
Google's favicon service). A relative `file:` path starts in this folder. A
`{size}` in a `file:` path names one file for each icon dimension:
`passage-{size}.svg` reads `passage-16.svg` and `passage-32.svg`, and the tool
uses each file as it is drawn. Symbols use the optical size that matches the
glyph size in pixels (20 at 16 px, not 48). Thus the strokes have a
sufficient thickness to read on the bar.

### The icons

Each icon comes from the app that the bookmarklet belongs to. If the app has
art for small sizes, use that art. If the app's master icon does not read at 16
and 32 px, redraw it in `icons/` with the app's colors and shapes. A bookmarklet
with no app gets a Material Symbol for what it does.

| Bookmarklet | Icon | Source |
| --- | --- | --- |
| Wayback | The Internet Archive's own favicon | `like:https://web.archive.org/` |
| Passage | Passage's green breach in a brick wall, redrawn for the bar: a larger doorway, two chevrons at 32 px, one at 16 px | `icons/passage-{size}.svg`, from `passage/static/icon.svg` |
| Page → MP3 | Video Downloader's green bookmark-bar tile, made green so that it is not read as YouTube's red button | the app's `favicon.svg` |
| Unlock [Select/Copy/Paste] | A clipboard with text (`assignment`) | Material Symbols, on `#3297fd`, the color the bookmarklet paints selections in |
| Allow Text Selection | A text cursor (`highlight_text_cursor`) | Material Symbols, on the same blue |

Chrome holds the database with an exclusive lock while it runs, so `apply`
needs it closed. `--quit` quits it over AppleScript, writes, and relaunches it
with `--restore-last-session`. A copy of the database goes to
`~/Library/Application Support/bookmarklet-favicon/backups/` first (with a
`copy-` prefix when `--user-data-dir` points at a copy of a profile). `check`
copies the profile into a throwaway user data dir, runs the same Chrome binary
headless there, and asks `chrome://favicon2` for each bookmarklet: that is the
lookup the bookmarks bar makes, with a negative and a positive control first.

`export-html` writes a bookmarks file with `ICON` data for Chrome's importer
(`chrome://settings/importData`), which works while Chrome runs, but Chrome
re-encodes imported icons at 16 px and never replaces an icon a URL already has,
so it is the fallback, not the path. Safari and Arc are not covered.
