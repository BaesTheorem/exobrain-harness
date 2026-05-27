# Phone — two-way voice calls with Claude (full Exobrain parity)

Claude rings your phone and you have a real spoken conversation — and it has
your actual Exobrain tools. Twilio's **ConversationRelay** does speech-to-text
and text-to-speech; a local server runs a **Claude Agent SDK** session that
loads the harness `CLAUDE.md`, the project MCP servers, and the skills, so the
voice on the phone is effectively the same assistant as Claude Code.

```
You (phone) <--voice--> Twilio (STT/TTS) <--text/WS--> server.py <--Agent SDK--> Claude + tools
```

## What it can do

Loaded via `setting_sources=["project"]` (your `CLAUDE.md`, `.mcp.json`, skills):

- **Things 3** (read + create/update tasks), **Fitbit**, **Withings**
- **Your Obsidian vault** — read and write notes (`add_dirs` grants access)
- **Bash, web search/fetch**, and all harness skills

**Known parity gap:** Gmail, Google Calendar, Drive, MyChart, and LinkedIn are
managed-app MCP servers configured *outside* `.mcp.json`, so they are NOT loaded
here yet. Closing that gap means wiring those server configs into the Agent SDK
options explicitly. Until then, phone-Claude can't send email or touch calendar.

## Security model (read the PIN part)

A phone line is weakly authenticated (caller ID is spoofable), so:

- **Read-only tools** (`get_/list_/search_/show_`) — always allowed.
- **Mutating tools** (create/edit/send/delete, plus `Bash`/`Write`/`Edit`) —
  **blocked by a PreToolUse hook until you enter `VOICE_PIN`** on the keypad
  (DTMF) or speak it. The hook fires on every tool regardless of the project
  permission allowlist, so allow-listed write tools can't sneak past it.
- Calls are currently **outbound-only** (you run `call.py`), so in practice only
  whoever holds your verified phone is ever on the line. The PIN is defense in
  depth for if you ever enable inbound.

Set `VOICE_PIN` in `.env` to something you'll remember. Blank = all writes stay
locked (fail-safe).

## Files

- `server.py` — the conversation brain (FastAPI WebSocket + TwiML endpoint).
- `call.py` — places an outbound call to your phone.
- `.env` — real credentials (gitignored). Built from `.env.example`.
- `requirements.txt` — Python deps.

## What you (the human) must set up

Claude scaffolded the code, but these steps need a person:

1. **Twilio account** — sign up at console.twilio.com. Grab the **Account SID**
   and **Auth Token** from the dashboard. (Account SID is already in `.env`.)
2. **A Twilio phone number** — buy/claim one in the console. Put it in
   `TWILIO_FROM_NUMBER` (E.164, e.g. `+18165551234`).
3. **Verify your cell** — on a *trial* account, outbound calls only reach
   numbers you've verified (Console → Phone Numbers → Verified Caller IDs).
   Put your cell in `MY_PHONE_NUMBER`. Trial calls also play a short "trial
   account" preamble before our greeting — upgrade (~$1/mo number) to remove it.
4. **Anthropic API key** — from console.anthropic.com. This is pay-per-token and
   separate from the Claude Code subscription. Put it in `ANTHROPIC_API_KEY`.

## Running it

A Python venv (`.venv/`) and `cloudflared` are used (both gitignored / Homebrew).

```bash
cd phone
python3 -m venv .venv && .venv/bin/pip install -r requirements.txt   # one time

.venv/bin/uvicorn server:app --host 0.0.0.0 --port 8080   # terminal 1

cloudflared tunnel --url http://localhost:8080            # terminal 2 (no signup)
# copy the printed https host, e.g. something.trycloudflare.com
# set in .env:  PUBLIC_WS_URL=wss://something.trycloudflare.com/ws
# then restart the server so /twiml picks up the URL

.venv/bin/python call.py                                  # terminal 3 — your phone rings
```

Answer and talk. To do anything that writes, key in your `VOICE_PIN` on the
keypad when prompted. Hang up to end.

### Inbound (you call Claude)

The Twilio number's voice webhook is set to `https://<tunnel-host>/twiml`, so
dialing the number reaches Claude. Set it via the console or API:

```bash
curl -s -u "$SID:$TOKEN" -X POST \
  "https://api.twilio.com/2010-04-01/Accounts/$SID/IncomingPhoneNumbers/$PN.json" \
  --data-urlencode "VoiceUrl=https://<tunnel-host>/twiml" --data-urlencode "VoiceMethod=POST"
```

Because the tunnel URL rotates on restart, re-run this whenever the tunnel changes.

**Caller-ID safeguard:** on setup, the server trusts the call only if a number in
`ALLOWED_CALLERS` is on either end. Trusted callers get free reads; unknown
inbound callers must enter the PIN even to read anything. Writes always need the
PIN. Caller ID is spoofable, so this is defense in depth, not a hard lock.

## Latency tuning

The full agent loop is the slow part. Current mitigations in `server.py`:
- `include_partial_messages=True` — TTS speaks tokens as Claude generates them.
- `effort="low"` and `skills=None` — less deliberation, smaller prompt.
- The session connects on call setup so MCP boots during the greeting.
- First reply on a call is slowest (~3s, uncached prompt); later turns are faster
  as the prompt caches. Tool requests add a round trip (a "ToolSearch" step before
  the tool runs), which is why lookups pause longer than chat.

Bigger levers if you need it snappier (trade capability): switch `AGENT_MODEL` to
`claude-haiku-4-5-20251001`, or shrink the MCP/tool surface (fewer servers) to
avoid the tool-search round trip.

## Notes / gotchas

- **NAT:** Twilio dials *into* the server, so the Mac needs a public URL.
  `cloudflared` is the no-signup option; the free `trycloudflare.com` subdomain
  rotates on each restart, so re-set `PUBLIC_WS_URL` (and restart the server)
  whenever you restart the tunnel.
- **Latency:** runs the full agent loop (Sonnet by default via `AGENT_MODEL`),
  so tool lookups add a few seconds of "one moment" silence. The session connects
  on call setup so MCP servers boot while the greeting plays.
- **Auth/cost:** the Agent SDK drives the local `claude` CLI; the conversation
  bills against the API key in `.env`.
- **Privacy:** real credentials and `VOICE_PIN` live only in the gitignored
  `.env`. Conversation context (your vault, tasks, health) is sent to the API
  during a call, same as Claude Code.
- **Memory:** each call is a fresh agent session — nothing persists between calls.
