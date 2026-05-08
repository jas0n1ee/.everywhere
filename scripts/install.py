#!/usr/bin/env python3
"""Bootstrap checks for Everywhere."""
from __future__ import annotations

import argparse
import shutil
import subprocess
import sys
from pathlib import Path


STATE_DIR = Path("~/.everywhere/feishu-bridge").expanduser()


def log(message: str) -> None:
    print(f"[everywhere install] {message}")


def warn(message: str) -> None:
    print(f"[everywhere install] warning: {message}", file=sys.stderr)


def run_check(argv: list[str]) -> tuple[bool, str]:
    result = subprocess.run(argv, text=True, capture_output=True, check=False)
    if result.returncode == 0:
        return True, "ok"
    detail = result.stderr.strip() or result.stdout.strip() or f"exit {result.returncode}"
    return False, detail


def check_python() -> bool:
    version = sys.version_info
    if version < (3, 10):
        warn(f"Python >= 3.10 is recommended; current is {version.major}.{version.minor}")
        return False
    log(f"python: {version.major}.{version.minor}.{version.micro}")
    return True


def check_lark_cli(strict: bool) -> bool:
    if not shutil.which("lark-cli"):
        message = "lark-cli not found on PATH"
        if strict:
            print(f"[everywhere install] error: {message}", file=sys.stderr)
        else:
            warn(message)
        return False
    ok, detail = run_check(["lark-cli", "event", "--help"])
    if ok:
        log("lark-cli event API available")
        return True
    message = f"lark-cli event --help failed: {detail}"
    if strict:
        print(f"[everywhere install] error: {message}", file=sys.stderr)
    else:
        warn(message)
    return False


def ensure_state_dir() -> None:
    STATE_DIR.mkdir(parents=True, exist_ok=True)
    log(f"state dir: {STATE_DIR}")


def print_next_steps() -> None:
    print()
    print("Next steps:")
    print("  1. Configure lark-cli if needed:")
    print("     lark-cli config init --new")
    print("  2. Save a default Feishu chat:")
    print("     everywhere feishu bootstrap-chat --chat-id <chat_id>")
    print("  3. Start the bridge:")
    print("     everywhere feishu run")
    print("  4. In the target tmux session, attach remote control:")
    print("     everywhere feishu attach")
    print()
    print("Update:")
    print("  npm install -g @jas0n1ee/everywhere@latest")
    print("  everywhere install")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Check local Everywhere prerequisites")
    parser.add_argument("--strict", action="store_true", help="Exit non-zero when required tools are missing")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    checks = [
        check_python(),
        check_lark_cli(strict=args.strict),
    ]
    ensure_state_dir()
    print_next_steps()
    if args.strict and not all(checks):
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
