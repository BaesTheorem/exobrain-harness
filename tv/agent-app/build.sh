#!/bin/bash
# Builds the MIST TV Agent package. The LAN token comes from the harness .env
# (MIST_TV_AGENT_TOKEN) and is written into service/config.js, which is
# gitignored, so the public repo never carries it.
set -e
cd "$(dirname "$0")"
TOKEN=$(grep '^MIST_TV_AGENT_TOKEN=' ../../.env | cut -d= -f2)
[ -n "$TOKEN" ] || { echo "MIST_TV_AGENT_TOKEN missing from .env" >&2; exit 2; }
printf '"use strict";\nmodule.exports = { token: %s };\n' "\"$TOKEN\"" > service/config.js
export PATH="$HOME/tizen-studio/tools/ide/bin:$PATH"
rm -f ./*.wgt dist/*.wgt
tizen package -t wgt -s MIST -- . | grep -E 'Package File|rror'
mv ./*.wgt dist/ 2>/dev/null || true
ls -la dist/*.wgt
