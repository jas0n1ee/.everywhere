#!/usr/bin/env python3
from __future__ import annotations

import importlib.util
import inspect
import tempfile
from pathlib import Path


def load_test_module():
    path = Path(__file__).with_name("test_feishu_bridge.py")
    spec = importlib.util.spec_from_file_location("test_feishu_bridge", path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"Could not load {path}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class MonkeyPatch:
    def __init__(self) -> None:
        self._env: list[tuple[str, str | None]] = []

    def setenv(self, key: str, value: str) -> None:
        import os

        self._env.append((key, os.environ.get(key)))
        os.environ[key] = value

    def undo(self) -> None:
        import os

        for key, old_value in reversed(self._env):
            if old_value is None:
                os.environ.pop(key, None)
            else:
                os.environ[key] = old_value
        self._env.clear()


def main() -> int:
    module = load_test_module()
    tests = [
        item
        for _, item in sorted(vars(module).items())
        if callable(item) and getattr(item, "__name__", "").startswith("test_")
    ]
    for test in tests:
        kwargs = {}
        tmpdir = None
        monkeypatch = None
        signature = inspect.signature(test)
        if "tmp_path" in signature.parameters:
            tmpdir = tempfile.TemporaryDirectory()
            kwargs["tmp_path"] = Path(tmpdir.name)
        if "monkeypatch" in signature.parameters:
            monkeypatch = MonkeyPatch()
            kwargs["monkeypatch"] = monkeypatch
        try:
            test(**kwargs)
        finally:
            if monkeypatch:
                monkeypatch.undo()
            if tmpdir:
                tmpdir.cleanup()
    print(f"{len(tests)} tests passed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
