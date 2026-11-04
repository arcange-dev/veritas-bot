#!/usr/bin/env bash
# PostToolUse: format and syntax-check a touched Python file.
set -uo pipefail
payload="$(cat)"
path="$(printf '%s' "$payload" | python3 -c \
  'import json,sys;print(json.load(sys.stdin).get("tool_input",{}).get("file_path",""))' \
  2>/dev/null || true)"
[ -z "${path:-}" ] && exit 0
case "$path" in *.py) ;; *) exit 0 ;; esac
[ -f "$path" ] || exit 0
if command -v ruff >/dev/null 2>&1; then ruff format "$path" >/dev/null 2>&1 || true; fi
python3 -m py_compile "$path" 2>&1 | head -20 || true
exit 0
