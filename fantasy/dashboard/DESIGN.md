# Live week dashboard: design

Direction B, "Forecast desk" (picked 2026-10-19 from three mockups). Mood:
editorial data journalism, light paper, one large chart, a headline that the
data writes. Reference: FiveThirtyEight's NFL Predictions pages.

## Type

- Headings and the hero number: Source Serif 4 (600, 700)
- Body and labels: IBM Plex Sans (400, 500, 600)
- Numbers in tables and bars: IBM Plex Mono (500)

## Palette (five tokens)

| Token | Light | Dark | Use |
| --- | --- | --- | --- |
| `--paper` | `#FBFAF7` | `#16181B` | page surface |
| `--ink` | `#1C1F24` | `#ECEBE7` | text, heavy rules |
| `--mute` | `#6B6F76` | `#9A9EA5` | secondary text, axis labels |
| `--rule` | `#DEDBD3` | `#2C3036` | hairlines, grid |
| `--blue` | `#2F5D8A` | `#7FA6CF` | Chaos Legion, the one accent |

The rival team's bars use neutral gray `#8A8F98` so that the accent marks only
our side. Banked points are solid and expected remaining points are hatched:
the hatch is the secondary encoding, so the two never depend on color alone.

## Layout

- Spacing on an 8 px scale (8, 16, 24, 32, 40, 48, 56).
- One radius: 4 px, on bar ends only.
- No gradients or shadows. The hatch is the only pattern.
- Below 820 px the two-column grids stack into one column.
