# Snicker-Snack

A pencil-length replica of Snicker-Snack, the vorpal greatsword with the rose
pommel from Dungeons & Dragons. The two faces are sculpted. A loop on top of
the rose lets it hang on a necklace chain or a keychain.

The model comes from one front-view painting. The script `build.py` traces the
painting, makes the silhouette symmetric, and adds the depth. Its docstring
gives the method.

## Dimensions

| Feature | Size |
| --- | --- |
| Tip to rose top | 189 mm |
| Overall, with the loop | 42.6 x 194.5 x 12.1 mm |
| Blade | 7 to 10 mm wide, 2.5 to 2.7 mm thick through the middle, 0.9 mm edges |
| Crossguard | 42.6 mm wide, 5.5 mm thick at the lower gem |
| Rose pommel | 12 mm across, circular |
| Loop | 3.6 mm hole, 7.2 mm outer diameter, 3 mm wide |
| Mass | approximately 6 g of PLA, solid |

The loop's hole runs parallel to the crossguard. A chain through it holds the
sword face-on against the chest. A jump ring is not necessary. Put the chain
directly through the loop.

## Printing

There are two methods. `bin/cad build` makes the files for each:

1. **Two halves (recommended for FDM).** `snicker_snack_halves.3mf` holds the
   front and back halves cut at the mid-plane, each lying cut face down. They
   print without supports, and the two sculpted faces print as clean top
   surfaces. Push a short piece of 1.75 mm filament into each of the two pin
   holes (rose and lower gem). Then bond the halves with CA glue.
2. **One piece.** `snicker_snack.3mf` is the full sword. When it lies flat,
   only the rose touches the bed. Thus it needs tree supports, and the bottom
   face shows their marks. A resin printer is better for this method.

Suggested settings: 0.12 mm layers, 0.4 mm nozzle, PLA, 100% infill (the parts
are thin, so infill is mostly walls). PrusaSlicer, with its generic printer
settings, gives 42 minutes and 3 g for each half. A Bambu Lab printer is
faster. Slice in Bambu Studio for accurate numbers.

## Rebuild

The reference painting is not in the repo. Put a front-view image of the sword
on a white background at `reference/snicker_snack.png`, then:

```
bin/cad build models/snicker_snack/build.py                                        # one piece + coloured preview
bin/cad build models/snicker_snack/build.py -p variant=halves --name snicker_snack_halves
.venv/bin/python models/snicker_snack/build.py stage=2d                            # 2D maps only, 2 s
```

`out/snicker_snack/analysis/relief.png` (shaded front face) and `regions.png`
(blade, fuller, pockets, gems) show the 2D design before the meshing step.

Snicker-Snack and its art belong to Wizards of the Coast. This is a fan-made
model for personal use.
