from __future__ import annotations

import importlib
import os
import subprocess
import sys
from pathlib import Path

import numpy
import pytest

from sugar_lift_py_tests.idd import (
    CommandResult,
    collect_panic_audit,
    main,
    render_text,
)

panic_audit_module = importlib.import_module(
    "sugar_lift_py_tests.idd.collect_panic_audit"
)
from sugar_lift_py_tests.idd.collect_panic_audit import (
    _cached_audit_workspace,
    _prepare_audit_workspace,
)
from sugar_lift_py_tests.witness_harness import _ensure_sugar_bin

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
                    "write more Floor for this Construction: owner=pandas.frame.sum blame=pandas.py:3:8 "
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
    assert all("--audit-only" not in command for command in calls)
    assert all(
        command[:4] == ["sugar", "lift", "--report", "--visual"] for command in calls
    )

    text = render_text(report)
    assert "python numpy/pandas lift panic audit" in text
    assert "R:" in text
    assert "write more Sugar for this AST" in text
    assert "write more Floor for this AST" in text
    assert "fix=create sugar_lift_py_tests.sugar.call.call_sugar" in text


def test_installed_package_audit_target_counts_against_language_axis(tmp_path) -> None:
    (tmp_path / "examples/numpy-showcase").mkdir(parents=True)
    (tmp_path / "examples/pandas-showcase").mkdir(parents=True)
    package = tmp_path / "site-packages/numpy"
    package.mkdir(parents=True)
    (package / "sample.py").write_text(
        "def f():\n    assert not g()\n", encoding="utf-8"
    )
    calls: list[list[str]] = []

    def fake_runner(command: list[str], cwd: Path) -> CommandResult:
        calls.append(command)
        target = command[-1]
        if target.endswith("numpy-showcase") or target.endswith("pandas-showcase"):
            return CommandResult(returncode=0, stdout="", stderr="")
        assert target.endswith("numpy")
        return CommandResult(
            returncode=1,
            stdout=(
                "write more Sugar for this AST: owner=python.factory.literal-call "
                "blame=sample.py:2:4 observed=assert-test:UnaryOp "
                "requested=EqualityAssertion fix=lift this assertion shape\n"
            ),
            stderr="",
        )

    report = collect_panic_audit(
        tmp_path,
        run_command=fake_runner,
        installed_packages=("numpy",),
        package_path_resolver=lambda package_name: package,
    )

    assert [target.name for target in report.targets] == [
        "numpy",
        "pandas",
        "numpy-all",
    ]
    assert report.r.values == {
        "numpy_sugar_panics": 1,
        "numpy_floor_panics": 0,
        "pandas_sugar_panics": 0,
        "pandas_floor_panics": 0,
        "unexpected_panics": 0,
    }
    assert all(
        command[:4] == ["sugar", "lift", "--report", "--visual"] for command in calls
    )


def test_audit_workspace_manifest_passes_audit_flag_to_python_lifter(tmp_path) -> None:
    target = tmp_path / "target"
    stale_manifest = target / ".sugar/lift/python/manifest.toml"
    stale_manifest.parent.mkdir(parents=True)
    stale_manifest.write_text(
        'command = ["python3", "-m", "sugar_lift_py_tests.lsp"]\n',
        encoding="utf-8",
    )
    (target / "pkg").mkdir()
    (target / "pkg/sample.py").write_text("def f():\n    return {}\n", encoding="utf-8")
    audit_workspace = tmp_path / "audit"

    _prepare_audit_workspace(target, ROOT, audit_workspace)

    config = (audit_workspace / ".sugar/config.toml").read_text(encoding="utf-8")
    manifest = (audit_workspace / ".sugar/lift/python/manifest.toml").read_text(
        encoding="utf-8"
    )
    assert (audit_workspace / "pkg/sample.py").is_file()
    assert 'emit = "ir-document"' in config
    assert "sugar_lift_py_tests/lift_rpc.py" in manifest
    assert '"--rpc", "--audit-only"' in manifest
    assert "sugar_lift_py_tests.lsp" not in manifest


