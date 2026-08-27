"""General-purpose, read-only Facebook toolkit.

Drives a real logged-in browser via exported session cookies and reads the
feed's own GraphQL, because Facebook killed the Groups API and CrowdTangle and
the UI has no "sort by reactions". Works on any group/page/profile feed via
named targets. Three resumable stages plus a CLI (`bin/fb`):

  session.py -- reusable authenticated browser + GraphQL capture (import this)
  crawl.py   -- scroll a target's feed, dump raw GraphQL to data/<target>/raw/
  parse.py   -- walk the raw JSON offline into ranked post records
  report.py  -- top-N and per-year breakdowns with downloaded images

INVARIANTS:
  - Read-only: never reacts, comments, posts, or clicks into a post.
  - Nothing under secrets/, data/, report/, .profile/ is committed. It holds
    live session cookies and real people's names/faces from private groups.
"""
