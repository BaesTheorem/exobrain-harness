#!/usr/bin/env python3
"""Build the local dataset for the Bible Study PWA.

Fetches the Skeptic's Annotated Bible (KJV, 66 books) and the Skeptic's
Annotated Book of Mormon (15 books) from skepticsannotatedbible.com and
converts each chapter into JSON the app can render: verse text with the
site's category spans, Steve Wells' side notes, section summaries, and
endnotes.

The output goes to bible-study/data/ which is gitignored on purpose. The
annotations are Steve Wells' copyrighted work, so they stay on your
machine instead of being redistributed through this repo. Rebuild any
time with:

    python3 bible-study/build-data.py            # everything (~20 min)
    python3 bible-study/build-data.py --sample   # a few books, for testing
    python3 bible-study/build-data.py --book gen --book 1ne

Stdlib only. Be nice to the site: default 0.4s delay between requests.
"""

import argparse
import json
import re
import sys
import time
import urllib.request
import urllib.error
from html.parser import HTMLParser
from pathlib import Path

BASE = "https://www.skepticsannotatedbible.com"
OUT_DIR = Path(__file__).resolve().parent / "data"
UA = "exobrain-bible-study/1.0 (personal study app; single polite crawl)"

# (slug, display name) in canonical order
BIBLE_BOOKS = [
    ("gen", "Genesis"), ("ex", "Exodus"), ("lev", "Leviticus"),
    ("num", "Numbers"), ("dt", "Deuteronomy"), ("jos", "Joshua"),
    ("jg", "Judges"), ("ru", "Ruth"), ("1sam", "1 Samuel"),
    ("2sam", "2 Samuel"), ("1kg", "1 Kings"), ("2kg", "2 Kings"),
    ("1chr", "1 Chronicles"), ("2chr", "2 Chronicles"), ("ezra", "Ezra"),
    ("neh", "Nehemiah"), ("est", "Esther"), ("job", "Job"),
    ("ps", "Psalms"), ("pr", "Proverbs"), ("ec", "Ecclesiastes"),
    ("sofs", "Song of Solomon"), ("is", "Isaiah"), ("jer", "Jeremiah"),
    ("lam", "Lamentations"), ("ezek", "Ezekiel"), ("dan", "Daniel"),
    ("hos", "Hosea"), ("jl", "Joel"), ("am", "Amos"), ("ob", "Obadiah"),
    ("jon", "Jonah"), ("mic", "Micah"), ("nah", "Nahum"),
    ("hab", "Habakkuk"), ("zeph", "Zephaniah"), ("hag", "Haggai"),
    ("zech", "Zechariah"), ("mal", "Malachi"),
    ("mt", "Matthew"), ("mk", "Mark"), ("lk", "Luke"), ("jn", "John"),
    ("acts", "Acts"), ("rom", "Romans"), ("1cor", "1 Corinthians"),
    ("2cor", "2 Corinthians"), ("gal", "Galatians"), ("eph", "Ephesians"),
    ("phil", "Philippians"), ("col", "Colossians"),
    ("1th", "1 Thessalonians"), ("2th", "2 Thessalonians"),
    ("1tim", "1 Timothy"), ("2tim", "2 Timothy"), ("tit", "Titus"),
    ("philem", "Philemon"), ("heb", "Hebrews"), ("jas", "James"),
    ("1pet", "1 Peter"), ("2pet", "2 Peter"), ("1jn", "1 John"),
    ("2jn", "2 John"), ("3jn", "3 John"), ("jude", "Jude"),
    ("rev", "Revelation"),
]

BOM_BOOKS = [
    ("1ne", "1 Nephi"), ("2ne", "2 Nephi"), ("jacob", "Jacob"),
    ("enos", "Enos"), ("jarom", "Jarom"), ("omni", "Omni"),
    ("words", "Words of Mormon"), ("mosiah", "Mosiah"), ("alma", "Alma"),
    ("hel", "Helaman"), ("3ne", "3 Nephi"), ("4ne", "4 Nephi"),
    ("mormon", "Mormon"), ("ether", "Ether"), ("moroni", "Moroni"),
]

SAMPLE_BOOKS = ["gen", "jon", "ob", "mk", "1ne", "enos", "alma"]

# category icon filename stem -> category code used by the app
ICON_TO_CAT = {
    "abs": "a", "inj": "i", "cr": "v", "int": "int", "contra": "c",
    "sci": "sci", "fv": "f", "interp": "interp", "wom": "w",
    "good": "g", "sex": "s", "pr": "pr", "lang": "l", "gay": "h",
    "pol": "pol", "plag": "plag", "boring": "b", "ejat": "ejat",
}

