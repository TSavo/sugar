"""Measurement integrity for Criterion-2 process floors (S0.2 repair).

Two co-equal defects from run 30727525884:

1. Scratch must never mkdir under the population root (read-only vendor tree).
2. Pre-measure crash must never serialize bankable ``R_axis = 0``.

Recognition/teeth only — no corpus run, no drain.
"""

from __future__ import annotations

import importlib.util
import os
import stat
from pathlib import Path

import pytest

from sugar_lift_py_tests.repo_root import sugar_lift_py_tests_package_root

_KIT = sugar_lift_py_tests_package_root()
_RUNTIME = _KIT / "scripts" / "_enum_floor_runtime.py"
_SPEC = importlib.util.spec_from_file_location("enum_floor_runtime", _RUNTIME)
assert _SPEC is not None and _SPEC.loader is not None
_RT = importlib.util.module_from_spec(_SPEC)
_SPEC.loader.exec_module(_RT)


def test_default_out_dir_is_never_under_population(tmp_path: Path, monkeypatch) -> None:
    population = tmp_path / "site-packages" / "pandas"
    population.mkdir(parents=True)
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    monkeypatch.setenv("SUGAR_FLOOR_WORKSPACE", str(workspace))
    monkeypatch.delenv("GITHUB_WORKSPACE", raising=False)
    monkeypatch.delenv("RUNNER_TEMP", raising=False)

    out = _RT.default_out_dir(population, "timeout")
    assert out == workspace / ".sugar" / "ci-floors" / "timeout"
    # Must not nest under the population even when env is empty later.
    assert population.resolve() not in out.resolve().parents
    assert not str(out.resolve()).startswith(str(population.resolve()))


def test_prepare_floor_io_refuses_scratch_under_population(tmp_path: Path) -> None:
    population = tmp_path / "pandas"
    population.mkdir()
    under = population / ".sugar" / "ci-floors" / "native-crash"
    with pytest.raises(ValueError, match="must not live under the population"):
        _RT.prepare_floor_io(
            repo_root=population,
            floor="native-crash",
            out_dir=under,
            engine_log=None,
            progress=None,
        )


def test_prepare_floor_io_uses_workspace_when_population_is_read_only(
    tmp_path: Path, monkeypatch
) -> None:
    """Plant: non-writable population. Scratch still lands and is outside it."""
    population = tmp_path / "pandas"
    population.mkdir()
    # Make population non-writable (no mkdir of children).
    population.chmod(stat.S_IRUSR | stat.S_IXUSR)
    workspace = tmp_path / "ws"
    workspace.mkdir()
    monkeypatch.setenv("SUGAR_FLOOR_WORKSPACE", str(workspace))
    monkeypatch.delenv("GITHUB_WORKSPACE", raising=False)
    monkeypatch.delenv("RUNNER_TEMP", raising=False)
    # Avoid importing the full kit just to open engine logs.
    monkeypatch.setattr(_RT, "configure_engine_log", lambda path: None)
    monkeypatch.setattr(_RT, "silence_console_logging", lambda: None)

    try:
        base, engine, progress = _RT.prepare_floor_io(
            repo_root=population,
            floor="silent",
            out_dir=None,
            engine_log=None,
            progress=None,
        )
    finally:
        population.chmod(stat.S_IRWXU)

    assert base.is_dir()
    assert base.resolve().is_relative_to(workspace.resolve())
    assert not base.resolve().is_relative_to(population.resolve())
    assert engine.parent == base
    assert progress.parent == base


def test_format_unmeasured_never_serializes_r_equals_zero() -> None:
    """Plant: pre-measure crash path — artifact must not bank R=0."""
    text = _RT.format_unmeasured_axis(
        "R_timeouts", reason="PermissionError: mkdir under population"
    )
    assert "unmeasured" in text
    assert "completed-with-error" in text
    assert "no-value" in text
    assert "R_timeouts = 0" not in text
    assert " = 0" not in text


def test_configure_engine_log_defaults_trace_off_and_does_not_re_raise_debug(
    tmp_path: Path, monkeypatch
) -> None:
    """TRACE=0 must short-circuit DEBUG enter/exit before json.dumps.

    The pre-#7039 floor bug: setLevel(DEBUG) after configure made TRACE=0 a
    no-op — FileHandler filtered, but every span still serialised.
    """
    import json
    import logging
    import os
    import time

    # Kit path for engine_log import inside configure_engine_log.
    kit_src = _KIT / "src"
    monkeypatch.syspath_prepend(str(kit_src))

    from sugar_lift_py_tests import engine_log

    path = tmp_path / "engine.jsonl"
    previous = engine_log._LIVE_HANDLER
    engine_log._LIVE_HANDLER = None
    engine_log.LOGGER.handlers.clear()
    # Ambient TRACE=1 must not win over the floor default.
    monkeypatch.setenv("SUGAR_ENGINE_TRACE_EVENTS", "1")
    dumps_calls: list[int] = []
    real_dumps = engine_log.json.dumps

    def counting_dumps(*args, **kwargs):
        dumps_calls.append(1)
        return real_dumps(*args, **kwargs)

    monkeypatch.setattr(engine_log.json, "dumps", counting_dumps)
    try:
        _RT.configure_engine_log(path)
        assert os.environ["SUGAR_ENGINE_TRACE_EVENTS"] == "0"
        assert engine_log.LOGGER.level == logging.WARNING
        assert not engine_log.LOGGER.isEnabledFor(logging.DEBUG)
        with engine_log.reduction_span(
            sugar="NameSugar", role="term", site="floor.py:1:0"
        ):
            assert dumps_calls == []
            engine_log._emit_heartbeats(
                now=time.monotonic() + 1.0, minimum_seconds=0.01
            )
        events = [json.loads(line)["event"] for line in path.read_text().splitlines()]
        assert events == ["heartbeat"]
        assert len(dumps_calls) == 1
    finally:
        if engine_log._LIVE_HANDLER is not None:
            engine_log.LOGGER.removeHandler(engine_log._LIVE_HANDLER)
            engine_log._LIVE_HANDLER.close()
        engine_log._LIVE_HANDLER = previous
        engine_log.json.dumps = real_dumps
        engine_log.LOGGER.handlers.clear()


def test_format_completed_zero_only_when_measurement_finished() -> None:
    """Completed measurement with zero findings may print = 0; that is honest."""
    text = _RT.format_completed_axis_report("R_silent", 0)
    assert text == "R_silent = 0"


def test_sole_construction_group_names_do_not_embed_equals_zero() -> None:
    here = Path(__file__).resolve()
    floors = None
    for parent in [here, *here.parents]:
        candidate = parent / "tools" / "run_sole_construction_floors.sh"
        if candidate.is_file():
            floors = candidate
            break
    assert floors is not None, "run_sole_construction_floors.sh not found"
    text = floors.read_text(encoding="utf-8")
    for axis in (
        "R_native_crashes",
        "R_bare_exceptions",
        "R_timeouts",
        "R_silent",
    ):
        needle = f'axis "{axis}"'
        assert needle in text, f"missing {needle}"
        assert f'axis "{axis} = 0"' not in text
    assert "FLOOR_SCRATCH" in text or "--out-dir" in text
