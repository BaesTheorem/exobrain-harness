# Live week dashboard: design

Direction A, "Scorebug" (picked 2026-10-19). Mood: TV broadcast graphics,
dark, dense, numbers first. Reference: ESPN Gamecast's win-probability strip
and network score bugs. The page keeps the data-written headline from
direction B, shown as a broadcast lower third (the chyron).

Changed the same evening: Alex first picked B ("Forecast desk": Source Serif 4
and IBM Plex, paper `#FBFAF7`, ink blue `#2F5D8A`), saw it live, then asked
for A's look. B's headline and "what would change this" note stayed.

## Type

- Scores, labels, headings, tables: Barlow Condensed (500, 600, 700)
- Body and small text: Inter (400, 500, 600)

## Palette (five tokens)

| Token | Value | Use |
| --- | --- | --- |
| `--bg` | `#0E1013` | page surface |
| `--panel` | `#171A1F` | cards, score bug, ticker |
| `--ink` | `#F2F2F0` | text, the chyron surface |
| `--mute` | `#8B9099` | secondary text, axis labels |
| `--red` | `#E5383B` | Chaos Legion, the one accent |

Support colors, not tokens: hairline `#262A31`, bar track `#22262C`, and the
rival team's bars in steel `#C9C2B8`, so that the accent marks only our side.
Banked points are solid and expected remaining points are hatched: the hatch
is the secondary encoding, so the two never depend on color alone.

Dark only. A score bug is a dark-surface form, and there is no light theme.

## Layout

- Spacing on an 8 px scale (8, 16, 24); 2 px gaps between ticker cells.
- One radius: 0. Square corners throughout, the broadcast look.
- No gradients or shadows. The only fills are the 12% red area under the
  win-probability line and the hatch.
- Below 980 px the grid is one column; below 640 px the win-probability box
  moves above the two scores.
