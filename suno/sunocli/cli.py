"""Command-line front end for the Suno client.

Human-readable output by default; ``--json`` emits records for other tools. Two commands spend
something and say so before they do: ``generate``/``describe`` spend credits, and ``download``
spends one of the plan's monthly downloads when the clip is still locked. Both ask at a
terminal and need ``--yes`` anywhere else. ``raw`` is the escape hatch for a route no named
command covers.

Exit status: 0 ok, 1 server or transport error, 2 usage or input error, 3 login needed or
rejected, 4 blocked (not confirmed, bot check, quota, duplicate, locked), 5 the web API
changed shape, 6 a paid request went out and no answer came back.
"""

from __future__ import annotations

import argparse
import json
import os
import shutil
import subprocess
import sys
import time
import urllib.request
from datetime import datetime
from pathlib import Path
from typing import Any, Callable

from sunocli import model, session as sess
from sunocli.api import (AuthRejected, NotAuthorized, OutcomeUnknown, RateLimited, Rejected,
                         SchemaDrift, SunoClient, SunoError)
from sunocli.captcha import CaptchaBlocked, token_for
from sunocli.ledger import Blocked, Ledger
from sunocli.model import InputError

Json = dict[str, Any]

HERE = Path(__file__).resolve().parent.parent  # suno/
LIBRARY = Path(os.environ.get("SUNO_LIBRARY") or HERE / "library")
STANDARD_COST = 10  # credits for one standard generation (two songs), per Suno's v6 FAQ
PAID_ROUTES = ("/generate/", "/download/authorize")
SEEN_CAP = 5000  # ids kept for short-id lookup


# -- small helpers -----------------------------------------------------------------------------


def out(text: str = "") -> None:
    print(text)


def note(text: str) -> None:
    print(text, file=sys.stderr)


def emit_json(value: Any) -> None:
    print(json.dumps(value, indent=1, ensure_ascii=False))


def local_day(iso: str | None) -> str:
    if not iso:
        return "?"
    try:
        return datetime.fromisoformat(iso.replace("Z", "+00:00")).astimezone().strftime("%Y-%m-%d %H:%M")
    except ValueError:
        return iso[:16]


def clip_line(c: Json) -> str:
    lock = "yes" if c["unlocked"] else "-"
    title = (c["title"] or "(untitled)")[:38]
    return (f"{local_day(c['created_at']):16}  {str(c['id'])[:8]}  {model.fmt_duration(c['duration']):>5}  "
            f"{(c['version'] or '?'):4}  {lock:3}  {c['status'] or '?':9}  {title}")


CLIP_HEAD = f"{'created':16}  {'id':8}  {'len':>5}  {'ver':4}  {'dl':3}  {'status':9}  title"


def confirm(args: argparse.Namespace, question: str) -> None:
    """Spend gate. A terminal gets a question; anything else needs ``--yes``."""
    if getattr(args, "yes", False):
        return
    if sys.stdin.isatty() and sys.stdout.isatty():
        if input(f"{question} [y/N] ").strip().lower() in ("y", "yes"):
            return
        raise Blocked("not confirmed; nothing was sent")
    raise Blocked(f"{question} Pass --yes to confirm. Nothing was sent.")


def downloads_left(billing: Json) -> tuple[int, int, int]:
    use = billing.get("download_usage") or {}
    limit = int(use.get("current_period_downloads_limit") or 0)
    used = int(use.get("current_period_downloads_used") or 0)
    return max(limit - used, 0), limit, int(use.get("additional_download_remaining") or 0)


def remember(ctx: "Ctx", clips: list[Json]) -> None:
    """Keep the ids this CLI has shown, so a short id works for an old song too."""
    path = ctx.ledger.root / "seen-ids.json"
    try:
        seen: list[str] = json.loads(path.read_text()) if path.exists() else []
    except ValueError:
        seen = []
    fresh = [str(c["id"]) for c in clips if c.get("id") and str(c["id"]) not in seen]
    if fresh:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps((fresh + seen)[:SEEN_CAP]))


