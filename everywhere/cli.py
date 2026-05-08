from __future__ import annotations

import argparse
import sys

from . import feishu_bridge, install


def print_help() -> None:
    print(
        """Usage: everywhere <command> [args]

Commands:
  install             Check local prerequisites and initialize state
  feishu <command>    Run Feishu bridge commands
  help                Show this help

Examples:
  everywhere install
  everywhere feishu bootstrap-chat --chat-id <chat_id>
  everywhere feishu run
  everywhere feishu attach
  everywhere feishu notify --message "Need human decision"
"""
    )


def run_install(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(prog="everywhere install", description="Check local Everywhere prerequisites")
    parser.add_argument("--strict", action="store_true", help="Exit non-zero when required tools are missing")
    args = parser.parse_args(argv)
    return install.main(["--strict"] if args.strict else [])


def main(argv: list[str] | None = None) -> int:
    args = list(sys.argv[1:] if argv is None else argv)
    command = args.pop(0) if args else "help"
    if command == "install":
        return run_install(args)
    if command in {"feishu", "feishu-bridge"}:
        return feishu_bridge.main(args)
    if command in {"help", "--help", "-h"}:
        print_help()
        return 0
    print(f"Unknown command: {command}", file=sys.stderr)
    print(file=sys.stderr)
    print_help()
    return 2
