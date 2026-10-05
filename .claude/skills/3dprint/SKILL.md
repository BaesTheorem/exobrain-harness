---
name: 3dprint
description: "Design 3D-printable parts in code and get them ready to print: build123d (Python B-rep CAD) or OpenSCAD + BOSL2 for the model, trimesh/pymeshfix for checks and repair, f3d for preview renders, PrusaSlicer for time and filament estimates, and the Console's inline 3D viewer to show the result. Use when Alex says 'design a part', '3D print', 'make an STL', 'model this', 'print a bracket/clip/holder/case/mount', 'fix this STL', 'is this printable', 'how long will this print', 'convert to 3MF', names a .stl/.3mf/.step/.scad file, or mentions the Bambu or the other printer."
metadata:
  toolkit: "/Users/alexhedtke/Documents/Exobrain harness/3dprint (bin/cad, bin/cad-setup, README.md)"
  venv: "3dprint/.venv (Python 3.12: build123d 0.13, trimesh 5, manifold3d, pymeshfix, lxml)"
  apps: "OpenSCAD snapshot (brew cask openscad@snapshot, manifold backend), PrusaSlicer 2.9 (cask), f3d 3.5 (formula), BOSL2 in ~/Documents/OpenSCAD/libraries"
  console: "![name](/abs/path.stl|3mf|obj|glb) renders an orbitable 3D viewer in the MIST Console (static/model.js)"
---

# /3dprint

Parts are code. A model is a Python script (build123d) or a `.scad` file, the CLI
exports it, checks that it will print, renders it, and the Console shows it as a
model Alex can orbit. No GUI in the loop until the final slice. Read
`3dprint/README.md` for the command list and the model script contract.

## The loop

1. **Pin the numbers before modelling.** Ask for or measure the dimensions that
   matter (the thing it must hold, the hole it must clear, the surface it mounts
   to). Write them as the defaults dict at the top of the script, in mm.
2. **Model.** `bin/cad build models/<name>.py -p key=value` for build123d, or
   `bin/cad scad models/<name>.scad -D key=value` for OpenSCAD. Both write STL
   (plus STEP and 3MF for build123d), run the printability check and render a
   four-view contact sheet to `out/<name>/`.
3. **Look at it.** Read the PNG contact sheet yourself, then embed the model in
   the reply so Alex can turn it: `![name](/Users/alexhedtke/Documents/Exobrain harness/3dprint/out/<name>/<name>.stl)`,
   path raw with literal spaces. The caption shows measured size and triangle
   count. Embed the STL, not the PNG, unless a view needs calling out.
4. **Read the check.** `cad check` prints size, volume, mass, watertight,
   bodies, bed contact, overhang share, and whether it fits the printer. It
   exits 1 when the part is not watertight or does not fit. Fix the model, not
   the mesh, when the cause is in the design. `cad fix` (pymeshfix) is for
   meshes from elsewhere.
5. **Estimate.** `cad slice <stl> --layer 0.2 --infill 15 [--supports]` gives
   print time and grams through PrusaSlicer with a generic profile.
6. **Hand off.** The house printer is a housemate's Bambu Lab; PrusaSlicer has
   no profile for it. Give Alex the STL or 3MF (the Console's download button
   on the viewer) and say to slice it in Bambu Studio. The `bambu` profile in
   `printers.json` is unconfirmed (256 mm bed assumed).

## Design rules that keep parts printable

- Flat face down, biggest face on the bed. Design the part around its print
  orientation, and say which face is down.
- Overhangs over 45 degrees need supports, or a chamfer instead of a fillet on
  the underside. Bridges under 30 mm are fine. Holes print better when the top
  is a teardrop or has a 45 degree roof.
- Walls are multiples of the 0.4 mm line: 0.8, 1.2, 1.6, 2.0 mm. Floors and
  roofs are multiples of the 0.2 mm layer.
- Fits in PLA: 0.2 mm per side for a friction fit, 0.3 to 0.4 mm for a slide,
  0.5 mm for a loose fit. Horizontal holes come out about 0.2 mm small.
- Vertical outer edges get a small fillet or chamfer (0.5 to 1 mm) for the
  hand. The first layer gets a 0.5 mm chamfer to beat elephant's foot.
- Text and small features: embossed text 0.6 mm tall and 1.2 mm wide minimum.
- Split anything that cannot print cleanly as one piece and return a dict of
  parts from the script so each gets its own STL.

## build123d notes

- Prefer the builder API (`BuildPart`, `BuildSketch`, `BuildLine`) with
  `Locations`, `Mode.SUBTRACT`, `fillet`, `chamfer`, `offset` for shelling.
  Select with `.edges().filter_by(Axis.Z)`, `.faces().sort_by(Axis.Z)[-1]`.
- Hollow a box with `offset(amount=-wall, openings=<top face>)`.
- Threads: `build123d` has `IsoThread` in `bd_warehouse` (not installed). For a
  threaded cap, ask before adding the dependency; a bayonet or friction fit
  usually wins for a print.
- STEP export keeps the exact geometry for later edits; keep it next to the
  STL for anything that may be revised.
- Docs: https://build123d.readthedocs.io/ . Cheat sheet in the docs under
  "Cheat Sheet"; `help(build123d.X)` works in the venv.

## OpenSCAD notes

- Always `include <BOSL2/std.scad>`; `cuboid`, `cyl`, `ycyl`, `tube`,
  `prismoid` with `rounding`, `chamfer`, `anchor`, `orient`, `spin` cover most
  parts, and `attach()` places children on faces without arithmetic.
- `$fn = 64` for round parts, 128 for anything the hand touches.
- The CLI always runs the manifold backend, which is fast and exact. A WARNING
  line from OpenSCAD is printed with the result.

## Showing work in the Console

`![label](/abs/path.stl)` (also .3mf, .obj, .glb, .gltf) becomes an inline
turntable viewer: drag orbits, wheel zooms, double-click resets, a wireframe
toggle and a Save to Downloads button sit on the frame, and a share snapshot
captures the current view as an image. The file must live under the harness
root (`3dprint/out/` qualifies). Write the path raw, never percent-encoded.
Embed each part of a multi-part print separately.

## Gotchas

- `3dprint/out/` and `.venv/` are gitignored. Models worth keeping go in
  `3dprint/models/` and get committed.
- trimesh needs `networkx` for hole filling and `lxml` for 3MF; both are in
  `requirements.txt`. `bin/cad-setup` rebuilds the venv and installs the apps.
- `cad fix` output replaces fine detail at a hole's edge with a flat patch.
  Check the result in the viewer before printing.
- The mass line assumes solid PLA (1.24 g/cm3). `cad slice` gives the real
  figure for the chosen infill.
- OpenSCAD 2021.01 (the stable cask) lacks manifold and is three orders of
  magnitude slower. Stay on `openscad@snapshot`.
