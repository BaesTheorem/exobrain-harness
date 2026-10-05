# Snicker-Snack

A pencil-length replica of Snicker-Snack, the vorpal greatsword with the rose
pommel from Dungeons & Dragons. The two faces are sculpted. A loop on top of
the rose lets it hang on a necklace chain or a keychain.

The quillon is a thorny mass, like a rose bush. Each painted vine of the
guard becomes a round cane, as thick as it is wide, so the face keeps the
painted outline. Around it, 46 grown bramble canes curl in all directions
in a rounded volume, with side shoots and hooked rose prickles. A small
clear tunnel in front of each gem keeps the gems in view.

## Dimensions

| Feature | Size |
| --- | --- |
| Tip to rose top | 189 mm |
| Overall, with the loop | 41.3 x 194.5 x 27.8 mm |
| Blade | 7 to 10 mm wide, 2.5 to 2.7 mm thick through the middle, 0.9 mm edges |
| Crossguard | 41.3 mm wide, a thorn thicket 27.8 mm deep |
| Rose pommel | 12 mm across, circular |
| Loop | 3.6 mm hole, 7.2 mm outer diameter, 3 mm wide |
| Volume | 5.7 cm3 (approximately 6.3 g of resin, 7.1 g of PLA) |

The loop's hole runs parallel to the crossguard. A chain through it holds the
sword face-on against the chest. A jump ring is not necessary. Put the chain
directly through the loop.

## Printing

Print `snicker_snack.3mf` (or the STL) in one piece.

- **Resin (recommended).** The canes are 0.9 to 1.8 mm thick and go in all
  directions, and a resin printer can make canes that thin. Tilt the sword in the
  slicer and let it add supports.
- **FDM with tree supports.** Possible, but the supports touch many canes and
  the center of the thicket stays rough.

A cut through the thicket at a plane leaves loose arcs of cane in each half.
Thus, you cannot cut this guard into halves that print without supports. The build refuses
`-p variant=halves` for that reason.

## Rebuild

The reference painting is not in the repo. Put a front-view image of the sword
on a white background at `reference/snicker_snack.png`, then:

```
bin/cad build models/snicker_snack/build.py                                        # one piece + coloured preview
.venv/bin/python models/snicker_snack/build.py stage=2d                            # 2D maps only, 2 s
```

`out/snicker_snack/analysis/relief.png` (shaded front face) and `regions.png`
(blade, fuller, pockets, gems) show the 2D design before the meshing step.

Studio renders (Blender, Cycles on the GPU), from the coloured preview:

```
bin/cad render out/snicker_snack/snicker_snack_preview.glb --material color --up y
bin/cad render out/snicker_snack/snicker_snack_preview.glb --material clay --up y --focus 0,160,0 --frame 74 --azimuth -60 --elevation 18
```

Snicker-Snack and its art belong to Wizards of the Coast. This is a fan-made
model for personal use.