def resolve(ctx: "Ctx", ref: str, trashed: bool = False) -> str:
    """A full clip id from an id, a song link, or the short id that `suno list` prints.

    A short id is matched first against the ids this CLI has shown before, then against the
    newest 100 songs (or the newest 100 in the trash).
    """
    clip_id = model.parse_clip_ref(ref)
    if len(clip_id) == 36:
        return clip_id
    path = ctx.ledger.root / "seen-ids.json"
    try:
        seen: list[str] = json.loads(path.read_text()) if path.exists() else []
    except ValueError:
        seen = []
    hits = [i for i in seen if i.startswith(clip_id)]
    if not hits:
        hits = [c["id"] for c in ctx.client.library(limit=100, trashed=trashed)
                if str(c["id"]).startswith(clip_id)]
    if len(hits) == 1:
        return hits[0]
    if not hits:
        raise InputError(f"no known clip starts with {clip_id!r}; find it with `suno list -s TEXT` "
                         "or give the full id")
    raise InputError(f"{len(hits)} clips start with {clip_id!r}; give more characters")


def read_text_arg(inline: str | None, path: str | None) -> str:
    if inline and path:
        raise InputError("give the lyrics inline or as a file, not both")
    if path == "-":
        return sys.stdin.read()
    if path:
        return Path(path).expanduser().read_text()
    return (inline or "").replace("\\n", "\n")


def fetch_file(url: str, dest: Path) -> int:
    """Stream a signed URL to ``dest`` through a ``.part`` file. Returns the byte count."""
    part = dest.with_name(dest.name + ".part")
    req = urllib.request.Request(url, headers={"user-agent": sess.user_agent()})
    total = 0
    with urllib.request.urlopen(req, timeout=120) as resp, part.open("wb") as fh:
        while chunk := resp.read(1 << 16):
            fh.write(chunk)
            total += len(chunk)
    part.replace(dest)
    return total


def probe_duration(path: Path) -> float | None:
    """The decoded length in seconds from ffprobe, or None when ffprobe is absent or fails."""
    exe = shutil.which("ffprobe")
    if not exe:
        return None
    done = subprocess.run([exe, "-v", "error", "-show_entries", "format=duration", "-of",
                           "default=nw=1:nk=1", str(path)], capture_output=True, text=True, check=False)
    try:
        return float(done.stdout.strip())
    except ValueError:
        return None


# -- commands: account -------------------------------------------------------------------------


def cmd_auth(args: argparse.Namespace, ctx: "Ctx") -> int:
    action = args.action or "status"
    if action == "import":
        sess.import_from_browser(args.browser)
        ctx.reset()
        out(f"Imported the Suno login from {args.browser}.")
    elif action == "set":
        value = sess.clean_pasted(sys.stdin.read() if not sys.stdin.isatty() else input("__client cookie: "))
        sess.save({"client": value, "device_id": None, "source": "pasted", "imported_at": int(time.time())})
        ctx.reset()
        out("Stored the pasted login.")
    elif action == "clear":
        out("Removed the stored login." if sess.clear() else "No stored login.")
        return 0
    who = ctx.client.whoami()
    billing = ctx.client.billing()
    out(f"Logged in as @{who['handle']} ({who['display_name']}), {(billing.get('plan') or {}).get('name')}.")
    return 0


def cmd_status(args: argparse.Namespace, ctx: "Ctx") -> int:
    client = ctx.client
    billing, gate = client.billing(), client.captcha_gate()
    left, limit, extra = downloads_left(billing)
    plan = billing.get("plan") or {}
    record = {
        "handle": client.session.handle(), "plan": plan.get("name"), "period": billing.get("period"),
        "credits_left": billing.get("total_credits_left"), "credits_monthly": billing.get("monthly_limit"),
        "credits_used": billing.get("monthly_usage"), "downloads_left": left, "downloads_limit": limit,
        "downloads_extra": extra, "renews_on": billing.get("renews_on"), "cancel_on": billing.get("cancel_on"),
        "models": [m.get("name") for m in billing.get("models") or [] if m.get("can_use") is not False],
        "bot_check": gate,
    }
    if args.json:
        emit_json(record)
        return 0
    out(f"Suno      @{record['handle']}  {record['plan']} ({record['period']})")
    out(f"Credits   {record['credits_left']:,} left  ({record['credits_used']:,} of "
        f"{record['credits_monthly']:,} used this period)")
    out(f"Downloads {left} of {limit} left this period, plus {extra} extra")
    out(f"Renews    {local_day(record['renews_on'])}" +
        (f"   (cancel_on: {local_day(record['cancel_on'])})" if record["cancel_on"] else ""))
    out(f"Models    {', '.join(record['models'])}")
    kinds: dict[Any, str] = {1: "hCaptcha", 2: "Turnstile"}
    kind = kinds.get(gate.get("captcha_version"), "unknown kind")
    out(f"Bot check {'required for generation (' + kind + ')' if gate.get('required') else 'not required'}")
    return 0


