"""MIST Studio: the Flask app.

    mist-music/bin/mist-studio            # http://127.0.0.1:5032
    python -m studio.server --port 5032   # from mist-music/

Everything slow goes through the job queue; the page polls /api/jobs.
"""
from __future__ import annotations

import argparse
import os
import time
import webbrowser

from flask import Flask, jsonify, render_template, request, send_file

from . import assist
from . import config as cfgmod
from . import library as lib
from . import stems as stemsmod
from .engine import (LANGUAGES, MODELS, TASKS, TIME_SIGNATURES, Engine, EngineError, GenRequest,
                     build_engine, probe_duration)
from .jobs import Job, JobQueue

HERE = os.path.dirname(os.path.abspath(__file__))
app = Flask(__name__, static_folder=os.path.join(HERE, "static"),
            template_folder=os.path.join(HERE, "templates"))
app.config["MAX_CONTENT_LENGTH"] = 200 * 1024 * 1024
app.json.sort_keys = False          # preset groups render in the order written below
queue = JobQueue()

_engine: Engine | None = None
_engine_key: tuple | None = None
_health_cache: dict = {}

PRESETS = {
    "genres": ["pop", "indie pop", "synthwave", "lo-fi hip hop", "hip hop", "trap", "house", "techno",
               "drum and bass", "rock", "indie rock", "punk", "metal", "folk", "country", "blues", "jazz",
               "bossa nova", "soul", "funk", "r&b", "reggae", "afrobeats", "latin pop", "k-pop", "j-pop",
               "cinematic", "orchestral", "ambient", "chiptune", "surf rock", "shoegaze", "dream pop",
               "gospel", "sea shanty", "bluegrass", "disco", "trip hop", "post-rock", "city pop"],
    "moods": ["upbeat", "melancholic", "hopeful", "dark", "dreamy", "nostalgic", "euphoric", "intimate",
              "aggressive", "playful", "romantic", "epic", "chill", "tense", "bittersweet", "triumphant",
              "eerie", "warm", "cold", "wistful"],
    "instruments": ["acoustic guitar", "electric guitar", "piano", "rhodes", "synth pads", "analog synth",
                    "808 bass", "upright bass", "strings", "brass section", "saxophone", "trumpet", "violin",
                    "cello", "banjo", "mandolin", "harp", "flute", "organ", "drum machine", "live drums",
                    "hand percussion", "vibraphone", "accordion", "harmonica", "ukulele", "choir"],
    "vocals": ["male vocals", "female vocals", "soft vocals", "powerful vocals", "raspy vocals",
               "falsetto", "breathy vocals", "rap vocals", "spoken word", "harmonies", "duet",
               "whispered vocals", "belting", "autotune"],
    "tempo": ["60 BPM", "72 BPM", "85 BPM", "95 BPM", "105 BPM", "120 BPM", "128 BPM", "140 BPM",
              "160 BPM", "174 BPM"],
    "production": ["lo-fi", "hi-fi", "vintage tape", "wide stereo", "reverb-drenched", "dry and punchy",
                   "live room", "8-bit", "orchestral swell", "minimal", "wall of sound", "radio-ready"],
    "eras": ["1960s", "1970s", "1980s", "1990s", "2000s", "2010s", "modern"],
}


# -- engine plumbing --------------------------------------------------------

def get_engine() -> Engine:
    global _engine, _engine_key
    cfg = cfgmod.load()
    key = (cfg["backend"], cfg["space_id"], cfg["use_token"], cfg["api_url"])
    if _engine is None or key != _engine_key:
        _engine = build_engine(cfg, cfgmod.hf_token())
        _engine_key = key
        _health_cache.clear()
    return _engine


def _json() -> dict:
    data = request.get_json(silent=True)
    return data if isinstance(data, dict) else {}


def _job_json(job: Job, code: int = 202):
    return jsonify(job.to_dict()), code


def _not_found(what: str = "not found"):
    return jsonify({"error": what}), 404


