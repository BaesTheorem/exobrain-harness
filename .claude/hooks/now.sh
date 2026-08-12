#!/bin/bash
# UserPromptSubmit hook: stamp every turn with the wall-clock time.
#
# Why this exists: SessionStart fires maybe three times in a long session, so
# between those stamps there was no clock at all, and elapsed time within a
# session had to be inferred. On 2026-08-12 that produced a confident "yesterday"
# about work committed 32 minutes earlier. The date was in context and matched
# the commits; nothing was missing except the habit of looking. A per-turn stamp
# makes "when did that happen" a subtraction instead of a guess.
#
# Deliberately one short line: this rides along with every single prompt, so it
# has to stay cheap in tokens.
date '+Current time: %A, %B %-d, %Y at %-I:%M %p %Z'
