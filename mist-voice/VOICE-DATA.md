# Voice data → PRIVATE repo

The MIST voice **data** is NOT in this public harness. It lives in a separate
private repo because it's copyrighted *Pantheon* show audio:

## → https://github.com/BaesTheorem/mist-voice-data  (private · git-lfs)

Contents (mirrors this `mist-voice/` layout):
- `samples/raw/mist_supercut.wav` -- ~335MB raw corpus of MIST's lines
- `samples/raw/mist_supercut.segments.tsv` -- 605-segment curation (which spans are clean MIST)
- `samples/reference/06_need_your_help.wav` -- active cloning reference
- `samples/reference/_archive/*.wav` -- dropped takes
- `samples/mist_windows.tsv` -- window manifest
- `demo_mist.wav` -- approved canonical sample

## Rebuild
```bash
git clone https://github.com/BaesTheorem/mist-voice-data.git   # needs git-lfs
cp -R mist-voice-data/samples       /path/to/exobrain-harness/mist-voice/
cp    mist-voice-data/demo_mist.wav  /path/to/exobrain-harness/mist-voice/
```
Then follow `README.md` here for env + pipeline. To redo the clone with better
tools later, the raw corpus + segment TSV in that repo are the training inputs.
