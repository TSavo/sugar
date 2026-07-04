from __future__ import annotations

import ast
import json
from dataclasses import replace
from pathlib import Path

import pytest
from factory_reduce import reduce_value

from sugar_lift_py_tests.claim import SugarRole
from sugar_lift_py_tests.context import FactoryBuildContext, ReduceContext
from sugar_lift_py_tests.factory import FactoryGap
from sugar_lift_py_tests.factory.build import build_node, default_catalog
from sugar_lift_py_tests.floor import ArrayLiteral, SymbolicValue, TermValue
from sugar_lift_py_tests.ir import make_var
from sugar_lift_py_tests.temporal import TemporalContext
from sugar_lift_py_tests.witness_harness import run_source_through_real_solver


def test_literal_list_comp_reduces_finite_domain() -> None:
    assert reduce_value("[x + 1 for x in [1, 2, 3]]") == ArrayLiteral(
        (TermValue(2), TermValue(3), TermValue(4))
    )


def test_literal_list_comp_filter_reduces_finite_domain() -> None:
    assert reduce_value("[x for x in [1, 2, 3] if x != 2]") == ArrayLiteral(
        (TermValue(1), TermValue(3))
    )


def test_literal_list_comp_bad_twin_flips(tmp_path: Path) -> None:
    truthful = run_source_through_real_solver(
        tmp_path / "list-comp-truthful",
        "def A():\n"
        "    return len([x + 1 for x in [1, 2, 3]])\n"
        "\n"
        "def test_list_comp_truthful():\n"
        "    assert A() == 3\n",
    )
    lying = run_source_through_real_solver(
        tmp_path / "list-comp-lying",
        "def A():\n"
        "    return len([x + 1 for x in [1, 2, 3]])\n"
        "\n"
        "def test_list_comp_lying():\n"
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
    assert "ListCompSugar" in truthful.selected_sugars
    assert "ListCompSugar" in lying.selected_sugars


def test_runtime_iterable_list_comp_is_typed_runtime_effect() -> None:
    ctx = FactoryBuildContext(filename="list_comp.py", catalog=default_catalog())
    body = ctx.build_body(ast.parse("[x for x in xs]", mode="eval").body, SugarRole.TERM)
    reduce_ctx = replace(
        ReduceContext.root(owner="list-comp-test"),
        temporal=TemporalContext.empty().bind_value(
            "xs", SymbolicValue(make_var("xs"))
        ),
    )

    with pytest.raises(FactoryGap) as raised:
        body.reduce(reduce_ctx)

    assert raised.value.audit_row.status == "refused"
    assert raised.value.audit_row.selected == "ListCompSugar"
    assert "list comprehension runtime iterable" in raised.value.info["fix"]
    assert "use a literal finite domain" in raised.value.info["fix"]


def test_list_comp_factory_selects_shape_recognizer() -> None:
    ctx = FactoryBuildContext(filename="list_comp.py", catalog=default_catalog())
    result = build_node(
        ast.parse("[x for x in [1]]", mode="eval").body,
        filename="list_comp.py",
        role=SugarRole.TERM,
        ctx=ctx,
    )

    assert result.audit_row.selected == "ListCompSugar"
    assert result.audit_row.status == "selected"
