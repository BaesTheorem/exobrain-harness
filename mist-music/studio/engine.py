"""Generation engines for MIST Studio: one request shape, three backends.

  SpaceEngine -- ACE-Step 1.5 on a Hugging Face Space through gradio_client.
                 Free, but every GPU call reserves ~180 s of the caller's
                 ZeroGPU quota, so a free account gets a handful of songs a day.
  ApiEngine   -- the ACE-Step REST server (`uv run acestep-api`) on any box with
                 a GPU: a rented RunPod/Vast instance, or a friend's machine.
                 No quota. Contract from docs/en/API.md in the ACE-Step repo.
  MockEngine  -- no GPU. Returns a stand-in track after a short fake wait so the
                 whole app can be exercised when quota is gone.

INVARIANTS
  * GenRequest.from_dict() is the only way UI input becomes a request; it clamps
    every numeric field to the ranges the Space's sliders accept.
  * SpaceEngine never hardcodes vector positions. It builds the /generation_wrapper
    argument list from the Space's live defaults and writes by parameter name
    (PARAM_NAMES); a renamed or reordered slot surfaces in health() as `drift`.
  * A ZeroGPU quota rejection raises QuotaError with the reset delay parsed out.
"""
from __future__ import annotations

import contextlib
import io
import json
import os
import re
import shutil
import subprocess
import time
from dataclasses import asdict, dataclass, field, fields
from typing import Any, Callable

from .config import DOWNLOADS_DIR, HARNESS, TOOL_DIR

MODELS = ["acestep-v15-xl-turbo", "acestep-v15-turbo"]
TASKS = ["text2music", "cover", "repaint"]
LANGUAGES = [
    "unknown", "en", "es", "fr", "de", "it", "pt", "ja", "ko", "zh", "yue", "ru",
    "ar", "az", "bg", "bn", "ca", "cs", "da", "el", "fa", "fi", "he", "hi", "hr",
    "ht", "hu", "id", "is", "la", "lt", "ms", "ne", "nl", "no", "pa", "pl", "ro",
    "sa", "sk", "sr", "sv", "sw", "ta", "te", "th", "tl", "tr", "uk", "ur", "vi",
]
TIME_SIGNATURES = ["", "2", "3", "4"]
INSTRUMENTAL_TAG = "[Instrumental]"

# The DiT instruction the Space's UI swaps in per task (acestep/constants.py).
TASK_INSTRUCTIONS = {
    "text2music": "Fill the audio semantic mask based on the given conditions:",
    "repaint": "Repaint the mask area based on the given conditions:",
    "cover": "Generate audio semantic tokens based on the given conditions:",
}

# Logical field -> the Space's parameter name for /generation_wrapper.
# param_N is N-th input wired to the generate button in
# acestep/gradio_ui/events/__init__.py; param_40 is a hidden gr.State, so the
# numbering skips it. Verified against the live Space 2026-09-23.
PARAM_NAMES = {
    "model": "selected_model",
    "generation_mode": "generation_mode",
    "description": "simple_query_input",
    "simple_vocal_language": "simple_vocal_language",
    "caption": "param_4",
    "lyrics": "param_5",
    "bpm": "param_6",
    "key_scale": "param_7",
    "time_signature": "param_8",
    "vocal_language": "param_9",
    "steps": "param_10",
    "guidance_scale": "param_11",
    "random_seed": "param_12",
    "seed": "param_13",
    "reference_audio": "param_14",
    "duration": "param_15",
    "batch_size": "param_16",
    "src_audio": "param_17",
    "audio_codes": "param_18",
    "repaint_start": "param_19",
    "repaint_end": "param_20",
    "instruction": "param_21",
    "cover_strength": "param_22",
    "task": "param_23",
    "use_adg": "param_24",
    "cfg_interval_start": "param_25",
    "cfg_interval_end": "param_26",
    "shift": "param_27",
    "infer_method": "param_28",
    "custom_timesteps": "param_29",
    "audio_format": "param_30",
    "lm_temperature": "param_31",
    "thinking": "param_32",
    "lm_cfg_scale": "param_33",
    "lm_top_k": "param_34",
    "lm_top_p": "param_35",
    "lm_negative_prompt": "param_36",
    "use_cot_metas": "param_37",
    "use_cot_caption": "param_38",
    "use_cot_language": "param_39",
    "constrained_decoding_debug": "param_41",
    "allow_lm_batch": "param_42",
    "auto_score": "param_43",
    "auto_lrc": "param_44",
    "score_scale": "param_45",
    "lm_batch_chunk_size": "param_46",
    "track_name": "param_47",
    "complete_track_classes": "param_48",
    "autogen": "param_49",
}
# Labels the Space shows on a few of those slots. If one moves, drift is real.
EXPECTED_LABELS = {
    "param_10": "DiT Inference Steps",
    "param_16": "batch size",
    "param_17": "Source Audio",
    "param_30": "Audio Format",
    "param_43": "Get Scores",
    "param_44": "Get LRC",
}