def test_audit_workspace_cache_reuses_same_stamp(
    tmp_path, monkeypatch: pytest.MonkeyPatch
) -> None:
    target = tmp_path / "target"
    (target / "pkg").mkdir(parents=True)
    (target / "pkg/sample.py").write_text("def f():\n    return 1\n", encoding="utf-8")
    cache_root = tmp_path / "cache"
    monkeypatch.setenv("SUGAR_PANIC_AUDIT_WORKSPACE_CACHE_DIR", str(cache_root))

    cold = _cached_audit_workspace(target, ROOT)
    warm = _cached_audit_workspace(target, ROOT)

    assert cold.cache_key == warm.cache_key
    assert cold.workspace == warm.workspace
    assert cold.hit is False
    assert warm.hit is True
    assert (warm.workspace / "pkg/sample.py").read_text(encoding="utf-8") == (
        "def f():\n    return 1\n"
    )


def test_audit_workspace_cache_misses_when_vendor_source_changes(
    tmp_path, monkeypatch: pytest.MonkeyPatch
) -> None:
    target = tmp_path / "target"
    (target / "pkg").mkdir(parents=True)
    sample = target / "pkg/sample.py"
    sample.write_text("VALUE = 1\n", encoding="utf-8")
    cache_root = tmp_path / "cache"
    monkeypatch.setenv("SUGAR_PANIC_AUDIT_WORKSPACE_CACHE_DIR", str(cache_root))

    before = _cached_audit_workspace(target, ROOT)
    sample.write_text("VALUE = 2\n", encoding="utf-8")
    after = _cached_audit_workspace(target, ROOT)

    assert before.cache_key != after.cache_key
    assert before.workspace != after.workspace
    assert before.hit is False
    assert after.hit is False
    assert (before.workspace / "pkg/sample.py").read_text(encoding="utf-8") == (
        "VALUE = 1\n"
    )
    assert (after.workspace / "pkg/sample.py").read_text(encoding="utf-8") == (
        "VALUE = 2\n"
    )


def test_lift_command_uses_cached_audit_workspace(
    tmp_path, monkeypatch: pytest.MonkeyPatch
) -> None:
    target = tmp_path / "target"
    (target / "pkg").mkdir(parents=True)
    (target / "pkg/sample.py").write_text("VALUE = 1\n", encoding="utf-8")
    cache_root = tmp_path / "cache"
    monkeypatch.setenv("SUGAR_PANIC_AUDIT_WORKSPACE_CACHE_DIR", str(cache_root))
    commands: list[list[str]] = []

    def fake_subprocess(command: list[str], cwd: Path) -> CommandResult:
        commands.append(command)
        return CommandResult(0, "", "")

    monkeypatch.setattr(panic_audit_module, "_run_subprocess", fake_subprocess)

    command = ["sugar", "lift", "--report", "--visual", str(target)]
    assert panic_audit_module._run_command(command, ROOT).returncode == 0
    assert panic_audit_module._run_command(command, ROOT).returncode == 0

    assert len(commands) == 2
    assert commands[0][-1] == commands[1][-1]
    cached_workspace = Path(commands[0][-1])
    assert cached_workspace.is_dir()
    assert cached_workspace.parent.parent == cache_root


def test_cli_exits_red_until_numpy_pandas_have_zero_panics(monkeypatch, capsys) -> None:
    from sugar_lift_py_tests.idd import cli

    def fake_collect(root: Path, **_kwargs):
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
        return CommandResult(
            returncode=1, stdout="", stderr="error: no construction gaps\n"
        )

    report = collect_panic_audit(ROOT, run_command=failing_runner)

    assert report.r.values["unexpected_panics"] == 2
    assert not report.is_zero
    assert all(record.kind == "unexpected" for record in report.records)


def test_extracts_audit_only_gaps_from_rust_wrapped_rpc_error() -> None:
    def failing_runner(command: list[str], cwd: Path) -> CommandResult:
        return CommandResult(
            returncode=1,
            stdout="",
            stderr=(
                "\x1b[1m\x1b[31merror\x1b[39m\x1b[0m: kit transform failed: "
                "lift plugin transport: lift plugin returned error: "
                '{"code":-32603,"message":"audit-only construction gaps",'
                '"data":{"auditOnlyGaps":[{"kind":"audit-only-construction-gap",'
                '"label":"a.py","message":"write more Sugar for this AST: '
                "owner=python.factory blame=a.py:1:0 observed=Dict requested=term "
                'fix=create sugar_lift_py_tests.sugar.dict.dict_sugar",'
                '"gap":{"owner":"python.factory","blame":"a.py:1:0",'
                '"observed":"Dict","requested":"term",'
                '"fix":"create sugar_lift_py_tests.sugar.dict.dict_sugar"},'
                '"auditRow":{}},{"kind":"audit-only-construction-gap",'
                '"label":"b.py","message":"write more Floor for this Construction: '
                "owner=python-test blame=b.py:2:4 observed=TermValue requested=map_with "
                'fix=add map_with to TermValue or emit a real effect",'
                '"gap":{"owner":"python-test","blame":"b.py:2:4",'
                '"observed":"TermValue","requested":"map_with",'
                '"fix":"add map_with to TermValue or emit a real effect"},'
                '"auditRow":{}}]}}\n'
            ),
        )

    report = collect_panic_audit(ROOT, run_command=failing_runner)

    assert report.r.values == {
        "numpy_sugar_panics": 1,
        "numpy_floor_panics": 1,
        "pandas_sugar_panics": 1,
        "pandas_floor_panics": 1,
        "unexpected_panics": 0,
    }


