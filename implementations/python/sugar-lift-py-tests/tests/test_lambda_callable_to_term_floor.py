"""LambdaCallable.to_term — construction gap drain (Part of #3809).

Lift-probe (before):

    assert f(lambda x: x + 1) == 1
    assert df.to_csv(float_format=lambda x: x) == 'x'

Refuse: FactoryGap · owner=literal_call_report[ kw:…] · observed=LambdaCallable
· requested=project this floor value to a term
· fix=write more Floor: implement LambdaCallable.to_term

Mechanism: missing floor projection on LambdaCallable — not a missing AST
recognizer. LambdaSugar already owns Lambda and reduces to LambdaCallable;
literal_call_report then projects call actuals through floor_to_term.

Fix: LambdaCallable.to_term mints callable identity ``python:lambda(<param>)``.
Body FOL needs a reduction context to_term does not receive; identity is the
honest opaque coordinate (never fabricate body/computed). Keyword bypass
removed so projection is owned by the floor.

Discrimination: dual-assert unsat via witness EXECUTION.
"""

from __future__ import annotations

import ast
from pathlib import Path

from sugar_lift_py_tests.claim import SugarRole
from sugar_lift_py_tests.context.factory_build_context import FactoryBuildContext
from sugar_lift_py_tests.factory import FactoryGap
from sugar_lift_py_tests.factory.build import default_catalog
from sugar_lift_py_tests.factory.literal_call_report import build_literal_call_report
from sugar_lift_py_tests.factory.source_fragment import SourceFragment
from sugar_lift_py_tests.floor.lambda_callable import LambdaCallable
from sugar_lift_py_tests.ir import _ConstStr, _Ctor
from sugar_lift_py_tests.outcome import complete_value
from sugar_lift_py_tests.sugar.floor_terms import floor_to_term
from sugar_lift_py_tests.witness_harness import run_source_through_real_solver


def _lambda_floor(src: str) -> LambdaCallable:
    node = ast.parse(src, mode="eval").body
    ctx = FactoryBuildContext(filename="t.py", catalog=default_catalog())
    frag = SourceFragment.from_node(node, "t.py")
    value = complete_value(
        ctx.build_body(frag, SugarRole.TERM).reduce(ctx), owner="probe"
    )
    assert isinstance(value, LambdaCallable)
    return value


def test_to_term_is_callable_identity_coordinate() -> None:
    value = _lambda_floor("lambda x: x + 1")
    term = value.to_term(owner="literal_call_report")
    assert isinstance(term, _Ctor)
    assert term.name == "python:lambda"
    assert len(term.args) == 1
    assert isinstance(term.args[0], _ConstStr)
    assert term.args[0].value == "x"
    # floor_to_term is the same door.
    assert floor_to_term(value, owner="probe") == term


def test_positional_lambda_arg_no_construction_gap() -> None:
    src = "def t(f):\n    assert f(lambda x: x + 1) == 1\n"
    try:
        report = build_literal_call_report(
            source=src, filename="t.py", memento_file="t.py"
        )
    except FactoryGap as exc:  # pragma: no cover - regression
        raise AssertionError(f"still construction gap: {exc.info}") from exc
    assert report is not None
    assert report.payload.ir
    blob = repr(report.payload)
    assert "implement LambdaCallable.to_term" not in blob
    assert "project this floor value to a term" not in blob
    assert "python:lambda" in blob


def test_keyword_lambda_projects_via_floor_not_unliftable_bypass() -> None:
    """Former LambdaCallable-unliftable RuntimeEffect is gone; floor owns it.

    Open formal ``df`` may still refuse EqualityFact (ProofIR open-var) — that
    is past the drained to_term projection.
    """
    src = (
        "def test_to_csv(df):\n"
        "    assert df.to_csv(float_format=lambda x: x) == 'x'\n"
    )
    report = build_literal_call_report(
        source=src,
        filename="pandas/tests/frame/methods/test_to_csv.py",
        memento_file="pandas/tests/frame/methods/test_to_csv.py",
    )
    assert report is not None
    blob = repr(report.payload)
    assert "LambdaCallable-unliftable" not in blob
    assert "implement LambdaCallable.to_term" not in blob
    assert not (
        "observed=LambdaCallable" in blob
        and "project this floor value to a term" in blob
    )


def test_array_map_lambda_no_to_term_gap() -> None:
    src = "def t():\n    assert [1, 2].map(lambda x: x + 1) == [2, 3]\n"
    try:
        report = build_literal_call_report(
            source=src, filename="t.py", memento_file="t.py"
        )
    except FactoryGap as exc:  # pragma: no cover - regression
        raise AssertionError(f"still construction gap: {exc.info}") from exc
    assert report is not None
    assert "implement LambdaCallable.to_term" not in repr(report.payload)


def test_map_lambda_dual_assert_refutes_lie_via_witness(tmp_path: Path) -> None:
    """Dual-assert discrimination: truthful map vs lie → unsat via EXECUTION."""
    src = (
        "def t_true():\n"
        "    assert [1, 2].map(lambda x: x + 1) == [2, 3]\n"
        "def t_lie():\n"
        "    assert [1, 2].map(lambda x: x + 1) == [0, 0]\n"
    )
    report = build_literal_call_report(source=src, filename="t.py", memento_file="t.py")
    assert report is not None
    assert "implement LambdaCallable.to_term" not in repr(report.payload)

    result = run_source_through_real_solver(tmp_path / "lambda-map-dual", src)
    statuses = [row.get("status") for row in result.prove_doc.get("rows", [])]
    assert result.verdict == "unsat", (result.verdict, statuses)
    assert "refused" not in statuses
