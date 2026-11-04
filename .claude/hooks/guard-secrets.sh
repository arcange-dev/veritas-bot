#!/usr/bin/env bash
# PreToolUse guard for Write/Edit: refuse to persist obvious live credentials.
set -uo pipefail
payload="$(cat)"
python3 - "$payload" <<'PY'
import json, re, sys

raw = sys.argv[1] if len(sys.argv) > 1 else ""
try:
    data = json.loads(raw)
except Exception:
    sys.exit(0)

ti = data.get("tool_input", {}) or {}
text = json.dumps(ti)
path = str(ti.get("file_path", ""))

if path.endswith(".env.example") or "/docs/" in path or path.endswith(".md"):
    sys.exit(0)

patterns = {
    "OpenAI key": r"sk-[A-Za-z0-9]{20,}",
    "Anthropic key": r"sk-ant-[A-Za-z0-9\-_]{20,}",
    "Groq key": r"gsk_[A-Za-z0-9]{20,}",
    "Google API key": r"AIza[0-9A-Za-z\-_]{30,}",
    "GitHub token": r"gh[pousr]_[A-Za-z0-9]{30,}",
    "GitHub PAT v2": r"github_pat_[A-Za-z0-9_]{40,}",
    "private key block": r"-----BEGIN [A-Z ]*PRIVATE KEY-----",
    "Supabase service role": r"service_role['\"]?\s*[:=]\s*['\"]ey[A-Za-z0-9]",
}
for name, pat in patterns.items():
    if re.search(pat, text):
        print(
            f"BLOCKED by guard-secrets: possible live {name} in {path}. "
            "Reference an environment variable instead.",
            file=sys.stderr,
        )
        sys.exit(2)
sys.exit(0)
PY
