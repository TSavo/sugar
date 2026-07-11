from __future__ import annotations

import ast
import json
from dataclasses import replace
from pathlib import Path

from factory_reduce import reduce_value

from sugar_lift_py_tests.claim import SugarRole
from sugar_lift_py_tests.context import FactoryBuildContext, ReduceContext
from sugar_lift_py_tests.effect import RuntimeEffect
from sugar_lift_py_tests.factory.build import build_node, default_catalog
from sugar_lift_py_tests.floor import SymbolicValue, TermValue
from sugar_lift_py_tests.ir import make_var
from sugar_lift_py_tests.outcome import Incomplete
from sugar_lift_py_tests.temporal import TemporalContext
from sugar_lift_py_tests.witness_harness import run_source_through_real_solver


def test_literal_ifexp_true_branch_reduces() -> None:
    assert reduce_value("1 if True else 2") == TermValue(1)


def test_literal_ifexp_false_branch_reduces() -> None:
    assert reduce_value("1 if False else 2") == TermValue(2)


def test_literal_ifexp_bad_twin_flips(tmp_path: Path) -> None:
    truthful = run_source_through_real_solver(
        tmp_path / "if-exp-truthful",
        "def A():\n"
        "    return 1 if True else 2\n"
        "\n"
        "def test_if_exp_truthful():\n"
        "    assert A() == 1\n",
    )
    lying = run_source_through_real_solver(
        tmp_path / "if-exp-lying",
        "def A():\n"
        "    return 1 if True else 2\n"
        "\n"
        "def test_if_exp_lying():\n"
        "    assert A() == 2\n",
    )
    print(
        json.dumps(
            {
                "truthful": truthful.prove_doc,
                "lying": lying.prove_doc,
                "selected": {
                    "truthful": truthful.selected_sugars,
                    "lying": lying.selected_sugars,
                },
            },
            indent=2,
            sort_keys=True,
        )
    )

    assert truthful.verdict == "sat"
    assert lying.verdict == "unsat"


def test_runtime_condition_ifexp_is_py_if_exp_coordinate() -> None:
    """Symbolic condition is py.if_exp term coordinate — not RuntimeEffect red."""
    ctx = FactoryBuildContext(filename="if_exp.py", catalog=default_catalog())
    body = ctx.build_body(
        ast.parse("1 if flag else 2", mode="eval").body, SugarRole.TERM
    )
    reduce_ctx = replace(
        ReduceContext.root(owner="if-exp-test"),
        temporal=TemporalContext.empty().bind_value(
            "flag", SymbolicValue(make_var("flag"))
        ),
    )

    outcome = body.reduce(reduce_ctx)

    from sugar_lift_py_tests.floor import CallSiteValue
    from sugar_lift_py_tests.outcome import Complete

    assert isinstance(outcome, Complete)
    assert isinstance(outcome.value, CallSiteValue)
    assert outcome.value.target_name == "if_exp"
    term = outcome.value.term
    assert getattr(term, "name", None) == "py.if_exp"


def test_ifexp_factory_selects_shape_recognizer() -> None:
    ctx = FactoryBuildContext(filename="if_exp.py", catalog=default_catalog())
    result = build_node(
        ast.parse("1 if True else 2", mode="eval").body,
        filename="if_exp.py",
        role=SugarRole.TERM,
        ctx=ctx,
    )

    assert result.audit_row.selected == "IfExpSugar"
    assert result.audit_row.status == "selected"


def test_runtime_condition_inside_bridge_body_is_complete() -> None:
    module = ast.parse(
        "def choose(flag):\n"
        "    value = 1 if flag == 1 else 2\n"
        "    return value\n"
        "\n"
        "choose(1)\n"
    )
    function_node = module.body[0]
    call_node = module.body[1].value
    ctx = FactoryBuildContext(
        filename="if_exp.py",
        catalog=default_catalog(),
        name_resolver={"choose": function_node},
    )

    body = ctx.build_body(call_node, SugarRole.TERM)
    outcome = body.reduce(ReduceContext.root(owner="if-exp-bridge-test"))

    from sugar_lift_py_tests.outcome import Complete

    assert isinstance(outcome, Complete)
