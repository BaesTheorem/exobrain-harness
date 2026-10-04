"""Read audio without torchcodec.

torchaudio 2.9+ sends torchaudio.load() through torchcodec, and torchcodec
links against a system FFmpeg of version 4 to 8. Homebrew moved to FFmpeg 9 on
2026-08-25, and from then on every XTTS call failed when it read the reference
clip ("Could not load this library: libtorchcodec_core4.dylib").

The reference clips are plain WAV files, so soundfile (libsndfile, bundled in
its wheel) reads them with no FFmpeg at all. patch() swaps torchaudio.load for
a soundfile reader before XTTS imports it, so a later brew upgrade cannot break
the voice again.

INVARIANTS (do not break these in an edit):
  - patch() runs before the first synthesis call. Callers import this module
    and call patch() at the top, before TTS.api does any work.
  - The return shape matches torchaudio.load: (float32 tensor [channels,
    frames], sample_rate).
"""
import soundfile as sf
import torch
import torchaudio


def load(path, *_args, **_kwargs):
    data, sr = sf.read(str(path), dtype="float32", always_2d=True)
    return torch.from_numpy(data.T.copy()), sr


def patch():
    torchaudio.load = load
