# Curbside design

Direction: a photo grid with a map drawer. The reference is [are.na](https://www.are.na): quiet chrome, so the photos carry the page.

## Type

- Interface: Inter (variable, self-hosted in `static/vendor/fonts/`).
- Prices, distances, counts: IBM Plex Mono 400 and 600.

## Palette

The MD3 roles in `static/theme.css` come from the seed below through material-color-utilities (`SchemeTonalSpot`), light and dark. Five named tokens:

| Token | Role | Light |
| --- | --- | --- |
| Seed teal | `--primary` source, distance chip, clusters | `#00897B` (renders as `#006b5f`) |
| Ink | `--on-surface`, prices and titles | from the scheme |
| Paper | `--surface`, page background | from the scheme |
| Muted | `--on-surface-variant`, meta lines | from the scheme |
| Chip | `--secondary-container`, active filters | from the scheme |

## Rules

- Spacing is on an 8px scale (`--s1` to `--s4`).
- One border radius: 12px (`--radius`). Chips use 8px because they are 32px tall.
- No gradients and no shadows. `app.css` removes every Beer CSS shadow.
- Distance on a card is solid when it comes from a pin and muted when it is a ring band.
- On phones the filters are one row that scrolls, the map is a bottom sheet, and Map is a floating button.
