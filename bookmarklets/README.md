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

Lead every label with an emoji. Bookmarklets have no host, so browsers can't
fetch a favicon for them, and the emoji in the name is the only thing that makes
them identifiable on the bar.
