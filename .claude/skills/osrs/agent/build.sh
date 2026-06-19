#!/usr/bin/env bash
# Build the MIST in-process input/state agent jar from the tracked source here,
# outputting to the gitignored runtime location that osrs.py + the launch command use.
set -euo pipefail
HERE="$(cd "$(dirname "$0")" && pwd)"
JH="/opt/homebrew/opt/openjdk@17/bin"
OUT="$HOME/Documents/osrs-companion/mist-agent"
mkdir -p "$OUT"
cp "$HERE/MistAgent.java" "$HERE/manifest.txt" "$OUT/"
cd "$OUT"
"$JH/javac" MistAgent.java
"$JH/jar" cfm mist-agent.jar manifest.txt MistAgent*.class
echo "built $OUT/mist-agent.jar"
