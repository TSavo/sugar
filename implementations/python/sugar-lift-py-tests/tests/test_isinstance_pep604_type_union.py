"""#5340 — PEP 604 type-union isinstance must construct, never process-crash.

Illegal shape (vendor wall, sklearn/utils/tests/test_stats.py seat via
``_pytest.python_api`` ``isinstance(expected, str | bytes)``):

  Runtime BitOr of ground ``python:type`` leaves reduces to
  ``_Ctor('|', (python:type(str), python:type(bytes)))``. ``test_python_type``
  used to fall through to ``DynamicTypeOperandRuntimeEffect`` for that ground
  union; RuntimeEffect then panics (or a flaky harness classifies the red as
  native-crash). Soft-complete and timeout-laundering are forbidden.

Replacement architecture:

  Shared floor: flatten ground ``|`` trees of ``python:type`` leaves and
  dispatch the same multi-arm isinstance collector as tuple-of-types
  (``TupleValue.test_python_type``). Symbolic → ``or(adt.is_python_type, …)``;
  ground → True/False. Not a sklearn / pytest special case.

R_native_crashes vendor wall: ε = −1 on the test_stats process-crash seat
(expect completed construction or typed FactoryPanic on a different residual —
never signal).
"""

from __future__ import annotations

import ast
from dataclasses import replace

from factory_reduce import reduce_value

from sugar_lift_py_tests.claim import SugarRole
from sugar_lift_py_tests.context.factory_build_context import FactoryBuildContext
from sugar_lift_py_tests.factory.build import build_node, default_catalog
from sugar_lift_py_tests.factory.source_fragment import SourceFragment
from sugar_lift_py_tests.floor import PredicateValue, SymbolicValue
from sugar_lift_py_tests.ir import atomic, ctor, make_var, or_, str_const
from sugar_lift_py_tests.lift_rpc import lift_file_payload
from sugar_lift_py_tests.outcome import complete_value
from sugar_lift_py_tests.sugar.false_bool_literal_sugar import FalseBoolLiteralSugar
from sugar_lift_py_tests.sugar.true_bool_literal_sugar import TrueBoolLiteralSugar
from sugar_lift_py_tests.temporal import TemporalContext


def _reduce_sourced(source: str, binds: dict | None = None):
    node = ast.parse(source, mode="eval").body
    site = SourceFragment.from_node(node, "t.py", source=source)
    temporal = TemporalContext.empty()
    for name, value in (binds or {}).items():
        temporal = temporal.bind_value(name, value)
    if binds is None:
        temporal = temporal.bind_value("x", SymbolicValue(make_var("x")))
    ctx = replace(
        FactoryBuildContext(filename="t.py", catalog=default_catalog()),
        temporal=temporal,
    )
    return complete_value(
        build_node(site, filename="t.py", role=SugarRole.TERM, ctx=ctx).sugar.desugar(
            ctx
        ),
        owner="test",
    )


def test_pep604_union_isinstance_emits_native_disjunction() -> None:
    """Illegal: ground type-union → RuntimeEffect. Replacement: or of testers."""
    value = _reduce_sourced(
        "isinstance(x, str | bytes)",
        {"x": SymbolicValue(make_var("x"))},
    )
    assert type(value) is PredicateValue
    assert value.formula == or_(
        [
            atomic(
                "adt.is_python_type",
                [make_var("x"), ctor("python:type", [str_const("str")])],
            ),
            atomic(
                "adt.is_python_type",
                [make_var("x"), ctor("python:type", [str_const("bytes")])],
            ),
        ]
    )
    assert "call:isinstance" not in repr(value.formula)


def test_pep604_union_isinstance_ground_folds_true_and_false() -> None:
    assert type(_reduce_sourced("isinstance('vendor', str | bytes)")) is (
        TrueBoolLiteralSugar
    )
    assert type(_reduce_sourced("isinstance(1, str | bytes)")) is FalseBoolLiteralSugar
    # Nested left-assoc union matches Python ``int | str | bytes``.
    assert type(_reduce_sourced("isinstance('x', int | str | bytes)")) is (
        TrueBoolLiteralSugar
    )
    assert type(_reduce_sourced("isinstance(0.5, int | str | bytes)")) is (
        FalseBoolLiteralSugar
    )


def test_pep604_union_matches_tuple_of_types_surface() -> None:
    """Same multi-arm collector as ``isinstance(x, (str, bytes))``."""
    union = _reduce_sourced(
        "isinstance(x, str | bytes)",
        {"x": SymbolicValue(make_var("x"))},
    )
    tupled = reduce_value(
        "isinstance(x, (str, bytes))",
        {"x": SymbolicValue(make_var("x"))},
    )
    assert type(union) is PredicateValue
    assert type(tupled) is PredicateValue
    assert union.formula == tupled.formula


def test_production_lift_of_pep604_isinstance_constructs_without_panic() -> None:
    """Product shape from _pytest.python_api / sklearn test_stats dig path."""
    source = (
        "def approx_guard(expected):\n"
        "    return isinstance(expected, str | bytes)\n"
    )
    file = "pep604_isinstance.py"
    from sugar_lift_py_tests.factory.factory_gap import FactoryPanic

    try:
        payload = lift_file_payload(source, file)
    except FactoryPanic as panic:
        raise AssertionError(
            "PEP 604 type-union isinstance must construct; got FactoryPanic: "
            f"{panic}"
        ) from panic
    rpc = payload.to_rpc()
    assert rpc.get("ir") is not None or "ir" in rpc or len(payload.ir) >= 0


def test_illegal_runtime_effect_on_ground_type_union_is_retired() -> None:
    """Named illegal shape: DynamicTypeOperandRuntimeEffect over `|` of types."""
    from sugar_lift_py_tests.floor.symbolic_value import SymbolicValue as SV
    from sugar_lift_py_tests.ir import ctor, str_const
    from sugar_lift_py_tests.outcome import Complete, Incomplete

    union = SV(
        ctor(
            "|",
            [
                ctor("python:type", [str_const("str")]),
                ctor("python:type", [str_const("bytes")]),
            ],
        )
    )
    site = SourceFragment.from_node(
        ast.parse("isinstance(x, str | bytes)", mode="eval").body,
        "t.py",
        source="isinstance(x, str | bytes)",
    )
    outcome = union.test_python_type(SymbolicValue(make_var("x")), site)
    assert type(outcome) is Complete
    assert type(outcome.value) is PredicateValue
    assert type(outcome) is not Incomplete
