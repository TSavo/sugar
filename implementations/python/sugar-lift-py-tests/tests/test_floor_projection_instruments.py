from __future__ import annotations

from dataclasses import replace
from pathlib import Path

from sugar_lift_py_tests.factory.floor_contract_agreement import (
    floor_contract_agreement_diagnostic,
    floor_contract_agreement_violations_for_fact,
)
from sugar_lift_py_tests.factory.literal_call_report import (
    _formula_to_rpc,
    build_literal_call_report,
)
from sugar_lift_py_tests.idd import cli
from sugar_lift_py_tests.idd.collect_factory_spine_frontier import (
    collect_factory_spine_frontier,
)
from sugar_lift_py_tests.ir import eq, make_var, num

ROOT = Path(__file__).resolve().parents[4]

EXPECTED_FACTORY_SPINE_R = {
    "callee_body_worklists": 1,
    "block_of_callee_body_reductions": 1,
    "transitive_worklist_drains": 1,
    "projection_ladders": 2,
    "prior_assignment_replays": 1,
}


def _agreement_diagnostic(report):
    return next(
        row
        for row in report.payload.diagnostics
        if row.get("kind") == "floor-contract-agreement"
    )


def test_factory_spine_frontier_pins_current_second_engine_body_reductions() -> None:
    report = collect_factory_spine_frontier(ROOT)

    assert report.r.values == EXPECTED_FACTORY_SPINE_R
    assert report.r.total == 6
    assert not report.is_zero
    rows = {(row.kind, row.path, row.observed) for row in report.offenders}
    assert (
        "block_of_callee_body_reductions",
        "factory/literal_call_report.py",
        "build_body(Block.of(callee.node.body), ...).reduce(...)",
    ) in rows
    assert any("BlockSugar" in row.fix for row in report.offenders)
    assert any("BridgeStrategy dig_sink" in row.fix for row in report.offenders)


def test_factory_spine_frontier_cli_exits_red_until_body_side_doors_are_gone(
    capsys,
) -> None:
    status = cli.main(["--root", str(ROOT), "--factory-spine-frontier"])

    assert status == 1
    stdout = capsys.readouterr().out
    assert "python factory spine frontier audit" in stdout
    assert "  callee_body_worklists: 1" in stdout
    assert "  block_of_callee_body_reductions: 1" in stdout
    assert "  transitive_worklist_drains: 1" in stdout
    assert "  projection_ladders: 2" in stdout
    assert "  prior_assignment_replays: 1" in stdout
    assert "  total: 6" in stdout
    assert "second-engine body reductions:" in stdout


def test_factory_spine_frontier_bad_twin_flags_fresh_block_reduce(
    tmp_path,
) -> None:
    kit_src = tmp_path / "src" / "sugar_lift_py_tests" / "factory"
    kit_src.mkdir(parents=True)
    (kit_src / "literal_call_report.py").write_text(
        "def planted(callee, ctx):\n"
        "    return ctx.build_body(Block.of(callee.node.body), SugarRole.STATEMENT).reduce(ctx)\n",
        encoding="utf-8",
    )

    report = collect_factory_spine_frontier(tmp_path)

    assert report.r.values["block_of_callee_body_reductions"] == 1
    assert report.r.total == 1
    offender = report.offenders[0]
    assert offender.path == "factory/literal_call_report.py"
    assert offender.line == 2
    assert "Block.of(callee.node.body)" in offender.observed
    assert "force_floor" in offender.fix


def test_floor_contract_agreement_counter_reports_zero_for_current_chain() -> None:
    report = build_literal_call_report(
        source=(
            "def h(x):\n"
            "    return x + 1\n"
            "def g(x):\n"
            "    return h(x)\n"
            "def t():\n"
            "    assert g(5) == 6\n"
        ),
        filename="t.py",
        memento_file="t.py",
    )

    diagnostic = _agreement_diagnostic(report)
    assert diagnostic["r"] == {"agreement_violations": 0, "total": 0}
    assert diagnostic["violations"] == []


def test_floor_contract_agreement_bad_twin_counts_contradictory_callable_post() -> None:
    report = build_literal_call_report(
        source=(
            "def h(x):\n"
            "    return x + 1\n"
            "def t():\n"
            "    assert h(5) == 6\n"
        ),
        filename="t.py",
        memento_file="t.py",
    )
    callable_contract = next(c for c in report.payload.ir if c.name == "t::h::callable")
    planted = replace(
        callable_contract,
        post=_formula_to_rpc(eq(make_var("out"), num(99))),
    )

    diagnostic = floor_contract_agreement_diagnostic(
        floor_contract_agreement_violations_for_fact(
            callee="h",
            callable_contract=planted,
            arg_terms=[num(5)],
            floor_term=num(6),
            callsite_contract="h#euf#c:call:h(i:5)::assertion",
        )
    )

    assert diagnostic["r"] == {"agreement_violations": 1, "total": 1}
    assert diagnostic["violations"][0]["callee"] == "h"
    assert diagnostic["violations"][0]["contract"] == "t::h::callable"