def cmd_models(args: argparse.Namespace, ctx: "Ctx") -> int:
    models = ctx.client.billing().get("models") or []
    if args.json:
        emit_json(models)
        return 0
    for m in models:
        lim = m.get("max_lengths") or {}
        flags = "default" if m.get("is_default_model") else ""
        usable = "usable" if m.get("can_use") is not False else "not in plan"
        out(f"{m.get('name', '?'):9} {m.get('external_key', '?'):16} {usable:11} {flags:8} "
            f"lyrics {lim.get('prompt', '?')}  style {lim.get('tags', '?')}  title {lim.get('title', '?')}")
    return 0


# -- commands: library -------------------------------------------------------------------------


def cmd_list(args: argparse.Namespace, ctx: "Ctx") -> int:
    clips = [model.normalize_clip(c) for c in
             ctx.client.library(limit=args.limit, search=args.search, trashed=args.trashed)]
    remember(ctx, clips)
    if args.json:
        emit_json(clips)
        return 0
    if not clips:
        out("No songs.")
        return 0
    out(CLIP_HEAD)
    for c in clips:
        out(clip_line(c))
    return 0


def cmd_info(args: argparse.Namespace, ctx: "Ctx") -> int:
    clip = model.normalize_clip(ctx.client.clip(resolve(ctx, args.clip)))
    if args.json:
        emit_json(clip)
        return 0
    for label, key in (("Title", "title"), ("Id", "id"), ("Link", "url"), ("Status", "status"),
                       ("Model", "model"), ("Task", "task"), ("Style", "tags")):
        out(f"{label:9} {clip[key] or '-'}")
    out(f"{'Created':9} {local_day(clip['created_at'])}")
    out(f"{'Length':9} {model.fmt_duration(clip['duration'])}")
    out(f"{'Download':9} {'unlocked (free to download again)' if clip['unlocked'] else 'locked (an unlock costs 1 download)'}")
    if clip["lyrics"]:
        out("\n" + clip["lyrics"].strip())
    return 0


def cmd_lyrics(args: argparse.Namespace, ctx: "Ctx") -> int:
    clip_id = resolve(ctx, args.clip)
    if not (args.lrc or args.words or args.json):
        text = model.normalize_clip(ctx.client.clip(clip_id))["lyrics"]
    else:
        aligned = ctx.client.aligned_lyrics(clip_id)
        if args.lrc:
            text = model.to_lrc(aligned, model.normalize_clip(ctx.client.clip(clip_id))["title"])
        elif args.words:
            text = json.dumps(model.timed_words(aligned), indent=1, ensure_ascii=False)
        else:
            text = json.dumps({"lines": model.timed_lines(aligned), "words": model.timed_words(aligned)},
                              indent=1, ensure_ascii=False)
    if args.out:
        Path(args.out).expanduser().write_text(text if text.endswith("\n") else text + "\n")
        note(f"wrote {args.out}")
    else:
        out(text.rstrip("\n"))
    return 0


def cmd_set(args: argparse.Namespace, ctx: "Ctx") -> int:
    clip_id = resolve(ctx, args.clip)
    ctx.client.set_metadata(clip_id, {"title": args.title})
    out(f"Title set: {args.title}")
    return 0


def cmd_trash(args: argparse.Namespace, ctx: "Ctx") -> int:
    ids = [resolve(ctx, ref, trashed=args.command == "restore") for ref in args.clips]
    ctx.client.set_trashed(ids, args.command == "trash")
    out(f"{'Moved to trash' if args.command == 'trash' else 'Restored'}: {', '.join(i[:8] for i in ids)}")
    return 0


# -- commands: creating ------------------------------------------------------------------------


