from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

from sugar_lift_py_tests.idd import (
    CommandResult,
    collect_panic_audit,
    main,
    render_text,
)


ROOT = Path(__file__).resolve().parents[4]


def test_numpy_pandas_r_is_measured_from_observed_panics() -> None:
    calls: list[list[str]] = []

    def fake_runner(command: list[str], cwd: Path) -> CommandResult:
        calls.append(command)
        target = command[-1]
        if target.endswith("examples/numpy-showcase"):
            return CommandResult(
                returncode=1,
                stdout=(
                    "write more Sugar for this AST: owner=factory blame=numpy.py:1:0 "
                    "observed=Call requested=Term fix=create sugar_lift_py_tests.sugar.call.call_sugar\n"
                    "write more Floor for this AST: owner=numpy.reshape blame=numpy.py:2:4 "
                    "observed=Call requested=SequenceFloor fix=add SequenceFloor visitor for numpy.reshape\n"
                ),
                stderr="",
            )
        if target.endswith("examples/pandas-showcase"):
            return CommandResult(
                returncode=1,
                stdout=(
                    "write more Floor for this construction: owner=pandas.frame.sum blame=pandas.py:3:8 "
                    "observed=DataFrame requested=BodyUniverseFloor fix=add BodyUniverseFloor for pandas sum\n"
                ),
                stderr="",
            )
        raise AssertionError(target)

    report = collect_panic_audit(ROOT, run_command=fake_runner)

    assert report.r.values == {
        "numpy_sugar_panics": 1,
        "numpy_floor_panics": 1,
        "pandas_sugar_panics": 0,
        "pandas_floor_panics": 1,
        "unexpected_panics": 0,
    }
    assert len(report.records) == 3
    assert all("--audit-only" in command for command in calls)
    assert all(command[:2] == ["sugar", "lift"] for command in calls)

    text = render_text(report)
    assert "python numpy/pandas lift panic audit" in text
    assert "R:" in text
    assert "write more Sugar for this AST" in text
    assert "write more Floor for this AST" in text
    assert "fix=create sugar_lift_py_tests.sugar.call.call_sugar" in text


def test_cli_exits_red_until_numpy_pandas_have_zero_panics(monkeypatch, capsys) -> None:
    from sugar_lift_py_tests.idd import cli

    def fake_collect(root: Path):
        return collect_panic_audit(
            root,
            run_command=lambda command, cwd: CommandResult(
                returncode=1,
                stdout=(
                    "write more Sugar for this AST: owner=factory blame=x.py:1:0 "
                    "observed=Call requested=Term fix=create sugar_lift_py_tests.sugar.call.call_sugar\n"
                ),
                stderr="",
            ),
        )

    monkeypatch.setattr(cli, "collect_panic_audit", fake_collect)

    exit_code = main(["--root", str(ROOT)])
    stdout = capsys.readouterr().out
    assert exit_code == 1
    assert "numpy_sugar_panics" in stdout
    assert "fix:" in stdout


def test_failed_lift_without_gap_records_counts_as_unexpected() -> None:
    def failing_runner(command: list[str], cwd: Path) -> CommandResult:
        return CommandResult(returncode=2, stdout="", stderr="error: unknown option --audit-only\n")

    report = collect_panic_audit(ROOT, run_command=failing_runner)

    assert report.r.values["unexpected_panics"] == 2
    assert not report.is_zero
    assert all(record.kind == "unexpected" for record in report.records)


def test_missing_sugar_binary_counts_as_unexpected(tmp_path, monkeypatch) -> None:
    (tmp_path / "examples/numpy-showcase").mkdir(parents=True)
    (tmp_path / "examples/pandas-showcase").mkdir(parents=True)
    monkeypatch.setenv("PATH", "")

    report = collect_panic_audit(tmp_path)

    assert report.r.values["unexpected_panics"] == 2
    assert all(record.observed == "exit=127" for record in report.records)
    assert all("unable to execute sugar" in record.message for record in report.records)


def test_module_entrypoint_runs_cli(tmp_path) -> None:
    (tmp_path / "examples/numpy-showcase").mkdir(parents=True)
    (tmp_path / "examples/pandas-showcase").mkdir(parents=True)
    fake_bin = tmp_path / "bin"
    fake_bin.mkdir()
    sugar = fake_bin / "sugar"
    sugar.write_text(
        """#!/bin/sh
case "$*" in
  *numpy-showcase*)
    echo "write more Sugar for this AST: owner=factory blame=numpy.py:1:0 observed=Call requested=Term fix=create sugar_lift_py_tests.sugar.call.call_sugar"
    exit 1
    ;;
  *pandas-showcase*)
    echo "write more Floor for this AST: owner=pandas.sum blame=pandas.py:2:0 observed=Call requested=BodyUniverseFloor fix=add BodyUniverseFloor for pandas.sum"
    exit 1
    ;;
esac
exit 0
""",
        encoding="utf-8",
    )
    sugar.chmod(0o755)
    env = {
        **os.environ,
        "PATH": f"{fake_bin}{os.pathsep}{os.environ.get('PATH', '')}",
        "PYTHONPATH": str(ROOT / "implementations/python/sugar-lift-py-tests/src"),
    }

    completed = subprocess.run(
        [
            sys.executable,
            "-m",
            "sugar_lift_py_tests.idd.cli",
            "--root",
            str(tmp_path),
            "--json",
        ],
        text=True,
        capture_output=True,
        check=False,
        env=env,
    )

    assert completed.returncode == 1
    assert '"kind": "python-numpy-pandas-panic-audit"' in completed.stdout
    assert '"numpy_sugar_panics": 1' in completed.stdout
    assert '"pandas_floor_panics": 1' in completed.stdout