ProgressFn = Callable[[dict], None]


class EngineError(Exception):
    """Generation failed for a reason the user should read."""


class QuotaError(EngineError):
    """ZeroGPU quota exhausted. retry_in is seconds until it refills."""

    def __init__(self, message: str, retry_in: int | None = None, requested: int | None = None,
                 left: int | None = None):
        super().__init__(message)
        self.retry_in = retry_in
        self.requested = requested
        self.left = left


_QUOTA_RE = re.compile(
    r"quota \((\d+)s requested vs\. (\d+)s left\)\. Try again in (\d+):(\d+):(\d+)", re.I)


def classify_error(exc: Exception) -> EngineError:
    """Turn a backend exception into something the UI can explain."""
    text = str(exc) or type(exc).__name__
    m = _QUOTA_RE.search(text)
    if m:
        req, left, h, mi, s = (int(x) for x in m.groups())
        return QuotaError(
            f"Free ZeroGPU quota is spent ({left}s left, this call needs {req}s). "
            f"It refills in {h}h {mi}m. Switch the backend to a self-hosted server, "
            "or wait.", retry_in=h * 3600 + mi * 60 + s, requested=req, left=left)
    if "exceeded your" in text.lower() and "quota" in text.lower():
        return QuotaError(text)
    if "GPU task aborted" in text:
        return EngineError("The Space aborted the GPU task (usually quota or a cold start). "
                           "Retry in a minute.")
    return EngineError(text)


def _clamp(v: float, lo: float, hi: float) -> float:
    return max(lo, min(hi, v))


def _num(v: Any, default: float) -> float:
    try:
        if v is None or v == "":
            return default
        return float(v)
    except (TypeError, ValueError):
        return default


def _bool(v: Any, default: bool) -> bool:
    if isinstance(v, bool):
        return v
    if v is None:
        return default
    if isinstance(v, str):
        return v.strip().lower() in ("1", "true", "yes", "on")
    return bool(v)


