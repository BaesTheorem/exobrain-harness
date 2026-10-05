// Adhesive-mount cable clip. Run: bin/cad scad examples/cable_clip.scad -D cable_d=6
// Uses BOSL2 (installed in ~/Documents/OpenSCAD/libraries by cad-setup).
include <BOSL2/std.scad>

cable_d = 5;      // cable diameter, mm
wall    = 2;      // clip wall
width   = 10;     // along the cable
base_t  = 1.5;    // adhesive pad thickness
gap     = 0.75;   // opening as a fraction of cable_d (0..1), cable snaps in

$fn = 64;

r_in  = cable_d / 2;
r_out = r_in + wall;

// adhesive pad
cuboid([2 * r_out + 6, width, base_t], anchor=BOTTOM, rounding=1, edges="Z");

// C-shaped ring on top of the pad, open at the top
up(base_t)
  difference() {
    up(r_out) ycyl(r=r_out, h=width, anchor=CENTER);
    up(r_out) ycyl(r=r_in, h=width + 1, anchor=CENTER);
    // the opening
    up(r_out + r_in) cuboid([cable_d * gap, width + 1, r_out * 2], anchor=BOTTOM + FWD, orient=UP, spin=0)
      ;
  }
