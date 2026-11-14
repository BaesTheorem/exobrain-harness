# claytablet

Make a picture of a clay tablet from a transliterated cuneiform text.

The picture is a height field with one light, made with numpy. The command does
not use a photograph or an image model. Each sign comes from a cuneiform font,
and it is the sign that the transliteration names.

## Setup

```
bin/claytablet-setup
```

The command downloads two files into `assets/` (gitignored):

- `osl.asl` is the Oracc sign list. It gives the Unicode sign for each sign value. License: CC0.
- `Santakku.ttf` is an Old Babylonian cursive font by Sylvie Vanséveren, from the
  [Hethitologie Portal Mainz](https://hethport.net/cuneifont/). The font is free of charge. Its terms do not
  let a person change the font or sell it, thus the repo does not contain the file.

If the font is not there, the renderer uses Noto Sans Cuneiform from macOS. Python must have numpy, scipy and
Pillow.

## Commands

```
bin/cuneify examples/greeting.atf --back                 # ATF to Unicode cuneiform, with the sign names
bin/claytablet examples/greeting.atf -o out/greeting --rows 8
bin/claytablet letter.atf -o out/letter --stamp seal.png --scale-bar
```

`claytablet` writes one PNG for each face (`out/letter-obverse.png`, `out/letter-reverse.png`) and one picture
that shows all the faces (`out/letter.png`).

| Option | Effect |
| --- | --- |
| `--width N` | Tablet width in pixels (default 1000). The time for two faces is approximately 7 s at 500 and 40 s at 1200. |
| `--rows N` | Ruled rows on each face. The default is the number of lines on the longest face. |
| `--stamp PNG` | Push an image into the clay as a seal. The dark parts go deepest. The face must have empty rows at the bottom. |
| `--stamp-face NAME` | The section that gets the stamp (default `reverse`). |
| `--break-at X,Y,RX,RY` | A broken area on the first face, as fractions of the face. Use the option again for more areas. |
| `--scale-bar` | A centimeter scale below the tablets. `--width-cm` sets the width of the tablet in centimeters. |
| `--heights` | Write the height fields to `.npz` files also, for a mesh. |
| `--seed N` | A different seed gives different wear, stains and edges. |

## Input

The input is ATF, the transliteration format of [CDLI](https://cdli.earth). `@obverse` and `@reverse` start a
face. The sign values use the CDLI ASCII forms: `sz` for š, `s,` for ṣ, `t,` for ṭ, and a digit for the index
(`qi2` for qí). This command gets the ATF of a published tablet:

```
curl -s -H "Accept: application/json" \
  "https://cdli.earth/search?simple-value%5B%5D=BM+131236&simple-field%5B%5D=keyword" | jq -r '.[0].inscription.atf'
```

## Limits

- `cuneify` selects the sign that a value and its index name. It does not examine grammar or spelling.
- If the sign list does not contain a value, the command stops and shows that value.
- The relief is a top view. The tool does not make side views of the tablet.

## Tests

```
pytest tests/test_claytablet_cuneify.py
```
