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

import json
import tempfile
from dataclasses import dataclass

import pytest

from sugar_lift_py_tests.caller_parameter_contract import (
    ContractConditionalConstructionV1,
)
from sugar_lift_py_tests.floor.guarded_value import GuardedValue
from sugar_lift_py_tests.floor.universe_value import UniverseValue
from sugar_lift_py_tests.canonicalizer import encode_jcs
from sugar_lift_py_tests.ir import formula_to_value
from sugar_lift_py_tests.outcome import Complete
from sugar_lift_python_source.source_oracle import path_source
from sugar_lift_py_tests.sugar.sugar_base import Sugar
from sugar_source_tree.tree import SourceFile


def _out(source: str):
    with tempfile.NamedTemporaryFile("w", suffix=".py", delete=False, dir="/tmp") as f:
        f.write(source)
        path = f.name
    return next(SourceFile(path_source(path)).functions()).sugar().desugar()


def _statements(out):
    """Every body statement the lift produced, across whatever shape it produced.

    A function whose body partitions reduces to an ExitSet of universes rather
    than to one `Complete`; both are lawful, and a twin about "does this lift"
    must not be blind to the partitioned shape.
    """
    from sugar_lift_py_tests.outcome import Completed, ExitSet

    if isinstance(out, ExitSet):
        rows = []
        for exit_ in out.exits:
            if isinstance(exit_, Completed):
                assert isinstance(exit_.value, UniverseValue)
                rows.extend(exit_.value.record.statements)
        assert rows
        return tuple(rows)
    assert isinstance(out, Complete)
    assert isinstance(out.value, UniverseValue)
    return out.value.record.statements


def _pending(out):
    return tuple(
        row
        for row in _statements(out)
        if isinstance(row, ContractConditionalConstructionV1)
    )


@dataclass(frozen=True)
class _Site:
    """A minimal site: the effect vocabulary asks a locus for filename/line/col."""

    filename: str = "twin.py"
    line: int = 1
    col: int = 0


class _BoundState(Sugar):
    """A stand-in for a bound face: `delete_binding` treats any Sugar as bound."""

    @classmethod
    def witnesses(cls):
        return ()

    def desugar(self, ctx=None):  # pragma: no cover - never reduced by delete
        raise AssertionError("delete_binding must not reduce a bound face")


def _demand_shape(entry):
    """The demanded formula's outermost connective, as wire vocabulary."""
    return json.loads(
        encode_jcs(formula_to_value(entry.sole_demand().demanded_formula))
    )


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
        row.value
        for row in _statements(out)
        if isinstance(getattr(row, "value", None), GuardedValue)
    ]
    assert len(guarded) == 1
    # And the arms keep the test's OWN polarity: `then` under the guard, `else`
    # under its negation. Rebuilding the fusion from an exit-set union is only
    # correct while it re-fuses the faces the right way round.
    assert guarded[0].when_true.value == 1
    assert guarded[0].when_false.value == 2


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
    out = _out('def f(d, k, v):\n return f"x={d.setdefault(k, v)}"\n')
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
    answer None and refine no binding. Structural: no table of names.
    """
    from sugar_source_tree.nodes import Attribute, Call, Name, Subscript

    with tempfile.NamedTemporaryFile("w", suffix=".py", delete=False, dir="/tmp") as h:
        h.write("def f(a, d, k):\n return (a, a.b.c, a.b(), d[k].b)\n")
        path = h.name
    fn = next(SourceFile(path_source(path)).functions())
    named, dotted, called, subscripted = fn.body[0].value.elts
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
        require_single_value(ExitSet(()), owner="twin", blame="twin", arm="when_true")
    assert SINGLE_OUTCOME_LAW in str(raised.value)
    assert "when_true" in str(raised.value)


def test_conditional_receiver_with_one_pending_contract_arm_lifts() -> None:
    """POSITIVE. The live bare-assert offender: an operation distributed into a
    conditional arm whose answer carries a pending parameter contract. The demand
    is hoisted under that arm's guard and re-attached to the joined value."""
    out = _out(
        "def f(c, p):\n"
        " if c:\n"
        "  x = p\n"
        " else:\n"
        "  x = (1, 2)\n"
        " return x[0]\n"
    )
    pending = _pending(out)
    assert len(pending) == 1


