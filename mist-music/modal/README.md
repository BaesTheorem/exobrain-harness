# modalkit: a tune in a different scale

modalkit moves a tune from one scale to a different scale, arranges it for a band, and measures the result against the new scale. The first piece was a Phrygian dominant game tune played as a Dorian reel.

## Files

| File | Content |
| --- | --- |
| `modalkit.py` | The tune as scale degrees, the remap to a new scale, and the checks |
| `celtic.py` | A session band in code, from tin whistle to bodhran |
| `bandtake.py` | Sends rendered audio to the ACE-Step cover model, for a take that sounds recorded |
| `../bin/modal-cover` | The command line: `scales`, `fetch`, `remap`, `check` |
| `private/` | Piece files and source tabs. Not in git |
| `soundfonts/` | Downloaded soundfonts. Not in git. `CREDITS` records each one |

## The remap

A tune is a sequence of notes. Each note is a scale degree (1 to 7) in a named scale, with an optional accidental and an octave. Hooktheory stores its tabs as degrees too, so you can use the sections from `modal-cover fetch` directly.

In a new scale, each note keeps its degree number and takes the pitch that the new scale gives to that degree. Example: C Phrygian dominant to A Dorian. Degree 2 changes from D flat to B, degree 3 from E to C, and degree 6 from A flat to F sharp.

An altered note has a pitch that the source scale does not contain. If the new scale contains that pitch, the note takes it. If not, the note moves to the nearest tone of the new scale. If two tones are at the same distance, the note takes the tone with the same degree number. The result has scale tones only. `remap` prints each altered note, and `contour` counts the melodic steps that became one pitch two times.

## Procedure for a cover

1. Find the notes. Run `modal-cover fetch URL` for a Hooktheory tab, or type a `Section` by hand.
2. Download the recording. Measure its tempo, its number of bars and its structure.
3. Move the tab along the recording's chroma, in all 12 transpositions. The written key must have the highest score.
4. Run `modal-cover remap FILE.json --scale dorian --tonic A`. Read the altered notes and the census.
5. Write a piece file in `private/`. It puts the remapped notes in bars and writes each part as `Tone` records.
6. Run the piece with `--dump`. Read the census of all written notes.
7. Run the piece. Read the balance table and the three audio checks.
8. Run the piece with `--control`. The control must give the opposite result on the test for the new scale.

## The checks

`census` counts the written notes. It gives the time on each pitch class and the share that is in the scale. It also gives the tones that are different between the scale and each other mode. For Dorian against natural minor, that tone is the sixth.

`audio_census` reads the spectrum of the rendered audio. It also gives the pitch class of the low band (40 to 220 Hz), which is the tonal centre.

`transcribed_census` counts the notes that Basic Pitch hears in the audio. Basic Pitch is a third-party model, and it reports fundamentals.

`melody_presence` tests that the tune is in the audio at its written pitch. The other 11 transpositions are the control.

The control is the same arrangement with each sixth degree a semitone lower (natural minor). On the first piece, the transcription of the cover gave F sharp 2.8% and F 0.0%. The transcription of the control gave F sharp 0.0% and F 4.9%.

## Measured results from the first piece

- A spectrum census counts overtones. The fifth harmonic of each A is a C sharp, and the third harmonic of each B is an F sharp. An A Dorian mix showed 2% of its energy on C sharp with no C sharp in the score. Use the transcription census for the decision, and keep the control.
- An analysis window of 186 ms cannot isolate semitones below 400 Hz. The census uses 0.74 s for the middle band and 1.5 s for the low band.
- A drum has a pitch. The first bodhran model had its skin at 92 to 140 Hz with no relation to the key. The low band of an A Dorian mix then had 30% of its energy on A flat and B flat. The tonic was not in its three strongest pitch classes. `bodhran()` takes a tuning, and the default is A2 B2 D3 E3. With that tuning the low band shows A at 40%.
- A remap can remove the color of the new scale from the melody. The verse of the first piece has no sixth degree, so A Dorian and A minor gave the same melody. The arrangement supplies the F sharp in three places. The IV chord is at each cadence. A short scale passage through the sixth fills the silent part of the phrase. The subtonic chord has its major seventh as an inner voice.
- The fiddle preset of FluidR3 is 12 to 14 cents flat from E5 to A5. `tuning_table()` measures each note and `bowed()` corrects it with pitch bend. The preset also has a slow attack (half level after 90 to 190 ms), so it is better for long notes than for fast notes.
- Three free tin whistle soundfonts were tested. One was 33 to 93 cents out of tune. One was 60 cents sharp on D5 and gave no sound on A5 and E6. The header of the third names a sample converter, so its samples probably come from a commercial library. The whistle is synthesized.
- The melody instruments must be louder than the band. In the first mix they were 1 to 2 LU below the band in the verses. In the last mix they are approximately 3 LU above it in the verses and 5 LU above it in the solo.
- In a Hooktheory tab, the melody line can hold two voices. Notes two octaves below the melody were a bass answer in the recording.
- A constant-Q spectrum shows the third harmonic of a middle-register note as a strong note a twelfth higher. Compare with a pitch tracker before you say that a tab is incorrect.

## Band takes

`bandtake.py take SOURCE.mp3 "tags" -o OUT.mp3` sends rendered audio through the cover task of ACE-Step 1.5. It uses the backend that MIST Studio is set to. The model can change notes, so run `modal-cover check OUT.mp3 --scale S --tonic T --lead NOTES.json` on each take. A piece writes `NOTES.json` to `tmp/modal-cache/` when it renders.

On 2026-11-24 the free Space returned "Model not fully initialized" for each of its two models. The older Space returned a repository error. No take was made on that date.

## Private files

A piece file holds the melody of a different composer, so `private/` is not in the public repository. The daily backup includes it. `modal-cover fetch` gets the source tabs again.
