# ttrpg-memorial

Renders a memorial card for a retired tabletop character: portrait, class line, a stat grid,
their ideal and personality, what they carried, and a timeline of the campaign. Pure Pillow,
styled as Material Design 3 in the house flat/sharp skin.

Everything visual comes from the assets library at `~/Documents/material-design`:

- **Color:** `palette.ts` runs the vendored `material-color-utilities` (Celebi quantizer, Score,
  `SchemeTonalSpot`, dark) on the portrait's pixels, so the card's tonal roles are seeded by the art.
- **Type:** Roboto variable (`fonts/Roboto.ttf`) on the MD3 type scale.
- **Icons:** Material Symbols Sharp from `material-design-icons/variablefont/`.

## Usage

```bash
python3 memorial_card.py card.json -o card.png [--pdf card.pdf]
```

Needs Pillow and Node (`npx tsx` runs the color engine). Keep `card.json` next to the portrait,
outside this repo: it names real players and GMs.

## card.json fields

| Field | What |
|---|---|
| `portrait` | Image path, relative to the JSON |
| `campaign`, `name`, `full_name`, `class_line`, `summary` | Header text |
| `stats` | `[{icon, value, label}]`, drawn 3 per row. `icon` is a Material Symbols name |
| `ideal` | One-line quote in the tonal card |
| `personality` | `[[label, text], ...]` |
| `groups` | `[{title, icon, items}]` chip groups. Prefix an item with `~` to dim it (lost or dead) |
| `chip_note` | Optional line under the chips, e.g. what dimming means |
| `timeline` | `[{icon, when, text}]`, split across two columns |
| `credits` | `[[label, value], ...]` footer |
