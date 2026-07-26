"""Residual full-dump panic floors after sequence contains + GuardedValue.

Covers the next measured owners:
- StringValue.attribute (19) — bound methods as py.getattr
- UniverseValue.guarded (26) — nested def under if
- DictValue.contains (5) — key membership
- ComprehensionValue.contains (5) — py.in / finite fold
- PredicateValue.attribute (7) — py.getattr
"""

import tempfile

from sugar_lift_py_tests.floor import (
    DictValue,
    StringValue,
    SymbolicValue,
    TermValue,
)
from sugar_lift_py_tests.floor.comprehension_value import ComprehensionValue
from sugar_lift_py_tests.floor.predicate_value import PredicateValue
from sugar_lift_py_tests.ir import atomic, ctor, make_var
from sugar_lift_py_tests.outcome import Complete
from sugar_lift_py_tests.sugar.false_bool_literal_sugar import FalseBoolLiteralSugar
from sugar_lift_py_tests.sugar.true_bool_literal_sugar import TrueBoolLiteralSugar


def test_string_attribute_is_py_getattr_coordinate():
    outcome = StringValue("{:.2f}").attribute("format", "site")
    assert isinstance(outcome, Complete)
    assert isinstance(outcome.value, SymbolicValue)
    assert outcome.value.term.name == "py.getattr"


def test_predicate_attribute_is_py_getattr_coordinate():
    pred = PredicateValue(atomic("choose", []), "site")
    outcome = pred.attribute("dtype", "site")
    assert isinstance(outcome, Complete)
    assert isinstance(outcome.value, SymbolicValue)
    assert outcome.value.term.name == "py.getattr"


def test_dict_key_membership_folds():
    d = DictValue(((TermValue(1), TermValue(10)), (TermValue(2), TermValue(20))))
    assert isinstance(d.contains(TermValue(2), "site").value, TrueBoolLiteralSugar)
    assert isinstance(d.contains(TermValue(9), "site").value, FalseBoolLiteralSugar)


def test_opaque_comprehension_membership_emits_py_in():
    comp = ComprehensionValue(ctor("py.listcomp", [make_var("xs")]))
    result = comp.contains(TermValue(1), "site").value
    assert isinstance(result, PredicateValue)
    assert result.formula.name == "py.in"


def test_nested_function_def_under_if_does_not_panic_on_universe_guarded():
    from sugar_lift_python_source.source_oracle import path_source
    from sugar_source_tree.tree import SourceFile

    src = "def outer():\n    if True:\n        def inner():\n            return 1\n    return 2\n"
    with tempfile.NamedTemporaryFile("w", suffix=".py", delete=False, dir="/tmp") as f:
        f.write(src)
        path = f.name
    fn = next(SourceFile(path_source(path)).functions())
    outcome = fn.sugar().desugar()
    # Must complete without ConstructionPanic on UniverseValue.guarded.
    assert outcome is not None
