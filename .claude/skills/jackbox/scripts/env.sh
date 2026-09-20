#!/usr/bin/env bash
# Source before running any jackbox node script directly (bin/jackbox does this for you).
# 1) node deps live in this dir (playwright-core + @anthropic-ai/sdk; no bundled browser).
# 2) ANTHROPIC_API_KEY comes from a gitignored env file, never inlined.
JB_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
if [ ! -d "$JB_DIR/node_modules/playwright-core" ]; then
  echo "jackbox: installing node deps..." >&2
  (cd "$JB_DIR" && npm install --no-audit --no-fund >/dev/null) || echo "WARN: npm install failed in $JB_DIR" >&2
fi
ENV_FILE="${ANTHROPIC_ENV_FILE:-$JB_DIR/../../../../phone/.env}"
if [ -z "${ANTHROPIC_API_KEY:-}" ] && [ -f "$ENV_FILE" ]; then
  val="$(grep -E '^ANTHROPIC_API_KEY=' "$ENV_FILE" | head -1 | sed -E 's/^[^=]*=//')"
  val="${val%\"}"; val="${val#\"}"; val="${val%\'}"; val="${val#\'}"
  [ -n "$val" ] && export ANTHROPIC_API_KEY="$val"
fi
[ -n "${ANTHROPIC_API_KEY:-}" ] || echo "WARN: ANTHROPIC_API_KEY not set (autopilot needs it; join/shot/control do not)." >&2
