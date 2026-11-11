"""Pure data shaping for the Suno CLI: request bodies, clip records, timed lyrics, names.

Nothing here touches the network or the disk, so all of it is covered by offline tests.

INVARIANTS:
- ``generate_payload`` returns exactly the key set the web client's Create form sent on
  2026-11-11, for each of its two modes (``KEYS`` and ``METADATA_KEYS``). The modes differ:
  Advanced ("custom") carries title, style and lyrics; Simple carries one description in
  ``gpt_description_prompt`` with ``task: agentic_thinking`` and has no title or style keys
  at all. ``suno doctor --drift`` compares both with a new capture. When Suno changes the
  form, change the builder and the constants together.
- ``token_provider`` is always present: the provider number with a token, null without one.
- Suno's limits count UTF-16 code units, as the web form does, so one emoji can count as two.
- ``title`` and ``tags`` are sent as empty strings when absent. A null title got HTTP 422.
- Sliders are 0 to 100 on the command line and 0.0 to 1.0 on the wire.
"""

from __future__ import annotations

import re
import unicodedata
import uuid
from typing import Any

Json = dict[str, Any]

SITE = "https://suno.com"
UUID_RE = re.compile(r"[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}", re.I)

# Friendly model names to the keys the API wants. `suno models` shows the account's live list.
MODEL_ALIASES = {"v6": "chirp-hawk", "v6-wild": "chirp-hawk-wild", "v6-mini": "chirp-goose"}
DEFAULT_LIMITS = {"title": 100, "prompt": 5000, "tags": 1000, "negative_tags": 1000,
                  "gpt_description_prompt": 3000}

_SHARED_KEYS = frozenset({
    "token", "token_provider", "generation_type", "mv", "prompt", "make_instrumental",
    "user_uploaded_images_b64", "metadata", "override_fields", "cover_clip_id", "cover_start_s",
    "cover_end_s", "persona_id", "artist_clip_id", "artist_start_s", "artist_end_s",
    "continue_clip_id", "continued_aligned_prompt", "continue_at", "transaction_uuid",
})
_SHARED_METADATA = frozenset({
    "web_client_pathname", "create_surface", "is_max_mode", "is_mumble", "create_mode",
    "user_tier", "create_session_token", "disable_volume_normalization",
})
KEYS = {
    "custom": _SHARED_KEYS | {"title", "tags", "negative_tags", "lyrics_project_id"},
    "simple": _SHARED_KEYS | {"task", "gpt_description_prompt"},
}
METADATA_KEYS = {
    "custom": _SHARED_METADATA | {"control_sliders"},
    "simple": _SHARED_METADATA | {"lyrics_model"},
}
MODES = tuple(KEYS)
# Fields that differ on every send and say nothing about what was asked for.
VOLATILE = ("token", "token_provider", "transaction_uuid")


class InputError(ValueError):
    """The request cannot be sent as written. Nothing was submitted."""


def utf16_len(text: str) -> int:
    return len(text.encode("utf-16-le")) // 2


def resolve_model(name: str, billing: Json | None = None) -> str:
    """A model flag (``v6``, ``v6-wild``, a raw ``chirp-*`` key) to the key the API wants."""
    wanted = name.strip().lower()
    models = (billing or {}).get("models") or []
    for m in models:
        if wanted in (str(m.get("name", "")).lower(), str(m.get("external_key", "")).lower()):
            if m.get("can_use") is False:
                raise InputError(f"the plan cannot use model {m.get('name')}; see `suno models`")
            return m["external_key"]
    if models:
        names = ", ".join(str(m.get("name")) for m in models)
        raise InputError(f"unknown model {name!r}; the account offers: {names}")
    return MODEL_ALIASES.get(wanted, name)


def default_model(billing: Json) -> str:
    models = [m for m in billing.get("models") or [] if m.get("can_use") is not False]
    for m in models:
        if m.get("is_default_model"):
            return m["external_key"]
    return models[0]["external_key"] if models else MODEL_ALIASES["v6"]


def limits_for(model_key: str, billing: Json | None) -> dict[str, int]:
    for m in (billing or {}).get("models") or []:
        if m.get("external_key") == model_key:
            return {**DEFAULT_LIMITS, **(m.get("max_lengths") or {})}
    return dict(DEFAULT_LIMITS)


def _slider(value: float | None, name: str) -> float | None:
    if value is None:
        return None
    if not 0 <= value <= 100:
        raise InputError(f"--{name} takes 0 to 100")
    return round(value / 100, 2)