# -- job bodies -------------------------------------------------------------

def _song_meta_from(req: GenRequest, res, i: int, n: int, source: dict | None, job_id: str) -> dict:
    title = req.title
    if title and n > 1:
        title = f"{title} (take {i + 1})"
    metas = res.metas or {}
    return {
        "title": title, "caption": req.caption, "description": req.description,
        "lyrics": "" if req.instrumental else req.lyrics, "instrumental": req.instrumental,
        "task": req.task, "mode": req.generation_mode,
        "seed": res.seeds[i] if i < len(res.seeds) else None,
        "bpm": req.bpm or metas.get("bpm"), "key_scale": req.key_scale or metas.get("keyscale") or "",
        "time_signature": req.time_signature or metas.get("timesignature") or "",
        "vocal_language": req.vocal_language, "model": req.model, "engine": res.engine,
        "score": res.scores[i] if i < len(res.scores) else "",
        "lrc": res.lrcs[i] if i < len(res.lrcs) else "",
        "details": res.details, "status": res.status, "source": source, "job": job_id,
        "cover_strength": req.cover_strength if req.task == "cover" else None,
        "request": req.to_dict(), "take": i + 1, "takes": n,
    }


def run_generate(job: Job):
    req = GenRequest.from_dict(job.payload["request"])
    eng = get_engine()
    job.on_cancel = eng.cancel
    job.report({"stage": "starting", "detail": f"engine {eng.name}"})
    res = eng.generate(req, job.report)
    if job.cancel_requested:
        raise EngineError("Cancelled.")
    songs = []
    n = len(res.audio_paths)
    for i, p in enumerate(res.audio_paths):
        meta = lib.add_song(p, _song_meta_from(req, res, i, n, job.payload.get("source"), job.id))
        songs.append(meta)
    cfg = cfgmod.load()
    want_art = job.payload.get("auto_art")
    if want_art is None:
        want_art = cfg.get("auto_art", True)
    if want_art:
        for s in songs:
            queue.submit("art", {"song_id": s["id"]}, run_art, label=f"Art: {s['title']}")
    return {"songs": [s["id"] for s in songs], "details": res.details, "status": res.status}


def run_describe(job: Job):
    p = job.payload
    eng = get_engine()
    job.on_cancel = eng.cancel
    return eng.describe(p.get("description", ""), bool(p.get("instrumental")),
                        p.get("vocal_language") or "unknown", float(p.get("lm_temperature", 0.85)),
                        int(p.get("lm_top_k", 0)), float(p.get("lm_top_p", 0.9)))


def run_enhance(job: Job):
    p = job.payload
    eng = get_engine()
    job.on_cancel = eng.cancel
    return eng.enhance(p.get("caption", ""), p.get("lyrics", ""), float(p.get("bpm") or 0),
                       float(p.get("duration") or -1), p.get("key_scale") or "",
                       p.get("time_signature") or "")


def run_random(job: Job):
    return get_engine().random_description()


def run_analyze(job: Job):
    p = job.payload
    path = lib.resolve_source(p["kind"], p["id"])
    if not path:
        raise EngineError("That source track is gone.")
    eng = get_engine()
    job.on_cancel = eng.cancel
    job.report({"stage": "running", "detail": "listening to the track"})
    out = eng.analyze(path)
    if p["kind"] == "upload":
        lib.update_upload(p["id"], {"analysis": {k: v for k, v in out.items() if k != "codes"},
                                    "codes": out.get("codes", "")})
    return out


def run_lyrics(job: Job):
    p = job.payload
    cfg = cfgmod.load()
    writer = p.get("writer") or cfg.get("lyric_writer", "claude")
    if writer == "space":
        eng = get_engine()
        job.on_cancel = eng.cancel
        d = eng.describe(f"{p.get('theme', '')}. Style: {p.get('style', '')}", False,
                         p.get("language") or "en")
        return {"lyrics": d.get("lyrics", ""), "caption": d.get("caption", ""), "writer": "space"}
    job.report({"stage": "running", "detail": f"claude {cfg.get('claude_model')}"})
    text = assist.write_lyrics(p.get("theme", ""), p.get("style", ""), p.get("language") or "en",
                               p.get("structure", ""), cfg.get("claude_model", "claude-sonnet-5"))
    return {"lyrics": text, "writer": "claude"}