@dataclass
class GenRequest:
    """Everything a generation needs. Field names are the app's vocabulary;
    engines translate. Ranges follow the Space's sliders."""
    task: str = "text2music"                 # text2music | cover | repaint
    generation_mode: str = "custom"          # custom | simple
    description: str = ""                    # simple mode: one-sentence brief
    title: str = ""
    caption: str = ""                        # style tags
    lyrics: str = ""
    instrumental: bool = False
    vocal_language: str = "unknown"
    bpm: float = 0                           # 0 = let the model pick
    key_scale: str = ""
    time_signature: str = ""
    duration: float = -1                     # seconds, -1 = auto
    batch_size: int = 1
    model: str = MODELS[0]
    # audio inputs (absolute local paths)
    src_audio: str | None = None             # cover / repaint source
    reference_audio: str | None = None       # style reference
    audio_codes: str = ""
    cover_strength: float = 1.0
    repaint_start: float = 0.0
    repaint_end: float = -1
    # DiT
    steps: int = 8
    guidance_scale: float = 7.0
    seed: int | None = None                  # None = random
    shift: float = 3.0
    infer_method: str = "ode"
    custom_timesteps: str = ""
    audio_format: str = "mp3"
    use_adg: bool = False
    cfg_interval_start: float = 0.0
    cfg_interval_end: float = 1.0
    # 5Hz LM
    thinking: bool = True
    lm_temperature: float = 0.85
    lm_cfg_scale: float = 2.0
    lm_top_k: int = 0
    lm_top_p: float = 0.9
    lm_negative_prompt: str = "NO USER INPUT"
    use_cot_metas: bool = True
    use_cot_caption: bool = True
    use_cot_language: bool = True
    # extras
    auto_score: bool = False
    auto_lrc: bool = False
    score_scale: float = 0.5
    lm_batch_chunk_size: int = 8
    extra: dict = field(default_factory=dict)   # anything the UI wants to remember

    @classmethod
    def from_dict(cls, d: dict) -> "GenRequest":
        d = dict(d or {})
        r = cls()
        task = str(d.get("task") or "")
        r.task = task if task in TASKS else "text2music"
        r.generation_mode = "simple" if d.get("generation_mode") == "simple" else "custom"
        r.description = str(d.get("description") or "").strip()
        r.title = str(d.get("title") or "").strip()[:120]
        r.caption = str(d.get("caption") or "").strip()
        r.lyrics = str(d.get("lyrics") or "").strip()
        r.instrumental = _bool(d.get("instrumental"), False)
        lang = str(d.get("vocal_language") or "unknown")
        r.vocal_language = lang if lang in LANGUAGES else "unknown"
        r.bpm = _clamp(_num(d.get("bpm"), 0), 0, 300)
        if 0 < r.bpm < 30:
            r.bpm = 30
        r.key_scale = str(d.get("key_scale") or "").strip()[:32]
        ts = str(d.get("time_signature") or "")
        r.time_signature = ts if ts in TIME_SIGNATURES else ""
        dur = _num(d.get("duration"), -1)
        r.duration = -1 if dur <= 0 else _clamp(dur, 10, 600)
        r.batch_size = int(_clamp(_num(d.get("batch_size"), 1), 1, 8))
        model = str(d.get("model") or "")
        r.model = model if model in MODELS else MODELS[0]
        r.src_audio = d.get("src_audio") or None
        r.reference_audio = d.get("reference_audio") or None
        r.audio_codes = str(d.get("audio_codes") or "")
        r.cover_strength = _clamp(_num(d.get("cover_strength"), 1.0), 0, 1)
        r.repaint_start = max(0.0, _num(d.get("repaint_start"), 0.0))
        rend = _num(d.get("repaint_end"), -1)
        r.repaint_end = -1 if rend <= 0 else rend
        r.steps = int(_clamp(_num(d.get("steps"), 8), 1, 20))
        r.guidance_scale = _clamp(_num(d.get("guidance_scale"), 7.0), 1, 20)
        seed = d.get("seed")
        r.seed = None if seed in (None, "", -1, "-1") else int(_num(seed, -1))
        if r.seed is not None and r.seed < 0:
            r.seed = None
        r.shift = _clamp(_num(d.get("shift"), 3.0), 1, 5)
        r.infer_method = "sde" if d.get("infer_method") == "sde" else "ode"
        r.custom_timesteps = str(d.get("custom_timesteps") or "").strip()
        r.audio_format = "flac" if d.get("audio_format") == "flac" else "mp3"
        r.use_adg = _bool(d.get("use_adg"), False)
        r.cfg_interval_start = _clamp(_num(d.get("cfg_interval_start"), 0.0), 0, 1)
        r.cfg_interval_end = _clamp(_num(d.get("cfg_interval_end"), 1.0), 0, 1)
        r.thinking = _bool(d.get("thinking"), True)
        r.lm_temperature = _clamp(_num(d.get("lm_temperature"), 0.85), 0, 2)
        r.lm_cfg_scale = _clamp(_num(d.get("lm_cfg_scale"), 2.0), 1, 3)
        r.lm_top_k = int(_clamp(_num(d.get("lm_top_k"), 0), 0, 100))
        r.lm_top_p = _clamp(_num(d.get("lm_top_p"), 0.9), 0, 1)
        r.lm_negative_prompt = str(d.get("lm_negative_prompt") or "NO USER INPUT")
        r.use_cot_metas = _bool(d.get("use_cot_metas"), True)
        r.use_cot_caption = _bool(d.get("use_cot_caption"), True)
        r.use_cot_language = _bool(d.get("use_cot_language"), True)
        r.auto_score = _bool(d.get("auto_score"), False)
        r.auto_lrc = _bool(d.get("auto_lrc"), False)
        r.score_scale = _clamp(_num(d.get("score_scale"), 0.5), 0, 1)
        r.lm_batch_chunk_size = int(_clamp(_num(d.get("lm_batch_chunk_size"), 8), 1, 8))
        extra = d.get("extra")
        r.extra = extra if isinstance(extra, dict) else {}
        if r.instrumental:
            r.vocal_language = "unknown"
        return r

    def effective_lyrics(self) -> str:
        if self.instrumental or not self.lyrics.strip():
            return INSTRUMENTAL_TAG
        return self.lyrics

    def validate(self) -> None:
        if self.task in ("cover", "repaint") and not self.src_audio:
            raise EngineError(f"{self.task} needs a source track.")
        if self.src_audio and not os.path.isfile(self.src_audio):
            raise EngineError("The source track file is missing.")
        if self.reference_audio and not os.path.isfile(self.reference_audio):
            raise EngineError("The reference track file is missing.")
        if self.generation_mode == "simple":
            if not self.description:
                raise EngineError("Describe the song first.")
        elif not self.caption and self.effective_lyrics() == INSTRUMENTAL_TAG:
            raise EngineError("Give some style tags, or lyrics, or both.")

    def to_dict(self) -> dict:
        return asdict(self)


@dataclass
class GenResult:
    audio_paths: list[str]
    seeds: list[str] = field(default_factory=list)
    details: str = ""
    status: str = ""
    scores: list[str] = field(default_factory=list)
    lrcs: list[str] = field(default_factory=list)
    codes: list[str] = field(default_factory=list)
    metas: dict = field(default_factory=dict)
    engine: str = ""


