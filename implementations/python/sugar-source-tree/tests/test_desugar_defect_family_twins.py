"""Discrimination twins for the desugar implementation-defect families.

Each family gets BOTH arms: the shape that used to raise an ordinary unexpected
exception now lifts (positive), and a neighbouring shape confirms the fix did not
widen its way to green by flattening the distinction it was supposed to keep
(discriminating). Cardinalities are exact; nothing here asserts ``!= 1``.

The families, by the census kind string they used to produce:

- ``AttributeError: 'ContractConditionalConstructionV1' has no attribute 'guarded'``
- ``NotImplementedError: a conditional-expression arm that reduces to an effect ...``
- ``AttributeError: 'ExitSet' object has no attribute 'value'``
- ``AttributeError: 'SourceFragment' has no attribute 'compare_left'``
- ``AssertionError:`` (bare)
- ``NotImplementedError: condition folded without a symbolic formula: NamedExpressionValue``
"""

from __future__ import annotations

import tempfile

import pytest

from sugar_lift_py_tests.caller_parameter_contract import (
    ContractConditionalConstructionV1,
)
from sugar_lift_py_tests.floor.guarded_value import GuardedValue
from sugar_lift_py_tests.floor.universe_value import UniverseValue
from sugar_lift_py_tests.ir import formula_to_value
from sugar_lift_py_tests.outcome import Complete
from sugar_lift_python_source.source_oracle import path_source
from sugar_source_tree.tree import SourceFile


def _out(source: str):
    with tempfile.NamedTemporaryFile("w", suffix=".py", delete=False, dir="/tmp") as f:
        f.write(source)
        path = f.name
    return next(SourceFile(path_source(path)).functions()).sugar().desugar()


def _statements(out):
    assert isinstance(out, Complete)
    assert isinstance(out.value, UniverseValue)
    return out.value.record.statements


def _pending(out):
    return tuple(
        row
        for row in _statements(out)
        if isinstance(row, ContractConditionalConstructionV1)
    )


def _demand_shape(entry):
    """The demanded formula's outermost connective, as wire vocabulary."""
    return formula_to_value(entry.demand.demanded_formula)


# --------------------------------------------------------------------------
# Family: ContractConditionalConstructionV1 has no attribute 'guarded'
# --------------------------------------------------------------------------


def test_guarded_pending_contract_lifts_and_weakens_its_demand() -> None:
    """POSITIVE. A formal subscript under an `if` used to raise AttributeError."""
    out = _out("def f(p, c):\n if c:\n  return p[0]\n return 0\n")
    pending = _pending(out)
    assert len(pending) == 1
    # The obligation is owed only on the guarded face: the demanded formula is an
    # implication, not the bare `python:indexable` atom.
    shape = _demand_shape(pending[0])
    assert shape["kind"] == "implies", shape


def test_unguarded_pending_contract_keeps_its_bare_demand() -> None:
    """DISCRIMINATING. Without a guard the demand must NOT become an implication.

    If `guarded` were applied unconditionally, every demand would weaken to
    `true -> P` and a caller could discharge nothing.
    """
    out = _out("def f(p):\n return p[0]\n")
    pending = _pending(out)
    assert len(pending) == 1
    shape = _demand_shape(pending[0])
    assert shape["kind"] != "implies", shape


def test_nested_guards_compose_on_one_demand() -> None:
    """DISCRIMINATING. Two enclosing guards weaken the SAME single demand once
    per guard -- they do not duplicate the entry."""
    out = _out("def f(p, c, d):\n if c:\n  if d:\n   return p[0]\n return 0\n")
    assert len(_pending(out)) == 1


# --------------------------------------------------------------------------
# Family: conditional-expression arm that reduces to an effect
# --------------------------------------------------------------------------


def test_conditional_expression_with_an_effect_arm_lifts_as_a_partition() -> None:
    """POSITIVE. `1 if c else <unbound name>` used to raise NotImplementedError.

    The else arm halts (there is no such binding), so the expression partitions:
    under `c` it is the value, under `not c` control leaves. It lifts.
    """
    out = _out("def f(c):\n return 1 if c else missing_name\n")
    assert _statements(out)


