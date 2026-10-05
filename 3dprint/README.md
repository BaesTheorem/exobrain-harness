# 3dprint

Code-first 3D printing: design a part in Python or OpenSCAD, export it, check
that it will print, look at it, and estimate the print. No GUI in the loop.

## Toolchain

| Tool | Role | Install |
| --- | --- | --- |
| [build123d](https://build123d.readthedocs.io/) 0.13 | Primary modeler. B-rep CAD on OpenCascade: fillets, chamfers, sketches, threads, STEP in/out. | `requirements.txt` into `.venv` (Python 3.12) |
| [OpenSCAD](https://openscad.org/) snapshot + [BOSL2](https://github.com/BelfrySCAD/BOSL2) | Declarative CSG for quick parametric parts and the huge `.scad` ecosystem. Manifold backend renders in well under a second. | `brew install --cask openscad@snapshot`, BOSL2 cloned to `~/Documents/OpenSCAD/libraries` |
| [trimesh](https://trimesh.org/) + [manifold3d](https://github.com/elalish/manifold) + [pymeshfix](https://github.com/pyvista/pymeshfix) | Mesh inspection, repair, boolean, format conversion. | venv |
| `lib/sdfmesh.py` + [scikit-image](https://scikit-image.org/) | Signed distance field modelling: image silhouettes to heightfield reliefs, true 3D primitives, marching cubes in slabs, decimation, cleanup. For organic and image-traced parts that B-rep CAD handles badly. | venv |
| [f3d](https://f3d.app/) 3.5 | Headless renders of a mesh to PNG so the result can be inspected. | `brew install f3d` |
| [PrusaSlicer](https://www.prusa3d.com/prusaslicer/) 2.9 | Headless slicing for print time and filament estimates, plus `--info` manifold checks. | `brew install --cask prusaslicer` |
| [Blender](https://www.blender.org/) 5.2 | Studio renders (`cad render`): Cycles on the GPU, clay or the model's vertex colours. | `brew install --cask blender` |

`bin/cad-setup` installs or rebuilds all of it. `bin/cad info` prints versions.

## Commands

```
bin/cad build  examples/box_with_lid.py -p width=60     # build123d script -> STL + STEP + 3MF + check + preview
bin/cad scad   examples/cable_clip.scad -D cable_d=6    # OpenSCAD -> STL + check + preview
bin/cad check  out/box_with_lid/box_with_lid_box.stl    # printability report, exit 1 if not watertight or too big
bin/cad fix    broken.stl                               # repair normals/holes/duplicates
bin/cad view   part.stl --views iso,top,front,right     # contact sheet PNG
bin/cad view   part.stl --crop "y=150:197"              # close-up of one region
bin/cad slice  part.stl --layer 0.2 --infill 15         # PrusaSlicer estimate (generic profile)
bin/cad render part.glb --material color --up y         # Blender studio render; --material clay for form only
bin/cad convert part.stl part.3mf
```

Outputs land in `out/<name>/` (gitignored). Models that are worth keeping go in
`models/` (tracked). `printers.json` holds bed sizes for the fit check.

## Model script contract (build123d)

A script sets a module-level `result`: one Shape, or a dict of `name -> Shape`
for multi-part prints (each part gets its own STL and STEP, plus one combined
3MF). The CLI injects `PARAMS` (from `-p name=value`) before the script runs, so
`P.update(PARAMS)` after a defaults dict makes each model parametric from the
command line. See `examples/box_with_lid.py`.

## Printing on a Bambu Lab printer

PrusaSlicer has no Bambu profiles. Use `cad slice` for a ballpark time and
filament figure, then open the STL or 3MF in Bambu Studio (or OrcaSlicer) for
the final slice and send.