class Engine:
    name = "base"

    def generate(self, req: GenRequest, progress: ProgressFn) -> GenResult:
        raise NotImplementedError

    def describe(self, description: str, instrumental: bool, language: str,
                 temperature: float = 0.85, top_k: int = 0, top_p: float = 0.9) -> dict:
        """One-sentence brief -> caption, lyrics, bpm, key, duration, language."""
        raise NotImplementedError

    def enhance(self, caption: str, lyrics: str, bpm: float = 0, duration: float = -1,
                key_scale: str = "", time_signature: str = "", temperature: float = 0.85,
                top_k: int = 0, top_p: float = 0.9) -> dict:
        raise NotImplementedError

    def analyze(self, audio_path: str) -> dict:
        """Uploaded track -> caption, lyrics, bpm, key, duration, language, codes."""
        raise NotImplementedError

    def random_description(self) -> dict:
        raise NotImplementedError

    def cancel(self) -> None:
        pass

    def health(self) -> dict:
        return {"engine": self.name, "ok": True}


# ---------------------------------------------------------------------------
# Hugging Face Space
# ---------------------------------------------------------------------------

def _audio_path(item: Any) -> str | None:
    if isinstance(item, dict):
        item = item.get("path") or item.get("value") or item.get("name")
    if isinstance(item, str) and os.path.isfile(item):
        return item
    return None


