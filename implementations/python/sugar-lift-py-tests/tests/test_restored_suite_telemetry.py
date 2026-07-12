from __future__ import annotations

import importlib.util
from pathlib import Path

import pytest


_TOOL = Path(__file__).parents[4] / "tools" / "restored_suite_telemetry.py"
_SPEC = importlib.util.spec_from_file_location("restored_suite_telemetry", _TOOL)
assert _SPEC is not None and _SPEC.loader is not None
_MODULE = importlib.util.module_from_spec(_SPEC)
_SPEC.loader.exec_module(_MODULE)
markdown = _MODULE.markdown
restored_suite_vector = _MODULE.restored_suite_vector


def test_red_restored_suite_mints_failed_errors_modules_vector(tmp_path) -> None:
    log = tmp_path / "pytest.log"
    log.write_text(
        "FAILED tests/test_alpha.py::test_one - AssertionError\n"
        "FAILED tests/test_alpha.py::test_two - AssertionError\n"
        "ERROR tests/test_beta.py::test_setup - RuntimeError\n"
        "2 failed, 8 passed, 1 skipped, 1 error in 3.20s\n",
        encoding="utf-8",
    )

    vector = restored_suite_vector(log, pytest_exit=1)
    assert vector == (2, 1, 2)
    rendered = markdown("https://run", vector)
    assert "failed: 2" in rendered
    assert "errors: 1" in rendered
    assert "affected modules: 2" in rendered


def test_green_suite_is_valid_zero_vector(tmp_path) -> None:
    log = tmp_path / "pytest.log"
    log.write_text("12 passed in 0.40s\n", encoding="utf-8")

    assert restored_suite_vector(log, pytest_exit=0) == (0, 0, 0)


@pytest.mark.parametrize("pytest_exit", (2, 3, 4, 5, 137))
def test_suite_execution_failures_do_not_mint_telemetry(
    tmp_path, pytest_exit: int
) -> None:
    log = tmp_path / "pytest.log"
    log.write_text("collection aborted\n", encoding="utf-8")

    with pytest.raises(ValueError, match="did not complete"):
        restored_suite_vector(log, pytest_exit=pytest_exit)


def test_missing_terminal_summary_does_not_mint_telemetry(tmp_path) -> None:
    log = tmp_path / "pytest.log"
    log.write_text(
        "FAILED tests/test_alpha.py::test_one - AssertionError\n",
        encoding="utf-8",
    )

    with pytest.raises(ValueError, match="terminal summary"):
        restored_suite_vector(log, pytest_exit=1)
