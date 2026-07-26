"""Discrimination twins for `a, b = <rhs>`, one pair per RECEIVER CATEGORY.

`DynamicUnpackAssignSugar` submits ONE demand -- `SequenceProjectionOperation`,
arity N against one reduced RHS -- and the receiving floor value decides the
answer. So the axis that matters is the receiver's category, never the RHS's
spelling: a call is a call whether it is `o.split()`, `np.shape(x)`, or
`self._get()`, and nothing here names a vendor.

The categories, and what each one owes:

- **authenticated finite members** (tuple / array literal). The count is
  lift-time decidable, so each name binds to the member ALREADY IN HAND.
- **runtime cardinality** (symbolic term, object). `__iter__` owns the count, so
  the arity demand is RETAINED as a typed effect and nothing binds -- exactly
  as CPython binds nothing when `UNPACK_SEQUENCE` raises.
- **undug callsite coordinate**. Currently loud; see the frontier test at the
  bottom, which names the arm that retires it.

Every twin states its arity exactly. None asserts `!= 1`.
"""

from __future__ import annotations

import tempfile

import pytest

from sugar_lift_py_tests.effect import SequenceUnpackRuntimeEffect
from sugar_lift_py_tests.floor.scope_rebind import ScopeRebinds
from sugar_lift_py_tests.gap.panic import ConstructionPanic
from sugar_lift_py_tests.outcome import Complete, Completed, ExitSet, Halted, Incomplete
from sugar_lift_python_source.source_oracle import path_source
from sugar_source_tree.panic import SugarNotWritten
from sugar_source_tree.tree import SourceFile


def _out(source: str):
    with tempfile.NamedTemporaryFile("w", suffix=".py", delete=False, dir="/tmp") as f:
        f.write(source)
        path = f.name
    return next(SourceFile(path_source(path)).functions()).sugar().desugar()


def _receivers(source: str) -> tuple[list[str], object]:
    """Reduce `source`, recording the category of every submitted receiver.

    The receiver, not the source text, is what the operation dispatches on --
    so it is what the twins assert.
    """
    import sugar_lift_py_tests.operations.sequence_projection_operation as spo

    seen: list[str] = []
    original = spo.SequenceProjectionOperation.submit

    def recording(self, value, ctx):
        seen.append(type(value).__name__)
        return original(self, value, ctx)

    spo.SequenceProjectionOperation.submit = recording
    try:
        try:
            return seen, _out(source)
        except BaseException as raised:  # the raise IS the answer for some arms
            return seen, raised
    finally:
        spo.SequenceProjectionOperation.submit = original


def _operation(*names: str):
    from sugar_lift_py_tests.operations import SequenceProjectionOperation

    return SequenceProjectionOperation(
        target_names=names, owner="twin", blame="twin.py:1:0"
    )


# ==========================================================================
# Category: runtime cardinality -- the count belongs to __iter__
# ==========================================================================


def test_symbolic_receiver_retains_the_arity_demand_and_binds_nothing() -> None:
    """POSITIVE. A plain-name RHS has no lift-time cardinality."""
    seen, out = _receivers("def A(p):\n a, b = p\n return a\n")
    assert seen == ["SymbolicValue"]
    assert isinstance(out, Incomplete)
    assert isinstance(out.effect, SequenceUnpackRuntimeEffect)
    assert "exactly 2 members" in out.effect.reason
    assert "(a, b)" in out.effect.reason
    # CPython binds nothing when UNPACK_SEQUENCE raises. Neither does this.
    assert not isinstance(getattr(out.effect, "value", None), ScopeRebinds)


def test_the_retained_arity_is_the_targets_own_count_not_a_constant() -> None:
    """DISCRIMINATING. The demand must carry the arity the source spells.

    An obligation that always said "2" would satisfy the test above while
    stating a count the program never demanded.
    """
    _, two = _receivers("def A(p):\n a, b = p\n return a\n")
    _, three = _receivers("def A(p):\n a, b, c = p\n return a\n")
    assert "exactly 2 members" in two.effect.reason
    assert "exactly 3 members" in three.effect.reason
    assert "(a, b, c)" in three.effect.reason


