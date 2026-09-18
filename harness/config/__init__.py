"""Config loaders. Each module loads one kind of config file and reports every problem in it.

Shared by the loaders:
- ConfigError carries every problem found in one file, so callers can print them all.
- read_yaml turns a file into a mapping, or raises ConfigError saying why it could not.
"""

from __future__ import annotations

from pathlib import Path

import yaml


class ConfigError(Exception):
    """Every problem found in one config file."""

    def __init__(self, path: Path, problems: list[str]):
        super().__init__(f"{path}: {len(problems)} problem(s)")
        self.path = Path(path)
        self.problems = problems


def read_yaml(path: Path, expected: str) -> dict:
    """Load a YAML file that must hold a mapping. `expected` describes that mapping for errors."""
    path = Path(path)
    if not path.exists():
        raise ConfigError(path, ["file not found"])
    try:
        raw = yaml.safe_load(path.read_text(encoding="utf-8"))
    except yaml.YAMLError as err:
        mark = getattr(err, "problem_mark", None)
        where = f"line {mark.line + 1}: " if mark else ""
        raise ConfigError(path, [f"{where}not valid YAML ({getattr(err, 'problem', err)})"]) from None
    if not isinstance(raw, dict):
        raise ConfigError(path, [f"expected {expected}"])
    return raw
