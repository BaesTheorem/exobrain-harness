# location

GPS history for the evening wind-down: where Alex went during the day, and which plans had no matching visit.

## Parts

- `receiver.py`: a small HTTP server that accepts batches from the [Overland](https://github.com/aaronpk/Overland-iOS) iOS app. It writes one JSONL file for each local day to `data/points/`. The launchd job `com.exobrain.overland-receiver` keeps it running.
- `where.py` (`bin/where`): turns a day of points into stays, moves, and gaps. Then it names each stay.
- `where.py import-google FILE`: converts a Google Maps Timeline export (`location-history.json`) into the same point format in `data/points-google/`. It reads the two export formats (iOS and Android).

Google Maps Timeline has no API, and its data stays on the phone. Thus the Google export is for history only. Overland supplies the daily data.

## Data (gitignored)

`data/` is personal data and is not in the repo. To make it again:

| Path | Contents | How to make it again |
| --- | --- | --- |
| `data/points/` | Overland points | Overland sends them again only if they were not acknowledged. Points that it sent before do not come back. |
| `data/points-google/` | Points from a Google export | Export again from Google Maps, then run `import-google`. |
| `data/places.json` | Your names for places: `[{"name", "lat", "lon", "radius_m"}]` | Write it by hand. |
| `data/geocache.json` | Reverse geocode cache | It refills by itself. |

The Home point comes from `MYKCMO_HOME_LAT` and `MYKCMO_HOME_LON` in the harness `.env`.

## Setup

1. Add `OVERLAND_TOKEN` (a random string) and `OVERLAND_PORT` (default 5061) to the harness `.env`.
2. Copy the plist to `~/Library/LaunchAgents/` (a copy, not a symlink), then load it:
   `launchctl bootstrap gui/$(id -u) ~/Library/LaunchAgents/com.exobrain.overland-receiver.plist`
3. In Overland, set the Receiver Endpoint to `http://<mac-hostname>.local:5061/overland?token=<OVERLAND_TOKEN>`.
4. Make sure that `curl http://<mac-hostname>.local:5061/health` returns `{"ok": true}`.

The receiver listens on the local network only. Overland keeps points on the phone until the receiver replies `{"result": "ok"}`, so points from a day away from home come in when the phone is on home Wi-Fi again.

## Usage

```
location/bin/where                # today
location/bin/where yesterday --json
location/bin/where 2026-10-05 --offline   # no reverse geocode
location/bin/where import-google ~/Downloads/location-history.json
```

A gap is a period of 90 minutes or more with no points during travel. A gap means that there is no data. It does not show that Alex stayed at one location.

## Troubleshooting

- No points today: open Overland and look at the queue count. If the queue grows and does not send, examine `~/Library/Logs/exobrain/overland-receiver.log` and the endpoint URL.
- `401 bad token`: the token in the Overland URL is not the same as `OVERLAND_TOKEN`.
- Session start shows `WARN: GPS points stale` when the newest day file is more than 2 days old.