def test_an_attribute_receiver_is_the_same_category_as_a_name() -> None:
    """DISCRIMINATING (category, not spelling). `o.pair` and `p` reduce to the
    same symbolic category, so they must get the same answer -- the dispatch
    must not be reading the source shape."""
    seen, out = _receivers("def A(o):\n a, b = o.pair\n return a\n")
    assert seen == ["SymbolicValue"]
    assert isinstance(out.effect, SequenceUnpackRuntimeEffect)
    assert "exactly 2 members" in out.effect.reason


def test_the_obligation_survives_a_guard_as_one_halted_face() -> None:
    """DISCRIMINATING. Under an `if`, the demand is one HALTED face and the
    complementary face still completes. A refusal could not coexist with the
    guard; a retained obligation can, which is the whole point of the rung."""
    _, out = _receivers(
        "def A(i, values):\n"
        " if isinstance(i, tuple):\n"
        "  col, loc = i\n"
        "  return loc\n"
    )
    assert isinstance(out, ExitSet)
    halted = [exit_ for exit_ in out.exits if isinstance(exit_, Halted)]
    completed = [exit_ for exit_ in out.exits if isinstance(exit_, Completed)]
    assert len(halted) == 1
    assert len(completed) == 1
    assert isinstance(halted[0].effect, SequenceUnpackRuntimeEffect)
    assert "(col, loc)" in halted[0].effect.reason


# ==========================================================================
# Category: authenticated finite members -- the count is decidable
# ==========================================================================


def test_matching_arity_binds_each_name_to_the_member_already_in_hand() -> None:
    """POSITIVE. Members are handed over, never re-derived or fabricated."""
    from sugar_lift_py_tests.floor.tuple_literal_value import TupleLiteralValue
    from sugar_lift_py_tests.floor.term_value import TermValue

    members = (TermValue(7), TermValue(9))
    out = _operation("a", "b").submit(TupleLiteralValue(members), None)
    assert isinstance(out, Complete)
    assert isinstance(out.value, ScopeRebinds)
    assert len(out.value.bindings) == 2
    names = tuple(name for name, _ in out.value.bindings)
    bound = tuple(value for _, value in out.value.bindings)
    assert names == ("a", "b")
    # The SAME objects, not equal reconstructions.
    assert bound[0] is members[0]
    assert bound[1] is members[1]


def test_a_decidable_arity_mismatch_stays_loud_and_is_not_softened() -> None:
    """DISCRIMINATING. This is the one that keeps the runtime-cardinality arm
    honest: a count the lift CAN decide, and got wrong, must NOT be routed to
    the "belongs to __iter__" effect. Only an undecidable count is an
    obligation; a decided-and-wrong one is a gap."""
    from sugar_lift_py_tests.floor.tuple_literal_value import TupleLiteralValue
    from sugar_lift_py_tests.floor.term_value import TermValue

    with pytest.raises(ConstructionPanic) as raised:
        _operation("a", "b").submit(
            TupleLiteralValue((TermValue(1), TermValue(2), TermValue(3))), None
        )
    message = str(raised.value)
    assert "too many values" in message
    assert "ground ValueError" in message


def test_too_few_members_reports_the_other_direction() -> None:
    """DISCRIMINATING. The gap names WHICH way the count is wrong; a single
    "mismatch" message would lose the half that tells you what to write."""
    from sugar_lift_py_tests.floor.tuple_literal_value import TupleLiteralValue
    from sugar_lift_py_tests.floor.term_value import TermValue

    with pytest.raises(ConstructionPanic) as raised:
        _operation("a", "b", "c").submit(
            TupleLiteralValue((TermValue(1), TermValue(2))), None
        )
    assert "not enough values" in str(raised.value)


