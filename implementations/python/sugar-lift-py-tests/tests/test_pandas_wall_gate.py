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
    summarize_pandas_completed_wall,
    summarize_pandas_construction_gaps,
    summarize_pandas_frontier_error,
)


def test_wall_workflows_install_both_python_lift_packages() -> None:
    root = Path(__file__).resolve().parents[4]

    for workflow_name in ("pandas-wall.yml", "numpy-wall.yml"):
        workflow = (root / ".github" / "workflows" / workflow_name).read_text(
            encoding="utf-8"
        )
        assert "-e implementations/python/sugar-lift-python-source" in workflow
        assert "-e 'implementations/python/sugar-lift-py-tests[test]'" in workflow


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
    # Criterion 14 (#3706): the summary is built entirely from
    # `lineAccounting`, never a scrape of `--visual` ANSI text.
    report = {
        "lineAccounting": [
            {
                "file": "pkg.py",
                "line": 1,
                "class": "warrant",
                "grounds": "cid:blake3-512:x",
            },
            {
                "file": "pkg.py",
                "line": 2,
                "class": "effect",
                "grounds": "runtime-effect owner=await",
            },
            {"file": "pkg.py", "line": 3, "class": "effect", "grounds": ""},
        ],
        "contracts": [{"pre": {"kind": "atomic"}}, {"post": {"kind": "atomic"}}],
        "callEdges": [
            {"kind": "call-edge", "targetContractCid": "blake3-512:" + ("a" * 128)},
            {"kind": "implication"},
        ],
    }

    summary = summarize_pandas_completed_wall(report)

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


def _factory_walk_gap(
    kind: str,
    *,
    owner: str = "python.factory",
    observed: str = "While",
    requested: str = "statement",
) -> dict[str, object]:
    """Production factoryWalk red row shape (verdict=gap + top-level gap_kind)."""
    return {
        "kind": "factory-walk-row",
        "verdict": "gap",
        "status": "unresolved",
        "gap_kind": kind,
        "owner": owner,
        "observed": observed,
        "requested": requested,
        "reason": f"write more {kind} for this AST",
    }


def test_completed_wall_counts_factory_walk_gaps_not_false_green() -> None:
    """#4102 BAD TWIN: production gap rows cannot summarize as zero.

    Before: summarize_pandas_completed_wall hard-coded gaps_total=0.
    After: verdict==gap rows on factoryWalk are counted honestly.
    """
    report = {
        "lineAccounting": [
            {
                "file": "pkg.py",
                "line": 1,
                "class": "warrant",
                "grounds": "cid:blake3-512:x",
            }
        ],
        "contracts": [{"pre": {"kind": "atomic"}}],
        "callEdges": [],
        "factoryWalk": [
            {
                "kind": "factory-walk-row",
                "verdict": "complete",
                "status": "warranted",
            },
            _factory_walk_gap("Sugar", observed="While", requested="statement"),
            _factory_walk_gap("Sugar", observed="NamedExpr", requested="term"),
            _factory_walk_gap("Sugar", observed="ListComp", requested="term"),
            _factory_walk_gap(
                "Floor",
                owner="attribute",
                observed="TermValue",
                requested="stand on the attribute floor",
            ),
        ],
    }

    summary = summarize_pandas_completed_wall(report)

    # BAD TWIN teeth: must NOT be the false-green zero.
    assert summary.gaps_total != 0
    assert summary.gaps_total == 4
    assert summary.gaps_by_bucket["Sugar"] == 3
    assert summary.gaps_by_bucket["Floor"] == 1
    assert summary.gaps_by_bucket["Constructor"] == 0
    assert summary.gaps_by_bucket["ProofIR"] == 0
    # lineAccounting fields preserved.
    assert summary.green == 1
    assert summary.mode == "complete"
    assert summary.gap_templates == {
        "Floor|attribute|TermValue|stand on the attribute floor": 1,
        "Sugar|python.factory|ListComp|term": 1,
        "Sugar|python.factory|NamedExpr|term": 1,
        "Sugar|python.factory|While|statement": 1,
    }