def test_extracts_audit_only_gaps_when_rust_adds_trailing_context() -> None:
    def failing_runner(command: list[str], cwd: Path) -> CommandResult:
        return CommandResult(
            returncode=1,
            stdout="",
            stderr=(
                "error: kit transform failed: lift plugin transport: "
                "lift plugin returned error: "
                '{"code":-32603,"message":"audit-only construction gaps",'
                '"data":{"auditOnlyGaps":[{"kind":"audit-only-construction-gap",'
                '"label":"a.py","message":"write more Sugar for this AST: '
                "owner=python.factory blame=a.py:1:0 observed=Call requested=term "
                'fix=add call sugar","gap":{"owner":"python.factory",'
                '"blame":"a.py:1:0","observed":"Call","requested":"term",'
                '"fix":"add call sugar"},"auditRow":{}},'
                '{"kind":"audit-only-construction-gap","label":"b.py",'
                '"message":"write more Sugar for this AST: '
                "owner=python.factory blame=b.py:2:0 observed=Dict requested=term "
                'fix=add dict sugar","gap":{"owner":"python.factory",'
                '"blame":"b.py:2:0","observed":"Dict","requested":"term",'
                '"fix":"add dict sugar"},"auditRow":{}}]}}; '
                "fix=Inspect the lift PathAlgebra step and keep errors structured\n"
            ),
        )

    report = collect_panic_audit(
        ROOT,
        run_command=failing_runner,
        installed_packages=("numpy",),
        include_showcases=False,
        package_path_resolver=lambda _package: ROOT / "examples/numpy-showcase",
    )

    assert report.r.values == {
        "numpy_sugar_panics": 2,
        "numpy_floor_panics": 0,
        "pandas_sugar_panics": 0,
        "pandas_floor_panics": 0,
        "unexpected_panics": 0,
    }


def test_installed_numpy_totality_gate_is_stable_zero(monkeypatch) -> None:
    sugar = _ensure_sugar_bin()
    monkeypatch.setenv(
        "PATH",
        f"{sugar.parent}{os.pathsep}{os.environ.get('PATH', '')}",
    )

    report = collect_panic_audit(
        ROOT,
        installed_packages=("numpy",),
        include_showcases=False,
    )

    assert report.r.values == {
        "numpy_sugar_panics": 0,
        "numpy_floor_panics": 0,
        "pandas_sugar_panics": 0,
        "pandas_floor_panics": 0,
        "unexpected_panics": 0,
    }, f"numpy {numpy.__version__} construction-gap gate reopened: {render_text(report)}"
    assert not report.records


def test_extracts_audit_only_loud_floor_type_error() -> None:
    def failing_runner(command: list[str], cwd: Path) -> CommandResult:
        return CommandResult(
            returncode=1,
            stdout="",
            stderr=(
                "error: kit transform failed: lift plugin transport: "
                "lift plugin returned error: "
                '{"code":-32603,"message":"audit-only construction gaps",'
                '"data":{"auditOnlyGaps":[{"kind":"audit-only-construction-gap",'
                '"label":"numpy/core.py","message":"write more Floor for '
                'StringSubscriptSugar receiver: expected StringValue got SymbolicValue",'
                '"gap":{"owner":"StringSubscriptSugar receiver",'
                '"blame":"numpy/core.py","observed":"SymbolicValue",'
                '"requested":"StringValue","fix":"write the missing floor"},'
                '"auditRow":{}}]}}\n'
            ),
        )

    report = collect_panic_audit(ROOT, run_command=failing_runner)

    assert report.r.values == {
        "numpy_sugar_panics": 0,
        "numpy_floor_panics": 1,
        "pandas_sugar_panics": 0,
        "pandas_floor_panics": 1,
        "unexpected_panics": 0,
    }


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
