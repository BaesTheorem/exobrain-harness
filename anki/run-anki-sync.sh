#!/bin/bash
# Anki Session Sync runner
# Wraps the Python script so launchd uses bash (which typically has Full Disk Access)

cd "$(dirname "$0")/.." || exit 1
/usr/bin/python3 anki/anki-sync.py
