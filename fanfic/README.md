# fanfic

Tools to answer fanfic questions ("what is the most popular story with premise
X") without direct access to AO3 or FanFiction.net.

## `bin/fic-stats`

```bash
fanfic/bin/fic-stats https://archiveofourown.org/works/25440826 https://www.fanfiction.net/s/6035532/1/
fanfic/bin/fic-stats --json URL ...
```

For each URL, the tool prints the title, author, word count, status, summary,
and popularity counts:

- FicHub (`fichub.net/api/v0/epub`) supplies the metadata for both sites, and
  the favs, follows, and reviews for FFN.
- The Wayback Machine supplies AO3 kudos, hits, bookmarks, and tags. The tool
  uses the newest full snapshot and prints its date, because the count can be
  a year old.

AO3 and FFN both refuse scripted requests. AO3 sends HTTP 418 with a
maintenance page for every path while it is down. On 2026-10-29 it went down
after a security incident, and the OTW estimated 2 to 4 weeks for restoration.
To find out if AO3 is down or if it blocks this IP, read its status feed:

```bash
curl -s "https://public.api.bsky.app/xrpc/app.bsky.feed.getAuthorFeed?actor=status.archiveofourown.org&limit=5"
```

FFN sends a Cloudflare challenge, and most of its Wayback snapshots are copies
of that challenge.

## Finding candidates

To get a candidate list, read the recommendation threads on r/HPfanfiction
(and other fandom subreddits) with `reddit/bin/reddit-search <sub> "<terms>"
--title`. Then rank the candidates with `fic-stats`.
