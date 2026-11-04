#!/usr/bin/env bash
# Stop hook: append a checkpoint marker so PROJECT_STATUS.md stays honest about
# when work happened. Deliberately does not claim any feature is complete.
set -uo pipefail
[ -f PROJECT_STATUS.md ] || exit 0
printf '\n<!-- session checkpoint: %s — update status by hand, do not treat as verified -->\n' \
  "$(date -u +%Y-%m-%dT%H:%M:%SZ)" >> PROJECT_STATUS.md
exit 0
