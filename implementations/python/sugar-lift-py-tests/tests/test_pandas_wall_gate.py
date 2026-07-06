from __future__ import annotations

import json
from pathlib import Path

from sugar_lift_py_tests.idd.command_result import CommandResult
from sugar_lift_py_tests.idd.pandas_wall import (
    PandasWallFloors,
    PandasWallSummary,
    build_pandas_wall,
    check_pandas_wall_floors,
    summarize_pandas_completed_wall,
    summarize_pandas_construction_gaps,
    summarize_pandas_frontier_error,
)


def test_summarizes_structured_construction_gaps_by_bucket() -> None:
    output = _structured_gap_output(
        [
            _gap("Floor", "dict-read", observed="DictLiteral", requested="entry floor"),
            _gap("Sugar", "walrus", observed="NamedExpr", requested="owner"),
            _gap("Floor", "dict-read", observed="DictLiteral", requested="entry floor"),
            _gap(
                "ProofIR",
                "effect-lowering",
                observed="RuntimeEffect",
                requested="typed member",
            ),
        ]
    )

    summary = summarize_pandas_construction_gaps(output)

    assert summary == PandasWallSummary(
        mode="construction-gaps",
        gaps_total=4,
        gaps_by_bucket={"Constructor": 0, "Floor": 2, "ProofIR": 1, "Sugar": 1},
        gap_templates={
            "Floor|dict-read|DictLiteral|entry floor": 2,
            "ProofIR|effect-lowering|RuntimeEffect|typed member": 1,
            "Sugar|walrus|NamedExpr|owner": 1,
        },
        frontier={},
        green=0,
        red_reasoned=0,
        red_bare=0,
        contracts=0,
        pre_bearing=0,
        call_edges_resolved=0,
        implications=0,
    )


def test_construction_gap_ceiling_names_total_and_template_breach() -> None:
    summary = PandasWallSummary(
        mode="construction-gaps",
        gaps_total=3,
        gaps_by_bucket={"Constructor": 0, "Floor": 2, "ProofIR": 0, "Sugar": 1},
        gap_templates={
            "Floor|dict-read|DictLiteral|entry floor": 2,
            "Sugar|walrus|NamedExpr|owner": 1,
        },
        frontier={},
        green=0,
        red_reasoned=0,
        red_bare=0,
        contracts=0,
        pre_bearing=0,
        call_edges_resolved=0,
        implications=0,
    )
    floors = PandasWallFloors(
        mode="construction-gaps",
        gaps_total_ceiling=2,
        gap_template_ceilings={"Floor|dict-read|DictLiteral|entry floor": 1},
        green=0,
        pre_bearing=0,
        implications=0,
        frontier_needle="",
        frontier_owner="",
        frontier_shape="",
    )

    assert check_pandas_wall_floors(summary, floors) == [
        "construction gap ceiling breached: observed=3 ceiling=2 delta=1",
        "construction gap template ceiling breached: template=Floor|dict-read|DictLiteral|entry floor observed=2 ceiling=1 delta=1",
        "construction gap template ceiling breached: template=Sugar|walrus|NamedExpr|owner observed=1 ceiling=0 delta=1",
    ]


def test_named_frontier_is_pinned_by_owner_shape_and_needle() -> None:
    output = _frontier_output(
        "UuidExtensionArray constructor argument cannot read completed value "
        "from incomplete effect: named expression runtime boundary: "
        "crime=walrus binding requested as a term; owner=NamedExprSugar; "
        "shape=NamedExpr target `u` value `Call`; "
        "replacement=route through the alias/binding floor before green testimony; "
        "blame=pandas/tests/extension/uuid/test_uuid.py:83:41"
    )

    summary = summarize_pandas_frontier_error(output)

    assert summary is not None
    assert summary.mode == "frontier"
    assert summary.frontier["owner"] == "NamedExprSugar"
    assert summary.frontier["shape"] == "NamedExpr target `u` value `Call`"
    assert "named expression runtime boundary" in summary.frontier["message"]
    assert (
        check_pandas_wall_floors(
            summary,
            PandasWallFloors(
                mode="frontier",
                gaps_total_ceiling=0,
                gap_template_ceilings={},
                green=0,
                pre_bearing=0,
                implications=0,
                frontier_needle="named expression runtime boundary",
                frontier_owner="NamedExprSugar",
                frontier_shape="NamedExpr target `u` value `Call`",
            ),
        )
        == []
    )
    assert check_pandas_wall_floors(
        summary,
        PandasWallFloors(
            mode="frontier",
            gaps_total_ceiling=0,
            gap_template_ceilings={},
            green=0,
            pre_bearing=0,
            implications=0,
            frontier_needle="different runtime boundary",
            frontier_owner="OtherSugar",
            frontier_shape="OtherShape",
        ),
    ) == [
        "pandas wall frontier needle breached: needle='different runtime boundary' message='UuidExtensionArray constructor argument cannot read completed value from incomplete effect: named expression runtime boundary: crime=walrus binding requested as a term; owner=NamedExprSugar; shape=NamedExpr target `u` value `Call`; replacement=route through the alias/binding floor before green testimony; blame=pandas/tests/extension/uuid/test_uuid.py:83:41'",
        "pandas wall frontier owner breached: observed='NamedExprSugar' expected='OtherSugar'",
        "pandas wall frontier shape breached: observed='NamedExpr target `u` value `Call`' expected='OtherShape'",
    ]


