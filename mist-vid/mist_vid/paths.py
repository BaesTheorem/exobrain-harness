"""Where mist-vid finds its downloaded assets. Project paths are relative to the
project directory (the folder holding the edit YAML); the CLI chdirs there first."""
from __future__ import annotations

import os

TOOL = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
ASSETS = os.environ.get("MIST_VID_ASSETS", os.path.join(TOOL, "assets"))
FONTS = os.path.join(ASSETS, "fonts")
PAPER = os.path.join(ASSETS, "paper")
SFX = os.path.join(ASSETS, "sfx")
GL_TRANSITIONS = os.path.join(ASSETS, "gl-transitions", "transitions")
RIFE_DIR = os.path.join(ASSETS, "rife")
RIFE = os.path.join(RIFE_DIR, "rife-ncnn-vulkan")
RIFE_MODEL = os.path.join(RIFE_DIR, "rife-v4.6")
CACHE = os.path.join("work", "cache")


def asset(path: str) -> str:
    """Resolve 'asset:sub/path' to the assets folder; other paths pass through."""
    if path.startswith("asset:"):
        return os.path.join(ASSETS, path[len("asset:"):])
    return path
