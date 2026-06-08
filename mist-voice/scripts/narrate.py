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
    sents = [s for s in sents if s != "" or True]  # keep pause markers

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
