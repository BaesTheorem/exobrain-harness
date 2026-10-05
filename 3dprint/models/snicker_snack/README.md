# Snicker-Snack

A pencil-length replica of Snicker-Snack, the vorpal greatsword with the rose
pommel from Dungeons & Dragons. The two faces are sculpted. A loop on top of
the rose lets it hang on a necklace chain or a keychain.

The quillon extends into the third axis. The painted crossguard is turned 90
degrees about the blade and joined to itself, so the guard is a cross when you
look down the blade, and each of its four sides shows the painted artwork.
Thus the guard protects the hand on all four sides. The hanging claw tendrils
stay adjacent to the collar, as in the painting, because they hold onto the collar
and not onto the guard.

The model comes from one front-view painting. The script `build.py` traces the
painting, makes the silhouette symmetric, and adds the depth. Its docstring
gives the method.

## Dimensions

| Feature | Size |
| --- | --- |
| Tip to rose top | 189 mm |
| Overall, with the loop | 42.6 x 194.5 x 42.5 mm |
| Blade | 7 to 10 mm wide, 2.5 to 2.7 mm thick through the middle, 0.9 mm edges |
| Crossguard | 42.6 x 42.5 mm, a cross of the painted guard |
| Rose pommel | 12 mm across, circular |
| Loop | 3.6 mm hole, 7.2 mm outer diameter, 3 mm wide |
| Mass | approximately 7.6 g of PLA, solid |

The loop's hole runs parallel to the crossguard. A chain through it holds the
sword face-on against the chest. A jump ring is not necessary. Put the chain
directly through the loop.

## Printing

There are two methods. `bin/cad build` makes the files for each:

1. **Six-piece kit (recommended for FDM).** `snicker_snack_kit.3mf` holds six
   pieces, each lying flat on a cut face, so no piece needs supports:
   - the body (blade, painted guard, grip, rose, loop) cut at the mid-plane
     into a front half and a back half;
   - the front arm and the back arm of the turned guard, each cut into a left
     half and a right half.

   Assembly:
   1. Push a short piece of 1.75 mm filament into each of the two pin holes
      (rose and lower gem). Bond the two body halves with CA glue.
   2. Bond the two halves of each arm along their flat faces.
   3. Bond each arm to the middle of its face of the guard. The root of the
      arm has the shape of the guard surface, so it fits in one position only.
2. **One piece.** `snicker_snack.3mf` is the full sword. A cross-shaped guard
   has no flat side, so this method needs supports. A resin printer is better
   for this method.

Suggested settings: 0.12 mm layers, 0.4 mm nozzle, PLA, 100% infill (the parts
are thin, so infill is mostly walls). PrusaSlicer, with its generic printer
settings, gives 44 minutes and 3.1 g for each body half and 6 minutes and
0.3 g for each arm half. It reports low bed adhesion on the body halves, so
add a brim. A Bambu Lab printer is faster. Slice in Bambu Studio for accurate
numbers.

## Rebuild

The reference painting is not in the repo. Put a front-view image of the sword
on a white background at `reference/snicker_snack.png`, then:

```
bin/cad build models/snicker_snack/build.py                                        # one piece + coloured preview
bin/cad build models/snicker_snack/build.py -p variant=kit --name snicker_snack_kit
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
