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

ROOT = Path(__file__).resolve().parents[4]


def _is_visual_lift(command: list[str]) -> bool:
    return command[1:4] == ["lift", "--report", "--visual"]


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
        "statistics_sugar_panics": 0,
        "statistics_floor_panics": 0,
        "decimal_sugar_panics": 0,
        "decimal_floor_panics": 0,
        "fractions_sugar_panics": 0,
        "fractions_floor_panics": 0,
        "unexpected_panics": 0,
    }
    assert len(report.records) == 3
    assert all("--audit-only" not in command for command in calls)
    assert all(_is_visual_lift(command) for command in calls)

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
        "statistics_sugar_panics": 0,
        "statistics_floor_panics": 0,
        "decimal_sugar_panics": 0,
        "decimal_floor_panics": 0,
        "fractions_sugar_panics": 0,
        "fractions_floor_panics": 0,
        "unexpected_panics": 0,
    }
    assert all(_is_visual_lift(command) for command in calls)


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

    command = ["/cache/sugar-stamp", "lift", "--report", "--visual", str(target)]
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
        "statistics_sugar_panics": 0,
        "statistics_floor_panics": 0,
        "decimal_sugar_panics": 0,
        "decimal_floor_panics": 0,
        "fractions_sugar_panics": 0,
        "fractions_floor_panics": 0,
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
        "statistics_sugar_panics": 0,
        "statistics_floor_panics": 0,
        "decimal_sugar_panics": 0,
        "decimal_floor_panics": 0,
        "fractions_sugar_panics": 0,
        "fractions_floor_panics": 0,
        "unexpected_panics": 0,
    }


def test_installed_numpy_totality_gate_is_stable_zero() -> None:
    """Installed numpy package construction-gap R stays at 0 (per-package arm)."""
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
        "statistics_sugar_panics": 0,
        "statistics_floor_panics": 0,
        "decimal_sugar_panics": 0,
        "decimal_floor_panics": 0,
        "fractions_sugar_panics": 0,
        "fractions_floor_panics": 0,
        "unexpected_panics": 0,
    }, f"numpy {numpy.__version__} construction-gap gate reopened: {render_text(report)}"
    assert not report.records


def test_installed_pandas_totality_gate_is_stable_zero() -> None:
    """Installed pandas package construction-gap R stays at 0 (per-package arm)."""
    import pandas

    report = collect_panic_audit(
        ROOT,
        installed_packages=("pandas",),
        include_showcases=False,
    )

    assert report.r.values == {
        "numpy_sugar_panics": 0,
        "numpy_floor_panics": 0,
        "pandas_sugar_panics": 0,
        "pandas_floor_panics": 0,
        "statistics_sugar_panics": 0,
        "statistics_floor_panics": 0,
        "decimal_sugar_panics": 0,
        "decimal_floor_panics": 0,
        "fractions_sugar_panics": 0,
        "fractions_floor_panics": 0,
        "unexpected_panics": 0,
    }, (
        f"pandas {pandas.__version__} construction-gap gate reopened: "
        f"{render_text(report)}"
    )
    assert not report.records


def test_numpy_pandas_wall_construction_gap_r_is_stable_zero() -> None:
    """Capstone ratchet: combined installed numpy+pandas construction-gap R == 0.

    Part of #3809. The drain sequence repeatedly unmasked deeper floors once a
    recognizer/totalizer closed; this gate measures the same combined R vector
    drain workers read on battleaxe and refuses any silent climb after honest-0.
    """
    import pandas

    report = collect_panic_audit(
        ROOT,
        installed_packages=("numpy", "pandas"),
        include_showcases=False,
    )

    assert report.is_zero, (
        f"numpy {numpy.__version__} + pandas {pandas.__version__} wall R reopened: "
        f"{render_text(report)}"
    )
    assert report.r.is_zero
    assert not report.records
    assert not report.diagnostics
    assert sum(report.r.values.values()) == 0


