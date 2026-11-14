from __future__ import annotations

import json
import tomllib
from pathlib import Path

import pytest

from sugar_lift_py_tests.idd.command_result import CommandResult
from sugar_lift_py_tests.idd.pandas_wall import (
    PandasWallFloors,
    PandasWallSummary,
    build_pandas_wall,
    check_pandas_wall_floors,
)
from sugar_lift_py_tests.repo_root import resolve_repo_root


def test_wall_workflows_install_both_python_lift_packages() -> None:
    root = resolve_repo_root()

    for workflow_name in ("pandas-wall.yml", "numpy-wall.yml"):
        workflow = (root / ".github" / "workflows" / workflow_name).read_text(
            encoding="utf-8"
        )
        assert "-e implementations/python/sugar-lift-python-source" in workflow
        assert "-e 'implementations/python/sugar-lift-py-tests[test]'" in workflow


def _write_frontier(command: list[str]) -> None:
    frontier_path = Path(command[command.index("-o") + 1])
    frontier_path.write_text(
        json.dumps(
            {
                "kind": "recovered-construction-audit",
                "recoveryOverride": True,
                "status": "failed",
                "census": {
                    "kind": "recovered-frontier-census",
                    "sourceFilesEnumerated": 1,
                    "sourceBodiesDemanded": 1,
                    "auditLeavesCompleted": 1,
                },
                "panics": [
                    {
                        "kind": "ConstructionPanic",
                        "status": "mandatory-panic",
                        "reason": "missing subscript term construction",
                        "locus": "pkg.py:2:11",
                        "demandedSource": "pkg.py:2:11",
                        "terminalGapLocus": "pkg.py:2:11",
                        "gap": {"blame": "pkg.py:2:11"},
                        "demandedBody": {"file": "pkg.py", "line": 1},
                        "ownerIdentity": {
                            "demandedBody": {"file": "pkg.py", "line": 1},
                            "demandedSource": "pkg.py:2:11",
                            "terminalGapLocus": "pkg.py:2:11",
                        },
                    }
                ],
                "effects": [
                    {
                        "locus": "pkg.py:1:4",
                        "effect": "GetattrRuntimeEffect",
                        "category": "runtime",
                        "status": "boundary",
                        "reason": "attribute access crosses a runtime boundary",
                    }
                ],
                "suppressedDescendants": [
                    {
                        "locus": "pkg.py:2:18",
                        "reason": "parent construction already panicked",
                    }
                ],
            }
        )
        + "\n",
        encoding="utf-8",
    )


def test_build_mints_only_the_recovered_frontier_in_the_cached_workspace(
    tmp_path: Path,
) -> None:
    root = _fake_repo_root(tmp_path)
    package = tmp_path / "pandas"
    package.mkdir()
    (package / "__init__.py").write_text(
        'def f():\n    return config["mode"]\n', encoding="utf-8"
    )
    commands: list[list[str]] = []

    def fake_runner(
        command: list[str], cwd: Path, env: dict[str, str]
    ) -> CommandResult:
        commands.append(command)
        if command == [str(root / "bin/sugarbin"), "--profile", "release"]:
            return CommandResult(
                0,
                str(tmp_path / "shelf" / "sugar-darwin-x86_64-release-stamp") + "\n",
                "",
            )
        if command[1:3] == ["lift", "--audit-frontier"]:
            assert command[0].endswith("sugar-darwin-x86_64-release-stamp")
            assert command[-1].startswith(str(tmp_path / "cache"))
            assert env["SUGAR_BIN"] == command[0]
            _write_frontier(command)
            return CommandResult(2, "", "RECOVERY OVERRIDE: wrote panic inventory")
        raise AssertionError(f"unexpected command: {command}")

    result = build_pandas_wall(
        root=root,
        output_dir=tmp_path / "wall",
        floors=PandasWallFloors(
            frontier_independent_panics=1, frontier_suppressed_descendants=1
        ),
        package_path_resolver=lambda _package: package,
        run_command=fake_runner,
        cache_root=tmp_path / "cache",
    )

    assert result.summary.mode == "frontier"
    assert result.summary.frontier["independentPanicCount"] == 1
    assert result.summary.frontier["suppressedDescendantCount"] == 1
    assert result.summary.frontier["effectCount"] == 1
    assert result.breaches == ()
    assert result.frontier_path == tmp_path / "wall/frontier.json"
    assert result.frontier_path.is_file()
    assert not (tmp_path / "wall/report.json").exists()
    assert len(commands) == 2
    # #7806: `sugar lift --report` is not a driver of the Python kit.
    assert all("--report" not in command for command in commands)
    assert commands[-1][1:4] == [
        "lift",
        "--audit-frontier",
        "--continue-on-construction-gaps",
    ]
    flag = commands[-1].index("--allowed-broken-components")
    assert commands[-1][flag + 1] == "python"
    assert commands[-1][-1] == str(result.workspace_path)
    manifest = result.workspace_path / ".sugar/lift/python/manifest.toml"
    manifest_command = tomllib.loads(manifest.read_text(encoding="utf-8"))["command"]
    assert Path(manifest_command[1]).name == "lift_rpc.py"
    assert manifest_command[2:] == ["--rpc"]
    assert "--audit-only" not in manifest_command
    assert '"mode": "frontier"' in result.summary_path.read_text(encoding="utf-8")


