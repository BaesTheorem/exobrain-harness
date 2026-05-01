#!/bin/bash
# Things 3 ↔ Obsidian sync runner
# Wraps the Python script so launchd uses bash (which typically has Full Disk Access)

cd "$(dirname "$0")/.." || exit 1
/usr/bin/python3 things3-sync/things3-obsidian-sync.py
