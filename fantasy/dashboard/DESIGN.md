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
In another team's game (the ticker cells are tabs) the accent marks the
home side, the left half of the score bug. Banked points are solid and expected remaining points are hatched: the hatch
is the secondary encoding, so the two never depend on color alone.

Dark only. A score bug is a dark-surface form, and there is no light theme.

## Layout

- Spacing on an 8 px scale (8, 16, 24); 2 px gaps between ticker cells.
- One radius: 0. Square corners throughout, the broadcast look.
- No gradients or shadows. The only fills are the 12% red area under the
  win-probability line and the hatch.
- Below 980 px the grid is one column; below 640 px the win-probability box
  moves above the two scores.

## Both sides of the win probability

- Score bug center: two halves, the left team's chance on red and the right
  team's on steel, over a 6 px bar split at the left team's chance.
- Chart: one line on a centered scale. The 50% line is the middle; the left
  team's chance runs up to 100% at the top, the right team's down to 100% at
  the bottom. The area between the line and 50% fills red above and steel
  below. Each end of the axis carries that team's picture and name. The last
  point is the live value, so the chart ends where the score bug reads.

## The Wire (added 2026-10-22)

The third tab, between SCORES and CHAT, for the other twelve teams. Same
tokens, type and square corners; nothing new in the palette.

- Chyron: the tag reads `WEEK N · PICK P OF 13`; the text is the most urgent
  line (trades in review first, then the count of rival moves in 48 hours).
- Cards: IN FLIGHT (our claims with their odds, offers, trades in review),
  MIST READ (the brief from `rival-scan`, labels in steel), ON WAIVERS (each
  player with the league's claim rate and the rivals with the same need),
  WAIVER ORDER AND NEEDS (a table in priority order; tap a row to filter the
  history), EVERY MOVE (the full history, grouped by week, 60 rows and then
  SHOW MORE, with filter chips and a team picker).
- Red stays ours: our team's row, our moves' badges, our claims. Other teams'
  badges sit on the bar track; a trade in review is the one ink-on-light
  badge, because it is the one time-limited thing on the tab.
- The tab's dot counts rival moves since the tab was last open
  (localStorage `sb-wire-seen`), like the chat's unread dot.
- Below 980 px the cards stack, and the board drops TIER, ADDS and K/DST.
  Below 640 px it also drops W-L and SEEN, and each move wraps to two lines.

## Pictures and numbers

- Team pictures: the league's own logos, served through `/logo/<team id>`
  because custom uploads on ESPN's image host need the league cookies. Square
  crops: 64 px in the score bug, 20 px in the tabs, 18 px in the season table.
- Jersey numbers: muted `#NN` after the name, from ESPN's public athlete API.