def test_installed_statistics_totality_gate_is_stable_zero() -> None:
    """Third-vendor pin: installed stdlib statistics construction-gap R == 0.

    Part of #3809 Task G. Single-module packages resolve to the module *file*
    (not the parent stdlib directory — that would audit asyncio/inspect and
    paper over with false panics). Panic / R>0 is sacred.
    """
    import statistics

    report = collect_panic_audit(
        ROOT,
        installed_packages=("statistics",),
        include_showcases=False,
    )
    r_total = sum(report.r.values.values())

    assert report.r.values == {
        "numpy_sugar_panics": 0,
        "numpy_floor_panics": 0,
        "pandas_sugar_panics": 0,
        "pandas_floor_panics": 0,
        "statistics_sugar_panics": 0,
        "statistics_floor_panics": 0,
        "decimal_sugar_panics": 0,
        "decimal_floor_panics": 0,
        "fractions_sugar_panics": 0,
        "fractions_floor_panics": 0,
        "unexpected_panics": 0,
    }, (
        f"statistics module construction-gap gate reopened (R={r_total}): "
        f"path={statistics.__file__} {render_text(report)}"
    )
    assert r_total == 0
    assert report.is_zero
    assert not report.records
    assert [t.name for t in report.targets] == ["statistics-all"]


def test_installed_decimal_totality_gate_is_stable_zero() -> None:
    """Fourth-vendor pin: pure-python decimal body construction-gap R == 0.

    Part of #3809. Public ``decimal`` prefers C ``_decimal``; the audit resolves
    to pure-python ``_pydecimal.py`` (never the C extension, never the thin
    ``decimal.py`` reexport alone — that would false-zero R). Panic / R>0 is sacred.
    """
    path = panic_audit_module._resolve_installed_package_path("decimal")

    report = collect_panic_audit(
        ROOT,
        installed_packages=("decimal",),
        include_showcases=False,
    )
    r_total = sum(report.r.values.values())

    assert report.r.values == {
        "numpy_sugar_panics": 0,
        "numpy_floor_panics": 0,
        "pandas_sugar_panics": 0,
        "pandas_floor_panics": 0,
        "statistics_sugar_panics": 0,
        "statistics_floor_panics": 0,
        "decimal_sugar_panics": 0,
        "decimal_floor_panics": 0,
        "fractions_sugar_panics": 0,
        "fractions_floor_panics": 0,
        "unexpected_panics": 0,
    }, (
        f"decimal pure-python body construction-gap gate reopened (R={r_total}): "
        f"path={path} {render_text(report)}"
    )
    assert r_total == 0
    assert report.is_zero
    assert not report.records
    assert [t.name for t in report.targets] == ["decimal-all"]
    assert path.is_file()
    assert path.name == "_pydecimal.py", path


def test_installed_fractions_totality_gate_is_stable_zero() -> None:
    """Fifth-vendor pin: installed stdlib fractions construction-gap R == 0.

    Part of #3809. Pure-python single-module ``fractions.py`` (like statistics) —
    resolve to the module *file*, never the parent stdlib directory. Panic / R>0
    is sacred.
    """
    import fractions

    path = panic_audit_module._resolve_installed_package_path("fractions")

    report = collect_panic_audit(
        ROOT,
        installed_packages=("fractions",),
        include_showcases=False,
    )
    r_total = sum(report.r.values.values())

    assert report.r.values == {
        "numpy_sugar_panics": 0,
        "numpy_floor_panics": 0,
        "pandas_sugar_panics": 0,
        "pandas_floor_panics": 0,
        "statistics_sugar_panics": 0,
        "statistics_floor_panics": 0,
        "decimal_sugar_panics": 0,
        "decimal_floor_panics": 0,
        "fractions_sugar_panics": 0,
        "fractions_floor_panics": 0,
        "unexpected_panics": 0,
    }, (
        f"fractions module construction-gap gate reopened (R={r_total}): "
        f"path={path} {render_text(report)}"
    )
    assert r_total == 0
    assert report.is_zero
    assert not report.records
    assert [t.name for t in report.targets] == ["fractions-all"]
    assert path.is_file()
    assert path.name == "fractions.py", path
    assert path == Path(fractions.__file__).resolve() or path.name == "fractions.py"