class SpaceEngine(Engine):
    name = "space"

    def __init__(self, space_id: str, token: str | None):
        self.space_id = space_id
        self.token = token
        self._client = None
        self._api: dict | None = None
        self._job = None
        self.drift: list[str] = []

    # -- plumbing ---------------------------------------------------------
    def client(self):
        if self._client is None:
            from gradio_client import Client
            os.makedirs(DOWNLOADS_DIR, exist_ok=True)
            try:
                self._client = Client(self.space_id, verbose=False, token=self.token,
                                      download_files=DOWNLOADS_DIR)
            except Exception as e:  # noqa: BLE001 - any transport failure reads the same
                raise EngineError(f"Couldn't reach the Space {self.space_id}: {e}") from e
        return self._client

    def api(self) -> dict:
        api = self._api
        if api is None:
            with contextlib.redirect_stdout(io.StringIO()):
                api = self.client().view_api(return_format="dict")
            if not isinstance(api, dict) or "/generation_wrapper" not in api.get("named_endpoints", {}):
                raise EngineError(f"{self.space_id} doesn't expose /generation_wrapper; is it an "
                                  "ACE-Step 1.5 Space?")
            params = api["named_endpoints"]["/generation_wrapper"]["parameters"]
            labels = {p.get("parameter_name"): p.get("label") for p in params}
            self.drift = [f"{k}: expected {v!r}, Space has {labels.get(k)!r}"
                          for k, v in EXPECTED_LABELS.items() if labels.get(k) != v]
            names = {p.get("parameter_name") for p in params}
            self.drift += [f"{k} -> {v} missing" for k, v in PARAM_NAMES.items() if v not in names]
            self._api = api
        return api

    def _vector(self, req: GenRequest) -> list:
        def handle_file(path: str):
            from gradio_client import handle_file as hf
            return hf(path)

        params = self.api()["named_endpoints"]["/generation_wrapper"]["parameters"]
        vec = [p.get("parameter_default") for p in params]
        idx = {p.get("parameter_name"): i for i, p in enumerate(params)}

        def put(field_name: str, value: Any) -> None:
            pname = PARAM_NAMES[field_name]
            if pname in idx:
                vec[idx[pname]] = value

        simple = req.generation_mode == "simple"
        put("model", req.model)
        put("generation_mode", "simple" if simple else req.task if req.task != "text2music" else "custom")
        put("description", req.description or req.caption)
        put("simple_vocal_language", req.vocal_language)
        put("caption", req.caption)
        put("lyrics", req.effective_lyrics())
        put("bpm", float(req.bpm or 0))
        put("key_scale", req.key_scale)
        put("time_signature", req.time_signature)
        put("vocal_language", req.vocal_language)
        put("steps", int(req.steps))
        put("guidance_scale", float(req.guidance_scale))
        put("random_seed", req.seed is None)
        put("seed", "-1" if req.seed is None else str(req.seed))
        put("reference_audio", handle_file(req.reference_audio) if req.reference_audio else None)
        put("duration", -1.0 if req.task in ("cover", "repaint") else float(req.duration))
        put("batch_size", int(req.batch_size))
        put("src_audio", handle_file(req.src_audio) if req.src_audio else None)
        put("audio_codes", req.audio_codes or "")
        put("repaint_start", float(req.repaint_start))
        put("repaint_end", float(req.repaint_end))
        put("instruction", TASK_INSTRUCTIONS[req.task])
        put("cover_strength", float(req.cover_strength))
        put("task", req.task)
        put("use_adg", bool(req.use_adg))
        put("cfg_interval_start", float(req.cfg_interval_start))
        put("cfg_interval_end", float(req.cfg_interval_end))
        put("shift", float(req.shift))
        put("infer_method", req.infer_method)
        put("custom_timesteps", req.custom_timesteps)
        put("audio_format", req.audio_format)
        put("lm_temperature", float(req.lm_temperature))
        put("thinking", bool(req.thinking))
        put("lm_cfg_scale", float(req.lm_cfg_scale))
        put("lm_top_k", float(req.lm_top_k))
        put("lm_top_p", float(req.lm_top_p))
        put("lm_negative_prompt", req.lm_negative_prompt)
        put("use_cot_metas", bool(req.use_cot_metas))
        put("use_cot_caption", bool(req.use_cot_caption))
        put("use_cot_language", bool(req.use_cot_language))
        put("constrained_decoding_debug", False)
        put("allow_lm_batch", True)
        put("auto_score", bool(req.auto_score))
        put("auto_lrc", bool(req.auto_lrc))
        put("score_scale", float(req.score_scale))
        put("lm_batch_chunk_size", float(req.lm_batch_chunk_size))
        put("track_name", "strings")          # a valid literal is required even when unused
        put("complete_track_classes", [])
        put("autogen", False)
        return vec

    # -- operations -------------------------------------------------------
    def generate(self, req: GenRequest, progress: ProgressFn) -> GenResult:
        req.validate()
        vec = self._vector(req)
        try:
            job = self.client().submit(*vec, api_name="/generation_wrapper")
        except Exception as e:  # noqa: BLE001
            raise classify_error(e) from e
        self._job = job
        t0 = time.time()
        try:
            while not job.done():
                st = job.status()
                code = getattr(st.code, "name", str(st.code))
                progress({
                    "stage": "queued" if code in ("IN_QUEUE", "JOINING_QUEUE", "STARTING") else "running",
                    "detail": code.lower().replace("_", " "),
                    "rank": st.rank, "queue_size": st.queue_size, "eta": st.eta,
                    "elapsed": round(time.time() - t0, 1),
                })
                time.sleep(1.0)
            out = job.result()
        except Exception as e:  # noqa: BLE001
            raise classify_error(e) from e
        finally:
            self._job = None
        if not isinstance(out, (list, tuple)) or len(out) < 12:
            raise EngineError(f"Unexpected reply from the Space: {str(out)[:200]}")
        paths = [p for p in (_audio_path(x) for x in out[:8]) if p]
        if not paths:
            raise EngineError(f"The Space returned no audio. Status: {out[10]}")
        n = len(paths)
        seeds = [s.strip() for s in str(out[11] or "").split(",") if s.strip()]
        return GenResult(
            audio_paths=paths, seeds=seeds, details=str(out[9] or ""), status=str(out[10] or ""),
            scores=[str(x or "") for x in out[12:12 + n]] if len(out) > 19 else [],
            codes=[str(x or "") for x in out[20:20 + n]] if len(out) > 27 else [],
            lrcs=[str(x or "") for x in out[28:28 + n]] if len(out) > 35 else [],
            engine=f"space:{self.space_id}",
        )

    def cancel(self) -> None:
        job = self._job
        if job is not None:
            with contextlib.suppress(Exception):
                job.cancel()

    def describe(self, description, instrumental, language, temperature=0.85, top_k=0, top_p=0.9):
        try:
            r = self.client().predict(description, bool(instrumental), language or "unknown",
                                      float(temperature), float(top_k), float(top_p), False,
                                      api_name="/handle_create_sample_wrapper")
        except Exception as e:  # noqa: BLE001
            raise classify_error(e) from e
        return {
            "caption": r[0] or "", "lyrics": r[1] or "", "bpm": r[2] or 0, "duration": r[3] or -1,
            "key_scale": r[4] or "", "vocal_language": r[5] or "unknown",
            "time_signature": r[7] or "", "instrumental": bool(r[8]), "status": r[10] or "",
        }

    def enhance(self, caption, lyrics, bpm=0, duration=-1, key_scale="", time_signature="",
                temperature=0.85, top_k=0, top_p=0.9):
        try:
            r = self.client().predict(caption, lyrics, float(bpm or 0), float(duration or -1),
                                      key_scale or "", time_signature or "", float(temperature),
                                      float(top_k), float(top_p), False,
                                      api_name="/handle_format_sample_wrapper")
        except Exception as e:  # noqa: BLE001
            raise classify_error(e) from e
        return {
            "caption": r[0] or "", "lyrics": r[1] or "", "bpm": r[2] or 0, "duration": r[3] or -1,
            "key_scale": r[4] or "", "vocal_language": r[5] or "unknown",
            "time_signature": r[6] or "", "status": r[7] or "",
        }

    def analyze(self, audio_path):
        from gradio_client import handle_file
        try:
            r = self.client().predict(handle_file(audio_path), False,
                                      api_name="/process_source_audio_wrapper")
        except Exception as e:  # noqa: BLE001
            raise classify_error(e) from e
        return {
            "codes": r[0] or "", "status": r[1] or "", "caption": r[2] or "", "lyrics": r[3] or "",
            "bpm": r[4] or 0, "duration": r[5] or -1, "key_scale": r[6] or "",
            "vocal_language": r[7] or "unknown", "time_signature": r[8] or "",
        }

    def random_description(self):
        try:
            r = self.client().predict(api_name="/load_random_simple_description")
        except Exception as e:  # noqa: BLE001
            raise classify_error(e) from e
        return {"description": r[0] or "", "instrumental": bool(r[1]), "vocal_language": r[2] or "unknown"}

    def health(self):
        info: dict[str, Any] = {"engine": self.name, "space": self.space_id, "token": bool(self.token)}
        try:
            self.api()
            info.update(ok=True, drift=self.drift)
        except Exception as e:  # noqa: BLE001
            info.update(ok=False, error=str(e)[:300])
        return info


