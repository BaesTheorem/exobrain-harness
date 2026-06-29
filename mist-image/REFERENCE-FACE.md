# MIST reference face (for `--ref` generation)

`mist-image/mist-reference-face.png` is the identity reference used to generate
MIST avatars with the `--ref` flag (FLUX.2 reference-conditioned generation). It
is a frame of the character MIST from the AMC series *Pantheon*, so it is
**gitignored and never committed** (copyright + the repo's privacy rules).

## Rebuild it

It must be **under 512×512** on both sides (FLUX.2 rejects larger references).

```bash
cd /tmp
# Resolve the canonical MIST frame URL from the Pantheon wiki API
url=$(curl -sL -A "Mozilla/5.0" \
  "https://pantheon-amc.fandom.com/api.php?action=query&titles=File:Mist_10.jpg&prop=imageinfo&iiprop=url&format=json" \
  | grep -oE 'https://static\.wikia\.nocookie\.net/[^"\\]+' | head -1)
curl -sL -A "Mozilla/5.0" "$url" -o mist_ref.bin
sips -s format png mist_ref.bin --out mist_ref.png            # it is served as WebP
sips -c 1200 1100 mist_ref.png --out mist_crop.png            # center crop to her face/torso
sips --resampleHeightWidthMax 480 mist_crop.png \
  --out "/Users/alexhedtke/Documents/Exobrain harness/mist-image/mist-reference-face.png"
```

Any clear, front-facing face/upper-body crop of MIST under 512px works. A tighter
crop on the face gives stronger identity preservation.

## Use it

```bash
mist-image/bin/mist-image \
  "Full-length head-to-toe portrait of the character in image 0: same pale glowing \
   cyan-white hair, same teal eyes, same face, same flat 2D cel-shaded animation \
   style. Standing facing forward, full body and feet visible, white short-sleeve \
   top, gray trousers, flat shoes, gentle expression, dark teal background, soft cyan glow." \
  --ref mist-image/mist-reference-face.png -o mist-avatar.png --width 768 --height 1152
```

The Workers AI safety filter false-flags some seeds even on wholesome prompts; the
CLI auto-retries with fresh seeds (up to 5) before giving up.