def generate_payload(*, mode: str, model_key: str, title: str = "", tags: str = "",
                     exclude: str = "", text: str = "", instrumental: bool = False,
                     plan_id: str = "", weirdness: float | None = None,
                     style_influence: float | None = None,
                     max_mode: bool = False, persona_id: str | None = None,
                     request_id: str | None = None, limits: dict[str, int] | None = None) -> Json:
    """The body for ``POST /generate/v2-web/``.

    ``mode`` is ``custom`` (the form's Advanced tab: ``text`` is the lyrics, ``tags`` the
    style) or ``simple`` (the Simple tab: ``text`` is one description and Suno plans the
    song). The captcha token is added later, by the caller, right before the send.
    """
    if mode not in MODES:
        raise InputError(f"unknown mode {mode!r}")
    lim = {**DEFAULT_LIMITS, **(limits or {})}
    metadata: Json = {
        "web_client_pathname": "/create",
        "create_surface": "desktop_create_form",
        "is_max_mode": bool(max_mode),
        "is_mumble": False,
        "create_mode": mode,
        "user_tier": plan_id,
        "create_session_token": str(uuid.uuid4()),
        "disable_volume_normalization": False,
    }
    tail: Json = {
        "override_fields": [],
        "cover_clip_id": None,
        "cover_start_s": None,
        "cover_end_s": None,
        "persona_id": persona_id,
        "artist_clip_id": None,
        "artist_start_s": None,
        "artist_end_s": None,
        "continue_clip_id": None,
        "continued_aligned_prompt": None,
        "continue_at": None,
        "transaction_uuid": request_id or str(uuid.uuid4()),
        "token_provider": None,
    }
    if mode == "simple":
        if title or tags or exclude or instrumental or weirdness is not None or style_influence is not None:
            raise InputError("Simple mode takes one description; put the title, style and "
                             "'instrumental' into the description, or use `generate`")
        if not text.strip():
            raise InputError("a description is necessary")
        if utf16_len(text) > lim["gpt_description_prompt"]:
            raise InputError(f"the description is {utf16_len(text)} characters; the limit is "
                             f"{lim['gpt_description_prompt']}")
        metadata["lyrics_model"] = "default"
        return {
            "token": None,
            "task": "agentic_thinking",
            "generation_type": "TEXT",
            "mv": model_key,
            "prompt": "",
            "gpt_description_prompt": text,
            "make_instrumental": False,
            "user_uploaded_images_b64": None,
            "metadata": metadata,
            **tail,
        }
    for label, value, cap in (("title", title, lim["title"]), ("style", tags, lim["tags"]),
                              ("excluded styles", exclude, lim["negative_tags"]),
                              ("lyrics", text, lim["prompt"])):
        if utf16_len(value) > cap:
            raise InputError(f"the {label} text is {utf16_len(value)} characters; the limit is {cap}")
    if not (text.strip() or tags.strip()):
        raise InputError("give lyrics, a style, or both")
    if not text.strip() and not instrumental:
        raise InputError("no lyrics given: add lyrics, or pass --instrumental")
    sliders: Json = {"aug_creativity": 1}  # what the form sends with no slider touched
    for key, value in (("weirdness_constraint", _slider(weirdness, "weirdness")),
                       ("style_weight", _slider(style_influence, "style-influence"))):
        if value is not None:
            sliders[key] = value
    metadata["control_sliders"] = sliders
    return {
        "token": None,
        "generation_type": "TEXT",
        "title": title,
        "tags": tags,
        "negative_tags": exclude,
        "mv": model_key,
        "prompt": "" if instrumental else text,
        "make_instrumental": bool(instrumental),
        "user_uploaded_images_b64": None,
        "metadata": metadata,
        **tail,
        "lyrics_project_id": None,
    }


def with_token(payload: Json, token: str | None, provider: int | None) -> Json:
    """The payload as sent: token and provider number, or both null when no check is due."""
    out = dict(payload)
    out["token"] = token
    out["token_provider"] = provider if token else None
    return out


def fingerprint_source(payload: Json) -> Json:
    """What was asked for, without the fields that change on every send."""
    out = {k: v for k, v in payload.items() if k not in VOLATILE}
    out["metadata"] = {k: v for k, v in payload.get("metadata", {}).items() if k != "create_session_token"}
    return out


def shape_of(value: Any) -> Any:
    """The structure of a JSON value with every leaf replaced by its type name."""
    if isinstance(value, dict):
        return {k: shape_of(v) for k, v in sorted(value.items())}
    if isinstance(value, list):
        return [shape_of(value[0])] if value else []
    if value is None:
        return "null"
    return type(value).__name__


def key_diff(ours: Json, theirs: Json) -> Json:
    """Keys the live web client sends that this builder does not, and the reverse."""
    out: Json = {}
    for label, a, b in (("top", set(ours), set(theirs)),
                        ("metadata", set(ours.get("metadata") or {}), set(theirs.get("metadata") or {}))):
        if b - a:
            out[f"{label}_missing_here"] = sorted(b - a)
        if a - b:
            out[f"{label}_extra_here"] = sorted(a - b)
    return out