def test_fractions_resolves_to_module_file_not_stdlib_dir() -> None:
    """fractions must resolve to fractions.py — not the parent stdlib tree."""
    path = panic_audit_module._resolve_installed_package_path("fractions")
    assert path.is_file(), path
    assert path.name == "fractions.py", path
    assert not str(path).endswith((".so", ".pyd", ".dll"))
    text = path.read_text(encoding="utf-8", errors="replace")
    assert "class Fraction" in text
    assert len(text) > 5_000, "expected full pure-python body"


def test_single_module_package_resolves_to_module_file_not_stdlib_dir() -> None:
    """statistics must not resolve to /usr/lib/pythonX.Y (entire stdlib)."""
    path = panic_audit_module._resolve_installed_package_path("statistics")
    assert path.is_file(), path
    assert path.name == "statistics.py", path
    assert path.parent.name.startswith("python") or "site-packages" in str(path)


def test_decimal_resolves_to_pure_python_pydecimal_not_c_extension() -> None:
    """decimal audit path is _pydecimal.py — not decimal.py shim, not _decimal.so."""
    path = panic_audit_module._resolve_installed_package_path("decimal")
    assert path.is_file(), path
    assert path.name == "_pydecimal.py", path
    assert not str(path).endswith((".so", ".pyd", ".dll"))
    assert "lib-dynload" not in str(path)
    # Must not be the thin reexport alone (that would false-zero R).
    text = path.read_text(encoding="utf-8", errors="replace")
    assert "class Decimal" in text
    assert len(text) > 10_000, "expected full pure-python body, not thin shim"


def test_prepare_audit_workspace_stages_single_module_file(tmp_path) -> None:
    """Single-module targets must stage the .py file (rglob on a file is empty)."""
    module = tmp_path / "statistics.py"
    module.write_text("def mean(xs):\n    return sum(xs) / len(xs)\n", encoding="utf-8")
    workspace = tmp_path / "audit-ws"
    panic_audit_module._prepare_audit_workspace(module, ROOT, workspace)
    staged = workspace / "statistics.py"
    assert staged.is_file()
    assert "def mean" in staged.read_text(encoding="utf-8")
    assert (workspace / ".sugar/config.toml").is_file()


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
        "statistics_sugar_panics": 0,
        "statistics_floor_panics": 0,
        "decimal_sugar_panics": 0,
        "decimal_floor_panics": 0,
        "fractions_sugar_panics": 0,
        "fractions_floor_panics": 0,
        "unexpected_panics": 0,
    }


def test_missing_sugar_binary_counts_as_unexpected(tmp_path, monkeypatch) -> None:
    (tmp_path / "examples/numpy-showcase").mkdir(parents=True)
    (tmp_path / "examples/pandas-showcase").mkdir(parents=True)
    monkeypatch.setenv("PATH", "")

    report = collect_panic_audit(tmp_path, sugar_bin=tmp_path / "missing-stamp-sugar")

    assert report.r.values["unexpected_panics"] == 2
    assert all(record.observed == "exit=127" for record in report.records)
    assert all(
        "unable to execute" in record.message
        and "missing-stamp-sugar" in record.message
        for record in report.records
    )


def test_module_entrypoint_runs_cli(tmp_path) -> None:
    (tmp_path / "examples/numpy-showcase").mkdir(parents=True)
    (tmp_path / "examples/pandas-showcase").mkdir(parents=True)
    fake_bin = tmp_path / "bin"
    fake_bin.mkdir()
    sugar = fake_bin / "sugar-darwin-x86_64-release-blake3_abc123"
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
        "SUGAR_BIN": os.fspath(sugar),
        "PATH": os.environ.get("PATH", ""),
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
