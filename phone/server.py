"""
Voice-call brain for the Exobrain harness — FULL PARITY edition.

Twilio ConversationRelay handles speech<->text on the phone side and connects
to this server over a WebSocket. Each call drives a Claude Agent SDK session
that loads the harness CLAUDE.md, the project MCP servers (Things 3, Fitbit,
Withings), and the skills — so the voice on the phone is effectively the same
assistant as Claude Code, with tools.

    You (phone) <--voice--> Twilio (STT/TTS) <--text/WS--> server.py <--Agent SDK--> Claude + tools

SECURITY: a phone line is weakly authenticated, so any *mutating* tool
(create/edit/send/delete, plus Bash/Write/Edit) is blocked by a PreToolUse hook
until the caller enters VOICE_PIN on the keypad (DTMF) or speaks it. Read-only
tools (get/list/search/show) are always allowed.

Run locally:
    .venv/bin/uvicorn server:app --host 0.0.0.0 --port 8080
    cloudflared tunnel --url http://localhost:8080   # public URL -> PUBLIC_WS_URL
"""
import os
import re
import json
from pathlib import Path

from dotenv import load_dotenv
from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.responses import Response
from claude_agent_sdk import (
    ClaudeSDKClient,
    ClaudeAgentOptions,
    HookMatcher,
    ResultMessage,
    StreamEvent,
)

load_dotenv()

HARNESS_DIR = Path(__file__).resolve().parent.parent
AGENT_MODEL = os.environ.get("AGENT_MODEL", "claude-sonnet-4-6")
VOICE_PIN = os.environ.get("VOICE_PIN", "")
PUBLIC_WS_URL = os.environ.get("PUBLIC_WS_URL", "")
TTS_PROVIDER = os.environ.get("TTS_PROVIDER", "Amazon")
TTS_VOICE = os.environ.get("TTS_VOICE", "Matthew-Neural")

# Phone numbers trusted for read access on INBOUND calls. Defaults to your cell.
# Unknown callers must enter the PIN even to read. (Outbound calls are always trusted.)
MY_PHONE = os.environ.get("MY_PHONE_NUMBER", "")
ALLOWED_CALLERS = {
    n.strip() for n in os.environ.get("ALLOWED_CALLERS", MY_PHONE).split(",") if n.strip()
}

# Directories outside the repo the agent must reach (vault, Plaud/Supernote).
ADD_DIRS = ["/Users/alexhedtke/Exobrain", "/Users/alexhedtke/My Drive"]

# Google Calendar MCP (scoped to the phone agent). Loads only once the OAuth
# credentials file exists, so the phone keeps working during setup.
PHONE_DIR = Path(__file__).resolve().parent
GCAL_CREDS = os.environ.get("GOOGLE_OAUTH_CREDENTIALS", str(PHONE_DIR / "gcp-oauth.keys.json"))
GCAL_TOKEN = os.environ.get("GOOGLE_CALENDAR_MCP_TOKEN_PATH", str(PHONE_DIR / "gcal-token.json"))


def extra_mcp_servers() -> dict:
    servers = {}
    if Path(GCAL_CREDS).exists():
        servers["google-calendar"] = {
            "command": "npx",
            "args": ["@cocal/google-calendar-mcp"],
            "env": {
                "GOOGLE_OAUTH_CREDENTIALS": GCAL_CREDS,
                "GOOGLE_CALENDAR_MCP_TOKEN_PATH": GCAL_TOKEN,
            },
        }
    return servers

WELCOME = "Hey Alex, it's Claude. I've got your Exobrain in front of me. What do you need?"

PHONE_APPEND = (
    "You are on a LIVE PHONE CALL with Alex. Everything you say is read aloud by "
    "text-to-speech, so keep replies short and conversational: no markdown, no "
    "bullet lists, no emoji, no URLs spelled out. One or two sentences unless he "
    "asks for detail. You have your full Exobrain toolset (Things 3, calendar, "
    "Gmail, the vault, health data). IMPORTANT: any action that creates, edits, "
    "sends, or deletes is locked until Alex enters his PIN on the phone keypad. If "
    "a tool comes back denied for that reason, tell him plainly to key in his PIN, "
    "then retry. Looking things up takes a few seconds, so it's fine to say 'one "
    "moment' while you check."
)

app = FastAPI()

# --- mutating-tool classification (denylist; reads pass, writes get gated) -----
MUTATING_BUILTINS = {"Write", "Edit", "NotebookEdit", "Bash"}
MUTATING_VERBS = (
    "add", "create", "update", "delete", "remove", "send", "draft", "book",
    "respond", "label", "unlabel", "move", "complete", "refill", "connect_with",
    "post", "request", "cancel", "schedule", "set_", "write", "trash", "archive",
    "star",
)


def is_mutating(tool_name: str) -> bool:
    if tool_name in MUTATING_BUILTINS:
        return True
    base = tool_name.split("__")[-1].lower()
    return any(v in base for v in MUTATING_VERBS)


def _deny(reason: str) -> dict:
    return {"hookSpecificOutput": {
        "hookEventName": "PreToolUse",
        "permissionDecision": "deny",
        "permissionDecisionReason": reason,
    }}


