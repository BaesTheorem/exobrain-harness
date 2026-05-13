# Awair Element — CO2 watcher

Polls the Awair Element's local API every 5 minutes via launchd and fires a
macOS notification when CO2 crosses thresholds during active hours
(default 7am–11pm).

## Setup

1. Enable Local API in the Awair phone app: tap device → gear icon → Awair API
   section → toggle **Awair Local API** on.
2. Find the device on the LAN:
   ```
   dns-sd -B _http._tcp local
   ```
   Look for an `AWAIR-ELEM-XXXXXX` entry. Resolve to confirm:
   ```
   dns-sd -G v4 AWAIR-ELEM-XXXXXX.local
   ```
3. Add the hostname to `.env` at the harness root:
   ```
   AWAIR_HOST=AWAIR-ELEM-XXXXXX.local
   ```
4. Load the launchd agent (real file copy, not a symlink — see
   `feedback_launchd_symlinks`):
   ```
   cp com.exobrain.awair-co2-watcher.plist ~/Library/LaunchAgents/
   launchctl load ~/Library/LaunchAgents/com.exobrain.awair-co2-watcher.plist
   ```

## Thresholds

Edit constants at the top of `awair-co2-watcher.py`:

| Constant            | Default | Meaning                                 |
|---------------------|---------|-----------------------------------------|
| `CO2_WARN`          | 1000    | Standard ventilation alert (ppm)        |
| `CO2_URGENT`        | 1500    | Urgent alert with Basso sound (ppm)     |
| `HYSTERESIS_MIN`    | 30      | Min minutes between same-tier alerts    |
| `ACTIVE_HOUR_START` | 7       | Earliest hour to send alerts (local)    |
| `ACTIVE_HOUR_END`   | 23      | Latest hour (exclusive)                 |

## Files

- `awair-co2-watcher.py` — the script
- `state.json` — last-notified timestamps (gitignored)
- Logs: `~/.claude/channels/awair/co2-watcher.log`