ALLOWED_TAGS = {
    "p", "blockquote", "i", "b", "em", "strong", "sup", "sub",
    "span", "a", "br", "ol", "ul", "li", "h4", "h5", "table",
    "tr", "td", "th",
}
ALLOWED_SPAN_CLASSES = {
    "a", "c", "sci", "i", "v", "int", "interp", "pr", "w", "l", "s",
    "f", "pol", "g", "h", "plag", "b", "ejat", "highlight",
}
VOID_TAGS = {"img", "br", "hr", "meta", "link", "input", "source", "wbr"}


# ---------------------------------------------------------------- tiny DOM

class Node:
    __slots__ = ("tag", "attrs", "children")

    def __init__(self, tag, attrs=None):
        self.tag = tag
        self.attrs = dict(attrs or {})
        self.children = []

    def classes(self):
        return (self.attrs.get("class") or "").split()

    def find_all(self, tag=None, cls=None):
        out = []
        stack = list(self.children)
        while stack:
            n = stack.pop(0)
            if isinstance(n, Node):
                if (tag is None or n.tag == tag) and (cls is None or cls in n.classes()):
                    out.append(n)
                stack = n.children + stack
        return out

    def text(self):
        parts = []
        stack = list(self.children)
        while stack:
            n = stack.pop(0)
            if isinstance(n, str):
                parts.append(n)
            else:
                stack = n.children + stack
        return "".join(parts)


