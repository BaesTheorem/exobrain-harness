"""Settings for MIST Studio.

Two layers: DEFAULTS below, overridden by studio/config.json (gitignored,
per machine). Secrets never live here; HF_TOKEN comes from the harness .env
through load_env(), same as the mist-music CLI.
"""
import json
import os
import threading

HERE = os.path.dirname(os.path.abspath(__file__))
TOOL_DIR = os.path.dirname(HERE)            # mist-music/
HARNESS = os.path.dirname(TOOL_DIR)         # the harness root
ENV_FILE = os.path.join(HARNESS, ".env")
CONFIG_FILE = os.path.join(HERE, "config.json")

LIBRARY_DIR = os.path.join(HERE, "library")
UPLOADS_DIR = os.path.join(HERE, "uploads")
DOWNLOADS_DIR = os.path.join(HERE, "downloads")   # gradio_client scratch

PORT = int(os.environ.get("MIST_STUDIO_PORT", "5032"))

DEFAULTS = {
    # Which engine answers generate/describe/analyze.
    #   space -- a Hugging Face Space running ACE-Step 1.5 (free, ZeroGPU quota)
    #   api   -- a self-hosted ACE-Step REST server (rented GPU, no quota)
    #   mock  -- no GPU at all; returns a stand-in track so the UI can be driven
    "backend": "space",
    "space_id": "ACE-Step/Ace-Step-v1.5",
    "use_token": True,                 # send HF_TOKEN (bigger ZeroGPU pool)
    "api_url": "http://127.0.0.1:8001",
    "default_model": "acestep-v15-xl-turbo",
    "default_batch": 1,                # takes per generation (1..8)
    "auto_art": True,                  # cover art via mist-image after each song
    "art_size": 768,
    "stems_engine": "local",           # local (demucs) | cloud (HF Space)
    "lyric_writer": "claude",          # claude | space
    "claude_model": "claude-sonnet-5",
    "sfx": True,
    "theme_seed": "#00A6B8",
    "theme_mode": "dark",
}

_lock = threading.Lock()


def load_env():
    """Pull KEY=VALUE lines from the harness .env into os.environ (real env wins)."""
    try:
        with open(ENV_FILE) as f:
            for line in f:
                line = line.strip()
                if not line or line.startswith("#") or "=" not in line:
                    continue
                if line.startswith("export "):
                    line = line[len("export "):]
                k, _, v = line.partition("=")
                os.environ.setdefault(k.strip(), v.strip().strip('"').strip("'"))
    except FileNotFoundError:
        pass


def load() -> dict:
    cfg = dict(DEFAULTS)
    try:
        with open(CONFIG_FILE) as f:
            saved = json.load(f)
        if isinstance(saved, dict):
            cfg.update({k: v for k, v in saved.items() if k in DEFAULTS})
    except (FileNotFoundError, json.JSONDecodeError):
        pass
    return cfg


def save(patch: dict) -> dict:
    """Merge a patch into config.json; unknown keys are dropped."""
    with _lock:
        cfg = load()
        cfg.update({k: v for k, v in patch.items() if k in DEFAULTS})
        tmp = CONFIG_FILE + ".tmp"
        with open(tmp, "w") as f:
            json.dump(cfg, f, indent=2)
        os.replace(tmp, CONFIG_FILE)
    return cfg


def hf_token() -> str | None:
    load_env()
    return os.environ.get("HF_TOKEN") or os.environ.get("HUGGINGFACE_TOKEN")


def ensure_dirs():
    for d in (LIBRARY_DIR, UPLOADS_DIR, DOWNLOADS_DIR):
        os.makedirs(d, exist_ok=True)
