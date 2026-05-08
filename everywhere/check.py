from __future__ import annotations

import argparse
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def log(message: str) -> None:
    print(f"[everywhere check] {message}")


def run_step(name: str, command: list[str], *, cwd: Path = ROOT) -> bool:
    log(name)
    result = subprocess.run(command, cwd=str(cwd), text=True, check=False)
    if result.returncode == 0:
        return True
    print(f"[everywhere check] failed: {name} (exit {result.returncode})", file=sys.stderr)
    return False


def run_tests() -> bool:
    return run_step("unit tests", [sys.executable, "tests/run_feishu_bridge_tests.py"])


def run_wheel_build() -> bool:
    with tempfile.TemporaryDirectory() as tmpdir:
        return run_step("wheel build", [sys.executable, "-m", "pip", "wheel", ".", "-w", tmpdir, "--no-deps"])


def run_skill_discovery() -> bool:
    if not shutil.which("npx"):
        print("[everywhere check] failed: skill discovery requires npx", file=sys.stderr)
        return False
    return run_step("skill discovery", ["npx", "skills", "add", ".", "--list", "--full-depth"])


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run developer checks for Everywhere")
    parser.add_argument("--skip-skill-check", action="store_true", help="Skip `npx skills add . --list --full-depth`")
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    checks = [
        run_tests(),
        run_wheel_build(),
    ]
    if not args.skip_skill_check:
        checks.append(run_skill_discovery())
    if all(checks):
        log("ok")
        return 0
    return 1
