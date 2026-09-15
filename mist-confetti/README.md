# mist-confetti

A fullscreen confetti burst over every display, with an optional victory tone.

```sh
bin/mist-confetti                                  # confetti + tone
bin/mist-confetti --silent                         # visuals only
bin/mist-confetti --duration 10 --emit 4.5 --intensity 2.2   # bigger
bin/mist-confetti --tone success                   # the shorter cue
```

`build.sh` compiles `main.swift` to `build/mist-confetti` (gitignored). The
wrapper builds on demand, so a fresh clone needs no setup step.

## Why the window is built the way it is

Four properties are load-bearing. Removing any one turns a celebration into an
annoyance, so they are commented in `main.swift` as well:

- **`.accessory` activation policy.** The burst never steals focus and puts
  nothing in the dock or menu bar.
- **`ignoresMouseEvents`.** The overlay covers the whole screen. If it swallowed
  a click it would be a trap.
- **`screenSaver` window level, plus `.canJoinAllSpaces` and
  `.fullScreenAuxiliary`.** Draws over fullscreen apps, on whichever Space is
  front, without switching Spaces.
- **`CAEmitterLayer`.** Core Animation runs particles on the render server, so a
  few thousand of them cost almost nothing.

## Verifying it actually drew something

A process that draws nothing also exits 0, so exit status proves nothing. Without
Screen Recording permission, ask the window server directly while a burst is up:

```sh
bin/mist-confetti --silent --duration 10 &
sleep 2
# CGWindowListCopyWindowInfo, filtered to owner "mist-confetti"
```

A healthy run reports one on-screen window per display at `layer=1000`
(`CGWindowLevelForKey(.screenSaverWindow)`) spanning the full display bounds. The
check returns zero windows when nothing is running, so it discriminates.

## Sound

`sounds/` holds two cues from [UI SFX](https://github.com/romainsimon/uisfx)
(`arcade` pack), the house default for interface sound. The audio is **CC0**, so
there is no attribution requirement and no credits ledger to maintain.

- `arcade-complete.mp3` (0.78s) is the default, a fanfare shape
- `arcade-success.mp3` (0.65s) is shorter and flatter

Sound is off by default everywhere else in this harness, on the principle that a
watcher firing unattended should not make noise in an empty room. This tool
inverts that, because the only thing that calls it is a celebration someone asked
to hear. Automated callers that should stay quiet pass `--silent`.
