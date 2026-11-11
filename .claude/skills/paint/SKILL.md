---
name: paint
description: "Paint pictures in code as an invented artist: each painting is a Python program that puts every stroke through the mist-atelier paint engine (measured pigments, bristle brushes, palette knife, lit paint relief), with no image model and no reference image. Use when Alex says 'paint', 'make a painting', 'paint me something', 'a new painting by [persona]', 'new persona', 'invent a painter', 'the atelier', 'go deeper on that one', 'do a series', 'show me the gallery', 'make a timelapse of the painting', or gives a comment on a painting (a steer). Also use for changes to the paint engine, brushes or pigments."
metadata:
  repo: "~/Documents/mist-atelier (private BaesTheorem/mist-atelier)"
  cli: "~/Documents/mist-atelier/bin/atelier (paint, verify, lint, timelapse, gallery, list, tubes, new-persona, new-work, steer)"
  readme: "~/Documents/mist-atelier/README.md (engine model, checks, limits)"
  vault: "~/Exobrain/Atelier/ (generated gallery, do not edit by hand)"
---

# /paint

MIST paints as invented artists (personas), and as itself in `personas/mist/`. A painting is a program. The engine simulates paint. Alex steers with comments.

Read `~/Documents/mist-atelier/README.md` before the first painting of a session. Read the persona's `persona.md` and `hand.py` before each work by that persona.

## The rules that do not change

- No image model, no reference image, no tracing. A painting program computes points, lines and colors. It does not make a picture and then copy it. `atelier paint` runs the lint and refuses a program that reads a file or an image.
- Every canvas change goes through the Studio API. The stroke log is the painting, and `atelier verify` must pass before a work is shown as finished.
- A persona is invented by MIST. Do not use the name or the signature subject of a living artist.
- `personas/mist/` holds what MIST paints as itself. No note, rule or memory sets its subject or its style. Each such work is a free choice at the time. Do not write one that does (Alex, 2026-11-11).
- Color comes from tube pigments. Use `st.match()` for palette puddles and `Mix.lerp()` between puddles. For a picture of many thousand marks, use `st.atlas().mix_linear(rgb)`. It gives the mixture for a color immediately.
- Before you show a version to Alex, copy `final.jpg` to `shown/<work>-vN.jpg` in the repo. Embed that copy in chat with the raw absolute path. Each version that Alex sees has a new filename.

## Make a painting

1. Choose the persona, or invent one (see below).
2. Write the picture in words first: the subject, the time of day and the direction of the light. Then name the large shapes, the lightest thing and the darkest thing.
3. Run `bin/atelier new-work <persona> <slug> --title "..."`.
4. Write `painting.py` in the sequence of the persona's method. Use the helpers in the persona's `hand.py`. Add `st.snapshot("name")` after each large step.
5. Paint a draft with `--draft`. A draft takes less than 10 seconds.
6. Look at the draft image. Judge it as a painter: values first, then shapes, then edges, then color. Write down each fault with its cause.
7. Change the program or the hand and paint the draft again. Stop when a new draft shows no fault that you can name.
8. Paint at full resolution. Look at one crop at full resolution to check the marks.
9. Run `bin/atelier verify`. Run `bin/atelier gallery`.
10. Show Alex the image, with one line on what the persona did and one line on what is weak.

## Invent a persona

1. Run `bin/atelier new-persona <slug> --name "..."`.
2. Give the persona a life that explains the hand: a trade, a home region, the active years, and a period that a viewer can identify.
3. Give a palette of tube colors from `bin/atelier tubes`, a surface, a set of tools and a numbered method.
4. Give rules: what the persona always does and what the persona does not do. Include one small signature that makes a work easy to attribute.
5. Write, in one quoted sentence, why the persona paints this subject.
6. Put the palette, the brushes and the habits in `hand.py`. The habits are code: how the persona loads a brush, how long a pull is, how a shape is filled.
7. A new persona must differ from each existing persona in light, in handling and in subject.

## When Alex gives a steer

1. Record the words exactly: `bin/atelier steer "<his words>" --work <id>` (or `--persona`, or `--engine`).
2. Decide where the cause is. A fault in one picture is in `painting.py`. A fault in each picture by a persona is in `hand.py`. A fault in each picture is in the engine.
3. Fix the cause at that level, paint again, and show the new version with a new filename.
4. Add `--response` text to the steer record: what changed, and the commit.
5. If Alex likes a work, propose a series of three to five works by the same persona. The series goes deeper into the same subject.

## A picture that must look like a photograph

1. Decide the photograph first: the camera position, the lens, the exposure and the white balance. Put the sun at its position for a location, a date and a time with `light.sun_position`.
2. Write the scene as functions in `painting.py`: `see(x, y)` gives the color that the camera records at a canvas point. `atelier/light.py` has the formulas: sun through an opening, sky from a window, light from sunlit surfaces, the shine of a floor.
3. Do not make an image of the scene to look at, in the program or outside it. Read numbers at a small number of points as a light meter does.
4. Paint in passes with `personas/mist/hand.py`, each pass with a smaller brush, and let each pass dry. The last pass must have marks less than 2 pixels wide. A camera has a mark of 1 pixel, and a judge that looks at a full-resolution crop finds larger marks.
5. Put texture in the color function (wood grain, wear), not in drawn lines. A judge reads drawn grain as line art.
6. Add film grain to each mark, a tone curve with a shoulder, and a small quantity of wear: scuffs, scratches, dust. A scene with no flaw reads as a 3D render.
7. Run the blind test. Copy the painting and three or more camera photographs of the same type of subject to neutral file names. Add one full-resolution crop of each image, and one known 3D render. Give the set to a new agent with no context. Ask which images a camera made, with a probability and the cause for each. Do not look at the control photographs yourself.
8. Fix the causes that the judge names, and test again with a new agent. Record each test in the `notes.md` of the work.

## Engine changes

- Paint `studies/marksheet` before and after an engine change, and look at both.
- Run `uv run pytest` in the repo. The tests hold the color math to spectrophotometer data, and they check paint conservation and exact replay.
- An engine change can alter the finished paintings. Paint each finished work again, then run `verify` before the commit.

## Lessons from the first works

- Wipe the brush before each load (`brush.wipe(0.1)`), and clean it between passages. A brush that is not wiped carries the first color into each subsequent color.
- Call `st.dry()` before a shape that needs a crisp edge against wet paint.
- A brush that is almost dry makes hatch marks. Do not use it for a glow or for smoke. Paint these with full-body pulls. Then soften the edges with a soft brush while the paint is wet.
- A wide brush that carries almost no paint does not blend. It makes pale rectangles.
- Pulls that follow the shape (along a ridge, down a cylinder) make no seams. Hatch fills in slabs make a seam at each slab edge.
- Keep fire, lamps and other light sources small, and make them the lightest and most saturated paint on the canvas.
- `st.match()` takes approximately half a second. Use it one time for each puddle.
