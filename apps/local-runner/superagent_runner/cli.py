"""Command line interface.

  superagent-runner pair --api-url URL    pair this machine
  superagent-runner allow DIR             approve a workspace root
  superagent-runner run                   connect and serve
  superagent-runner doctor                print local state
"""
from __future__ import annotations

import argparse
import asyncio
import hashlib
import json
import platform
import socket
import sys

import httpx

from . import __version__
from .client import RunnerClient
from .config import RunnerConfig, config_path


def fingerprint() -> str:
    """Stable per-machine hash. The raw hostname never leaves the machine."""
    raw = f"{socket.gethostname()}|{sys.platform}|{platform.machine()}"
    return hashlib.sha256(raw.encode()).hexdigest()[:32]


def cmd_pair(args: argparse.Namespace) -> int:
    config = RunnerConfig.load()
    config.api_url = args.api_url.rstrip("/")
    code = args.code or input("Enter the 6-digit code from the web app: ").strip()
    email = args.email or input("Your account email: ").strip()

    payload = {
        "code": code, "email": email, "fingerprint": fingerprint(),
        "os": sys.platform, "arch": platform.machine(), "runner_version": __version__,
    }
    try:
        response = httpx.post(
            f"{config.api_url}/api/v1/runners/pairing/claim/", json=payload, timeout=20.0
        )
    except httpx.HTTPError as exc:
        print(f"Cannot reach {config.api_url}: {exc}", file=sys.stderr)
        return 1

    if response.status_code != 200:
        print(f"Pairing failed ({response.status_code}). Check the code and try again.",
              file=sys.stderr)
        return 1

    body = response.json()
    config.device_id = body["device_id"]
    config.device_token = body["access_token"]
    config.refresh_token = body.get("refresh_token", "")
    config.save()
    print(f"Paired as device {config.device_id}.")
    print(f"Config written to {config_path()} (mode 600).")
    print("Next: superagent-runner allow ~/code/my-project")
    return 0


def cmd_allow(args: argparse.Namespace) -> int:
    config = RunnerConfig.load()
    try:
        resolved = config.add_root(args.path)
    except (NotADirectoryError, PermissionError) as exc:
        print(str(exc), file=sys.stderr)
        return 1
    print(f"Approved workspace root: {resolved}")
    print("The platform can read this list but cannot add to it.")
    return 0


def cmd_run(args: argparse.Namespace) -> int:
    config = RunnerConfig.load()
    if not config.device_id or not config.device_token:
        print("This machine is not paired. Run: superagent-runner pair", file=sys.stderr)
        return 1
    if not config.workspace_roots:
        print("No workspace approved yet. Run: superagent-runner allow <dir>", file=sys.stderr)
        return 1

    client = RunnerClient(config)
    if not args.quiet:
        print(f"Connecting to {config.api_url} ... Ctrl+C to stop.")
    try:
        asyncio.run(client.run_forever())
    except KeyboardInterrupt:
        killed = client.processes.stop_all()
        print(f"\nStopped. Terminated {killed} child process group(s).")
    return 0


def cmd_doctor(args: argparse.Namespace) -> int:
    config = RunnerConfig.load()
    print(json.dumps({
        "runner_version": __version__,
        "config_path": str(config_path()),
        "api_url": config.api_url,
        "paired": bool(config.device_id),
        "device_id": config.device_id or None,
        "workspace_roots": config.workspace_roots,
        "fingerprint": fingerprint(),
    }, indent=2))
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="superagent-runner", description=__doc__)
    parser.add_argument("--version", action="version", version=f"%(prog)s {__version__}")
    sub = parser.add_subparsers(dest="command", required=True)

    pair = sub.add_parser("pair", help="pair this machine with your account")
    pair.add_argument("--api-url", default="http://localhost:8000")
    pair.add_argument("--code", default="")
    pair.add_argument("--email", default="")
    pair.set_defaults(func=cmd_pair)

    allow = sub.add_parser("allow", help="approve a directory the platform may use")
    allow.add_argument("path")
    allow.set_defaults(func=cmd_allow)

    run = sub.add_parser("run", help="connect and serve commands")
    run.add_argument("--quiet", action="store_true")
    run.set_defaults(func=cmd_run)

    doctor = sub.add_parser("doctor", help="print local state")
    doctor.set_defaults(func=cmd_doctor)

    args = parser.parse_args(argv)
    return int(args.func(args))


if __name__ == "__main__":
    raise SystemExit(main())
