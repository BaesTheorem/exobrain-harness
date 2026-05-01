---
name: antivirus
description: Native macOS LOCAL MACHINE security audit — XProtect state, persistence mechanisms (LaunchAgents/Daemons, login items), network listeners, browser extensions, known-malware paths, and quarantine history on THIS LAPTOP. No third-party AV required. SCOPE IS THE LOCAL MAC, not this repo or the public internet. Use when the user says "antivirus scan", "machine antivirus scan", "macOS security check", "am I infected", "check my machine", "is my Mac compromised", or during a bodyguard incident response. For online/public attack surface use cybersecurity-bodyguard; for repo/codebase privacy use exobrain-audit.
---

# Antivirus (macOS Native Audit)

Lightweight, install-free security audit of this Mac. Uses only built-in macOS tooling. Signature-based AV scanning (ClamAV, Malwarebytes, Objective-See tools) is opt-in and not run by default.

## Scope

**What this does:** enumerate what's persistent, what's listening, what's been quarantined, and whether OS-level protections are on. Catches ~90% of real-world macOS compromises (which are mostly persistence-based adware and credential stealers, not kernel exploits).

**What this does NOT do:** signature scanning of every file on disk, memory forensics, kernel rootkit detection, or network traffic analysis. If the native audit is clean but you still suspect compromise, escalate to Objective-See's KnockKnock / BlockBlock / LuLu or a full Malwarebytes scan.

## When to run

- User asks for an antivirus / malware / security scan
- During cybersecurity-bodyguard incident response (Mode 3)
- After installing unsigned software or clicking a suspicious link
- Monthly baseline (add to monthly-review skill if not already)

## Config

No config file. The skill enumerates everything and compares against:
1. A hard-coded known-bad-path list (common macOS malware install locations)
2. A "normal for Alex" allowlist below — update this when new legitimate software is installed

**Known-good LaunchAgent prefixes:**
- `com.exobrain.*` — all exobrain harness jobs
- `com.google.*` — Google Updater, Keystone, Drive
- `us.zoom.*` — Zoom auto-update
- `com.apple.*` — Apple system agents

**Known-good login items:**
- Things Helper, BetterTouchTool, Claude, Google Drive, Plaud, Discord

Anything outside these prefixes should be flagged for review.

## Phases

Run in parallel where possible. Every phase writes to `/Users/alexhedtke/Documents/Exobrain/Areas/Security/av-scans/YYYY-MM-DD.md`.

### Phase 1 — OS protections

```bash
csrutil status                                      # SIP
spctl --status                                      # Gatekeeper
fdesetup status                                     # FileVault
/usr/libexec/ApplicationFirewall/socketfilterfw --getglobalstate   # Firewall
defaults read /Library/Apple/System/Library/CoreServices/XProtect.bundle/Contents/Info CFBundleShortVersionString   # XProtect version
```

Flag any that are disabled. Firewall off on a personal laptop is a HIGH finding; everything else should be on by default.

### Phase 2 — Persistence enumeration

```bash
ls ~/Library/LaunchAgents/ 2>/dev/null
ls /Library/LaunchAgents/ 2>/dev/null
ls /Library/LaunchDaemons/ 2>/dev/null
launchctl list | grep -v "^com.apple\."
osascript -e 'tell application "System Events" to get the name of every login item'
```

Compare each entry against the known-good allowlist above. Investigate unknowns:
- `plutil -p <plist path>` shows what it runs
- `codesign -dv <binary>` shows signing identity
- Unsigned or ad-hoc-signed binaries in user directories are a red flag

### Phase 3 — Known-bad path sweep

Check these paths; existence of any is a HIGH finding:

```
~/Library/Application Support/Genieo/
~/Library/Application Support/MacKeeper/
~/Library/Application Support/VSearch/
~/Library/mdworker_shared
~/Library/softwareupdated
/Applications/MPlayerX.app
/Applications/Shlayer.app
/Library/LaunchAgents/com.apple.softwareupdated.plist   # Apple doesn't install plists here
/private/tmp/GoogleSoftwareUpdateAgent.bundle
```

Plus: any plist in `~/Library/LaunchAgents/` modified in last 30 days that isn't on the allowlist.

### Phase 4 — Network listeners

