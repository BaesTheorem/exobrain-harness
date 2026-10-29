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

Lead every label with an emoji. Bookmarklets have no host, so browsers never
fetch a favicon for them. The emoji in the name identifies them on the bar until
you give them a real icon with the tool below, which uses that emoji as the icon
by default.

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
bin/bookmarklet-favicon preview              # a PNG sheet of the planned icons at bar size
bin/bookmarklet-favicon apply --dry-run      # the plan, applied to a copy; Chrome can stay open
bin/bookmarklet-favicon apply --quit         # quit Chrome, write the icons, relaunch with the tabs
bin/bookmarklet-favicon check                # Chrome's own favicon service confirms each icon
bin/bookmarklet-favicon apply --browser brave --quit
```

Where an icon comes from, first match wins: an entry in `icons.json` (keys are
bookmark names, matched with emoji and symbols stripped, so a bookmark renamed
from `🕰️ Wayback` to `Wayback` keeps its icon), then the emoji the name starts
with, then a one-letter badge. Specs: `emoji:🕰️`, `symbol:history` (Material
Symbols Outlined on a rounded square, `bg=`/`fg=`/`fill=`/`wght=` options),
`text:W`, `file:/path.svg`, `like:https://web.archive.org/` (the icon the
profile already holds for that site), `url:https://site/` (fetched from
Google's favicon service).

Chrome holds the database with an exclusive lock while it runs, so `apply`
needs it closed. `--quit` quits it over AppleScript, writes, and relaunches it
with `--restore-last-session`. A copy of the database goes to
`~/Library/Application Support/bookmarklet-favicon/backups/` first. `check`
copies the profile into a throwaway user data dir, runs the same Chrome binary
headless there, and asks `chrome://favicon2` for each bookmarklet: that is the
lookup the bookmarks bar makes, with a negative and a positive control first.

`export-html` writes a bookmarks file with `ICON` data for Chrome's importer
(`chrome://settings/importData`), which works while Chrome runs, but Chrome
re-encodes imported icons at 16 px and never replaces an icon a URL already has,
so it is the fallback, not the path. Safari and Arc are not covered.