def test_completed_wall_gap_ceiling_reds_the_wall() -> None:
    """Completed wall with construction gaps breaches when ceiling is 0."""
    report = {
        "lineAccounting": [],
        "contracts": [],
        "callEdges": [],
        "factoryWalk": [
            _factory_walk_gap("Sugar", observed="While"),
            _factory_walk_gap("Floor", owner="attribute", observed="TermValue"),
        ],
    }
    summary = summarize_pandas_completed_wall(report)
    floors = PandasWallFloors(
        mode="complete",
        gaps_total_ceiling=0,
        gap_template_ceilings={},
        green=0,
        pre_bearing=0,
        implications=0,
        frontier_needle="",
        frontier_owner="",
        frontier_shape="",
    )
    breaches = check_pandas_wall_floors(summary, floors)
    assert breaches
    assert any("construction gap ceiling breached" in b for b in breaches)
    assert any("construction gap template ceiling breached" in b for b in breaches)


def test_completed_wall_zero_gaps_stays_clean() -> None:
    """Genuinely clean factoryWalk still summarizes gaps_total=0."""
    report = {
        "lineAccounting": [
            {
                "file": "pkg.py",
                "line": 1,
                "class": "warrant",
                "grounds": "cid:blake3-512:x",
            }
        ],
        "contracts": [{"pre": {"kind": "atomic"}}],
        "callEdges": [{"kind": "implication"}],
        "factoryWalk": [
            {
                "kind": "factory-walk-row",
                "verdict": "complete",
                "status": "warranted",
            },
            {
                "kind": "factory-walk-row",
                "verdict": "incomplete",
                "status": "runtime-effect",
            },
        ],
    }
    summary = summarize_pandas_completed_wall(report)
    assert summary.gaps_total == 0
    assert summary.gaps_by_bucket == {
        "Constructor": 0,
        "Floor": 0,
        "ProofIR": 0,
        "Sugar": 0,
    }
    assert summary.gap_templates == {}
    assert summary.green == 1
    assert summary.pre_bearing == 1
    assert summary.implications == 1
    assert (
        check_pandas_wall_floors(
            summary,
            PandasWallFloors(
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
        )
        == []
    )


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
    manifest_text = manifest.read_text(encoding="utf-8")
    manifest_command = tomllib.loads(manifest_text)["command"]
    assert Path(manifest_command[1]).name == "lift_rpc.py"
    assert manifest_command[2:] == ["--rpc"]
    assert "--audit-only" not in manifest_command
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
                        "lineAccounting": [
                            {
                                "file": "pkg.py",
                                "line": 1,
                                "class": "warrant",
                                "grounds": "cid:blake3-512:x",
                            }
                        ],
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
    manifest = result.workspace_path / ".sugar/lift/python/manifest.toml"
    manifest_text = manifest.read_text(encoding="utf-8")
    assert '"--rpc"' in manifest_text
    assert '"--audit-only"' not in manifest_text


def test_complete_mode_records_recovered_frontier_without_report_artifact(
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
            return CommandResult(0, str(tmp_path / "sugar") + "\n", "")
        if "--audit-frontier" not in command:
            return CommandResult(
                2,
                "",
                "FactoryPanic: observed=Subscript; lift plugin closed stdout",
            )
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
                            "kind": "factory-panic",
                            "status": "sugar-gap",
                            "reason": "missing subscript term construction",
                            "locus": "pkg.py:2:11",
                            "gap": {"gap_kind": "Sugar"},
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
        return CommandResult(2, "", "RECOVERY OVERRIDE: wrote panic inventory")

    result = build_pandas_wall(
        root=root,
        output_dir=tmp_path / "wall",
        floors=PandasWallFloors(
            mode="complete",
            gaps_total_ceiling=0,
            gap_template_ceilings={},
            green=0,
            pre_bearing=0,
            implications=0,
            frontier_needle="",
            frontier_owner="",
            frontier_shape="",
        ),
        package_path_resolver=lambda _package: package,
        run_command=fake_runner,
    )

    assert result.summary.mode == "frontier"
    assert result.summary.frontier["independentPanicCount"] == 1
    assert result.summary.frontier["suppressedDescendantCount"] == 1
    assert result.summary.frontier["effectCount"] == 1
    assert result.breaches
    assert result.frontier_path == tmp_path / "wall/frontier.json"
    assert result.frontier_path.is_file()
    assert not (tmp_path / "wall/report.json").exists()
    assert commands[-1][1:3] == ["lift", "--audit-frontier"]
    assert "--continue-on-construction-gaps" in commands[-1]
    assert len(commands) == 3


def test_complete_mode_audit_retry_does_not_relabel_unexpected_failure(
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
        if "--audit-frontier" in command:
            return CommandResult(7, "", "ordinary RPC framing failure")
        return CommandResult(2, "", "production process exited")

    with pytest.raises(RuntimeError, match="ordinary RPC framing failure"):
        build_pandas_wall(
            root=root,
            output_dir=tmp_path / "wall",
            floors=PandasWallFloors(
                mode="complete",
                gaps_total_ceiling=0,
                gap_template_ceilings={},
                green=0,
                pre_bearing=0,
                implications=0,
                frontier_needle="",
                frontier_owner="",
                frontier_shape="",
            ),
            package_path_resolver=lambda _package: package,
            run_command=fake_runner,
        )


def test_complete_mode_transport_death_mints_no_frontier_artifact(
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
            return CommandResult(0, str(tmp_path / "sugar") + "\n", "")
        if "--audit-frontier" not in command:
            return CommandResult(
                2,
                "",
                "lift plugin diagnostic kind=transport "
                "path=lift-plugin.transport: plugin process ended without responding",
            )
        frontier_path = Path(command[command.index("-o") + 1])
        frontier_path.write_text(
            json.dumps(
                {
                    "kind": "recovered-construction-audit",
                    "recoveryOverride": True,
                    "status": "clean",
                    "panics": [],
                    "effects": [],
                    "suppressedDescendants": [],
                }
            ),
            encoding="utf-8",
        )
        return CommandResult(0, "", "")

    output_dir = tmp_path / "wall"
    with pytest.raises(RuntimeError, match="producer.*transport"):
        build_pandas_wall(
            root=root,
            output_dir=output_dir,
            floors=PandasWallFloors(
                mode="complete",
                gaps_total_ceiling=0,
                gap_template_ceilings={},
                green=0,
                pre_bearing=0,
                implications=0,
                frontier_needle="",
                frontier_owner="",
                frontier_shape="",
            ),
            package_path_resolver=lambda _package: package,
            run_command=fake_runner,
        )

    assert len(commands) == 2
    assert not (output_dir / "frontier.json").exists()


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


def _pandas_frontier_summary(independent: int, suppressed: int) -> PandasWallSummary:
    return PandasWallSummary(
        mode="frontier",
        gaps_total=0,
        gaps_by_bucket={},
        gap_templates={},
        frontier={
            "kind": "recovered-construction-audit",
            "status": "failed",
            "independentPanicCount": independent,
            "effectCount": 0,
            "suppressedDescendantCount": suppressed,
        },
        green=0,
        red_reasoned=0,
        red_bare=0,
        contracts=0,
        pre_bearing=0,
        call_edges_resolved=0,
        implications=0,
    )


def _pandas_frontier_floors() -> PandasWallFloors:
    return PandasWallFloors(
        mode="frontier",
        gaps_total_ceiling=0,
        gap_template_ceilings={},
        green=0,
        pre_bearing=0,
        implications=0,
        frontier_needle="",
        frontier_owner="",
        frontier_shape="",
        frontier_independent_panics=11417,
        frontier_suppressed_descendants=12938,
    )


def test_pandas_frontier_ceilings_load_from_pinned_floors_json() -> None:
    root = Path(__file__).resolve().parents[4]
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
