# Writing Style Analysis

Tooling to learn Alex's personal (non-AI-assisted) writing voice from his own
correspondence and posts, and distill it into a `Writing Voice.md` reference
note in the Obsidian vault (the positive complement to the `/de-ai` skill).

## What's gitignored

`corpus/` holds the raw collected writing and is **gitignored** -- it contains
Alex's private messages, post text, and email, plus references to other people.
Never commit it.

To rebuild the corpus:

1. **iMessage** -- `python3 ../imessage/imessage-reader.py` style outgoing-only
   extraction from `~/Library/Messages/chat.db` (requires Full Disk Access).
   Only `is_from_me=1`; Claude-sent messages (signed `-Alex's Claude`) stripped.
2. **Facebook** -- parse the newest Meta export under
   `~/My Drive/4.) Archive/meta-*/facebook-<username>-*/your_facebook_activity/posts/*.html`.
   Alex's post text only.
3. **Email** -- sent mail via the Gmail MCP (`from:me`), excluding streetcar
   outage reports and any Claude-drafted mail (cover letters, CRM outreach).
4. **Blog** -- Substack `https://becomingstronger.substack.com`, posts dated
   September 2023 and earlier (his non-AI-assisted cutoff).

## Output

`Writing Voice.md` in the vault. Privacy-safe: voice mechanics and anonymized
examples only, no real names or private content lifted from sources.