def build_request(args: argparse.Namespace, billing: Json) -> Json:
    model_key = model.resolve_model(args.model, billing) if args.model else model.default_model(billing)
    common: Json = dict(model_key=model_key, plan_id=str((billing.get("plan") or {}).get("id") or ""),
                        max_mode=args.max_mode, persona_id=args.persona, request_id=args.request_id,
                        limits=model.limits_for(model_key, billing))
    if args.command == "describe":
        return model.generate_payload(mode="simple", text=args.description, **common)
    return model.generate_payload(
        mode="custom", title=args.title or "", tags=args.tags or "", exclude=args.exclude or "",
        text=read_text_arg(args.lyrics, args.lyrics_file), instrumental=args.instrumental,
        weirdness=args.weirdness, style_influence=args.style_influence, **common)


def show_clips(ctx: "Ctx", clips: list[Json], as_json: bool, extra: Json | None = None) -> None:
    records = [model.normalize_clip(c) for c in clips]
    remember(ctx, records)
    if as_json:
        emit_json({"clips": records, **(extra or {})})
        return
    out(CLIP_HEAD)
    for c in records:
        out(clip_line(c))
    for c in records:
        out(f"  listen: {c['url']}")


def cmd_generate(args: argparse.Namespace, ctx: "Ctx") -> int:
    client, ledger = ctx.client, ctx.ledger
    billing = client.billing()
    payload = build_request(args, billing)
    balance = int(billing.get("total_credits_left") or 0)
    cost_note = (f"about {STANDARD_COST} credits for 2 songs" if not args.max_mode
                 else f"more than {STANDARD_COST} credits (Max Mode)")
    if args.dry_run:
        shown = dict(payload)
        for key in ("prompt", "gpt_description_prompt"):
            if not args.json and len(shown.get(key) or "") > 200:
                shown[key] = shown[key][:200] + f"... ({model.utf16_len(payload[key])} characters)"
        emit_json({"would_send": shown, "cost": cost_note, "credits_left": balance})
        return 0
    saved = ledger.check(payload, force=args.force)
    if saved:
        note(f"Request {payload['transaction_uuid']} was already submitted; nothing was sent.")
        show_clips(ctx, client.clips(saved["ids"]), args.json, {"request_id": saved["request_id"], "reused": True})
        return 0
    if balance < STANDARD_COST:
        raise Blocked(f"{balance} credits left; a generation costs {cost_note}")
    label = payload.get("title") or (payload.get("gpt_description_prompt") or "")[:40] or "(untitled)"
    confirm(args, f"Generate '{label}' on {payload['mv']}: {cost_note}, {balance:,} credits left.")
    token, provider = token_for(client.captcha_gate())
    receipt = ledger.open(payload, {"title": label, "model": payload["mv"],
                                    "mode": payload["metadata"]["create_mode"], "credits_before": balance})
    try:
        clips = client.generate(model.with_token(payload, token, provider))
    except OutcomeUnknown:
        ledger.close(receipt, "unknown")
        raise
    except SunoError as err:
        ledger.close(receipt, "rejected", error=err.code)
        raise
    ids = [c["id"] for c in clips]
    after = int(client.billing().get("total_credits_left") or 0)
    ledger.close(receipt, "submitted", ids=ids, credits_after=after)
    ledger.log_spend("generate", request_id=receipt["request_id"], ids=ids, credits_before=balance,
                     credits_after=after, model=payload["mv"])
    note(f"Submitted. Credits: {balance:,} -> {after:,} ({balance - after} spent).")
    if args.wait:
        clips = client.wait(ids, timeout=args.timeout, on_tick=_ticker())
    show_clips(ctx, clips, args.json, {"request_id": receipt["request_id"], "credits_spent": balance - after})
    return 0


def _ticker() -> Callable[[list[Json]], None]:
    last: dict[str, str] = {}

    def tick(state: list[Json]) -> None:
        for clip in state:
            status = str(clip.get("status"))
            if last.get(clip["id"]) != status:
                last[clip["id"]] = status
                note(f"  {clip['id'][:8]} {status}")
    return tick