def test_two_pending_contract_arms_join_and_conserve_both_demands() -> None:
    """SUPERSEDED PANIC, NOW A LAW (#6352).

    This used to assert the panic: one entry carried exactly one demand, so a
    join of TWO pending arms had no representation and had to be loud. The
    panic named its own replacement -- "widen ContractConditionalConstructionV1
    to carry a demand SET" -- and that widening landed, so the assertion moves
    from "it refuses" to "it joins, and conserves BOTH obligations".

    The twin is rewritten rather than deleted: the obligation being conserved is
    what the panic was protecting, and deleting the test would retire the
    protection along with the panic. Both formals must still be owed.
    """
    out = _out(
        "def f(c, p, q):\n"
        " if c:\n"
        "  x = p\n"
        " else:\n"
        "  x = q\n"
        " return x[0]\n"
    )
    pending = _pending(out)
    assert pending

    formals = {
        demand.formal_coordinate_cid for entry in pending for demand in entry.demands
    }
    assert len(formals) == 2, (
        "a join of two pending arms conserved only one formal's obligation: the "
        "demands were dropped or conjoined instead of unioned (#6352)"
    )


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
    guard where there is none: a condition whose presented face carries no
    formula and is no boolean literal stays loud, and now names the PRESENTED
    type rather than the wrapper that merely carried it."""
    from sugar_lift_py_tests.floor.term_value import TermValue
    from sugar_lift_py_tests.floor.named_expression_value import NamedExpressionValue
    from sugar_lift_py_tests.sugar.if_sugar import predicate_formula

    carried = TermValue(5)

    class _Walrus:
        def truth(self, site):
            del site
            return Complete(NamedExpressionValue("n", carried))

    with pytest.raises(NotImplementedError, match="TermValue"):
        predicate_formula(_Walrus(), site="twin")


# --------------------------------------------------------------------------
# Family: TypeError: LoopGuardedProjection
# --------------------------------------------------------------------------


def test_delete_over_a_loop_guarded_projection_unions_its_faces() -> None:
    """POSITIVE. `del` over a loop-guarded projection had no arm at all, so it
    raised `TypeError: LoopGuardedProjection` -- while `read` over the SAME
    projection had had one all along. It now deletes ON EACH completed face,
    under that face's own guard, exactly as the read verb reads them."""
    from sugar_lift_py_tests.ir import atomic
    from sugar_lift_py_tests.outcome import Completed, Halted
    from sugar_lift_py_tests.sugar.binding_projection import (
        LoopGuardedCompletedFace,
        LoopGuardedProjection,
        UnboundProjection,
    )
    from sugar_lift_py_tests.sugar.delete_name_sugar import delete_binding

    entered = atomic("entered", [])
    empty = atomic("empty", [])
    projection = LoopGuardedProjection(
        (
            # The loop ran: `y` is bound, so deleting it completes.
            LoopGuardedCompletedFace("normal", entered, _BoundState()),
            # The loop never ran: `y` was never bound, so deleting it halts.
            LoopGuardedCompletedFace("normal", empty, UnboundProjection("y", _Site())),
        )
    )
    exits = delete_binding(projection, name="y", site=_Site(), ctx=None)
    completed = [e for e in exits.exits if isinstance(e, Completed)]
    halted = [e for e in exits.exits if isinstance(e, Halted)]
    assert len(completed) == 1
    assert len(halted) == 1
    # Each face keeps its OWN guard -- the union must not flatten them together.
    assert completed[0].guard == entered
    assert halted[0].guard == empty


def test_read_and_delete_answer_the_same_projection_union() -> None:
    """DISCRIMINATING. Both verbs over `BindingProjection` must cover the same
    four constructors, and an uncovered one must be NAMED, not a bare TypeError.
    """
    import inspect

    from sugar_lift_py_tests.sugar import delete_name_sugar, guarded_binding_read_sugar

    constructors = (
        "Sugar",
        "UnboundProjection",
        "GuardedProjection",
        "LoopGuardedProjection",
    )
    for module, verb in (
        (guarded_binding_read_sugar, "read_binding"),
        (delete_name_sugar, "delete_binding"),
    ):
        source = inspect.getsource(getattr(module, verb))
        missing = [name for name in constructors if name not in source]
        assert missing == [], f"{verb} has no arm for {missing}"
        assert "raise TypeError(" not in source, verb


def test_unhandled_projection_names_the_union_and_the_verb() -> None:
    """POSITIVE. The replacement for the bare TypeError states the closed union
    it is answering for and which verb is missing an arm."""
    from sugar_lift_py_tests.gap.panic import ConstructionPanic
    from sugar_lift_py_tests.sugar.delete_name_sugar import _unhandled_projection

    with pytest.raises(ConstructionPanic) as raised:
        _unhandled_projection(object(), verb="delete", name="y", site=_Site())
    message = str(raised.value)
    assert "BindingProjection" in message
    assert "LoopGuardedProjection" in message
    assert "delete" in message


# --------------------------------------------------------------------------
# Family: BindingStateWireGap
# --------------------------------------------------------------------------


def test_loop_outward_face_returning_a_partition_lifts() -> None:
    """POSITIVE. A loop's outward face whose `return` expression PARTITIONS used
    to raise `BindingStateWireGap: loop outward face did not construct return or
    raise testimony`. It was never a missing wire -- the face contributes its
    partition under its own guard."""
    out = _out(
        "def f(xs, d, k, v):\n"
        " for x in xs:\n"
        "  if x:\n"
        "   return d.setdefault(k, v)\n"
        " return 0\n"
    )
    assert _statements(out)


def test_loop_outward_face_with_a_plain_return_stays_one_completed_face() -> None:
    """DISCRIMINATING. The simple face must NOT be routed through the partition
    path: a plain `return` is still one completed exit carrying one return."""
    from sugar_lift_py_tests.floor import ReturnValue

    out = _out("def f(xs):\n for x in xs:\n  if x:\n   return 1\n return 0\n")
    returns = [
        row
        for row in _statements(out)
        if isinstance(row, ReturnValue)
        or isinstance(getattr(row, "value", None), ReturnValue)
    ]
    assert len(returns) >= 1


def test_loop_outward_face_returning_a_parameter_contract_lifts() -> None:
    """POSITIVE, and the only shape in this family that DISCRIMINATES.

    The two twins above were measured against the law itself: with the general
    arm in `loop_recurrence_sugar` replaced by the raise it retired, BOTH still
    pass. `d.setdefault(k, v)` never reaches that arm, so the partition twin
    cannot fail when the law is removed -- it is the ceremony shape the ruling
    names, and this test is the refutation rather than a third no-op.

    `return p[0]` DOES reach it: the face owes a caller-parameter contract, so
    it reduces to neither one return value nor one effect, which is exactly the
    residue `BindingStateWireGap: loop outward face did not construct return or
    raise testimony` was refusing to state. Removing the arm fails this node and
    only this node.
    """
    out = _out("def f(xs, p):\n for x in xs:\n  if x:\n   return p[0]\n return 0\n")
    assert _statements(out)
