# media-reencode

`bin/plex-reencode` converts oversized videos in a Plex library to HEVC, one file at a time. A file is replaced only after a full-length VMAF check passes.

It uses [ab-av1](https://github.com/alexheretic/ab-av1) (`brew install ab-av1`) to find the encoder setting, and ffmpeg with `libvmaf` to check the result.

```
plex-reencode plan            # queue, largest estimated saving first
plex-reencode run [--limit N] # work the queue; stop and start it again at any time
plex-reencode readme          # rebuild the log table in the drive README
```

The drive path, quality gates and encoder are constants at the top of the script. `REENCODE_ENCODER=libx265` changes the encoder. This is approximately 13 times slower on an M1 and gives smaller files.

Work files, resume state and the log are in `.reencode/` at the drive root. The full record of the decision, the scope rules and the per-file log are in the README at the drive root, because the record must stay with the media when the drive moves to another Mac.

Rules the script enforces:
- An original is deleted only by the rename that puts a checked replacement in its place.
- The script does not queue paths in `OnePace/`.
- The script does not queue AV1, HDR or Dolby Vision sources.
