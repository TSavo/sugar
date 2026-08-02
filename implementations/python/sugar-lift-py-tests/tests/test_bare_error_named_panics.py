"""Bare TypeError/RuntimeError/ValueError on construction doors must name the gap.

Construct or panic. A type dump is not a panic that says what could not be built.
"""

from __future__ import annotations

from sugar_lift_py_tests.gap.panic import ConstructionPanic
from sugar_source_tree.panic import SugarNotWritten


def test_unhandled_effect_panics_with_species() -> None:
    from sugar_lift_py_tests.effect.effect import _unhandled_effect

    class ForeignEffect:
        pass

    try:
        _unhandled_effect(ForeignEffect())  # type: ignore[arg-type]
        raise AssertionError("expected ConstructionPanic")
    except ConstructionPanic as p:
        assert "ForeignEffect" in p.info.observed
        assert p.info.requested
        assert p.info.fix


def test_complete_value_unknown_outcome_panics() -> None:
    from sugar_lift_py_tests.outcome.complete_value import complete_value

    class ForeignOutcome:
        pass

    try:
        complete_value(ForeignOutcome(), owner="test.owner")  # type: ignore[arg-type]
        raise AssertionError("expected ConstructionPanic")
    except ConstructionPanic as p:
        assert "ForeignOutcome" in p.info.observed
        assert p.info.owner == "test.owner"


def test_ordered_binding_keys_non_str_panics() -> None:
    from sugar_source_tree.nodes import _ordered_binding_keys

    try:
        _ordered_binding_keys(["ok", 12])  # type: ignore[list-item]
        raise AssertionError("expected SugarNotWritten")
    except SugarNotWritten as gap:
        assert "int" in gap.observed or "12" in gap.observed or "not a str" in gap.observed
        assert gap.fix


def test_unknown_unary_op_panics() -> None:
    from sugar_lift_py_tests.sugar.unary_op_sugar import UnaryOpSugar
    from sugar_lift_py_tests.sugar.name_sugar import NameSugar
    from sugar_source_tree.tree import SourceFile
    from sugar_lift_python_source.canonical import blake3_512_of

    src = "x\n"
    sf = SourceFile((src, "u.py", blake3_512_of(src.encode())))
    try:
        UnaryOpSugar(
            op_kind="NotARealOp",
            operand=NameSugar(name="x", site=sf.root.fragment),
            site=sf.root.fragment,
        )
        raise AssertionError("expected ConstructionPanic")
    except ConstructionPanic as p:
        assert "NotARealOp" in p.info.observed