def cmd_wait(args: argparse.Namespace, ctx: "Ctx") -> int:
    ids = [resolve(ctx, ref) for ref in args.clips]
    clips = ctx.client.wait(ids, timeout=args.timeout, on_tick=_ticker())
    show_clips(ctx, clips, args.json)
    done = len(clips) == len(ids) and all(c.get("status") == "complete" for c in clips)
    return 0 if done else 1


def cmd_jobs(args: argparse.Namespace, ctx: "Ctx") -> int:
    receipts = ctx.ledger.all()[: args.limit]
    if args.json:
        emit_json(receipts)
        return 0
    if not receipts:
        out("No paid requests on record.")
    for r in receipts:
        when = datetime.fromtimestamp(r.get("opened_at", 0)).strftime("%Y-%m-%d %H:%M")
        spent = (r["credits_before"] - r["credits_after"]) if "credits_after" in r and "credits_before" in r else "?"
        out(f"{when}  {r.get('state', '?'):10}  {str(spent):>3} cr  {(r.get('title') or '(untitled)')[:30]:30}  "
            f"{' '.join(i[:8] for i in r.get('ids') or [])}  {r['request_id']}")
    return 0


# -- commands: downloading ---------------------------------------------------------------------


def cmd_download(args: argparse.Namespace, ctx: "Ctx") -> int:
    client, ledger = ctx.client, ctx.ledger
    clip_id = resolve(ctx, args.clip)
    raw = client.clip(clip_id)
    clip = model.normalize_clip(raw)
    if clip["status"] != "complete":
        raise Blocked(f"the clip is {clip['status']}; run `suno wait {clip_id[:8]}` first")
    spent = False
    if not clip["unlocked"]:
        billing = client.billing()
        left, limit, extra = downloads_left(billing)
        if left + extra <= 0:
            raise Blocked(f"no downloads left this period (0 of {limit}, 0 extra)")
        confirm(args, f"'{clip['title']}' is locked. The unlock costs 1 download: {left} of {limit} left "
                      f"this period, plus {extra} extra.")
        client.authorize_download(clip_id)
        spent = True
        after = downloads_left(client.billing())
        ledger.log_spend("download", id=clip_id, title=clip["title"], left_before=left, extra_before=extra,
                         left_after=after[0], extra_after=after[2])
        note(f"Unlocked. Downloads left: {after[0]} of {after[1]}, plus {after[2]} extra.")
    try:
        url = client.prepare_download(clip_id, args.format)
    except NotAuthorized as err:
        raise Blocked("Suno still reports the clip as locked. Run the command again in a minute; "
                      "a clip is not charged twice.") from err
    folder = Path(args.out).expanduser() if args.out else LIBRARY / model.folder_name(clip)
    folder.mkdir(parents=True, exist_ok=True)
    dest = folder / f"{model.slug(clip['title'])}.{args.format}"
    size = ctx.fetch(url, dest)
    (folder / "meta.json").write_text(json.dumps(clip, indent=1, ensure_ascii=False) + "\n")
    if clip["lyrics"]:
        (folder / "lyrics.txt").write_text(clip["lyrics"].strip() + "\n")
    if not clip["instrumental"]:
        try:
            lrc = model.to_lrc(client.aligned_lyrics(clip_id), clip["title"])
            if lrc.count("\n") > 1:
                (folder / "lyrics.lrc").write_text(lrc)
        except SunoError as err:
            note(f"no timed lyrics ({err.code})")
    measured = probe_duration(dest)
    record = {"path": str(dest), "bytes": size, "format": args.format, "id": clip_id,
              "title": clip["title"], "seconds": measured, "seconds_expected": clip["duration"],
              "unlock_spent": spent, "embed": f"![{clip['title'] or 'song'}]({dest})"}
    if args.json:
        emit_json(record)
        return 0
    out(f"Saved {dest}  ({size / 1e6:.1f} MB" + (f", {model.fmt_duration(measured)}" if measured else "") + ")")
    if measured and clip["duration"] and abs(measured - clip["duration"]) > 2:
        note(f"warning: the file is {measured:.1f} s long and Suno lists {clip['duration']:.1f} s")
    out(record["embed"])
    return 0


# -- commands: tooling -------------------------------------------------------------------------