```bash
lsof -nP -iTCP -sTCP:LISTEN
```

Filter out known-good processes (rapportd, ControlCe, sharingd, mDNSResponder, nfsd, AirPlay, Discord IPC on 127.0.0.1, Chrome/Zed localhost). Flag anything binding to `0.0.0.0` or an external interface that you didn't start intentionally.

### Phase 5 — Browser extensions

```bash
# Chrome
ls ~/Library/Application\ Support/Google/Chrome/Default/Extensions/
# Safari
ls ~/Library/Safari/Extensions/
# Firefox (profile-specific)
ls ~/Library/Application\ Support/Firefox/Profiles/*/extensions/ 2>/dev/null
```

For each Chrome extension ID, resolve to name via the manifest:
```bash
cat ~/Library/Application\ Support/Google/Chrome/Default/Extensions/<ID>/*/manifest.json | python3 -c "import json, sys; m=json.load(sys.stdin); print(m.get('name'), '|', m.get('permissions', []))"
```

Flag:
- Extensions with `<all_urls>` or `webRequest` permission (can read all your traffic)
- Extensions not from a publisher you recognize
- Extensions you don't remember installing

Chrome extension supply-chain compromise is one of the top macOS attack vectors in 2026. Review ruthlessly.

### Phase 6 — Quarantine + recent downloads

```bash
sqlite3 ~/Library/Preferences/com.apple.LaunchServices.QuarantineEventsV2 \
  "SELECT datetime(LSQuarantineTimeStamp + 978307200, 'unixepoch', 'localtime'),
          LSQuarantineAgentName, LSQuarantineDataURLString
   FROM LSQuarantineEvent
   ORDER BY LSQuarantineTimeStamp DESC LIMIT 30;"
```

Review recent items for anything unexpected. Quarantine ≠ infection — it means macOS flagged a file as user-downloaded. But unexpected entries (from Safari/Chrome when you don't remember downloading anything) are worth checking.

### Phase 7 — Optional deep scan

Only if user requests or Phase 1–6 turns up anomalies.

**ClamAV:**
```bash
brew install clamav
sudo freshclam
clamscan -r --bell -i ~/Downloads ~/Desktop   # scan likely infection vectors first
```

**Objective-See tools** (recommended for macOS):
- KnockKnock — one-shot persistence scanner with signature database for known malware
- BlockBlock — real-time persistence alerts
- LuLu — outbound firewall (catches data exfiltration)
- Download from https://objective-see.org/tools.html (notarized by Patrick Wardle, ex-NSA)

Do not install these silently; the user decides.

## Output

Write a report to `/Users/alexhedtke/Documents/Exobrain/Areas/Security/av-scans/YYYY-MM-DD.md`:

```markdown
---
type: av-scan
date: YYYY-MM-DD
---
# Antivirus scan — YYYY-MM-DD

## Summary
- Status: CLEAN | REVIEW_NEEDED | SUSPICIOUS
- HIGH findings: N
- MED findings: N

## Phase 1 — OS protections
...

## Phase N — ...
...

## Actions
- [ ] Enable firewall
- [ ] Review Chrome extension X
```

Create Things 3 tasks for HIGH findings. Bundle MED findings into one review task. Send macOS notification with the summary.

## Integration

- **cybersecurity-bodyguard** Mode 3 (incident response) should invoke this skill's Phase 1–6 as part of the lockdown checklist.
- **monthly-review** — add a checklist item to run this skill monthly.
- **evening-winddown** — do NOT add here; this is not a daily check.

## Escalation

If HIGH findings appear, do not attempt to remediate silently — walk the user through each finding, confirm it's actually unexpected (vs. legitimate software they forgot about), then decide together whether to quarantine, remove, or investigate further.

For confirmed malware: don't just delete. Preserve the binary and plist in `~/Documents/Exobrain/Areas/Security/Incidents/YYYY-MM-DD-av-finding/` for later analysis, then remove persistence mechanisms and reboot.

## Ethical guardrails

- This skill only audits Alex's own machine. Never run these checks against someone else's system.
- If Alex asks to audit someone else's machine (partner, parent, employer), first confirm they have explicit consent and understand what's being collected.
- Do not exfiltrate scan results off-machine. The report stays in the vault.
