# Curbside design

Direction: a photo grid with a map drawer. The layout reference is [are.na](https://www.are.na): quiet chrome, so the photos carry the page. The colors are Facebook's.

## Type

- Interface: Inter (variable, self-hosted in `static/vendor/fonts/`).
- Prices, distances, counts: IBM Plex Mono 400 and 600.

## Palette

Facebook's own palette, at Alex's request (2026-10-24). `static/theme.css` copies the values from the CSS variables that facebook.com serves in `.__fb-light-mode` and `.__fb-dark-mode`, and maps the MD3 roles onto them. Five named tokens:

| Token | Facebook variable | Light | Dark |
| --- | --- | --- | --- |
| Blue | `primary-button-background` | `#1B74E4` | `#2374E1` |
| Text | `primary-text` | `#050505` | `#E4E6EB` |
| Wash | `web-wash` (page) | `#F0F2F5` | `#18191A` |
| Card | `card-background` (header, sheets) | `#FFFFFF` | `#242526` |
| Muted | `secondary-text` | `#65676B` | `#B0B3B8` |

Tags use Facebook's `positive` green for price drops, `negative` for a shared photo, and `warning` for pending.

## Rules

- Spacing is on an 8px scale (`--s1` to `--s4`).
- One border radius: 12px (`--radius`). Chips use 8px because they are 32px tall.
- No gradients and no shadows. `app.css` removes every Beer CSS shadow.
- Distance on a card is solid when it comes from a pin and muted when it is a ring band.
- On phones the filters are one row that scrolls, the map is a bottom sheet, and Map is a floating button.
- Theme: automatic (follows the system), light, or dark, from the half-circle button. The choice stays in localStorage. The map changes to the OpenFreeMap `dark` style with the page.
- Tags on a card: price drop (primary), Relisted (secondary container), Shared photo (error container), Pending (tertiary container), Dealer (neutral).
