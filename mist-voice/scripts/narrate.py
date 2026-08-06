#!/usr/bin/env python3
"""Narrate text/markdown in MIST's voice -> a single audio file.

Strips markdown to clean prose, sentence-splits, synthesizes each sentence via
the resident service (scripts/serve.py), concatenates with light pauses, and
writes an mp3 (or wav). Long-form friendly: the per-sentence calls keep each
XTTS request under its token limit.

  narrate.py briefing.md -o briefing.mp3
  echo "Good morning." | narrate.py - -o hi.mp3

Requires the service running:  python scripts/serve.py &
"""
import os, sys, re, io, argparse, subprocess, tempfile, urllib.request, json, wave

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
PORT = int(os.environ.get("MIST_PORT", "8087"))

# XTTS has no idea what to do with an emoji or a kaomoji. It burns a whole
# synthesis call on the face and vocalizes garbage. MIST's written voice is full
# of both, so they come out before anything reaches the model.
EMOJI = re.compile(
    "["
    "\U0001F000-\U0001FAFF"   # pictographs, emoticons, transport, supplemental
    "\U0001F3FB-\U0001F3FF"   # skin-tone modifiers
    "☀-➿"           # misc symbols + dingbats (✨ ✅ ➡)
    "⬀-⯿"
    "←-⇿"           # arrows
    "⌀-⏿"           # misc technical
    "︀-️"           # variation selectors
    "‍"                  # zero-width joiner
    "]+")

# A kaomoji is a short parenthetical with no real words in it. Anything longer
# than this, or containing an actual ASCII word, is a genuine aside and stays.
_FACE_MAX = 15
_ASCII_FACE = re.compile(r"^[<>ovOTxX^;:=\-_.,'\"`\s]+$")
# Stray arms that live outside the parens: ╯︵ ┻━┻ and ┬─┬ノ.
_FACE_PARTS = re.compile(r"[─-╿゠-ヿ︰-﹏]+")

def strip_faces(text):
    """Drop emoji and kaomoji, keeping ordinary parentheticals intact."""
    text = EMOJI.sub(" ", text)

    def drop(m):
        inner = m.group(1)
        if len(inner) > _FACE_MAX:
            return m.group(0)                      # "(it plays by default)"
        if _ASCII_FACE.match(inner):
            return " "                             # "(o.o)"  "(>_<)"
        if any(ord(c) > 127 for c in inner):
            return " "                             # "(ə_e)"  "(◠▽◠)"
        return m.group(0)                          # "(e.g.)"  "(1)"

    text = re.sub(r"\(([^()]*)\)", drop, text)
    return _FACE_PARTS.sub(" ", text)

def strip_markdown(md):
    """Markdown -> speakable prose. Drop syntax, keep sentences and paragraph breaks."""
    md = re.sub(r"```.*?```", "", md, flags=re.S)          # code fences
    md = re.sub(r"`([^`]+)`", r"\1", md)                    # inline code
    md = re.sub(r"!\[[^\]]*\]\([^)]*\)", "", md)            # images
    md = re.sub(r"\[([^\]]+)\]\([^)]*\)", r"\1", md)        # links -> text
    md = re.sub(r"\[\[([^\]|]+\|)?([^\]]+)\]\]", r"\2", md) # wikilinks -> label
    md = re.sub(r"^\s*>\s?", "", md, flags=re.M)            # blockquote markers
    md = re.sub(r"^[#>\-\*\+]\s*", "", md, flags=re.M)      # heading/list bullets
    md = re.sub(r"[*_~]{1,3}", "", md)                      # emphasis
    md = re.sub(r"\|", " ", md)                             # table pipes
    md = re.sub(r"^[-:\s]+$", "", md, flags=re.M)           # table rules / hr
    md = strip_faces(md)
    md = re.sub(r"[ \t]+", " ", md)
    md = re.sub(r"\n{2,}", "\n\n", md)
    return md.strip()

def sentences(text):
    try:
        import pysbd
        seg = pysbd.Segmenter(language="en", clean=True)
        out = []
        for para in text.split("\n\n"):
            para = para.strip()
            if para:
                out.extend(s.strip() for s in seg.segment(para) if s.strip())
                out.append("")  # paragraph pause marker
        return out
    except Exception:
        return [s.strip() for s in re.split(r"(?<=[.!?])\s+", text) if s.strip()]

def say(text):
    req = urllib.request.Request(
        f"http://127.0.0.1:{PORT}/say", method="POST",
        data=json.dumps({"text": text}).encode(),
        headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=300) as r:
        return r.read()

def silence_wav(seconds, sr=24000):
    buf = io.BytesIO()
    with wave.open(buf, "wb") as w:
        w.setnchannels(1); w.setsampwidth(2); w.setframerate(sr)
        w.writeframes(b"\x00\x00" * int(sr * seconds))
    return buf.getvalue()

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("input", help="markdown/text file, or - for stdin")
    ap.add_argument("-o", "--out", required=True, help="output .mp3 or .wav")
    ap.add_argument("--play", action="store_true")
    args = ap.parse_args()

    raw = sys.stdin.read() if args.input == "-" else open(args.input, encoding="utf-8").read()
    sents = sentences(strip_markdown(raw))
    # A stripped-out face can leave a fragment with nothing sayable in it ("!").
    # Synthesizing those costs a call and comes back as noise. "" is the
    # paragraph-pause marker, so it stays.
    sents = [s for s in sents if s == "" or re.search(r"\w", s)]

    try:
        urllib.request.urlopen(f"http://127.0.0.1:{PORT}/health", timeout=5)
    except Exception:
        sys.exit(f"MIST service not reachable on :{PORT}. Start it: python scripts/serve.py &")

    with tempfile.TemporaryDirectory() as td:
        parts, n = [], 0
        for s in sents:
            if s == "":
                p = os.path.join(td, f"p{len(parts)}.wav"); open(p, "wb").write(silence_wav(0.45)); parts.append(p)
                continue
            n += 1
            sys.stderr.write(f"\r[narrate] sentence {n}/{sum(1 for x in sents if x)}   "); sys.stderr.flush()
            p = os.path.join(td, f"p{len(parts)}.wav"); open(p, "wb").write(say(s)); parts.append(p)
            g = os.path.join(td, f"p{len(parts)}.wav"); open(g, "wb").write(silence_wav(0.18)); parts.append(g)
        sys.stderr.write("\n")
        lst = os.path.join(td, "list.txt")
        with open(lst, "w") as f:
            for p in parts: f.write(f"file '{p}'\n")
        subprocess.run(["ffmpeg", "-y", "-f", "concat", "-safe", "0", "-i", lst,
                        "-ar", "44100", args.out], check=True,
                       stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    print(f"[narrate] {n} sentences -> {args.out}")
    if args.play:
        subprocess.run(["afplay", args.out])

if __name__ == "__main__":
    main()