def cmd_raw(args: argparse.Namespace, ctx: "Ctx") -> int:
    method, path = args.method.upper(), args.path if args.path.startswith("/") else "/" + args.path
    if method != "GET" and any(route in path for route in PAID_ROUTES):
        raise InputError("`raw` does not send paid requests; use `generate` or `download`")
    body = json.loads(args.body) if args.body else None
    emit_json(ctx.client.call(method, path, body))
    return 0


def cmd_doctor(args: argparse.Namespace, ctx: "Ctx") -> int:
    checks: list[tuple[str, bool, str]] = []

    def check(name: str, fn: Callable[[], str]) -> None:
        try:
            checks.append((name, True, fn()))
        except Exception as err:  # noqa: BLE001 - a health check reports every failure kind
            checks.append((name, False, f"{type(err).__name__}: {err}"))

    check("stored login", lambda: "present" if sess.load() else "absent (the next call imports it from Chrome)")
    check("token", lambda: f"minted for @{ctx.client.session.handle()}")
    check("api", lambda: f"{ctx.client.base} answers, {ctx.client.billing().get('total_credits_left')} credits")
    check("bot check", lambda: json.dumps(ctx.client.captcha_gate()))
    check("chrome", lambda: "installed" if sess.CHROME_APP.exists() else "missing: generation needs Google Chrome")
    check("ffprobe", lambda: shutil.which("ffprobe") or "missing: downloads are not length-checked")
    if args.drift:
        from sunocli import drift
        check("create form", lambda: drift.report(ctx.client))
    width = max(len(name) for name, _, _ in checks)
    for name, ok, detail in checks:
        out(f"{'ok  ' if ok else 'FAIL'} {name:{width}}  {detail}")
    return 0 if all(ok for _, ok, _ in checks) else 1


# -- wiring ------------------------------------------------------------------------------------