def test_completed_wall_mode_uses_numpy_style_floors() -> None:
    visual = """
universe visual:
    pkg.py:1  GREEN
    pkg.py:2  RED HERE effect: runtime-effect owner=await
    pkg.py:3  RED
"""
    report = {
        "contracts": [{"pre": {"kind": "atomic"}}, {"post": {"kind": "atomic"}}],
        "callEdges": [
            {"kind": "call-edge", "targetContractCid": "blake3-512:" + ("a" * 128)},
            {"kind": "implication"},
        ],
    }

    summary = summarize_pandas_completed_wall(visual, report)

    assert summary == PandasWallSummary(
        mode="complete",
        gaps_total=0,
        gaps_by_bucket={"Constructor": 0, "Floor": 0, "ProofIR": 0, "Sugar": 0},
        gap_templates={},
        frontier={},
        green=1,
        red_reasoned=1,
        red_bare=1,
        contracts=2,
        pre_bearing=1,
        call_edges_resolved=1,
        implications=1,
    )
    assert check_pandas_wall_floors(
        summary,
        PandasWallFloors(
            mode="complete",
            gaps_total_ceiling=0,
            gap_template_ceilings={},
            green=2,
            pre_bearing=2,
            implications=2,
            frontier_needle="",
            frontier_owner="",
            frontier_shape="",
        ),
    ) == [
        "red_bare invariant breached: observed=1 expected=0; replacement=thread a typed effect/gap reason into every red wall row",
        "green floor breached: observed=1 floor=2 delta=-1",
        "pre_bearing floor breached: observed=1 floor=2 delta=-1",
        "implications floor breached: observed=1 floor=2 delta=-1",
    ]


def test_build_uses_sugarbin_cached_audit_workspace_and_structured_gap_mode(
    tmp_path: Path,
) -> None:
    root = _fake_repo_root(tmp_path)
    package = tmp_path / "pandas"
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
            assert command[-1].startswith(str(tmp_path / "cache"))
            assert env["SUGAR_BIN"] == command[0]
            return CommandResult(
                2,
                "",
                _structured_gap_output([_gap("Floor", "dict-read")]),
            )
        raise AssertionError(f"unexpected command: {command}")

    result = build_pandas_wall(
        root=root,
        output_dir=tmp_path / "wall",
        floors=PandasWallFloors(
            mode="construction-gaps",
            gaps_total_ceiling=1,
            gap_template_ceilings={"Floor|dict-read|observed|requested": 1},
            green=0,
            pre_bearing=0,
            implications=0,
            frontier_needle="",
            frontier_owner="",
            frontier_shape="",
        ),
        package_path_resolver=lambda _package: package,
        run_command=fake_runner,
        cache_root=tmp_path / "cache",
    )

    assert result.summary.mode == "construction-gaps"
    assert result.summary.gaps_total == 1
    assert result.report_path is None
    assert result.frontier_path is None
    assert result.breaches == ()
    assert commands == [
        [str(root / "bin/sugarbin"), "--profile", "release"],
        [
            str(tmp_path / "shelf" / "sugar-darwin-x86_64-release-stamp"),
            "lift",
            "--report",
            "--visual",
            str(result.workspace_path),
        ],
    ]
    manifest = result.workspace_path / ".sugar/lift/python/manifest.toml"
    assert '"--rpc"' in manifest.read_text(encoding="utf-8")
    assert '"--audit-only"' in manifest.read_text(encoding="utf-8")
    assert '"mode": "construction-gaps"' in result.summary_path.read_text(
        encoding="utf-8"
    )


def test_build_complete_mode_runs_json_report_and_checks_full_floors(
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
            return CommandResult(
                0,
                json.dumps(
                    {
                        "contracts": [{"pre": {"kind": "atomic"}}],
                        "callEdges": [{"kind": "implication"}],
                    }
                ),
                "",
            )
        raise AssertionError(f"unexpected command: {command}")

    result = build_pandas_wall(
        root=root,
        output_dir=tmp_path / "wall",
        floors=PandasWallFloors(
            mode="complete",
            gaps_total_ceiling=0,
            gap_template_ceilings={},
            green=1,
            pre_bearing=1,
            implications=1,
            frontier_needle="",
            frontier_owner="",
            frontier_shape="",
        ),
        package_path_resolver=lambda _package: package,
        run_command=fake_runner,
        cache_root=tmp_path / "cache",
    )

    assert result.summary.mode == "complete"
    assert result.summary.green == 1
    assert result.summary.pre_bearing == 1
    assert result.summary.implications == 1
    assert result.report_path is not None
    assert result.frontier_path is None
    assert result.breaches == ()


def _gap(
    kind: str,
    owner: str,
    *,
    observed: str = "observed",
    requested: str = "requested",
) -> dict[str, object]:
    return {
        "status": f"{kind.lower()}-gap",
        "gap": {
            "gap_kind": kind,
            "owner": owner,
            "observed": observed,
            "requested": requested,
            "blame": "pkg.py:1",
            "fix": "route through the closed vocabulary",
        },
    }


def _structured_gap_output(rows: list[dict[str, object]]) -> str:
    return "lift plugin returned error: " + json.dumps(
        {"data": {"auditOnlyGaps": rows}}, sort_keys=True
    )


def _frontier_output(message: str) -> str:
    return (
        "lift plugin returned error: "
        + json.dumps({"code": -32603, "message": message, "data": "trace"})
        + "; fix=keep the frontier structured"
    )


def _fake_repo_root(tmp_path: Path) -> Path:
    root = tmp_path / "repo"
    root.mkdir()
    (root / "bin").mkdir()
    (root / "bin/sugarbin").write_text("#!/bin/sh\n", encoding="utf-8")
    (root / "implementations/python/sugar-lift-py-tests/src").mkdir(parents=True)
    (root / "implementations/python/sugar-lift-python-source/src").mkdir(parents=True)
    return root