def run_caption(job: Job):
    cfg = cfgmod.load()
    return {"caption": assist.suggest_caption(job.payload.get("description", ""),
                                              cfg.get("claude_model", "claude-sonnet-5"))}


def run_art(job: Job):
    p = job.payload
    meta = lib.get_song(p["song_id"])
    if not meta:
        raise EngineError("Song is gone.")
    prompt = p.get("prompt") or assist.art_prompt(meta)
    cfg = cfgmod.load()
    job.report({"stage": "running", "detail": "mist-image"})
    assist.make_art(prompt, lib.art_path(meta["id"]), int(cfg.get("art_size", 768)))
    lib.update_song(meta["id"], {"art_prompt": prompt})
    return {"song_id": meta["id"], "prompt": prompt}


def run_stems(job: Job):
    p = job.payload
    path = lib.resolve_source(p["kind"], p["id"])
    if not path:
        raise EngineError("That track is gone.")
    out_dir = lib.stems_dir(p["id"]) if p["kind"] == "song" else lib.upload_stems_dir(p["id"])
    cfg = cfgmod.load()
    engine = p.get("engine") or cfg.get("stems_engine", "local")
    out = stemsmod.separate(path, out_dir, p.get("mode", "two"), engine, cfgmod.hf_token(), job.report)
    return {"kind": p["kind"], "id": p["id"], "stems": {k: os.path.basename(v) for k, v in out.items()}}


# -- pages ------------------------------------------------------------------

@app.get("/")
def index():
    return render_template("index.html")


@app.get("/api/meta")
def api_meta():
    return jsonify({
        "models": MODELS, "tasks": TASKS, "languages": LANGUAGES, "time_signatures": TIME_SIGNATURES,
        "presets": PRESETS, "section_tags": assist.SECTION_TAGS,
        "capabilities": {
            "demucs": stemsmod.local_available(), "claude": assist.claude_available(),
            "mist_image": os.access(assist.MIST_IMAGE, os.X_OK),
        },
    })


@app.get("/api/config")
def api_config_get():
    cfg = cfgmod.load()
    cfg["has_token"] = bool(cfgmod.hf_token())
    return jsonify(cfg)


@app.post("/api/config")
def api_config_set():
    cfg = cfgmod.save(_json())
    get_engine()
    cfg["has_token"] = bool(cfgmod.hf_token())
    return jsonify(cfg)


@app.get("/api/health")
def api_health():
    force = request.args.get("force") == "1"
    now = time.time()
    if force or not _health_cache or now - _health_cache.get("_at", 0) > 120:
        eng = get_engine()
        try:
            h = eng.health()
        except Exception as e:  # noqa: BLE001 - health must never raise
            h = {"engine": eng.name, "ok": False, "error": str(e)[:300]}
        _health_cache.clear()
        _health_cache.update(h, _at=now)
    out = {k: v for k, v in _health_cache.items() if k != "_at"}
    out.update(demucs=stemsmod.local_available(), claude=assist.claude_available(),
               queue_running=bool(queue.current), checked=_health_cache.get("_at"))
    return jsonify(out)


# -- generation -------------------------------------------------------------