# ---------------------------------------------------------------------------
# Self-hosted REST server (acestep-api)
# ---------------------------------------------------------------------------

class ApiEngine(Engine):
    name = "api"

    def __init__(self, base_url: str):
        self.base = base_url.rstrip("/")
        self._cancel = False

    def _request(self, method: str, path: str, *, json_body=None, data=None, files=None, timeout=60):
        import urllib.error
        import urllib.request
        url = self.base + path
        if files or data:
            body, ctype = _multipart(data or {}, files or {})
            req = urllib.request.Request(url, data=body, method=method)
            req.add_header("Content-Type", ctype)
        elif json_body is not None:
            req = urllib.request.Request(url, data=json.dumps(json_body).encode(), method=method)
            req.add_header("Content-Type", "application/json")
        else:
            req = urllib.request.Request(url, method=method)
        try:
            with urllib.request.urlopen(req, timeout=timeout) as resp:
                raw = resp.read()
        except urllib.error.HTTPError as e:
            raise EngineError(f"{method} {path} -> HTTP {e.code}: {e.read()[:300]!r}") from e
        except (urllib.error.URLError, OSError) as e:
            raise EngineError(f"Can't reach the ACE-Step server at {self.base}: {e}") from e
        return json.loads(raw) if raw else {}

    def _fields(self, req: GenRequest) -> dict:
        f: dict[str, Any] = {
            "caption": req.caption, "lyrics": req.effective_lyrics(), "thinking": req.thinking,
            "vocal_language": req.vocal_language, "audio_format": req.audio_format,
            "inference_steps": req.steps, "guidance_scale": req.guidance_scale,
            "use_random_seed": req.seed is None, "seed": -1 if req.seed is None else req.seed,
            "batch_size": req.batch_size, "shift": req.shift, "infer_method": req.infer_method,
            "use_adg": req.use_adg, "cfg_interval_start": req.cfg_interval_start,
            "cfg_interval_end": req.cfg_interval_end, "lm_temperature": req.lm_temperature,
            "lm_cfg_scale": req.lm_cfg_scale, "lm_negative_prompt": req.lm_negative_prompt,
            "lm_top_p": req.lm_top_p, "use_cot_caption": req.use_cot_caption,
            "use_cot_language": req.use_cot_language, "task_type": req.task,
            "repainting_start": req.repaint_start, "repainting_end": req.repaint_end,
            "audio_cover_strength": req.cover_strength, "model": req.model,
        }
        if req.lm_top_k:
            f["lm_top_k"] = req.lm_top_k
        if req.custom_timesteps:
            f["timesteps"] = req.custom_timesteps
        if req.bpm:
            f["bpm"] = int(req.bpm)
        if req.key_scale:
            f["key_scale"] = req.key_scale
        if req.time_signature:
            f["time_signature"] = req.time_signature
        if req.duration > 0 and req.task == "text2music":
            f["audio_duration"] = req.duration
        if req.audio_codes:
            f["audio_code_string"] = req.audio_codes
        if req.generation_mode == "simple":
            f.update(sample_mode=True, sample_query=req.description)
        return f

    def generate(self, req: GenRequest, progress: ProgressFn) -> GenResult:
        req.validate()
        self._cancel = False
        fields_ = self._fields(req)
        files = {}
        if req.src_audio:
            files["src_audio"] = req.src_audio
        if req.reference_audio:
            files["reference_audio"] = req.reference_audio
        if files:
            form = {k: (json.dumps(v) if isinstance(v, bool) else str(v)) for k, v in fields_.items()}
            job = self._request("POST", "/v1/music/generate", data=form, files=files, timeout=120)
        else:
            job = self._request("POST", "/v1/music/generate", json_body=fields_, timeout=120)
        job_id = job.get("job_id")
        if not job_id:
            raise EngineError(f"Server didn't return a job id: {job}")
        t0 = time.time()
        while True:
            if self._cancel:
                raise EngineError("Cancelled.")
            st = self._request("GET", f"/v1/jobs/{job_id}")
            status = st.get("status")
            progress({
                "stage": "queued" if status == "queued" else "running", "detail": status,
                "rank": st.get("queue_position"), "eta": st.get("eta_seconds"),
                "elapsed": round(time.time() - t0, 1),
            })
            if status == "succeeded":
                break
            if status in ("failed", "cancelled"):
                raise EngineError(f"Server job {status}: {st.get('error') or st}")
            time.sleep(2.0)
        result = st.get("result") or {}
        paths = []
        os.makedirs(DOWNLOADS_DIR, exist_ok=True)
        import urllib.request
        for i, rel in enumerate(result.get("audio_paths") or []):
            url = rel if rel.startswith("http") else self.base + rel
            ext = ".flac" if req.audio_format == "flac" else ".mp3"
            dst = os.path.join(DOWNLOADS_DIR, f"api-{job_id}-{i}{ext}")
            try:
                with urllib.request.urlopen(url, timeout=120) as r, open(dst, "wb") as f:
                    shutil.copyfileobj(r, f)
            except OSError as e:
                raise EngineError(f"Couldn't download {url}: {e}") from e
            paths.append(dst)
        if not paths:
            raise EngineError(f"Server returned no audio: {result.get('status_message')}")
        seeds = [s.strip() for s in str(result.get("seed_value") or "").split(",") if s.strip()]
        metas = result.get("metas") or {}
        for k in ("bpm", "duration", "keyscale", "timesignature"):
            if result.get(k) is not None:
                metas.setdefault(k, result.get(k))
        return GenResult(audio_paths=paths, seeds=seeds, details=str(result.get("generation_info") or ""),
                         status=str(result.get("status_message") or ""), metas=metas,
                         engine=f"api:{self.base}")

    def cancel(self):
        self._cancel = True

    def health(self):
        try:
            models = self._request("GET", "/v1/models", timeout=10)
            return {"engine": self.name, "ok": True, "url": self.base, "models": models}
        except EngineError as e:
            return {"engine": self.name, "ok": False, "url": self.base, "error": str(e)[:300]}


