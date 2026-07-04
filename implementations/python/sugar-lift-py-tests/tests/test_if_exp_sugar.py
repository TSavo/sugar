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
    assert "IfExpSugar" in truthful.selected_sugars
    assert "IfExpSugar" in lying.selected_sugars


def test_runtime_condition_ifexp_refuses() -> None:
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

    assert isinstance(outcome, Incomplete)
    assert isinstance(outcome.effect, RuntimeEffect)
    assert "conditional expression runtime boundary" in outcome.reason
    assert "condition `Name` is evaluated at runtime" in outcome.reason
    assert "typed red" in outcome.reason
    assert "blame=" in outcome.reason


def test_runtime_condition_inside_bridge_body_stays_typed_effect() -> None:
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

    assert isinstance(outcome, Incomplete)
    assert isinstance(outcome.effect, RuntimeEffect)
    assert "conditional expression runtime boundary" in outcome.reason
    assert "condition `Compare` is evaluated at runtime" in outcome.reason


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