@app.post("/api/generate")
def api_generate():
    body = _json()
    reqd = body.get("request") or body
    source = body.get("source")
    try:
        req = GenRequest.from_dict(reqd)
        if source and isinstance(source, dict) and req.task in ("cover", "repaint"):
            req.src_audio = lib.resolve_source(source.get("kind", ""), source.get("id", ""))
        ref = body.get("reference")
        if ref and isinstance(ref, dict):
            req.reference_audio = lib.resolve_source(ref.get("kind", ""), ref.get("id", ""))
        req.validate()
    except (EngineError, ValueError) as e:
        return jsonify({"error": str(e)}), 400
    label = {"cover": "Cover", "repaint": "Repaint"}.get(req.task, "Song")
    name = req.title or req.description or req.caption.split(",")[0] or "untitled"
    job = queue.submit("generate", {"request": req.to_dict(), "source": source,
                                    "auto_art": body.get("auto_art")},
                       run_generate, label=f"{label}: {name[:48]}")
    return _job_json(job)


@app.post("/api/describe")
def api_describe():
    body = _json()
    if not (body.get("description") or "").strip():
        return jsonify({"error": "Describe the song first."}), 400
    return _job_json(queue.submit("describe", body, run_describe, label="Write from description"))


@app.post("/api/enhance")
def api_enhance():
    return _job_json(queue.submit("enhance", _json(), run_enhance, label="Enhance prompt"))


@app.post("/api/random")
def api_random():
    return _job_json(queue.submit("random", {}, run_random, label="Random idea"))


@app.post("/api/lyrics")
def api_lyrics():
    body = _json()
    if not (body.get("theme") or "").strip():
        return jsonify({"error": "Give the lyric writer a theme."}), 400
    return _job_json(queue.submit("lyrics", body, run_lyrics, label=f"Lyrics: {body['theme'][:40]}"))


@app.post("/api/caption")
def api_caption():
    body = _json()
    if not (body.get("description") or "").strip():
        return jsonify({"error": "Describe the song first."}), 400
    return _job_json(queue.submit("caption", body, run_caption, label="Style tags from brief"))


@app.post("/api/analyze")
def api_analyze():
    body = _json()
    if not lib.resolve_source(body.get("kind", ""), body.get("id", "")):
        return jsonify({"error": "Pick a source track first."}), 400
    return _job_json(queue.submit("analyze", body, run_analyze, label="Analyze track"))


# -- jobs -------------------------------------------------------------------

@app.get("/api/jobs")
def api_jobs():
    return jsonify(queue.list())


@app.get("/api/jobs/<job_id>")
def api_job(job_id):
    job = queue.get(job_id)
    if job is None:
        return _not_found("no such job")
    return jsonify(job.to_dict())


@app.post("/api/jobs/<job_id>/cancel")
def api_job_cancel(job_id):
    return jsonify({"ok": queue.cancel(job_id)})


@app.post("/api/jobs/clear")
def api_jobs_clear():
    return jsonify({"cleared": queue.clear_finished()})


# -- library ----------------------------------------------------------------

@app.get("/api/songs")
def api_songs():
    return jsonify(lib.list_songs(request.args.get("q", ""), request.args.get("fav") == "1",
                                  request.args.get("sort", "newest")))


@app.get("/api/songs/<song_id>")
def api_song(song_id):
    meta = lib.get_song(song_id)
    if meta is None:
        return _not_found("no such song")
    return jsonify(meta)


@app.patch("/api/songs/<song_id>")
def api_song_patch(song_id):
    meta = lib.update_song(song_id, _json())
    if meta is None:
        return _not_found("no such song")
    return jsonify(meta)


@app.delete("/api/songs/<song_id>")
def api_song_delete(song_id):
    return jsonify({"ok": lib.delete_song(song_id)})


@app.post("/api/songs/<song_id>/art")
def api_song_art(song_id):
    meta = lib.get_song(song_id)
    if meta is None:
        return _not_found("no such song")
    body = _json()
    return _job_json(queue.submit("art", {"song_id": song_id, "prompt": body.get("prompt")}, run_art,
                                  label=f"Art: {meta.get('title', song_id)}"))


