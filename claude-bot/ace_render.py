"""Standalone Ace Attorney renderer.

Run by the dedicated `.ace-venv` Python as a SUBPROCESS (objection_engine pins
old, heavy deps that can't live in the bot's main venv, and rendering must never
block the gateway event loop). The bot writes a scene to JSON and invokes:

    .ace-venv/bin/python ace_render.py <scene.json> <out.mp4>

scene.json is a list of {"name": str, "text": str}. First run downloads the
sprite/music assets into the venv (~one-time, takes a while).
"""

import json
import sys


def main() -> None:
    if len(sys.argv) != 3:
        print("usage: ace_render.py <scene.json> <out.mp4>", file=sys.stderr)
        sys.exit(2)
    scene_path, out_path = sys.argv[1], sys.argv[2]
    with open(scene_path) as f:
        scene = json.load(f)

    # Imported here so the usage error above doesn't pay the heavy import cost.
    from objection_engine import render_comment_list
    from objection_engine.beans.comment import Comment

    comments = [
        Comment(user_name=(item.get("name") or "Witness")[:32], text_content=item["text"])
        for item in scene
        if item.get("text")
    ]
    if len(comments) < 2:
        print("need at least 2 comments", file=sys.stderr)
        sys.exit(3)

    render_comment_list(comments, output_filename=out_path)


if __name__ == "__main__":
    main()
