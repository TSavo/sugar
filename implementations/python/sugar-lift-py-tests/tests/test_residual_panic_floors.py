"""Residual full-dump panic floors after sequence contains + GuardedValue.

Covers the next measured owners:
- StringValue.attribute (19) — bound methods as py.getattr
- UniverseValue.guarded (26) — nested def under if
- DictValue.contains (5) — key membership
- ComprehensionValue.contains (5) — undecided membership / finite fold
- PredicateValue.attribute (7) — py.getattr
"""

import tempfile

from frame_fresh import fresh
from sugar_lift_py_tests.floor import (
    DictValue,
    StringValue,
    SymbolicValue,
    TermValue,
)
from sugar_lift_py_tests.floor.comprehension_value import ComprehensionValue
from sugar_lift_py_tests.floor.predicate_value import PredicateValue
from sugar_lift_py_tests.ir import atomic, ctor, make_var
from sugar_lift_py_tests.sugar.false_bool_literal_sugar import FalseBoolLiteralSugar
from sugar_lift_py_tests.sugar.true_bool_literal_sugar import TrueBoolLiteralSugar
from sugar_lift_py_tests.context_manager_resolution import TreeConstructionContextV1


def test_string_attribute_is_py_getattr_coordinate():
    outcome = StringValue("{:.2f}").attribute("format", "site", None)
    value = outcome.completed_value()
    assert isinstance(value, SymbolicValue)
    assert value.term.name == "py.getattr"


def test_predicate_attribute_is_py_getattr_coordinate():
    pred = PredicateValue(atomic("choose", []), "site")
    outcome = pred.attribute("dtype", "site", None)
    value = outcome.completed_value()
    assert isinstance(value, SymbolicValue)
    assert value.term.name == "py.getattr"


def test_dict_key_membership_folds():
    d = fresh(DictValue, ((TermValue(1), TermValue(10)), (TermValue(2), TermValue(20))))
    assert isinstance(
        d.contains(TermValue(2), "site").completed_value(), TrueBoolLiteralSugar
    )
    assert isinstance(
        d.contains(TermValue(9), "site").completed_value(), FalseBoolLiteralSugar
    )


def test_opaque_comprehension_membership_is_the_undecided_membership():
    """Its members' ``__eq__`` may raise: two faces, the halt kept, never
    the bare ``py.in`` (#7757 H10)."""
    from sugar_lift_py_tests.effect.raise_effect import UndeterminedRaiseEffect
    from sugar_lift_py_tests.outcome import Completed, Halted

    comp = ComprehensionValue(ctor("py.listcomp", [make_var("xs")]))
    outcome = comp.contains(TermValue(1), "site")
    assert outcome.completed_value() is None
    (completed,) = [face for face in outcome.exits if isinstance(face, Completed)]
    (halted,) = [face for face in outcome.exits if isinstance(face, Halted)]
    assert completed.guard.name == "python:compare.completes"
    assert isinstance(completed.value, PredicateValue)
    assert isinstance(halted.effect, UndeterminedRaiseEffect)
    assert halted.effect.producer_node_owner == "UndecidedCompare:In"


def test_nested_function_def_under_if_does_not_panic_on_universe_guarded():
    from sugar_lift_python_source.source_oracle import path_source
    from sugar_source_tree.tree import SourceFile

    src = "def outer():\n    if True:\n        def inner():\n            return 1\n    return 2\n"
    with tempfile.NamedTemporaryFile("w", suffix=".py", delete=False, dir="/tmp") as f:
        f.write(src)
        path = f.name
    fn = next(
        SourceFile(
            path_source(path),
            construction_context=TreeConstructionContextV1.for_test_without_workspace(),
        ).functions()
    )
    outcome = fn.sugar().desugar()
    # Must complete without ConstructionPanic on UniverseValue.guarded.
    assert outcome is not None
