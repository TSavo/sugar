"""Compare laws at pandas' arithmetic-helper boundary.

The source coordinate is the real caller family in
``pandas/tests/arithmetic/common.py``.  Each test keeps one comparison law
separate so ordering's exceptional exit cannot leak into equality, identity,
or membership.
"""

from pathlib import Path
import os

from sugar_lift_python_source.source_oracle import path_source
from sugar_source_tree.tree import SourceFile


def _comparison(tmp_path: Path, expression: str):
    path = tmp_path / "pandas" / "tests" / "arithmetic" / "common.py"
    path.parent.mkdir(parents=True, exist_ok=True)
    # pandas' helper evaluates these as expression statements inside
    # ``pytest.raises``.  A module assignment keeps the same Compare caller
    # while avoiding unrelated function-construction machinery in this focused
    # law test.
    path.write_text(f"result = {expression}\n")
    relative_path = os.path.relpath(path, Path.cwd())
    source_file = SourceFile(path_source(relative_path))
    (comparison,) = [node for node in source_file if node.kind == "Compare"]
    return comparison.sugar().desugar()


def test_pandas_ordering_helper_produces_named_type_error(tmp_path: Path) -> None:
    from sugar_lift_py_tests.floor import RaiseValue
    from sugar_lift_py_tests.outcome import Complete

    outcome = _comparison(tmp_path, '1 < "mismatched"')

    assert isinstance(outcome, Complete)
    assert isinstance(outcome.value, RaiseValue)
    assert outcome.value.effect.exception_name == "TypeError"


def test_pandas_ordering_helper_keeps_compatible_ordering_non_exceptional(
    tmp_path: Path,
) -> None:
    from sugar_lift_py_tests.outcome import Complete
    from sugar_lift_py_tests.sugar.true_bool_literal_sugar import TrueBoolLiteralSugar

    outcome = _comparison(tmp_path, "1 < 2")

    assert isinstance(outcome, Complete)
    assert isinstance(outcome.value, TrueBoolLiteralSugar)


def test_identity_remains_total_and_non_raising(tmp_path: Path) -> None:
    from sugar_lift_py_tests.outcome import Complete

    assert isinstance(_comparison(tmp_path, '1 is "mismatched"'), Complete)


def test_membership_dispatches_through_contains(tmp_path: Path) -> None:
    from sugar_lift_py_tests.outcome import Complete
    from sugar_lift_py_tests.sugar.true_bool_literal_sugar import TrueBoolLiteralSugar

    outcome = _comparison(tmp_path, "1 in [1, 2]")

    assert isinstance(outcome, Complete)
    assert isinstance(outcome.value, TrueBoolLiteralSugar)


def test_equality_does_not_borrow_orderings_exception_law(tmp_path: Path) -> None:
    from sugar_lift_py_tests.floor import PredicateValue
    from sugar_lift_py_tests.outcome import Complete

    outcome = _comparison(tmp_path, '1 == "mismatched"')

    assert isinstance(outcome, Complete)
    assert isinstance(outcome.value, PredicateValue)
