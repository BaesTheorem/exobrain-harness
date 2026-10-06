# twocam

twocam cuts two camera angles of one conversation into one video. The cut always
shows the person who speaks. Each camera films one person, and the two cameras record
audio.

## Tools

- `bin/twocam-stitch` syncs the two files by audio cross-correlation, finds the
  speaker, and renders the cut with ffmpeg (HEVC through VideoToolbox, one pass).
- `bin/twocam-diarize` writes the speaker turns for a file as JSON. It runs
  pyannote `speaker-diarization-community-1` and needs a Hugging Face token.

## Procedure

1. Find the pairs. A correct pair gives a score far above 2:

   ```bash
   twocam/bin/twocam-stitch pair cam1/*.MP4 cam2/*.MP4
   ```

2. Get the speaker turns for the camera A file:

   ```bash
   $PY twocam/bin/twocam-diarize A.MP4 -o a.turns.json
   ```

   `$PY` is a Python with pyannote.audio 4.x.

3. Find which voice is which. Transcribe the longest turn of each speaker, then
   give each voice the camera that films that person:

   ```bash
   twocam/bin/twocam-stitch A.MP4 B.MP4 --turns a.turns.json \
     --map SPEAKER_00=B,SPEAKER_01=A --dry-run
   ```

4. Make the video. Use `--preview 60` first to examine the cuts:

   ```bash
   twocam/bin/twocam-stitch A.MP4 B.MP4 --turns a.turns.json \
     --map SPEAKER_00=B,SPEAKER_01=A --min-shot 2.5 -o out.mp4
   ```

## Notes

- Without `--turns`, the script cuts on the level difference between the two mics.
  This works when each camera is near its own person. When the two cameras are on
  one table, the difference is too small (approximately 2 dB), and the direction
  can be incorrect. Thus the diarized path with a manual `--map` is the default.
- `--audio auto` keeps the track with the higher speech-to-noise ratio.
- GoPro splits a recording into 4 GB chapters (GH01xxxx, GH02xxxx, and other).
  Connect the chapters of each camera before the stitch.
- Output speed on an M-series Air is approximately 0.9x real time for 4K input.
