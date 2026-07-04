from __future__ import annotations

import ast
import json
from dataclasses import replace
from pathlib import Path

from factory_reduce import reduce_value

from sugar_lift_py_tests.claim import SugarRole
from sugar_lift_py_tests.context import FactoryBuildContext, ReduceContext
from sugar_lift_py_tests.factory.build import build_node, default_catalog
from sugar_lift_py_tests.floor import StringValue, SymbolicValue
from sugar_lift_py_tests.ir import make_var
from sugar_lift_py_tests.outcome import Complete
from sugar_lift_py_tests.temporal import TemporalContext
from sugar_lift_py_tests.witness_harness import (
    WitnessPipelineError,
    run_source_through_real_solver,
)


def test_static_joined_str_reduces_literal_segments() -> None:
    assert reduce_value("f'numpy-totality'") == StringValue("numpy-totality")


def test_static_joined_str_bad_twin_flips(tmp_path: Path) -> None:
    truthful = run_source_through_real_solver(
        tmp_path / "joined-str-truthful",
        "def A():\n"
        "    return f'numpy-totality'\n"
        "\n"
        "def test_joined_str_truthful():\n"
        "    assert A() == 'numpy-totality'\n",
    )
    lying = run_source_through_real_solver(
        tmp_path / "joined-str-lying",
        "def A():\n"
        "    return f'numpy-totality'\n"
        "\n"
        "def test_joined_str_lying():\n"
        "    assert A() == 'wrong-totality'\n",
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
    assert "JoinedStrSugar" in truthful.selected_sugars
    assert "JoinedStrSugar" in lying.selected_sugars


def test_formatted_joined_str_with_symbolic_field_is_addressable() -> None:
    ctx = FactoryBuildContext(filename="joined.py", catalog=default_catalog())
    body = ctx.build_body(ast.parse("f'value={x}'", mode="eval").body, SugarRole.TERM)
    reduce_ctx = replace(
        ReduceContext.root(owner="joined-str-test"),
        temporal=TemporalContext.empty().bind_value(
            "x", SymbolicValue(make_var("x"))
        ),
    )

    outcome = body.reduce(reduce_ctx)

    assert isinstance(outcome, Complete)
    assert isinstance(outcome.value, SymbolicValue)
    assert "py.fstring" in repr(outcome.value.term)
    assert "py.format" in repr(outcome.value.term)


def test_dynamic_joined_str_external_argument_refuses_without_transport_error(
    tmp_path: Path,
) -> None:
    source = (
        "import numpy as np\n"
        "\n"
        "def test_dynamic_joined_str_bridge_argument_refuses():\n"
        "    length = 9\n"
        "    assert np.dtype(f'S{length}') == 'S9'\n"
    )

    try:
        result = run_source_through_real_solver(
            tmp_path / "dynamic-joined-str-bridge-argument",
            source,
        )
    except WitnessPipelineError as exc:  # pragma: no cover - assertion payload
        raise AssertionError(
            "dynamic f-string external-call arguments must refuse through the "
            "typed effect path, not abort the lift transport"
        ) from exc

    trace = {
        "rows": result.prove_doc.get("rows"),
        "diagnostics": result.lift_doc.get("diagnostics"),
        "selected": result.selected_sugars,
    }
    print(json.dumps(trace, indent=2, sort_keys=True))

    statuses = [row.get("status") for row in result.prove_doc.get("rows", [])]
    assert statuses == ["refused"]
    assert "JoinedStrSugar" in result.selected_sugars


def test_joined_str_factory_selects_shape_recognizer() -> None:
    ctx = FactoryBuildContext(filename="joined.py", catalog=default_catalog())
    result = build_node(
        ast.parse("f'prefix-{x}'", mode="eval").body,
        filename="joined.py",
        role=SugarRole.TERM,
        ctx=ctx,
    )

    assert result.audit_row.selected == "JoinedStrSugar"
    assert result.audit_row.status == "selected"
