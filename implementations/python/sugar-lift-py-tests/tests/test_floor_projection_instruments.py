from __future__ import annotations

from dataclasses import replace
from pathlib import Path

import pytest

from sugar_lift_py_tests.factory import floor_contract_agreement as agreement_gate
from sugar_lift_py_tests.factory.floor_contract_agreement import (
    floor_contract_agreement_violations_for_fact,
)
from sugar_lift_py_tests.factory.literal_call_report import build_literal_call_report
from sugar_lift_py_tests.idd import cli
from sugar_lift_py_tests.idd.collect_factory_spine_frontier import (
    collect_factory_spine_frontier,
)
from sugar_lift_py_tests.ir import eq, make_var, num
from sugar_lift_py_tests.proofir import (
    ConstructionSite,
    Derived,
    FunctionContract,
    Provenance,
)
from sugar_lift_py_tests.proofir.formulas import Eq
from sugar_lift_py_tests.proofir.scope import PostCondition
from sugar_lift_py_tests.proofir.sorts import IntSort
from sugar_lift_py_tests.proofir.terms import ConstTerm, VarTerm

ROOT = Path(__file__).resolve().parents[4]

EXPECTED_FACTORY_SPINE_R = {
    "callee_body_worklists": 0,
    "block_of_callee_body_reductions": 0,
    "callsite_values_with_null_multistatement_body": 0,
    "mini_interpreter_consumers_not_reading_terms": 0,
    "transitive_worklist_drains": 0,
    "projection_ladders": 0,
    "prior_assignment_replays": 0,
    "xsugar_build_bypasses": 11,
}


def _agreement_diagnostic(report):
    return next(
        row
        for row in report.payload.diagnostics
        if row.get("kind") == "floor-contract-agreement"
    )


def test_factory_spine_frontier_pins_current_xsugar_bypass_baseline() -> None:
    report = collect_factory_spine_frontier(ROOT)

    assert report.r.values == EXPECTED_FACTORY_SPINE_R
    assert report.r.total == 11
    assert not report.is_zero
    assert [f"{o.path}:{o.line}" for o in report.offenders] == [
        "factory/array_map_report.py:202",
        "factory/array_map_report.py:311",
        "factory/array_map_report.py:313",
        "factory/literal_call_report.py:645",
        "floor/call_site_value.py:156",
        "sugar/builtin_call_sugar.py:54",
        "sugar/builtin_call_sugar.py:134",
        "sugar/builtin_call_sugar.py:194",
        "sugar/list_sugar.py:49",
        "sugar/map_builtin_sugar.py:33",
        "sugar/map_builtin_sugar.py:36",
    ]
    assert all(
        offender.kind == "xsugar_build_bypasses" for offender in report.offenders
    )


def test_factory_spine_frontier_cli_exits_red_with_pinned_bypasses(
    capsys,
) -> None:
    status = cli.main(["--root", str(ROOT), "--factory-spine-frontier"])

    assert status == 1
    stdout = capsys.readouterr().out
    assert "python factory spine frontier audit" in stdout
    assert "  callee_body_worklists: 0" in stdout
    assert "  block_of_callee_body_reductions: 0" in stdout
    assert "  callsite_values_with_null_multistatement_body: 0" in stdout
    assert "  mini_interpreter_consumers_not_reading_terms: 0" in stdout
    assert "  transitive_worklist_drains: 0" in stdout
    assert "  projection_ladders: 0" in stdout
    assert "  prior_assignment_replays: 0" in stdout
    assert "  xsugar_build_bypasses: 11" in stdout
    assert "  total: 11" in stdout
    assert "factory spine frontier offenders:" in stdout
    assert "factory/literal_call_report.py:645" in stdout
    assert "floor/call_site_value.py:156" in stdout
    assert "sugar/builtin_call_sugar.py:54" in stdout
    assert "sugar/map_builtin_sugar.py:36" in stdout


def test_factory_spine_frontier_bad_twin_flags_fresh_block_reduce(
    tmp_path,
) -> None:
    kit_src = tmp_path / "src" / "sugar_lift_py_tests" / "factory"
    kit_src.mkdir(parents=True)
    (kit_src / "literal_call_report.py").write_text(
        "def planted(callee, ctx):\n"
        "    return ctx.build_body(Block."
        "of(callee.node.body), SugarRole.STATEMENT).reduce(ctx)\n",
        encoding="utf-8",
    )

    report = collect_factory_spine_frontier(tmp_path)

    assert report.r.values["block_of_callee_body_reductions"] == 1
    assert report.r.total == 1
    offender = report.offenders[0]
    assert offender.path == "factory/literal_call_report.py"
    assert offender.line == 2
    assert "Block." "of(callee.node.body)" in offender.observed
    assert "force_floor" in offender.fix


