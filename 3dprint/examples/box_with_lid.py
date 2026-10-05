"""Parametric box with a friction-fit lid. Run: bin/cad build examples/box_with_lid.py -p width=60

Shows the conventions a model script follows:
  - defaults in a dict, overridden by PARAMS from the CLI
  - build with BuildPart, one solid per part
  - set `result` to a dict of name -> Part so each part gets its own STL
"""

from build123d import (
    Align,
    Axis,
    Box,
    BuildPart,
    Locations,
    Mode,
    fillet,
    offset,
)

P = {
    "width": 50.0,  # outer X
    "depth": 30.0,  # outer Y
    "height": 20.0,  # outer Z of the box body
    "wall": 1.6,  # 4 perimeters at 0.4 mm
    "lid_height": 6.0,
    "clearance": 0.2,  # per side, friction fit on PLA
    "corner": 3.0,
}
P.update(PARAMS)  # noqa: F821 - injected by `cad build`

w, d, h, t = P["width"], P["depth"], P["height"], P["wall"]

with BuildPart() as box:
    Box(w, d, h, align=(Align.CENTER, Align.CENTER, Align.MIN))
    fillet(box.edges().filter_by(Axis.Z), radius=P["corner"])
    # hollow out from the top face, leaving the floor
    offset(amount=-t, openings=box.faces().sort_by(Axis.Z)[-1])

with BuildPart() as lid:
    # cap the same footprint, then add an inner lip that drops into the box
    Box(w, d, t, align=(Align.CENTER, Align.CENTER, Align.MIN))
    fillet(lid.edges().filter_by(Axis.Z), radius=P["corner"])
    lip_w = w - 2 * t - 2 * P["clearance"]
    lip_d = d - 2 * t - 2 * P["clearance"]
    with Locations((0, 0, t)):
        Box(lip_w, lip_d, P["lid_height"] - t, align=(Align.CENTER, Align.CENTER, Align.MIN))
        Box(lip_w - 2 * t, lip_d - 2 * t, P["lid_height"] - t,
            align=(Align.CENTER, Align.CENTER, Align.MIN), mode=Mode.SUBTRACT)

result = {"box": box.part, "lid": lid.part}