# -- clips -------------------------------------------------------------------------------------


def parse_clip_ref(ref: str) -> str:
    """A clip id out of a bare UUID or a suno.com song link. Short prefixes pass through."""
    ref = ref.strip()
    found = UUID_RE.search(ref)
    if found:
        return found.group(0).lower()
    if re.fullmatch(r"[0-9a-f]{6,35}", ref, re.I):
        return ref.lower()
    raise InputError(f"not a clip id or a suno.com/song link: {ref!r}")


def song_url(clip_id: str) -> str:
    return f"{SITE}/song/{clip_id}"


def normalize_clip(raw: Json) -> Json:
    meta = raw.get("metadata") or {}
    return {
        "id": raw.get("id"),
        "title": raw.get("title") or "",
        "status": raw.get("status"),
        "created_at": raw.get("created_at"),
        "duration": meta.get("duration"),
        "model": raw.get("model_name"),
        "version": raw.get("major_model_version"),
        "tags": meta.get("tags") or raw.get("display_tags") or "",
        "lyrics": meta.get("prompt") or "",
        "description": meta.get("gpt_description_prompt") or "",
        "task": meta.get("task") or meta.get("type"),
        "instrumental": bool(meta.get("make_instrumental")) or meta.get("has_vocal") is False,
        "max_mode": bool(meta.get("is_max_mode")),
        "cover_of": meta.get("cover_clip_id"),
        "public": bool(raw.get("is_public")),
        "trashed": bool(raw.get("is_trashed")),
        "unlocked": bool(raw.get("is_download_unlocked")),
        "error": meta.get("error_message") or meta.get("error_type"),
        "image": raw.get("image_large_url") or raw.get("image_url"),
        "url": song_url(str(raw.get("id"))),
    }


def fmt_duration(seconds: float | None) -> str:
    if not seconds:
        return "-"
    whole = int(round(seconds))
    return f"{whole // 60}:{whole % 60:02d}"


def slug(text: str, fallback: str = "song") -> str:
    ascii_text = unicodedata.normalize("NFKD", text).encode("ascii", "ignore").decode()
    out = re.sub(r"[^a-z0-9]+", "-", ascii_text.lower()).strip("-")
    return out[:60].strip("-") or fallback


def folder_name(clip: Json) -> str:
    return f"{slug(clip.get('title') or '')}-{str(clip.get('id'))[:8]}"


# -- timed lyrics ------------------------------------------------------------------------------


def _stamp(seconds: float) -> str:
    seconds = max(seconds, 0.0)
    return f"{int(seconds // 60):02d}:{seconds % 60:05.2f}"


def timed_lines(aligned: Json) -> list[Json]:
    """Sung lines with start and end times, from either shape the endpoint returns."""
    lines = []
    for row in aligned.get("aligned_lyrics") or []:
        text = str(row.get("text") or "").strip()
        if text and row.get("start_s") is not None:
            lines.append({"start": float(row["start_s"]), "end": float(row.get("end_s") or row["start_s"]),
                          "text": text, "section": row.get("section") or ""})
    if lines:
        return lines
    # Older clips carry words only. A word that starts with a newline starts a line.
    current: Json | None = None
    for word in aligned.get("aligned_words") or []:
        text = str(word.get("word") or "")
        if word.get("start_s") is None:
            continue
        starts_line = current is None or text.startswith("\n") or current["text"].endswith("\n")
        if starts_line:
            if current and current["text"].strip():
                lines.append(current)
            current = {"start": float(word["start_s"]), "end": float(word.get("end_s") or word["start_s"]),
                       "text": "", "section": ""}
        assert current is not None
        current["text"] += text
        current["end"] = float(word.get("end_s") or current["end"])
    if current and current["text"].strip():
        lines.append(current)
    for line in lines:
        line["text"] = re.sub(r"\[[^\]]*\]", "", line["text"]).strip()
    return [line for line in lines if line["text"]]


def timed_words(aligned: Json) -> list[Json]:
    words = []
    for word in aligned.get("aligned_words") or []:
        text = re.sub(r"\[[^\]]*\]", "", str(word.get("word") or "")).strip()
        if text and word.get("start_s") is not None:
            words.append({"start": float(word["start_s"]), "end": float(word.get("end_s") or word["start_s"]),
                          "text": text, "confidence": word.get("p_align")})
    return words


def to_lrc(aligned: Json, title: str = "") -> str:
    head = [f"[ti:{title}]"] if title else []
    return "\n".join(head + [f"[{_stamp(line['start'])}]{line['text']}" for line in timed_lines(aligned)]) + "\n"
