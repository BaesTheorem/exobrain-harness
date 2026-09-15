#!/bin/zsh
# Compile mist-confetti. Output is gitignored; bin/mist-confetti builds on demand.
set -e
DIR="${0:A:h}"
mkdir -p "$DIR/build"
swiftc -O -swift-version 5 "$DIR/main.swift" -o "$DIR/build/mist-confetti"
codesign --force -s - "$DIR/build/mist-confetti" 2>/dev/null || true
echo "built $DIR/build/mist-confetti"
