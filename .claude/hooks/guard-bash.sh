#!/usr/bin/env bash
# PreToolUse guard for Bash. Reads the hook payload on stdin.
# Exit 2 blocks the call and feeds the reason back to the model.
set -euo pipefail
payload="$(cat)"
cmd="$(printf '%s' "$payload" | python3 -c \
  'import json,sys;print(json.load(sys.stdin).get("tool_input",{}).get("command",""))' \
  2>/dev/null || true)"

block() { echo "BLOCKED by guard-bash: $1" >&2; exit 2; }

[ ${#cmd} -gt 4000 ] && block "command too long to review"

# Assembled from fragments so this file never matches its own patterns.
RMREC="rm -r""f /"
MKFS="mk""fs"
ENVCAT="cat .en""v"
lower="$(printf '%s' "$cmd" | tr 'A-Z' 'a-z')"

case "$cmd" in
  *"$RMREC"*) block "recursive deletion of an absolute root path" ;;
  *"$MKFS"*)  block "filesystem format utility" ;;
  *"$ENVCAT"*) block "reading application secrets" ;;
  *"git push --force"*|*"git push -f"*) block "force push needs a human decision" ;;
  *"supabase db reset"*|*"DROP DATABASE"*|*"TRUNCATE TABLE"*) block "destructive database command" ;;
  *"chmod o+w"*|*"chmod a+w"*|*"chmod -R 7"*) block "world-writable permissions" ;;
  *"sudo "*) block "privilege escalation" ;;
esac

if printf '%s' "$lower" | grep -qE "(curl|wget).*\|[[:space:]]*(ba)?sh"; then
  block "piping a remote script into a shell"
fi
if printf '%s' "$lower" | grep -qE "(printenv|env)[[:space:]]*\|" && \
   printf '%s' "$lower" | grep -qE "(curl|nc|ncat|socat)"; then
  block "environment dump piped to the network"
fi
exit 0
