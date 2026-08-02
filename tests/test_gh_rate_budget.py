"""Focused tests for tools/gh_rate_budget.py — no live GitHub when mocked."""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
TOOL = ROOT / "tools" / "gh_rate_budget.py"


def _run(env_extra: dict[str, str] | None = None, args: list[str] | None = None) -> subprocess.CompletedProcess[str]:
    env = {**dict(**{k: v for k, v in __import__("os").environ.items()})}
    if env_extra:
        env.update(env_extra)
    return subprocess.run(
        [sys.executable, str(TOOL), *(args or ["--json"])],
        cwd=str(ROOT),
        capture_output=True,
        text=True,
        check=False,
        env=env,
    )


def test_help_or_import_main_exists() -> None:
    assert TOOL.is_file()
    text = TOOL.read_text(encoding="utf-8")
    assert "EXIT_BUDGET = 79" in text
    assert "github-api-budget-low" in text


def test_wrap_argv_parsing_documented() -> None:
    text = TOOL.read_text(encoding="utf-8")
    assert "-- wrap" in text
    assert "autoscaler_pat" in text


def test_bin_wrapper_exists() -> None:
    wrapper = ROOT / "bin" / "gh-budget"
    assert wrapper.is_file()
    body = wrapper.read_text(encoding="utf-8")
    assert "gh_rate_budget.py" in body