def test_a_display_right_hand_side_never_reaches_this_operation() -> None:
    """DISCRIMINATING, and the reason the two tests above are unit-level.

    `a, b = (1, 2)` is paired by the TREE (`Assign._destructured_binding` zips
    displays), so no dynamic unpack is ever constructed and the operation is not
    submitted. If a display ever did start arriving here, these twins would be
    asserting a path the source cannot reach, and this test would say so.
    """
    seen, out = _receivers("def A():\n a, b = (1, 2)\n return a\n")
    assert seen == []
    assert isinstance(out, Complete)

    seen, out = _receivers("def A():\n a, b = [1, 2]\n return a\n")
    assert seen == []
    assert isinstance(out, Complete)

    # And the tree owns the display mismatch, ahead of any floor question.
    seen, raised = _receivers("def A():\n a, b = (1, 2, 3)\n return a\n")
    assert seen == []
    assert isinstance(raised, SugarNotWritten)


# ==========================================================================
# Category: undug callsite coordinate -- THE LIVE FRONTIER
# ==========================================================================


def test_callsite_receiver_is_the_whole_remaining_panic_family() -> None:
    """FRONTIER. `a, b = <call>` is the entire measured residual on this axis.

    Bounded re-measure at `a4eade69a` over the first 40 installed-pandas modules
    (371 functions): 8 submits reached `CallSiteValue` and all 8 panicked, 6
    reached `SymbolicValue` and none did. Every panic was "no
    `project_sequence_with` arm", none was an arity mismatch.

    This is NOT a design question. `floor/call_site_value.py` already carries the
    pattern, named and in use for two sibling operations::

        def subscript_with(self, operation, ctx):
            return self._dig_or_symbolic_redispatch(
                operation, ctx, owner_suffix="callsite subscript receiver")

    `_dig_or_symbolic_redispatch` digs the callsite floor when the body projects
    and otherwise re-dispatches on `SymbolicValue(self.term)`, which lands
    exactly on the two lawful arms above with nothing invented. The arm is ~4
    lines and the file is held by another owner, so this test pins the loud gap
    and names its retirement rather than working around it.

    When that arm lands, this test is replaced by the positive/discriminating
    pair immediately below it, which is written and skipped, not deleted.
    """
    for source in (
        "def A(o):\n a, b = o.split()\n return a\n",
        "def A(d, k):\n a, b = d[k]\n return a\n",
    ):
        seen, raised = _receivers(source)
        assert seen == ["CallSiteValue"], seen
        assert isinstance(raised, ConstructionPanic)
        assert "project_sequence_with" in str(raised)


@pytest.mark.skip(
    reason=(
        "needs the project_sequence_with arm in floor/call_site_value.py, held "
        "by another owner; enable together with that arm"
    )
)
def test_callsite_receiver_answers_like_its_dug_floor() -> None:
    """The pair that retires the frontier test above, written ahead of the arm.

    An opaque call body carries no cardinality, so it must land on the SAME
    answer a symbolic receiver gets -- the retained arity obligation, nothing
    bound. That it goes through a callsite rather than a name must make no
    difference to the answer, only to how the answer is reached.
    """
    seen, out = _receivers("def A(o):\n a, b = o.split()\n return a\n")
    assert seen == ["CallSiteValue"]
    assert isinstance(out, Incomplete)
    assert isinstance(out.effect, SequenceUnpackRuntimeEffect)
    assert "exactly 2 members" in out.effect.reason
    assert not isinstance(getattr(out.effect, "value", None), ScopeRebinds)


@pytest.mark.skip(
    reason=(
        "needs the project_sequence_with arm in floor/call_site_value.py, held "
        "by another owner; enable together with that arm"
    )
)
def test_a_callsite_that_digs_to_a_display_binds_its_members() -> None:
    """DISCRIMINATING partner. When the callee's body DOES project a finite
    display, the count is decidable after the dig and the names bind -- so the
    arm must not answer every callsite with the runtime obligation."""
    seen, out = _receivers(
        "def pair():\n return (1, 2)\n\ndef A():\n a, b = pair()\n return a\n"
    )
    assert seen == ["CallSiteValue"]
    assert isinstance(out, Complete)
