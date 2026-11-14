from __future__ import annotations

import json
from pathlib import Path

import pytest

from sugar_lift_py_tests.idd.command_result import CommandResult
from sugar_lift_py_tests.idd.numpy_wall import (
    NumpyWallFloors,
    NumpyWallSummary,
    build_numpy_wall,
    check_frontier_ceilings,
)
from sugar_lift_py_tests.repo_root import resolve_repo_root


def _repo_and_package(tmp_path: Path) -> tuple[Path, Path]:
    root = tmp_path / "repo"
    (root / "bin").mkdir(parents=True)
    (root / "bin/sugarbin").write_text("#!/bin/sh\n", encoding="utf-8")
    package = tmp_path / "numpy"
    package.mkdir()
    (package / "__init__.py").write_text("x = 1\n", encoding="utf-8")
    return root, package


def _write_frontier(command: list[str], *, panics: int) -> None:
    frontier = Path(command[command.index("-o") + 1])
    frontier.write_text(
        json.dumps(
            {
                "kind": "recovered-construction-audit",
                "recoveryOverride": True,
                "status": "failed" if panics else "complete",
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
                        "reason": "fixture gap",
                        "locus": "pkg.py:1:0",
                        "demandedSource": "pkg.py:1:0",
                        "terminalGapLocus": "pkg.py:1:0",
                        "gap": {"blame": "pkg.py:1:0"},
                        "demandedBody": {"file": "pkg.py", "line": 1},
                        "ownerIdentity": {
                            "demandedBody": {"file": "pkg.py", "line": 1},
                            "demandedSource": "pkg.py:1:0",
                            "terminalGapLocus": "pkg.py:1:0",
                        },
                    }
                ][:panics],
                "suppressedDescendants": [],
                "effects": [],
            }
        ),
        encoding="utf-8",
    )


def test_build_uses_sugarbin_and_mints_only_the_recovered_frontier(
    tmp_path: Path, monkeypatch
) -> None:
    root, package = _repo_and_package(tmp_path)
    commands: list[list[str]] = []
    monkeypatch.setenv("SUGAR_BIN", "/ambient/stale/sugar")
    monkeypatch.setenv("SUGAR_BINARY_DIR", "/ambient/stale")

    def fake_runner(
        command: list[str], cwd: Path, env: dict[str, str]
    ) -> CommandResult:
        commands.append(command)
        if command == [str(root / "bin/sugarbin"), "--profile", "release"]:
            assert "SUGAR_BIN" not in env
            assert "SUGAR_BINARY_DIR" not in env
            return CommandResult(
                0,
                str(tmp_path / "shelf" / "sugar-darwin-x86_64-release-stamp") + "\n",
                "",
            )
        if command[1:3] == ["lift", "--audit-frontier"]:
            assert command[0].endswith("sugar-darwin-x86_64-release-stamp")
            assert command[-1].startswith(str(tmp_path / "wall" / "workspace"))
            assert env["SUGAR_BIN"] == command[0]
            _write_frontier(command, panics=1)
            return CommandResult(2, "", "red by design")
        raise AssertionError(f"unexpected command: {command}")

    result = build_numpy_wall(
        root=root,
        output_dir=tmp_path / "wall",
        floors=NumpyWallFloors(),
        package_path_resolver=lambda _package: package,
        run_command=fake_runner,
    )

    assert result.frontier_path == tmp_path / "wall" / "frontier.json"
    assert result.summary.frontier == {
        "kind": "recovered-construction-audit",
        "independentPanicCount": 1,
        "suppressedDescendantCount": 0,
        "effectCount": 0,
    }
    assert result.breaches == ("recovered construction audit is red",)
    assert commands[0] == [str(root / "bin/sugarbin"), "--profile", "release"]
    assert len(commands) == 2
    # #7806: `sugar lift --report` is not a driver of the Python kit.
    assert all("--report" not in command for command in commands)
    manifest = (
        tmp_path / "wall" / "workspace" / "numpy" / ".sugar/lift/python/manifest.toml"
    )
    assert '"--rpc"' in manifest.read_text(encoding="utf-8")
    assert '"--audit-only"' not in manifest.read_text(encoding="utf-8")
    assert not (tmp_path / "wall" / "report.json").exists()
    summary = json.loads((tmp_path / "wall" / "summary.json").read_text())
    assert summary["mode"] == "frontier"
    assert summary["frontier"]["independentPanicCount"] == 1