@app.post("/api/songs/<song_id>/stems")
def api_song_stems(song_id):
    meta = lib.get_song(song_id)
    if meta is None:
        return _not_found("no such song")
    body = _json()
    return _job_json(queue.submit("stems", {"kind": "song", "id": song_id, "mode": body.get("mode", "two"),
                                            "engine": body.get("engine")}, run_stems,
                                  label=f"Stems: {meta.get('title', song_id)}"))


@app.get("/media/song/<song_id>")
def media_song(song_id):
    meta = lib.get_song(song_id)
    path = lib.song_path(song_id)
    if meta is None or path is None:
        return _not_found("no such song")
    return send_file(path, conditional=True, as_attachment=request.args.get("download") == "1",
                     download_name=lib.download_name(meta))


@app.get("/media/song/<song_id>/art")
def media_song_art(song_id):
    try:
        p = lib.art_path(song_id)
    except ValueError:
        return _not_found("no such song")
    if not os.path.isfile(p):
        return _not_found("no art yet")
    return send_file(p, conditional=True, max_age=0)


@app.get("/media/song/<song_id>/stem/<stem>")
def media_song_stem(song_id, stem):
    path = lib.resolve_source("stem", f"song:{song_id}:{stem}")
    if path is None:
        return _not_found("no such stem")
    meta = lib.get_song(song_id) or {}
    base = lib.download_name(meta).rsplit(".", 1)[0]
    ext = os.path.splitext(path)[1]
    return send_file(path, conditional=True, as_attachment=request.args.get("download") == "1",
                     download_name=f"{base}-{stem}{ext}")


# -- uploads ----------------------------------------------------------------

@app.get("/api/uploads")
def api_uploads():
    return jsonify(lib.list_uploads())


@app.post("/api/uploads")
def api_upload():
    f = request.files.get("file")
    if not f or not f.filename:
        return jsonify({"error": "No file."}), 400
    try:
        meta = lib.add_upload(f.stream, f.filename)
    except ValueError as e:
        return jsonify({"error": str(e)}), 400
    return jsonify(meta), 201


@app.delete("/api/uploads/<upload_id>")
def api_upload_delete(upload_id):
    return jsonify({"ok": lib.delete_upload(upload_id)})


@app.post("/api/uploads/<upload_id>/stems")
def api_upload_stems(upload_id):
    meta = lib.get_upload(upload_id)
    if meta is None:
        return _not_found("no such upload")
    body = _json()
    return _job_json(queue.submit("stems", {"kind": "upload", "id": upload_id, "mode": body.get("mode", "two"),
                                            "engine": body.get("engine")}, run_stems,
                                  label=f"Stems: {meta.get('name', upload_id)}"))


@app.get("/media/upload/<upload_id>")
def media_upload(upload_id):
    path = lib.upload_path(upload_id)
    if path is None:
        return _not_found("no such upload")
    return send_file(path, conditional=True)


@app.get("/media/upload/<upload_id>/stem/<stem>")
def media_upload_stem(upload_id, stem):
    path = lib.resolve_source("stem", f"upload:{upload_id}:{stem}")
    if path is None:
        return _not_found("no such stem")
    return send_file(path, conditional=True, as_attachment=request.args.get("download") == "1")


@app.get("/api/duration")
def api_duration():
    kind, ident = request.args.get("kind", ""), request.args.get("id", "")
    path = lib.resolve_source(kind, ident)
    return jsonify({"duration": probe_duration(path) if path else None})


# -- main -------------------------------------------------------------------

def main(argv=None):
    ap = argparse.ArgumentParser(description="MIST Studio web app")
    ap.add_argument("--host", default="127.0.0.1")
    ap.add_argument("--port", type=int, default=cfgmod.PORT)
    ap.add_argument("--open", action="store_true", help="open the browser")
    args = ap.parse_args(argv)
    cfgmod.ensure_dirs()
    cfgmod.load_env()
    if args.open:
        webbrowser.open(f"http://{args.host}:{args.port}/")
    app.run(host=args.host, port=args.port, threaded=True, use_reloader=False, debug=False)


if __name__ == "__main__":
    main()
