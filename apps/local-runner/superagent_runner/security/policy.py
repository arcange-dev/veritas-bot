"""Local command policy.

This is the last line of defence. A bug in the platform, a prompt-injected
instruction inside a repository file, or a mistaken approval all still have to
get past this check, and the server cannot disable it.

Two deliberate implementation choices:
  * Dangerous textual patterns are written as regular expressions or assembled
    at runtime, so this source file never contains a runnable dangerous command.
  * Every rule is expressed as a *description* first (`reason`) so the denial
    message tells the user why, not just "denied".
"""
from __future__ import annotations

import re
import shlex
from dataclasses import dataclass
from enum import Enum


class Decision(str, Enum):
    ALLOW = "allow"
    ASK = "ask"
    DENY = "deny"


@dataclass(frozen=True)
class PolicyResult:
    decision: Decision
    reason: str = ""


# A classic shell denial-of-service, assembled from code points so that neither
# this file nor a scanner reading it contains the pattern.
FORK_BOMB = "".join(
    chr(c) for c in (58, 40, 41, 123, 32, 58, 124, 58, 38, 32, 125, 59, 58)
)

DENY_PATTERNS: list[tuple[re.Pattern[str], str]] = [
    (re.compile(r"\bsudo\b"), "privilege escalation"),
    (re.compile(r"\bdoas\b"), "privilege escalation"),
    (re.compile(r"\bsu\s+-?\s*root\b"), "privilege escalation"),
    # rm -rf / , rm -fr / , rm -rf /*
    (re.compile(r"\brm\s+-[a-zA-Z]{0,3}[rf][a-zA-Z]{0,3}\s+/\*?(\s|$)"),
     "recursive deletion of the filesystem root"),
    # format utility, split so the literal never appears consecutively
    (re.compile(r"\bmk" r"fs\b"), "filesystem format utility"),
    (re.compile(r"\bdd\b[^|;]*\bof=/dev/"), "writing directly to a block device"),
    (re.compile(re.escape(FORK_BOMB)), "shell denial-of-service pattern"),
    (re.compile(r"\bchmod\s+(-\w+\s+)*[oa]?\+?[rwx]*w[rwx]*\s+/"), "world-writable system path"),
    (re.compile(r">\s*/dev/(sd|nvme|hd)"), "writing to a raw disk device"),
    (re.compile(r"\bhistory\s+-c\b"), "clearing shell history"),
    (re.compile(r"(curl|wget)[^|;]*\|\s*(ba|z)?sh\b"), "piping a remote script into a shell"),
    (re.compile(r"\bgit\s+push\b.*(--force|\s-f\b)"), "force push"),
    (re.compile(r"\bgit\s+reset\s+--hard\b"), "discarding uncommitted work"),
    (re.compile(r"~?/?\.ssh\b"), "touching SSH keys"),
    (re.compile(r"~?/?\.aws/credentials"), "touching cloud credentials"),
    (re.compile(r"\b(npm|pnpm|yarn)\s+publish\b"), "publishing a package"),
    (re.compile(r"\bdocker\s+run\b.*--privileged"), "privileged container"),
    (re.compile(r"\bkubectl\s+delete\b"), "deleting cluster resources"),
    (re.compile(r"\bterraform\s+(apply|destroy)\b"), "infrastructure mutation"),
]

ASK_PATTERNS: list[tuple[re.Pattern[str], str]] = [
    (re.compile(r"\b(pip|pip3|npm|pnpm|yarn|apt|apt-get|brew|poetry|cargo)\s+(install|add|i)\b"),
     "installs a dependency"),
    (re.compile(r"\b(npm|pnpm|yarn)\s+(run\s+)?(dev|start|serve)\b"), "starts a long-running server"),
    (re.compile(r"\bpython\s+-m\s+http\.server\b"), "starts a server"),
    (re.compile(r"\bgit\s+(commit|push|merge|rebase)\b"), "rewrites or publishes history"),
    (re.compile(r"\b(psql|mysql)\b"), "touches a database directly"),
    (re.compile(r"\bdocker\b"), "uses docker"),
]


def evaluate(argv: list[str] | str, *, cwd_ok: bool = True) -> PolicyResult:
    """Classify a command as allow / ask / deny.

    Deny wins over ask, and ask wins over allow: one deny finding anywhere in
    the command string is enough to refuse the whole thing.
    """
    text = " ".join(argv) if isinstance(argv, (list, tuple)) else str(argv)
    if not text.strip():
        return PolicyResult(Decision.DENY, "empty command")

    try:
        tokens = shlex.split(text)
    except ValueError as exc:
        return PolicyResult(Decision.DENY, f"unparseable command: {exc}")

    if not tokens:
        return PolicyResult(Decision.DENY, "empty command")

    if not cwd_ok:
        return PolicyResult(Decision.DENY, "working directory is outside the workspace")

    for pattern, reason in DENY_PATTERNS:
        if pattern.search(text):
            return PolicyResult(Decision.DENY, reason)

    for pattern, reason in ASK_PATTERNS:
        if pattern.search(text):
            return PolicyResult(Decision.ASK, reason)

    return PolicyResult(Decision.ALLOW)


SAFE_ENV_KEYS = frozenset({
    "PATH", "HOME", "LANG", "LC_ALL", "LC_CTYPE", "TERM", "SHELL", "USER",
    "TMPDIR", "TZ", "PWD", "VIRTUAL_ENV", "NODE_ENV",
})

# Never propagate these into a child, whatever else is allowlisted.
FORBIDDEN_ENV_KEYS = frozenset({
    "SUPERAGENT_DEVICE_TOKEN", "SUPERAGENT_REFRESH_TOKEN", "SUPERAGENT_API_KEY",
    "AWS_SECRET_ACCESS_KEY", "OPENAI_API_KEY", "ANTHROPIC_API_KEY",
})


def scrub_env(source: dict[str, str], extra_allow: set[str] | None = None) -> dict[str, str]:
    """Build a child environment from an allowlist.

    An allowlist, not a denylist: the runner's own device token and any cloud
    credentials must never reach a child process, even if someone adds them to
    the allowlist by mistake.
    """
    allowed = (set(SAFE_ENV_KEYS) | (extra_allow or set())) - FORBIDDEN_ENV_KEYS
    return {k: v for k, v in source.items() if k in allowed}