def test_green_frontier_has_no_breach(tmp_path: Path) -> None:
    root, package = _repo_and_package(tmp_path)

    def runner(command, _cwd, _env):
        if command == [str(root / "bin/sugarbin"), "--profile", "release"]:
            return CommandResult(0, str(root / "sugar") + "\n", "")
        if command[1:3] == ["lift", "--audit-frontier"]:
            _write_frontier(command, panics=0)
            return CommandResult(0, "", "")
        raise AssertionError(command)

    result = build_numpy_wall(
        root=root,
        output_dir=tmp_path / "wall",
        floors=NumpyWallFloors(
            frontier_independent_panics=0, frontier_suppressed_descendants=0
        ),
        package_path_resolver=lambda _package: package,
        run_command=runner,
    )

    assert result.breaches == ()


def test_missing_frontier_is_a_loud_failure(tmp_path: Path) -> None:
    root, package = _repo_and_package(tmp_path)

    def runner(command, _cwd, _env):
        if command == [str(root / "bin/sugarbin"), "--profile", "release"]:
            return CommandResult(0, str(root / "sugar") + "\n", "")
        return CommandResult(2, "", "ConstructionPanic")

    with pytest.raises(RuntimeError, match="failed without frontier.json"):
        build_numpy_wall(
            root=root,
            output_dir=tmp_path / "wall",
            floors=NumpyWallFloors(),
            package_path_resolver=lambda _package: package,
            run_command=runner,
        )

    assert not (tmp_path / "wall" / "summary.json").exists()


def _frontier_summary(independent: int, suppressed: int) -> NumpyWallSummary:
    return NumpyWallSummary(
        frontier={
            "kind": "recovered-construction-audit",
            "independentPanicCount": independent,
            "suppressedDescendantCount": suppressed,
            "effectCount": 0,
        },
    )


def test_frontier_ceilings_load_from_pinned_floors_json() -> None:
    root = resolve_repo_root()
    floors = NumpyWallFloors.from_json_dict(
        json.loads((root / "tools" / "numpy-wall-floors.json").read_text())
    )
    # #4489 re-baseline: honest instrument reach, pinned on the record.
    assert floors.frontier_independent_panics == 5569
    assert floors.frontier_suppressed_descendants == 7315


def test_frontier_ceiling_reds_on_planted_higher_count() -> None:
    floors = NumpyWallFloors(
        frontier_independent_panics=5569,
        frontier_suppressed_descendants=7315,
    )
    breaches = check_frontier_ceilings(_frontier_summary(5570, 7316), floors)
    assert breaches == [
        "frontier independent_panics ceiling breached: "
        "observed=5570 ceiling=5569 delta=1",
        "frontier suppressed_descendants ceiling breached: "
        "observed=7316 ceiling=7315 delta=1",
    ]


def test_frontier_ceiling_passes_at_or_below_the_pin() -> None:
    floors = NumpyWallFloors(
        frontier_independent_panics=5569,
        frontier_suppressed_descendants=7315,
    )
    assert check_frontier_ceilings(_frontier_summary(5569, 7315), floors) == []
    assert check_frontier_ceilings(_frontier_summary(0, 0), floors) == []


def test_unpinned_frontier_ceilings_do_not_gate() -> None:
    floors = NumpyWallFloors()
    assert check_frontier_ceilings(_frontier_summary(10**6, 10**6), floors) == []