class Ctx:
    """What a command needs. Tests replace the client, the ledger and the byte fetcher."""

    def __init__(self, client: SunoClient | None = None, ledger: Ledger | None = None,
                 fetch: Callable[[str, Path], int] = fetch_file) -> None:
        self._client = client
        self.ledger = ledger or Ledger()
        self.fetch = fetch

    @property
    def client(self) -> SunoClient:
        if self._client is None:
            self._client = SunoClient(sess.Session())
        return self._client

    def reset(self) -> None:
        self._client = None


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="suno", description="Unofficial command line for suno.com.")
    sub = p.add_subparsers(dest="command", required=True)

    def add(name: str, fn: Callable[..., int], help_text: str, json_flag: bool = True) -> argparse.ArgumentParser:
        sp = sub.add_parser(name, help=help_text, description=help_text)
        sp.set_defaults(fn=fn)
        if json_flag:
            sp.add_argument("--json", action="store_true", help="machine-readable output")
        return sp

    a = add("auth", cmd_auth, "Show, import, paste or clear the Suno login.", json_flag=False)
    a.add_argument("action", nargs="?", choices=("status", "import", "set", "clear"))
    a.add_argument("--browser", default="chrome", choices=sorted(sess.BROWSERS))

    add("status", cmd_status, "Plan, credits, downloads left, and the bot-check state.")
    add("models", cmd_models, "The models the account can use, with their input limits.")

    ls = add("list", cmd_list, "The account's songs, newest first.")
    ls.add_argument("-n", "--limit", type=int, default=20, help="how many (0 = all; slow on a large library)")
    ls.add_argument("-s", "--search", help="text to find in titles and styles")
    ls.add_argument("--trashed", action="store_true", help="list the trash")

    info = add("info", cmd_info, "One song: status, style, lyrics, lock state, link.")
    info.add_argument("clip")

    ly = add("lyrics", cmd_lyrics, "A song's lyrics, plain or with timings.")
    ly.add_argument("clip")
    kind = ly.add_mutually_exclusive_group()
    kind.add_argument("--lrc", action="store_true", help="line-timed LRC")
    kind.add_argument("--words", action="store_true", help="word-level timings as JSON")
    ly.add_argument("-o", "--out", help="write to a file")

    def creation_flags(sp: argparse.ArgumentParser) -> None:
        sp.add_argument("--model", help="v6, v6-wild, v6-mini (default: the account's default)")
        sp.add_argument("--max-mode", action="store_true", help="more compute, more credits")
        sp.add_argument("--persona", help="voice persona id")
        sp.add_argument("--request-id", help="a UUID; the same id never sends twice")
        sp.add_argument("--wait", action="store_true", help="wait until the songs are complete")
        sp.add_argument("--timeout", type=float, default=600, help="seconds to wait (default 600)")
        sp.add_argument("--dry-run", action="store_true", help="print the request; send nothing")
        sp.add_argument("--force", action="store_true", help="send even if an identical request just went out")
        sp.add_argument("-y", "--yes", action="store_true", help="confirm the credit spend")

    g = add("generate", cmd_generate, "Make 2 songs from a style and lyrics. Spends credits.")
    g.add_argument("--tags", "--style", dest="tags", help="the style: genre, mood, voice, instruments, tempo")
    g.add_argument("--lyrics", help="lyrics inline; \\n starts a line")
    g.add_argument("--lyrics-file", help="lyrics from a file (- for stdin)")
    g.add_argument("--title", help="song title (Suno names it when absent)")
    g.add_argument("--exclude", help="styles to keep out")
    g.add_argument("--instrumental", action="store_true", help="no vocals")
    g.add_argument("--weirdness", type=float, help="0 to 100")
    g.add_argument("--style-influence", type=float, help="0 to 100")
    creation_flags(g)

    d = add("describe", cmd_generate, "Make 2 songs from one description (the form's Simple tab). Spends credits.")
    d.add_argument("description", help="what the song is: subject, style, voice, 'instrumental'")
    creation_flags(d)

    w = add("wait", cmd_wait, "Wait until songs are complete.")
    w.add_argument("clips", nargs="+")
    w.add_argument("--timeout", type=float, default=600)

    j = add("jobs", cmd_jobs, "Receipts for the paid requests sent from this machine.")
    j.add_argument("-n", "--limit", type=int, default=20)

    dl = add("download", cmd_download, "Save a song's audio. A locked song costs 1 download to unlock.")
    dl.add_argument("clip")
    dl.add_argument("-f", "--format", default="mp3", choices=("mp3", "wav", "m4a"))
    dl.add_argument("-o", "--out", help="folder (default: suno/library/<title>-<id>/)")
    dl.add_argument("-y", "--yes", action="store_true", help="confirm the download spend")

    st = add("set", cmd_set, "Rename a song.", json_flag=False)
    st.add_argument("clip")
    st.add_argument("--title", required=True)

    for name, text in (("trash", "Move songs to the trash."), ("restore", "Take songs out of the trash.")):
        t = add(name, cmd_trash, text, json_flag=False)
        t.add_argument("clips", nargs="+")

    r = add("raw", cmd_raw, "Call any API route and print the JSON. Refuses the two paid routes.", json_flag=False)
    r.add_argument("method", choices=("GET", "POST", "DELETE", "get", "post", "delete"))
    r.add_argument("path", help="for example /billing/info/")
    r.add_argument("body", nargs="?", help="JSON body")

    doc = add("doctor", cmd_doctor, "Health checks: login, token, API, bot check, tools.", json_flag=False)
    doc.add_argument("--drift", action="store_true",
                     help="capture the live Create form's request (sent nowhere) and compare shapes")
    return p


def main(argv: list[str] | None = None, ctx: Ctx | None = None) -> int:
    args = build_parser().parse_args(argv)
    ctx = ctx or Ctx()
    try:
        return args.fn(args, ctx)
    except (InputError, json.JSONDecodeError, FileNotFoundError) as err:
        note(f"suno: {err}")
        return 2
    except (sess.LoginNeeded, AuthRejected) as err:
        note(f"suno: {err}")
        return 3
    except (Blocked, CaptchaBlocked) as err:
        note(f"suno: {err}")
        return 4
    except SchemaDrift as err:
        note(f"suno: {err}\nSuno changed its web API. Run `suno doctor --drift` to see the difference.")
        return 5
    except OutcomeUnknown as err:
        note(f"suno: {err}\nThe request possibly went through. Read `suno list` and `suno jobs` first.")
        return 6
    except (RateLimited, Rejected, SunoError) as err:
        note(f"suno: {err}")
        return 1
    except KeyboardInterrupt:
        return 130


if __name__ == "__main__":
    sys.exit(main())