def _multipart(fields_: dict, files: dict) -> tuple[bytes, str]:
    """Minimal multipart/form-data encoder (stdlib only)."""
    import mimetypes
    import uuid
    boundary = "----mist-studio-" + uuid.uuid4().hex
    out = io.BytesIO()
    for k, v in fields_.items():
        out.write(f"--{boundary}\r\nContent-Disposition: form-data; name=\"{k}\"\r\n\r\n{v}\r\n".encode())
    for k, path in files.items():
        name = os.path.basename(path)
        ctype = mimetypes.guess_type(name)[0] or "application/octet-stream"
        out.write(f"--{boundary}\r\nContent-Disposition: form-data; name=\"{k}\"; "
                  f"filename=\"{name}\"\r\nContent-Type: {ctype}\r\n\r\n".encode())
        with open(path, "rb") as f:
            out.write(f.read())
        out.write(b"\r\n")
    out.write(f"--{boundary}--\r\n".encode())
    return out.getvalue(), f"multipart/form-data; boundary={boundary}"


# ---------------------------------------------------------------------------
# Mock (no GPU)
# ---------------------------------------------------------------------------

class MockEngine(Engine):
    """Stands in for a GPU. Waits a few seconds with progress ticks, then hands
    back a real audio file: a track already under tmp/audio if there is one,
    else a synthesized two-tone so the player has something to play."""
    name = "mock"

    def __init__(self, delay: float = 4.0):
        self.delay = delay
        self._cancel = False

    def _fixture(self, duration: float) -> str:
        os.makedirs(DOWNLOADS_DIR, exist_ok=True)
        pool = []
        for d in (os.path.join(HARNESS, "tmp", "audio"), os.path.join(TOOL_DIR, "out")):
            if os.path.isdir(d):
                pool += [os.path.join(d, f) for f in os.listdir(d) if f.lower().endswith(".mp3")]
        if pool:
            src = pool[int(time.time()) % len(pool)]
            dst = os.path.join(DOWNLOADS_DIR, f"mock-{int(time.time() * 1000)}.mp3")
            shutil.copy2(src, dst)
            return dst
        dst = os.path.join(DOWNLOADS_DIR, f"mock-{int(time.time() * 1000)}.mp3")
        secs = 12 if duration <= 0 else min(duration, 30)
        subprocess.run([which("ffmpeg"), "-y", "-v", "error", "-f", "lavfi",
                        "-i", f"sine=frequency=220:duration={secs}", "-f", "lavfi",
                        "-i", f"sine=frequency=330:duration={secs}", "-filter_complex",
                        "amix=inputs=2,afade=t=in:d=1,afade=t=out:st={0}:d=1".format(max(0, secs - 1)),
                        "-c:a", "libmp3lame", "-q:a", "4", dst], check=True)
        return dst

    def generate(self, req: GenRequest, progress: ProgressFn) -> GenResult:
        req.validate()
        self._cancel = False
        t0 = time.time()
        steps = max(1, int(self.delay * 4))
        for i in range(steps):
            if self._cancel:
                raise EngineError("Cancelled.")
            progress({"stage": "queued" if i < 2 else "running", "detail": "mock",
                      "rank": max(0, 2 - i), "eta": round(self.delay - i / 4, 1),
                      "elapsed": round(time.time() - t0, 1)})
            time.sleep(0.25)
        paths = [self._fixture(req.duration) for _ in range(req.batch_size)]
        seeds = [str(req.seed if req.seed is not None else 1000 + i) for i in range(len(paths))]
        return GenResult(audio_paths=paths, seeds=seeds, details="mock engine: stand-in audio",
                         status="ok (mock)", metas={"bpm": req.bpm or 96, "keyscale": req.key_scale or "C Major"},
                         engine="mock")

    def cancel(self):
        self._cancel = True

    def describe(self, description, instrumental, language, temperature=0.85, top_k=0, top_p=0.9):
        time.sleep(0.5)
        lyrics = "" if instrumental else (
            "[Verse 1]\nThe kettle hums a minor key\nA window full of rain\n"
            "[Chorus]\nSing it back to me\nSing it back again\n")
        return {"caption": f"indie pop, {description[:60]}, warm vocals, 100 BPM", "lyrics": lyrics,
                "bpm": 100, "duration": 120, "key_scale": "G Major",
                "vocal_language": "unknown" if instrumental else (language or "en"),
                "time_signature": "4", "instrumental": bool(instrumental), "status": "ok (mock)"}

    def enhance(self, caption, lyrics, bpm=0, duration=-1, key_scale="", time_signature="",
                temperature=0.85, top_k=0, top_p=0.9):
        time.sleep(0.5)
        return {"caption": (caption + ", polished production, wide stereo").strip(", "), "lyrics": lyrics,
                "bpm": bpm or 100, "duration": duration, "key_scale": key_scale or "C Major",
                "vocal_language": "unknown", "time_signature": time_signature or "4", "status": "ok (mock)"}

    def analyze(self, audio_path):
        time.sleep(0.5)
        return {"codes": "", "status": "ok (mock)", "caption": "acoustic folk, guitar, soft vocals",
                "lyrics": "[Verse]\n(lyrics not transcribed by the mock engine)", "bpm": 92,
                "duration": probe_duration(audio_path) or -1, "key_scale": "D Major",
                "vocal_language": "en", "time_signature": "4"}

    def random_description(self):
        pool = [("a sun-drenched surf rock song about a cat stealing sandwiches", False, "en"),
                ("slow cinematic piano piece for a rainy morning", True, "unknown"),
                ("upbeat synthwave with soaring chorus vocals", False, "en"),
                ("romantic Spanish guitar ballad with heartfelt lyrics", False, "es")]
        d = pool[int(time.time()) % len(pool)]
        return {"description": d[0], "instrumental": d[1], "vocal_language": d[2]}

    def health(self):
        return {"engine": self.name, "ok": True, "note": "mock engine: no GPU, stand-in audio"}


