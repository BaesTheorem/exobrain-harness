---
name: defuddle
description: Extract clean markdown content from web pages using Defuddle CLI, removing clutter and navigation to save tokens. Use instead of WebFetch when the user provides a URL to read or analyze, for online documentation, articles, blog posts, or any standard web page. Do NOT use for URLs ending in .md -- those are already markdown, use WebFetch directly.
---

# Defuddle

Use Defuddle CLI to extract clean readable content from web pages. Prefer over WebFetch for standard web pages -- it removes navigation, ads, and clutter, reducing token usage.

If not installed: `npm install -g defuddle`

## Usage

Always use `--md` for markdown output:

```bash
defuddle parse <url> --md
```

Save to file:

```bash
defuddle parse <url> --md -o content.md
```

Extract specific metadata:

```bash
defuddle parse <url> -p title
defuddle parse <url> -p description
defuddle parse <url> -p domain
```

## Output formats

| Flag | Format |
|------|--------|
| `--md` | Markdown (default choice) |
| `--json` | JSON with both HTML and markdown |
| (none) | HTML |
| `-p <name>` | Specific metadata property |

## Fallback: Jina Reader

Defuddle fetches and parses locally, so it returns empty output or a challenge
page when the target is behind Cloudflare/anti-bot or renders its content in
JavaScript. Jina Reader fetches server-side with a real renderer, which clears
both. No install, no API key.

```bash
curl -sS "https://r.jina.ai/<full-url-including-https>"
```

**It serves a cached snapshot by default.** The response says so in a `Warning:`
line near the top. Anywhere freshness is the point (a watcher, a price, a job
listing, anything where a stale read is a wrong answer), opt out:

```bash
curl -sS -H "x-no-cache: true" "https://r.jina.ai/<url>"
```

**Never send a private URL through it.** The whole URL goes to a third-party
service, so no authenticated pages, no signed/expiring links, nothing with a
token or session id in the query string. Public pages only. For a page that
needs a login, use a real browser session instead (`/browser-render`, or the
site's own CLI).

Escalation order: `defuddle` first, Jina when defuddle comes back empty or
challenged, `WebFetch` last.