def make_gate(session: dict):
    """PreToolUse hook. Mutating tools always need the PIN. Reads are free for a
    trusted caller, but unknown callers (inbound) must PIN even to read."""
    async def gate(input_data, tool_use_id, context):
        if session["authed"]:
            return {}
        if is_mutating(input_data.get("tool_name", "")):
            return _deny(
                "Locked: Alex must enter his phone PIN on the keypad before any "
                "create, edit, send, or delete action. Tell him to key it in now."
            )
        if not session["caller_allowed"]:
            return _deny(
                "Unrecognized caller: no data access until the phone PIN is entered "
                "on the keypad. Ask them to key it in now."
            )
        return {}
    return gate


async def start_agent(session: dict) -> ClaudeSDKClient:
    opts = ClaudeAgentOptions(
        cwd=str(HARNESS_DIR),
        setting_sources=["project"],          # load CLAUDE.md + .mcp.json + skills
        mcp_servers=extra_mcp_servers(),      # + Google Calendar, once creds exist
        system_prompt={"type": "preset", "preset": "claude_code", "append": PHONE_APPEND},
        permission_mode="bypassPermissions",  # the PreToolUse hook is the only gate
        model=AGENT_MODEL,
        skills=None,                  # skip skill loading — trims prompt for lower latency
        effort="low",                 # less deliberation per turn
        include_partial_messages=True,  # stream text deltas so TTS starts immediately
        max_turns=30,
        add_dirs=ADD_DIRS,
        hooks={"PreToolUse": [HookMatcher(matcher=None, hooks=[make_gate(session)])]},
    )
    client = ClaudeSDKClient(options=opts)
    await client.connect()  # boots MCP servers while the greeting plays
    return client


def twiml_response() -> Response:
    xml = (
        '<?xml version="1.0" encoding="UTF-8"?>'
        "<Response><Connect>"
        f'<ConversationRelay url="{PUBLIC_WS_URL}" welcomeGreeting="{WELCOME}" '
        f'ttsProvider="{TTS_PROVIDER}" voice="{TTS_VOICE}" '
        'dtmfDetection="true" interruptible="true" />'
        "</Connect></Response>"
    )
    return Response(content=xml, media_type="text/xml")


@app.get("/twiml")
@app.post("/twiml")
async def twiml():
    return twiml_response()


async def say(ws: WebSocket, text: str):
    """Speak a complete utterance to ConversationRelay."""
    await ws.send_text(json.dumps({"type": "text", "token": text, "last": False}))
    await ws.send_text(json.dumps({"type": "text", "token": "", "last": True}))


@app.websocket("/ws")
async def conversation_relay(ws: WebSocket):
    await ws.accept()
    session = {"authed": False, "pin": "", "client": None, "caller_allowed": False}
    try:
        while True:
            msg = json.loads(await ws.receive_text())
            kind = msg.get("type")

            if kind == "setup":
                # Trust the call if Alex's number is on either end (outbound: he's
                # the "to"; inbound: he's the "from"). PIN still gates all writes.
                ends = {msg.get("from", ""), msg.get("to", "")}
                session["caller_allowed"] = bool(ALLOWED_CALLERS & ends)
                session["client"] = await start_agent(session)

            elif kind == "dtmf":
                await handle_dtmf(ws, session, msg.get("digit", ""))

            elif kind == "prompt":
                await handle_prompt(ws, session, msg.get("voicePrompt", "").strip())

            elif kind == "interrupt":
                client = session.get("client")
                if client:
                    try:
                        await client.interrupt()
                    except Exception:
                        pass

            elif kind == "error":
                print("ConversationRelay error:", msg.get("description"))

    except WebSocketDisconnect:
        pass
    finally:
        client = session.get("client")
        if client:
            try:
                await client.disconnect()
            except Exception:
                pass


async def handle_dtmf(ws: WebSocket, session: dict, digit: str):
    if session["authed"] or not VOICE_PIN:
        return
    if digit == "#":
        session["pin"] = ""
        return
    session["pin"] += digit
    if session["pin"].endswith(VOICE_PIN):
        session["authed"] = True
        await say(ws, "Got it, you're unlocked. What would you like me to do?")


async def handle_prompt(ws: WebSocket, session: dict, text: str):
    if not text:
        return
    # Allow speaking the PIN as a fallback to the keypad.
    if not session["authed"] and VOICE_PIN:
        if VOICE_PIN in re.sub(r"\D", "", text):
            session["authed"] = True
            await say(ws, "Got it, you're unlocked. What would you like me to do?")
            return
    await run_agent_turn(ws, session, text)


async def run_agent_turn(ws: WebSocket, session: dict, text: str):
    client = session.get("client")
    if client is None:
        client = session["client"] = await start_agent(session)

    await client.query(text, session_id="phone")
    spoke_filler = False
    async for message in client.receive_response():
        if isinstance(message, StreamEvent):
            event = message.event or {}
            etype = event.get("type")
            if etype == "content_block_delta":
                delta = event.get("delta", {})
                if delta.get("type") == "text_delta":
                    token = delta.get("text", "")
                    if token:  # stream each token so TTS speaks as Claude types
                        await ws.send_text(json.dumps(
                            {"type": "text", "token": token, "last": False}
                        ))
            elif etype == "content_block_start":
                block = event.get("content_block", {})
                if block.get("type") == "tool_use" and not spoke_filler:
                    spoke_filler = True
                    await ws.send_text(json.dumps(
                        {"type": "text", "token": "One moment. ", "last": False}
                    ))
        elif isinstance(message, ResultMessage):
            break
    await ws.send_text(json.dumps({"type": "text", "token": "", "last": True}))
