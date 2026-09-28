# bin/

Loose command-line tools that belong to no single module. Each line below comes from the tool's own header comment or docstring; read the file for usage and flags.

| Tool | What it does |
|------|--------------|
| `avatar-fit` | Sizes an image so nothing clips in a circular avatar cropper (ESPN Fantasy, most social platforms), which pad-to-square alone does not guarantee. |
| `cowork-sync` | Keeps the harness `CLAUDE.md` and the iCloud "Claude Cowork" copy identical in both directions; run by `com.exobrain.cowork-sync`. |
| `deezer-dl` | Downloads a track from Deezer given a Deezer or Spotify link, for when Spotify's free tier cannot download. |
| `drive-evict` | Drops the local bytes of Google Drive (or any File Provider) files, leaving cloud-only placeholders; same as Finder's "Remove Download". |
| `drive-fetch` | Reads a Google Drive file's bytes through the Drive API, bypassing the DriveFS mount when its on-demand hydration wedges (EDEADLK). |
| `jackbox` | Plays Jackbox party games from the command line: launch a CDP-driven Chrome, join a room, run the autopilot. Used by the `/jackbox` skill. |
| `letter-pdf` | Renders a plain-markdown letter into a formal, print-ready PDF. |
| `linkedin-mcp` | Launches `mcp-server-linkedin` in real headless mode instead of macOS hidden-target mode, which breaks every navigation. Registered as the `linkedin` MCP server. |
| `luma` | Luma event management CLI (cookie-auth write lane, works on the free plan), using `LUMA_AUTH_SESSION_KEY` from the harness `.env`. Used by the `/luma` skill. |
| `luma-to-meetup` | Mirrors the Kansas City EA Luma calendar onto the Meetup group, creating each missing future event with a link back to Luma. |
| `pe-triage` | Static triage of a Windows PE file (headers, sections, imports, resources, packer tells, hashes); never executes it. |
| `spotify-dl` | Downloads a Spotify track by URL or id, taking metadata from the embed page instead of the rate-limited Spotify Web API. Needs Premium. |
| `yt-transcript` | Pulls a YouTube video's captions as clean, readable text (wraps `yt-dlp`, then strips the auto-caption duplication). |

Anything executable in a `bin/` directory is picked up automatically by the tools registry (`tools-registry/tools-registry-scan.py` scans every `~/Documents/*/bin`), so a new tool here needs no manual `log-tool.py add`. Add a line to this table when you add one.
