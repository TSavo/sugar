from __future__ import annotations

from pathlib import Path

import pytest

from sugar_lift_py_tests.idd.command_result import CommandResult
from sugar_lift_py_tests.idd.numpy_wall import (
    NumpyWallFloors,
    NumpyWallSummary,
    build_numpy_wall,
    check_wall_floors,
    summarize_numpy_wall,
)


def test_summarizes_wall_with_report_json_census_definitions() -> None:
    visual = """
report sections: unit test facts=1541, body universes=1566, factory report=37230, implications=736, source mementos=2383
universe visual:
  universe demo::post
    a.py:1  GREEN
    a.py:2  RED HERE effect: runtime-effect owner=await
    a.py:3  RED via gap at a.py:2
    a.py:4  RED
factory visual:
call edges observed:
  - a.post -> b.pre cid=blake3-512:abc [pre: x > 0]
  - a.post -> missing.pre cid=null
"""
    report = {
        "contracts": [
            {"name": "plain", "post": {"kind": "atomic"}},
            {"name": "pre-one", "pre": {"kind": "atomic"}},
            {"name": "pre-two", "pre": {"kind": "atomic"}},
        ],
        "callEdges": [
            {
                "kind": "call-edge",
                "targetContractCid": "blake3-512:" + ("a" * 128),
            },
            {"kind": "call-edge", "targetContractCid": None},
            {"kind": "implication"},
        ],
    }

    assert summarize_numpy_wall(visual, report) == NumpyWallSummary(
        green=1,
        red_reasoned=2,
        red_bare=1,
        contracts=3,
        pre_bearing=2,
        call_edges_resolved=1,
        implications=1,
    )


def test_floor_gate_names_every_delta() -> None:
    summary = NumpyWallSummary(
        green=9,
        red_reasoned=7,
        red_bare=1,
        contracts=3,
        pre_bearing=2,
        call_edges_resolved=1,
        implications=0,
    )
    floors = NumpyWallFloors(green=10, pre_bearing=3, implications=1)

    messages = check_wall_floors(summary, floors)

    assert messages == [
        "red_bare invariant breached: observed=1 expected=0; replacement=thread a typed effect/gap reason into every red wall row",
        "green floor breached: observed=9 floor=10 delta=-1",
        "pre_bearing floor breached: observed=2 floor=3 delta=-1",
        "implications floor breached: observed=0 floor=1 delta=-1",
    ]


def test_build_uses_sugarbin_and_reuses_one_audit_workspace(tmp_path: Path) -> None:
    root = tmp_path / "repo"
    root.mkdir()
    (root / "bin").mkdir()
    (root / "bin/sugarbin").write_text("#!/bin/sh\n", encoding="utf-8")
    package = tmp_path / "numpy"
    package.mkdir()
    (package / "__init__.py").write_text("x = 1\n", encoding="utf-8")
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
        if command[1:4] == ["lift", "--report", "--visual"]:
            assert command[0].endswith("sugar-darwin-x86_64-release-stamp")
            assert command[-1].startswith(str(tmp_path / "wall" / "workspace"))
            assert env["SUGAR_BIN"] == command[0]
            return CommandResult(0, "    pkg.py:1  GREEN\n", "")
        if command[1:4] == ["lift", "--report", "--json"]:
            assert command[0].endswith("sugar-darwin-x86_64-release-stamp")
            assert command[-1].startswith(str(tmp_path / "wall" / "workspace"))
            assert env["SUGAR_BIN"] == command[0]
            return CommandResult(
                0,
                '{"contracts": [{"pre": {"kind": "atomic"}}], "callEdges": [{"kind": "implication"}]}\n',
                "",
            )
        raise AssertionError(f"unexpected command: {command}")

    result = build_numpy_wall(
        root=root,
        output_dir=tmp_path / "wall",
        floors=NumpyWallFloors(green=1, pre_bearing=0, implications=0),
        package_path_resolver=lambda _package: package,
        run_command=fake_runner,
    )

    assert result.summary.green == 1
    assert result.summary.contracts == 1
    assert result.summary.pre_bearing == 1
    assert result.summary.implications == 1
    assert result.breaches == ()
    assert commands[0] == [str(root / "bin/sugarbin"), "--profile", "release"]
    assert all(command[0] != "cargo" for command in commands)
    manifest = (
        tmp_path / "wall" / "workspace" / "numpy" / ".sugar/lift/python/manifest.toml"
    )
    assert '"--rpc"' in manifest.read_text(encoding="utf-8")
    assert '"--audit-only"' not in manifest.read_text(encoding="utf-8")
    assert (tmp_path / "wall" / "wall.txt").read_text(encoding="utf-8") == (
        "    pkg.py:1  GREEN\n"
    )
    assert (
        (tmp_path / "wall" / "report.json")
        .read_text(encoding="utf-8")
        .startswith('{"contracts"')
    )
    assert '"implications": 1' in (tmp_path / "wall" / "summary.json").read_text()


def test_wall_gate_fails_on_breach(tmp_path: Path) -> None:
    root = tmp_path / "repo"
    root.mkdir()
    (root / "bin").mkdir()
    (root / "bin/sugarbin").write_text("#!/bin/sh\n", encoding="utf-8")
    package = tmp_path / "numpy"
    package.mkdir()
    (package / "__init__.py").write_text("x = 1\n", encoding="utf-8")

    def fake_runner(
        command: list[str], cwd: Path, env: dict[str, str]
    ) -> CommandResult:
        if command == [str(root / "bin/sugarbin"), "--profile", "release"]:
            return CommandResult(
                0,
                str(tmp_path / "shelf" / "sugar-darwin-x86_64-release-stamp") + "\n",
                "",
            )
        if command[1:4] == ["lift", "--report", "--visual"]:
            assert env["SUGAR_BIN"] == command[0]
            return CommandResult(0, "    pkg.py:1  GREEN\n", "")
        if command[1:4] == ["lift", "--report", "--json"]:
            assert env["SUGAR_BIN"] == command[0]
            return CommandResult(0, '{"contracts": [], "callEdges": []}\n', "")
        raise AssertionError(f"unexpected command: {command}")

    result = build_numpy_wall(
        root=root,
        output_dir=tmp_path / "wall",
        floors=NumpyWallFloors(green=2, pre_bearing=1, implications=1),
        package_path_resolver=lambda _package: package,
        run_command=fake_runner,
    )

    assert result.breaches == (
        "green floor breached: observed=1 floor=2 delta=-1",
        "pre_bearing floor breached: observed=0 floor=1 delta=-1",
        "implications floor breached: observed=0 floor=1 delta=-1",
    )