class TreeBuilder(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.root = Node("root")
        self.stack = [self.root]

    def handle_starttag(self, tag, attrs):
        node = Node(tag, attrs)
        self.stack[-1].children.append(node)
        if tag not in VOID_TAGS:
            self.stack.append(node)

    def handle_startendtag(self, tag, attrs):
        self.stack[-1].children.append(Node(tag, attrs))

    def handle_endtag(self, tag):
        for i in range(len(self.stack) - 1, 0, -1):
            if self.stack[i].tag == tag:
                del self.stack[i:]
                return
        # stray close tag: ignore

    def handle_data(self, data):
        if data:
            self.stack[-1].children.append(data)


def parse_html(html):
    tb = TreeBuilder()
    tb.feed(html)
    return tb.root


# ------------------------------------------------------------ sanitizing

def esc(s):
    return s.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


def esc_attr(s):
    return esc(s).replace('"', "&quot;")


def cat_from_img(src):
    stem = re.sub(r"\d*\.(gif|png|jpg|webp)$", "", (src or "").rsplit("/", 1)[-1].lower())
    return ICON_TO_CAT.get(stem)


def rewrite_href(href, corpus, slug, book_slugs):
    """Map the site's relative links onto app navigation or external URLs.

    Returns (href, data_nav, external).
    """
    href = href or "#"
    if href.startswith("#"):
        return href, None, False
    if href.startswith("http://") or href.startswith("https://"):
        return href, None, True

    m = re.match(r"^(\d+)\.html(#.*)?$", href)
    if m:
        return "#", f"{corpus}/{slug}/{m.group(1)}", False

    m = re.match(r"^\.\./([\w]+)/(\d+)\.html(#.*)?$", href)
    if m and m.group(1) in book_slugs:
        return "#", f"{corpus}/{m.group(1)}/{m.group(2)}", False

    m = re.match(r"^/BOM/([\w]+)/(\d+)\.html(#.*)?$", href)
    if m:
        return "#", f"bom/{m.group(1)}/{m.group(2)}", False

    m = re.match(r"^/([\w]+)/(\d+)\.html(#.*)?$", href)
    if m and m.group(1) in dict(BIBLE_BOOKS):
        return "#", f"bible/{m.group(1)}/{m.group(2)}", False

    # everything else (contra/, interp/, says_about/, ...) points at the site
    if href.startswith("/"):
        return BASE + href, None, True
    base_path = f"/BOM/{slug}/" if corpus == "bom" else f"/{slug}/"
    while href.startswith("../"):
        href = href[3:]
        base_path = base_path.rsplit("/", 2)[0] + "/"
    return BASE + base_path + href, None, True


def serialize(node, corpus, slug, book_slugs):
    """Sanitize a parsed subtree back into HTML for the app."""
    out = []
    for child in node.children:
        if isinstance(child, str):
            out.append(esc(child))
            continue
        tag = child.tag
        if tag in ("script", "style", "form", "textarea", "button"):
            continue
        if tag == "img":
            cat = cat_from_img(child.attrs.get("src"))
            if cat:
                out.append(f'<span class="cat-chip cat-{cat}" data-cat="{cat}"></span>')
            continue
        if tag == "iframe":
            src = child.attrs.get("src", "")
            if src.startswith("//"):
                src = "https:" + src
            if src.startswith("http"):
                out.append(f'<a href="{esc_attr(src)}" target="_blank" rel="noopener" class="embed-link">[embedded video]</a>')
            continue
        inner = serialize(child, corpus, slug, book_slugs)
        if tag == "a":
            attrs = ""
            anchor_id = child.attrs.get("id")
            if anchor_id:
                attrs += f' id="fn-{esc_attr(anchor_id)}"'
            if child.attrs.get("href") is None:
                out.append(f"<a{attrs}>{inner}</a>")
                continue
            href, nav, external = rewrite_href(child.attrs.get("href"), corpus, slug, book_slugs)
            if nav:
                attrs += f' href="#" data-nav="{esc_attr(nav)}"'
            elif external:
                attrs += f' href="{esc_attr(href)}" target="_blank" rel="noopener"'
            else:
                attrs += f' href="{esc_attr(href)}"'
            out.append(f"<a{attrs}>{inner}</a>")
            continue
        if tag not in ALLOWED_TAGS:
            out.append(inner)
            continue
        attrs = ""
        if tag == "span":
            cls = [c for c in child.classes() if c in ALLOWED_SPAN_CLASSES]
            if cls:
                attrs = f' class="{" ".join(cls)}"'
        out.append(f"<{tag}{attrs}>{inner}</{tag}>")
    html = "".join(out)
    return re.sub(r"\s+", " ", html).strip() if node.tag in ("p",) else html


# ------------------------------------------------------------- fetching

def fetch(url, delay, retries=4):
    last = None
    for attempt in range(retries):
        try:
            req = urllib.request.Request(url, headers={"User-Agent": UA})
            with urllib.request.urlopen(req, timeout=60) as r:
                data = r.read().decode("utf-8", errors="replace")
            time.sleep(delay)
            return data
        except urllib.error.HTTPError as e:
            if e.code == 404:
                return None
            last = e
        except Exception as e:  # noqa: BLE001 - retry on any transient error
            last = e
        time.sleep(2 ** attempt)
    raise RuntimeError(f"failed to fetch {url}: {last}")


def chapter_url(corpus, slug, n):
    prefix = "/BOM" if corpus == "bom" else ""
    return f"{BASE}{prefix}/{slug}/{n}.html"


# -------------------------------------------------------------- parsing

MARKER_REF_RE = re.compile(r"^[\s\d:,;.\-–and]+$")


def remove_node(root, target):
    """Detach target from wherever it sits under root (may be nested)."""
    stack = [root]
    while stack:
        n = stack.pop()
        if target in n.children:
            n.children.remove(target)
            return True
        stack.extend(c for c in n.children if isinstance(c, Node))
    return False


def parse_chapter(html, corpus, slug, book_slugs):
    root = parse_html(html)
    blocks_out = []
    heading = None
    footnotes = []

    chapblocks = root.find_all("div", cls="chapblock")
    if not chapblocks:
        return None
    for cb in chapblocks:
        for div in cb.children:
            if not isinstance(div, Node) or div.tag != "div":
                continue
            cls = div.classes()
            if "chapter" in cls:
                for p in div.find_all("p"):
                    txt = serialize(p, corpus, slug, book_slugs)
                    if txt:
                        heading = txt
            elif "summary" in cls:
                txt = serialize(div, corpus, slug, book_slugs).strip()
                if txt:
                    blocks_out.append({"t": "summary", "html": txt})
            elif "note" in cls:
                cats = []
                for img in div.find_all("img"):
                    cat = cat_from_img(img.attrs.get("src"))
                    if cat and cat not in cats:
                        cats.append(cat)
                plain = div.text().strip()
                if cats and (not plain or MARKER_REF_RE.match(plain)):
                    blocks_out.append({"t": "marker", "cats": cats, "ref": plain})
                else:
                    html_note = serialize(div, corpus, slug, book_slugs).strip()
                    if html_note:
                        blocks_out.append({"t": "note", "html": html_note})
            elif "text" in cls:
                verses = []
                for p in div.children:
                    if not isinstance(p, Node) or p.tag != "p":
                        continue
                    vnum = None
                    sups = p.find_all("sup")
                    if sups:
                        anchors = sups[0].find_all("a")
                        if anchors and anchors[0].attrs.get("id", "").isdigit():
                            vnum = int(anchors[0].attrs["id"])
                            # drop the number itself; the app renders it
                            remove_node(p, sups[0])
                    html_v = serialize(p, corpus, slug, book_slugs).strip()
                    if not html_v:
                        continue
                    if vnum is None and verses:
                        # continuation paragraph of the previous verse
                        verses[-1]["html"] += "<br>" + html_v
                    else:
                        verses.append({"v": vnum or 0, "html": html_v})
                if verses:
                    blocks_out.append({"t": "verses", "items": verses})

    for links in root.find_all("div", cls="links"):
        for li in links.find_all("li"):
            fid = li.attrs.get("id")
            if not fid or not re.match(r"^\d+n$", fid):
                continue
            footnotes.append({
                "id": fid,
                "html": serialize(li, corpus, slug, book_slugs).strip(),
            })

    if not any(b["t"] == "verses" for b in blocks_out):
        return None
    return {"heading": heading, "blocks": blocks_out, "footnotes": footnotes}


def discover_chapters(first_page_html, corpus, slug):
    prefix = f"/BOM/{slug}/" if corpus == "bom" else f"/{slug}/"
    nums = {
        int(m)
        for m in re.findall(re.escape(prefix) + r"(\d+)\.html", first_page_html)
    }
    return sorted(nums) if nums else [1]


# ----------------------------------------------------------------- main

def build_book(corpus, slug, name, delay, book_slugs):
    first = fetch(chapter_url(corpus, slug, 1), delay)
    if first is None:
        print(f"  !! {name}: chapter 1 not found, skipping", file=sys.stderr)
        return None
    chapter_nums = discover_chapters(first, corpus, slug)
    chapters = []
    for n in chapter_nums:
        html = first if n == 1 else fetch(chapter_url(corpus, slug, n), delay)
        if html is None:
            print(f"  !! {name} {n}: 404, skipping", file=sys.stderr)
            continue
        parsed = parse_chapter(html, corpus, slug, book_slugs)
        if parsed is None:
            print(f"  !! {name} {n}: no verses parsed, skipping", file=sys.stderr)
            continue
        parsed["c"] = n
        chapters.append(parsed)
    if not chapters:
        return None
    return {"slug": slug, "name": name, "corpus": corpus, "chapters": chapters}


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--sample", action="store_true", help="build a small test subset")
    ap.add_argument("--book", action="append", default=[], help="build specific book slug(s)")
    ap.add_argument("--delay", type=float, default=0.4, help="seconds between requests")
    args = ap.parse_args()

    wanted = set(args.book)
    if args.sample and not wanted:
        wanted = set(SAMPLE_BOOKS)

    corpora = [
        ("bible", "Bible (KJV)", BIBLE_BOOKS),
        ("bom", "Book of Mormon", BOM_BOOKS),
    ]

    # merge into any existing manifest so partial builds don't drop books
    manifest = {"generated": "", "corpora": {}}
    manifest_path = OUT_DIR / "manifest.json"
    if manifest_path.exists():
        try:
            manifest = json.loads(manifest_path.read_text())
        except ValueError:
            pass
    manifest["generated"] = time.strftime("%Y-%m-%d %H:%M:%S UTC", time.gmtime())

    total_chapters = 0
    for corpus, corpus_name, books in corpora:
        book_slugs = {s for s, _ in books}
        existing = {
            b["slug"]: b
            for b in manifest.get("corpora", {}).get(corpus, {}).get("books", [])
        }
        built_any = False
        for slug, name in books:
            if wanted and slug not in wanted:
                continue
            print(f"[{corpus}] {name} ...", flush=True)
            book = build_book(corpus, slug, name, args.delay, book_slugs)
            if book is None:
                continue
            dest = OUT_DIR / corpus / f"{slug}.json"
            dest.parent.mkdir(parents=True, exist_ok=True)
            dest.write_text(json.dumps(book, ensure_ascii=False, separators=(",", ":")))
            existing[slug] = {"slug": slug, "name": name, "chapters": [c["c"] for c in book["chapters"]]}
            built_any = True
            total_chapters += len(book["chapters"])
            print(f"    {len(book['chapters'])} chapters -> {dest.relative_to(OUT_DIR.parent)}")
        if built_any or existing:
            # keep canonical book order regardless of build order
            ordered = [existing[s] for s, _ in books if s in existing]
            manifest.setdefault("corpora", {})[corpus] = {"name": corpus_name, "books": ordered}

    if not manifest["corpora"]:
        print("nothing built", file=sys.stderr)
        sys.exit(1)

    OUT_DIR.mkdir(parents=True, exist_ok=True)
    (OUT_DIR / "manifest.json").write_text(json.dumps(manifest, ensure_ascii=False, indent=1))
    print(f"\nDone: {total_chapters} chapters. Manifest at data/manifest.json")


if __name__ == "__main__":
    main()