def test_factory_spine_frontier_bad_twin_flags_null_multistatement_body_drop(
    tmp_path,
) -> None:
    kit_src = tmp_path / "src" / "sugar_lift_py_tests" / "sugar"
    kit_src.mkdir(parents=True)
    (kit_src / "call_sugar.py").write_text(
        "def planted(self):\n"
        "    return CallSiteValue(body=self.body if isinstance(self.body, SugarBody) else None)\n",
        encoding="utf-8",
    )

    report = collect_factory_spine_frontier(tmp_path)

    assert report.r.values["callsite_values_with_null_multistatement_body"] == 1
    assert report.r.total == 1
    offender = report.offenders[0]
    assert offender.path == "sugar/call_sugar.py"
    assert offender.line == 2
    assert "FunctionBodyUniverse" in offender.observed
    assert "carry the FunctionBodyUniverse" in offender.fix


def test_factory_spine_frontier_bad_twin_flags_assert_consumer_side_door(
    tmp_path,
) -> None:
    kit_src = tmp_path / "src" / "sugar_lift_py_tests" / "factory"
    kit_src.mkdir(parents=True)
    (kit_src / "literal_call_report.py").write_text(
        "def _lift_assert(stmt):\n"
        "    return _construct_callsite(stmt, stmt, 'f', stmt, {})\n",
        encoding="utf-8",
    )

    report = collect_factory_spine_frontier(tmp_path)

    assert report.r.values["mini_interpreter_consumers_not_reading_terms"] == 1
    assert report.r.total == 1
    offender = report.offenders[0]
    assert offender.path == "factory/literal_call_report.py"
    assert offender.line == 2
    assert "_construct_callsite" in offender.observed
    assert "force_floor" in offender.fix


def test_factory_spine_frontier_bad_twin_flags_xsugar_build_bypass(
    tmp_path,
) -> None:
    kit_src = tmp_path / "src" / "sugar_lift_py_tests" / "consumer"
    kit_src.mkdir(parents=True)
    (kit_src / "bad_consumer.py").write_text(
        "def planted(site, ctx):\n" "    return CallSugar.build(site, ctx)\n",
        encoding="utf-8",
    )

    report = collect_factory_spine_frontier(tmp_path)

    assert report.r.values["xsugar_build_bypasses"] == 1
    assert report.r.total == 1
    offender = report.offenders[0]
    assert offender.path == "consumer/bad_consumer.py"
    assert offender.line == 2
    assert "CallSugar.build" in offender.observed
    assert "factory catalog" in offender.fix


def test_factory_spine_frontier_flags_neutrally_named_xsugar_build_bypass(
    tmp_path,
) -> None:
    kit_src = tmp_path / "src" / "sugar_lift_py_tests" / "consumer"
    kit_src.mkdir(parents=True)
    (kit_src / "bad_consumer.py").write_text(
        "def planted(site, ctx):\n"
        "    node = CallSugar(site)\n"
        "    return node.build(ctx)\n",
        encoding="utf-8",
    )

    report = collect_factory_spine_frontier(tmp_path)

    assert report.r.values["xsugar_build_bypasses"] == 1
    assert report.r.total == 1
    offender = report.offenders[0]
    assert offender.path == "consumer/bad_consumer.py"
    assert offender.line == 3
    assert "node.build" in offender.observed
    assert "factory catalog" in offender.fix


def test_factory_spine_frontier_does_not_flag_non_sugar_builders(tmp_path) -> None:
    kit_src = tmp_path / "src" / "sugar_lift_py_tests" / "proofir"
    kit_src.mkdir(parents=True)
    (kit_src / "nodes.py").write_text(
        "def planted(cls):\n" "    return cls.builder().post(1).build()\n",
        encoding="utf-8",
    )

    report = collect_factory_spine_frontier(tmp_path)

    assert report.r.total == 0


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


def test_floor_contract_agreement_bad_twin_trips_gate() -> None:
    provenance = Provenance(
        node_class="FunctionContract",
        construction_site=ConstructionSite(
            path="tests/test_floor_projection_instruments.py", line=1
        ),
        warrant=Derived(floor_chain=("construction-law",)),
    )
    planted = FunctionContract(
        symbol="t::h::callable",
        formals=(FunctionContract.formal("x", IntSort()),),
        post=PostCondition(
            Eq(VarTerm("out", sort=IntSort()), ConstTerm(99, sort=IntSort())),
            formals={"x": IntSort()},
            out_binding="out",
            out_sort=IntSort(),
        ),
        warrants=(provenance,),
        bridge_source_symbol="call:h",
    )

    violations = floor_contract_agreement_violations_for_fact(
        callee="h",
        callable_contract=planted,
        arg_terms=[num(5)],
        floor_term=num(6),
        callsite_contract="h#euf#c:call:h(i:5)::assertion",
    )

    with pytest.raises(RuntimeError) as exc:
        agreement_gate.enforce_floor_contract_agreement_gate(violations)
    message = str(exc.value)
    assert "floor-contract agreement gate" in message
    assert "h" in message
    assert "t::h::callable" in message
    assert "h#euf#c:call:h(i:5)::assertion" in message


def test_floor_contract_agreement_shadow_interpreter_is_deleted() -> None:
    assert not hasattr(agreement_gate, "_formula_models")
    assert not hasattr(agreement_gate, "_normalize_term")
    assert not hasattr(agreement_gate, "_fold_ctor")