def test_audit_failure_without_frontier_is_not_relabelled(
    tmp_path: Path,
) -> None:
    root = _fake_repo_root(tmp_path)
    package = tmp_path / "pandas"
    package.mkdir()
    (package / "__init__.py").write_text("x = 1\n", encoding="utf-8")

    def fake_runner(
        command: list[str], cwd: Path, env: dict[str, str]
    ) -> CommandResult:
        if command == [str(root / "bin/sugarbin"), "--profile", "release"]:
            return CommandResult(0, str(tmp_path / "sugar") + "\n", "")
        return CommandResult(7, "", "ordinary RPC framing failure")

    with pytest.raises(RuntimeError, match="ordinary RPC framing failure"):
        build_pandas_wall(
            root=root,
            output_dir=tmp_path / "wall",
            floors=PandasWallFloors(),
            package_path_resolver=lambda _package: package,
            run_command=fake_runner,
            cache_root=tmp_path / "cache",
        )

    assert not (tmp_path / "wall" / "summary.json").exists()


def _fake_repo_root(tmp_path: Path) -> Path:
    root = tmp_path / "repo"
    root.mkdir()
    (root / "bin").mkdir()
    (root / "bin/sugarbin").write_text("#!/bin/sh\n", encoding="utf-8")
    (root / "implementations/python/sugar-lift-py-tests/src").mkdir(parents=True)
    (root / "implementations/python/sugar-lift-python-source/src").mkdir(parents=True)
    return root


def _pandas_frontier_summary(independent: int, suppressed: int) -> PandasWallSummary:
    return PandasWallSummary(
        frontier={
            "kind": "recovered-construction-audit",
            "status": "failed",
            "independentPanicCount": independent,
            "effectCount": 0,
            "suppressedDescendantCount": suppressed,
        },
    )


def _pandas_frontier_floors() -> PandasWallFloors:
    return PandasWallFloors(
        frontier_independent_panics=11417,
        frontier_suppressed_descendants=12938,
    )


def test_pandas_frontier_ceilings_load_from_pinned_floors_json() -> None:
    root = resolve_repo_root()
    floors = PandasWallFloors.from_json_dict(
        json.loads((root / "tools" / "pandas-wall-floors.json").read_text())
    )
    # #4489 re-baseline: honest instrument reach, pinned on the record.
    assert floors.frontier_independent_panics == 11417
    assert floors.frontier_suppressed_descendants == 12938


def test_pandas_frontier_ceiling_reds_on_planted_higher_count() -> None:
    breaches = check_pandas_wall_floors(
        _pandas_frontier_summary(11418, 12939), _pandas_frontier_floors()
    )
    assert (
        "frontier independent_panics ceiling breached: "
        "observed=11418 ceiling=11417 delta=1"
    ) in breaches
    assert (
        "frontier suppressed_descendants ceiling breached: "
        "observed=12939 ceiling=12938 delta=1"
    ) in breaches


def test_pandas_frontier_ceiling_passes_at_or_below_the_pin() -> None:
    breaches = check_pandas_wall_floors(
        _pandas_frontier_summary(11417, 12938), _pandas_frontier_floors()
    )
    assert not any("ceiling breached" in breach for breach in breaches)
    # Recovered-audit stage: non-zero panics under the pin are residue, not red.
    assert breaches == []


def test_pandas_frontier_with_ceilings_allows_nonzero_panics_under_pin() -> None:
    breaches = check_pandas_wall_floors(
        _pandas_frontier_summary(9769, 11679), _pandas_frontier_floors()
    )
    assert breaches == []
    assert not any("audit is red" in breach for breach in breaches)


def test_unpinned_frontier_is_red_on_any_panic() -> None:
    breaches = check_pandas_wall_floors(
        _pandas_frontier_summary(1, 0), PandasWallFloors()
    )
    assert breaches == ["recovered construction audit is red: independent_panics=1"]
