# Cybersecurity Bodyguard — Setup

Defensive security skill targeting doxxing, stalking, and targeted harassment.
The main skill spec is in `SKILL.md`. This README covers **setup** only.

## One-time setup

### 1. Create `targets.json`

Copy the example and fill in real values:

```bash
cp targets.example.json targets.json
$EDITOR targets.json
```

This file is **gitignored**. Never commit it. It contains the PII the skill
monitors for (your name, emails, phones, aliases, addresses). Entries are
referenced by key in outputs (e.g., `email[0]`) — the actual values are not
echoed back in scan reports.

### 2. Get a HIBP API key

Have I Been Pwned requires a paid API key ($3.95/month) to query breach status
programmatically. Free for manual lookups at haveibeenpwned.com.

- Subscribe: https://haveibeenpwned.com/API/Key
- Add to your shell environment:
  ```bash
  export HIBP_API_KEY="..."
  ```
- Or add to your `.env` alongside the other Exobrain credentials.

Without this key, the skill falls back to manual HIBP checks (the skill will
prompt you to visit haveibeenpwned.com/unifiedsearch).

### 3. Install Pillow (for EXIF tooling)

The EXIF inspector uses Pillow:

```bash
pip install Pillow
```

Or `pip3 install -r requirements.txt` from the harness root if you add it
there.

### 4. Create the Obsidian security folder

The skill writes to these vault paths — create them now so later logging
doesn't fail:

```bash
mkdir -p "/Users/alexhedtke/Documents/Exobrain/Areas/Security/Incidents"
touch "/Users/alexhedtke/Documents/Exobrain/Areas/Security/Security Log.md"
touch "/Users/alexhedtke/Documents/Exobrain/Areas/Security/broker-removals.md"
```

### 5. (Optional) Subscribe to a broker-removal service

For serious attack-surface reduction, subscribe to DeleteMe, Optery, or Kanary
(~$100-130/yr). See `runbooks/data-broker-removal.md#bulk--paid-services`.
The skill's manual tracking still runs alongside paid services — they catch
different brokers.

### 6. Install the weekly passive scan (launchd)

The harness ships with `com.exobrain.bodyguard-weekly.plist` — install it:

```bash
chmod +x /Users/alexhedtke/Documents/Exobrain\ harness/.claude/skills/cybersecurity-bodyguard/scripts/weekly-scan.sh
cp /Users/alexhedtke/Documents/Exobrain\ harness/com.exobrain.bodyguard-weekly.plist ~/Library/LaunchAgents/
launchctl load ~/Library/LaunchAgents/com.exobrain.bodyguard-weekly.plist
```

Runs Sundays at 8 AM. Writes scan plan to `/tmp/bodyguard-weekly-YYYYMMDD.json`
and posts a macOS notification. Open Claude Code and say "ingest bodyguard scan"
to have it execute the Google dorks via WebSearch and append findings to
`Security Log.md`.

To uninstall: `launchctl unload ~/Library/LaunchAgents/com.exobrain.bodyguard-weekly.plist`

### 7. Exposure audit on staged commits

Already wired into the evening-winddown skill — step 7 of the wind-down runs
`scripts/exposure_audit.py --staged` before auto-committing. HIGH findings
(your real name, email, phone, partner info, or any credential shape) block
the commit. MED findings (employer, usernames, aliases) prompt for confirmation.
No manual install needed.

## What's tracked in git vs not

**Committed:**
- `SKILL.md`, runbooks, scripts, `targets.example.json`, this README

**Gitignored (via `.gitignore`):**
- `targets.json` — real PII
- `.claude/skills/cybersecurity-bodyguard/scan-results/` — runtime scan output
- `.claude/skills/cybersecurity-bodyguard/cache/` — any cached broker responses

All personal data and scan results stay local or in your Obsidian vault. This
follows the privacy pattern documented in the root `CLAUDE.md`.

## Triggering the skill

Natural language works:
- "Run a bodyguard scan"
- "Am I being doxxed?"
- "What's public about me right now?"
- "Vet this sender: [paste email/handle]"
- "Check this before I post"
- "I think I'm being followed"

Or explicitly: `/cybersecurity-bodyguard`.

## Safety notes

- This skill is **strictly defensive**. It will refuse any request to identify
  attackers, retaliate, or access harassment forums.
- For active threats involving physical safety, the skill will redirect to
  `runbooks/stalking-response.md` and professional resources (911, local PD,
  VictimConnect, EFF).
- Scan results stay local. No data is sent to any third party other than
  HIBP (breach check), Google (via your WebSearch), and public data-broker
  indices — all of which you could query yourself.