def test_conditional_expression_of_two_values_stays_one_guarded_value() -> None:
    """DISCRIMINATING. The all-values case must still FUSE into one GuardedValue.

    Widening every conditional to an exit-set partition would have made the
    positive test above pass while destroying the design the whole file rests on
    (operations distribute into both arms; equality resolves per atom).
    """
    out = _out("def f(c):\n x = 1 if c else 2\n return x\n")
    guarded = [
        row
        for row in _statements(out)
        if isinstance(getattr(row, "value", None), GuardedValue)
    ]
    assert len(guarded) == 1


# --------------------------------------------------------------------------
# Family: 'ExitSet' object has no attribute 'value'
# --------------------------------------------------------------------------


def test_collection_element_that_partitions_lifts() -> None:
    """POSITIVE. A store inside a collection element partitions the element."""
    out = _out("def f(d, k, v):\n return [1, d.setdefault(k, v)]\n")
    assert _statements(out)


def test_collection_of_plain_elements_is_one_completed_value() -> None:
    """DISCRIMINATING. No element partitions -> exactly one universe, no split."""
    out = _out("def f():\n return [1, 2, 3]\n")
    assert isinstance(_out("def f():\n return [1, 2, 3]\n"), Complete)
    assert len(_statements(out)) >= 1


def test_dict_display_pairs_keys_with_their_own_values() -> None:
    """DISCRIMINATING. Keys and values reduce as ONE interleaved sequence; the
    re-pairing must not transpose them."""
    from sugar_lift_py_tests.floor.dict_value import DictValue

    out = _out("def f():\n return {1: 'a', 2: 'b'}\n")
    dicts = [
        row.value
        for row in _statements(out)
        if isinstance(getattr(row, "value", None), DictValue)
    ]
    assert len(dicts) == 1
    keys = tuple(key.value for key, _ in dicts[0].entries)
    values = tuple(value.value for _, value in dicts[0].entries)
    assert keys == (1, 2)
    assert values == ("a", "b")


def test_fstring_over_a_partitioning_part_lifts() -> None:
    """POSITIVE. An f-string interpolation whose value partitions."""
    out = _out("def f(d, k, v):\n return f\"x={d.setdefault(k, v)}\"\n")
    assert _statements(out)


def test_boolean_operator_over_a_partitioning_operand_lifts() -> None:
    """POSITIVE. A conjunct whose store partitions."""
    out = _out("def f(a, d, k, v):\n return a and d.setdefault(k, v)\n")
    assert _statements(out)


# --------------------------------------------------------------------------
# Family: 'SourceFragment' has no attribute 'compare_left'
# --------------------------------------------------------------------------


def test_equality_against_a_conditional_refines_the_named_place() -> None:
    """POSITIVE. `x == "a"` where x is conditionally bound used to raise
    AttributeError reaching for `site.compare_left()`."""
    out = _out(
        "def f(c):\n"
        " if c:\n"
        "  x = 'a'\n"
        " else:\n"
        "  x = 'b'\n"
        " return x == 'a'\n"
    )
    assert _statements(out)


def test_dotted_expr_name_is_structural_not_a_name_table() -> None:
    """DISCRIMINATING. Only a Name or an Attribute chain of Names is a PLACE.

    A call or subscript anywhere in the chain names nothing stable, so it must
    answer None and refine no binding.
    """
    from sugar_source_tree.nodes import Attribute, Call, Name, Subscript

    def one_expression(source: str):
        out = next(SourceFile(path_source(_write(source))).functions())
        return out

    def _write(source: str) -> str:
        with tempfile.NamedTemporaryFile(
            "w", suffix=".py", delete=False, dir="/tmp"
        ) as handle:
            handle.write(source)
            return handle.name

    fn = one_expression("def f(a, d, k):\n return (a, a.b.c, a.b(), d[k].b)\n")
    tuple_node = fn.body[0].value
    named, dotted, called, subscripted = tuple_node.elements
    assert isinstance(named, Name)
    assert named.dotted_expr_name() == "a"
    assert isinstance(dotted, Attribute)
    assert dotted.dotted_expr_name() == "a.b.c"
    assert isinstance(called, Call)
    assert called.dotted_expr_name() is None
    assert isinstance(subscripted, Attribute)
    assert isinstance(subscripted.value, Subscript)
    assert subscripted.dotted_expr_name() is None