def which(name: str) -> str:
    """A binary by name, falling back to the Homebrew dirs launchd's PATH omits."""
    found = shutil.which(name)
    if found:
        return found
    for d in ("/opt/homebrew/bin", "/usr/local/bin", os.path.expanduser("~/.local/bin")):
        p = os.path.join(d, name)
        if os.access(p, os.X_OK):
            return p
    return name


def probe_duration(path: str) -> float | None:
    """Seconds of audio, via ffprobe. None if it can't be read."""
    try:
        out = subprocess.run([which("ffprobe"), "-v", "error", "-show_entries", "format=duration",
                              "-of", "csv=p=0", path], capture_output=True, text=True, check=True,
                             timeout=30).stdout.strip()
        return round(float(out), 2)
    except (subprocess.SubprocessError, ValueError, OSError):
        return None


def build_engine(cfg: dict, token: str | None) -> Engine:
    backend = cfg.get("backend", "space")
    if backend == "api":
        return ApiEngine(cfg.get("api_url") or "http://127.0.0.1:8001")
    if backend == "mock":
        return MockEngine()
    return SpaceEngine(cfg.get("space_id") or "ACE-Step/Ace-Step-v1.5",
                       token if cfg.get("use_token", True) else None)


REQUEST_FIELDS = [f.name for f in fields(GenRequest)]
