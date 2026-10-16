"""Brow plate for a Beast (Over the Garden Wall) mask: holds two puck lights as eyes.

The plate sits inside a spandex face mask at brow height. Each puck sits outside the
fabric on a flat pad, held by two magnets in the pad and two magnets (or steel discs)
stuck to the back of the puck. Slots at each end take zip ties to a cap or an elastic strap.

Print standing on its bottom edge (the arc lies on the bed): no supports, the magnet
pockets are short horizontal holes. Run: bin/cad build models/beast_brow_plate.py
"""

import math

from build123d import (
    Align,
    Axis,
    Box,
    BuildPart,
    BuildSketch,
    Cylinder,
    Location,
    Locations,
    Mode,
    Polygon,
    Pos,
    Rot,
    chamfer,
    extrude,
)

P = {
    "head_r": 95.0,  # horizontal radius of the forehead curve, foam padding included
    "band_t": 4.0,  # band wall thickness
    "height": 72.0,  # band height (Z when printed)
    "span_deg": 56.0,  # band reaches this far either side of centre
    "puck_d": 68.6,  # LED puck diameter (2.7 in)
    "pad_r": 101.0,  # distance from head centre to each flat pad face
    "eye_deg": 24.0,  # each pad's angle off the centre line
    "magnet_d": 12.0,  # disc magnet diameter
    "magnet_h": 3.0,  # disc magnet thickness
    "magnet_dx": 20.0,  # magnet offset from pad centre, along the pad
    "slot_w": 4.0,
    "slot_h": 16.0,
}
P.update(PARAMS)  # noqa: F821  # pyright: ignore[reportUndefinedVariable] - injected by `cad build`

R, T, H = P["head_r"], P["band_t"], P["height"]
pad_w = P["puck_d"] + 2.0
mag_d = P["magnet_d"] + 0.3  # press fit plus a drop of glue
mag_h = P["magnet_h"] + 0.2


def radial(angle_deg: float, dist: float) -> Location:
    """Location at angle_deg off +Y (forward), dist from the head centre, local Y pointing outward."""
    a = math.radians(angle_deg)
    return Location((dist * math.sin(a), dist * math.cos(a), 0), (0, 0, -angle_deg))


with BuildPart() as plate:
    # Band: a ring segment around the forehead.
    Cylinder(R + T, H, align=(Align.CENTER, Align.CENTER, Align.MIN))
    Cylinder(R, H, align=(Align.CENTER, Align.CENTER, Align.MIN), mode=Mode.SUBTRACT)
    # Keep only the front wedge of +-span_deg.
    reach = 2 * (R + T + 10)
    a = math.radians(P["span_deg"])
    with BuildSketch() as wedge:
        Polygon((0, 0), (reach * math.sin(a), reach * math.cos(a)), (reach, reach),
                (-reach, reach), (-reach * math.sin(a), reach * math.cos(a)), align=None)
    extrude(wedge.sketch, amount=H, mode=Mode.INTERSECT)

    # Flat pads, one per eye, so a flat puck seats without rocking on the curve.
    pad_depth = P["pad_r"] - (R - 12)
    for side in (1, -1):
        with Locations(radial(side * P["eye_deg"], P["pad_r"])):
            Box(pad_w, pad_depth, H, align=(Align.CENTER, Align.MAX, Align.MIN))
    Cylinder(R, H, align=(Align.CENTER, Align.CENTER, Align.MIN), mode=Mode.SUBTRACT)

    # Magnet pockets in each pad face.
    for side in (1, -1):
        pad = radial(side * P["eye_deg"], P["pad_r"])
        for dx in (-P["magnet_dx"], P["magnet_dx"]):
            # Rot(90) turns the cylinder axis to local -Y, so MIN alignment cuts inward.
            with Locations(pad * Pos(dx, 0, H / 2) * Rot(90, 0, 0)):
                Cylinder(mag_d / 2, mag_h, align=(Align.CENTER, Align.CENTER, Align.MIN),
                         mode=Mode.SUBTRACT)

    # Zip-tie slots near each end, one high and one low.
    for side in (1, -1):
        end = radial(side * (P["span_deg"] - 6), R + T / 2)
        for z in (H * 0.25, H * 0.75):
            with Locations(end * Pos(0, 0, z)):
                Box(P["slot_w"], 3 * T, P["slot_h"], mode=Mode.SUBTRACT)

    # Soften the edge that touches the bed and the edges a hand meets.
    chamfer(plate.edges().filter_by(Axis.Z), length=0.6)

result = plate.part