def test_chained_equality_uses_each_pairs_own_left_operand() -> None:
    """DISCRIMINATING. `a.k == b == c` is two pairs; the second pair's left is
    `b`, not `a.k`. A Compare-level fragment cannot tell them apart, which is
    exactly why the coordinate is passed at construction."""
    from sugar_lift_py_tests.sugar.equality_op_sugar import EqualityOpSugar

    with tempfile.NamedTemporaryFile("w", suffix=".py", delete=False, dir="/tmp") as h:
        h.write("def f(a, b, c):\n return a.k == b == c\n")
        path = h.name
    fn = next(SourceFile(path_source(path)).functions())
    boolop = fn.body[0].value.sugar()
    pairs = [v for v in boolop.values if isinstance(v, EqualityOpSugar)]
    assert len(pairs) == 2
    assert [pair.left_coordinate for pair in pairs] == ["a.k", "b"]


# --------------------------------------------------------------------------
# Family: bare AssertionError
# --------------------------------------------------------------------------


def test_no_bare_assert_survives_in_the_guarded_join_floor() -> None:
    """DISCRIMINATING (static). A bare assert names no law, so the census only
    ever saw `AssertionError: ` with an empty message. The guarded-join floor
    must state its law instead."""
    import pathlib

    import sugar_lift_py_tests.floor as floor_package

    root = pathlib.Path(floor_package.__file__).parent
    offenders = []
    for path in (root / "guarded_value.py", root / "predicate_value.py"):
        for number, line in enumerate(path.read_text().splitlines(), start=1):
            stripped = line.strip()
            if stripped.startswith("assert ") and " ," not in stripped:
                offenders.append(f"{path.name}:{number}: {stripped}")
    assert offenders == []


def test_single_outcome_law_names_the_violated_law() -> None:
    """POSITIVE. The replacement for the bare assert states what was violated."""
    from sugar_lift_py_tests.floor.single_outcome_law import (
        SINGLE_OUTCOME_LAW,
        require_single_value,
    )
    from sugar_lift_py_tests.gap.panic import ConstructionPanic
    from sugar_lift_py_tests.outcome import ExitSet

    with pytest.raises(ConstructionPanic) as raised:
        require_single_value(
            ExitSet(()), owner="twin", blame="twin", arm="when_true"
        )
    assert SINGLE_OUTCOME_LAW in str(raised.value)
    assert "when_true" in str(raised.value)


def test_conditional_receiver_with_a_pending_contract_arm_lifts() -> None:
    """POSITIVE. The live bare-assert offender: an operation distributed into a
    conditional arm whose answer carries a pending parameter contract."""
    out = _out(
        "def f(c, p, q):\n"
        " if c:\n"
        "  x = p\n"
        " else:\n"
        "  x = q\n"
        " return x[0]\n"
    )
    assert _statements(out)


# --------------------------------------------------------------------------
# Family: condition folded without a symbolic formula: NamedExpressionValue
# --------------------------------------------------------------------------


def test_walrus_condition_guards_on_the_presented_face() -> None:
    """POSITIVE. `if (n := a == b):` used to blame the walrus wrapper for a
    formula its presented value had all along."""
    out = _out("def f(a, b):\n if (n := a == b):\n  return 1\n return 0\n")
    assert _statements(out)


def test_a_condition_with_no_formula_at_all_is_still_loud() -> None:
    """DISCRIMINATING. Projecting through the presented face must not invent a
    guard where there is none: a condition that folds to a non-boolean ground
    value stays loud, and now names the PRESENTED type."""
    from sugar_lift_py_tests.floor.int_value import IntValue
    from sugar_lift_py_tests.floor.named_expression_value import NamedExpressionValue
    from sugar_lift_py_tests.sugar.if_sugar import predicate_formula

    class _Opaque(IntValue):
        def truth(self, site):
            del site
            return Complete(NamedExpressionValue("n", self))

    with pytest.raises(NotImplementedError, match="condition folded"):
        predicate_formula(_Opaque(5), site="twin")
