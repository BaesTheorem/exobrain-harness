#!/usr/bin/env bash
# Source this before running any jackbox node script:  source scripts/env.sh
# It resolves Playwright into NODE_PATH and loads the Anthropic API key from a
# gitignored .env (never inline the secret). Both are read by the node scripts.

# 1) NODE_PATH -> the directory that contains the 'playwright' package.
if ! node -e "require.resolve('playwright')" >/dev/null 2>&1; then
  PW="$(find "$HOME/.npm/_npx" /opt/homebrew/lib/node_modules "$HOME/.npm-global/lib/node_modules" \
        -type d -path '*/node_modules/playwright' 2>/dev/null | head -1)"
  if [ -n "$PW" ]; then export NODE_PATH="$(dirname "$PW")"; fi
fi
node -e "require.resolve('playwright')" >/dev/null 2>&1 || \
  echo "WARN: playwright not found. Install with:  npx -y playwright@1.60 install chromium  (and 'npm i -g playwright')" >&2

# 2) ANTHROPIC_API_KEY from a gitignored env file (phone/.env holds it in this repo).
ENV_FILE="${ANTHROPIC_ENV_FILE:-$HOME/Documents/Exobrain harness/phone/.env}"
if [ -z "$ANTHROPIC_API_KEY" ] && [ -f "$ENV_FILE" ]; then
  val="$(grep -E '^ANTHROPIC_API_KEY=' "$ENV_FILE" | head -1 | sed -E 's/^[^=]*=//')"
  val="${val%\"}"; val="${val#\"}"; val="${val%\'}"; val="${val#\'}"
  export ANTHROPIC_API_KEY="$val"
fi
[ -n "$ANTHROPIC_API_KEY" ] || echo "WARN: ANTHROPIC_API_KEY not set (autopilots need it; controller/shot do not)." >&2
