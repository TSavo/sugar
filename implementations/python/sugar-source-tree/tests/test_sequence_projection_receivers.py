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
from dataclasses import dataclass

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


@dataclass(frozen=True)
class _TwinLocus:
    """A genuine runtime locus. `RuntimeEffectSite` is a runtime-checkable
    Protocol, so structure is the whole requirement -- and a locus STRING is
    correctly refused, which is why this is a real object and not prose."""

    filename: str = "twin.py"
    line: int = 1
    col: int = 0


def _answers_when_dig_yields(dug, source: str):
    """Every `(receiver, answer)` the unpack demand produced, with the callsite
    dig forced to `dug`.

    A callsite whose callee body projects a finite display is not reachable from
    a two-function fixture here -- the callee universe is not available to the
    dig at this seam -- so the dig is driven directly. That keeps the twin about
    THIS arm's routing rather than about the availability of a callee universe.
    """
    import sugar_lift_py_tests.operations.sequence_projection_operation as spo
    from sugar_lift_py_tests.floor.call_site_value import CallSiteValue

    answers: list[tuple[str, object]] = []
    original_dig = CallSiteValue._dig_floor_or_none
    original_submit = spo.SequenceProjectionOperation.submit

    def recording(self, value, ctx):
        answer = original_submit(self, value, ctx)
        answers.append((type(value).__name__, answer))
        return answer

    CallSiteValue._dig_floor_or_none = lambda self, ctx, **kwargs: dug
    spo.SequenceProjectionOperation.submit = recording
    try:
        _out(source)
    finally:
        CallSiteValue._dig_floor_or_none = original_dig
        spo.SequenceProjectionOperation.submit = original_submit
    return answers


def _operation(*names: str):
    """One unpack demand, addressed by a genuine runtime locus.

    The blame must be a real `RuntimeEffectSite`: the runtime arm refuses to
    mint evidence from a locus string, so a twin that passed prose would be
    testing a path production cannot reach.
    """
    from sugar_lift_py_tests.operations import SequenceProjectionOperation

    return SequenceProjectionOperation(
        target_names=names, owner="twin", blame=_TwinLocus()
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


def test_callsite_receiver_answers_like_its_dug_floor() -> None:
    """POSITIVE. `a, b = <call>` was the entire measured residual on this axis.

    574 of the 828 unpack sites over 295 installed-pandas modules reach this
    receiver -- 561 `Call` plus 13 `Subscript`, because `a, b = d[k]` reduces
    here too -- and every one panicked with "no `project_sequence_with` arm".

    An opaque call body carries no cardinality, so it must land on exactly the
    answer a symbolic receiver gets: the arity obligation retained, nothing
    bound. That it arrives through a callsite changes how the answer is reached,
    never what the answer is.
    """
    seen, out = _receivers("def A(o):\n a, b = o.split()\n return a\n")
    # Dug to the opaque residual, then re-dispatched on the EUF receiver term.
    assert seen == ["CallSiteValue", "SymbolicValue"], seen
    assert isinstance(out, Incomplete)
    assert isinstance(out.effect, SequenceUnpackRuntimeEffect)
    assert "exactly 2 members" in out.effect.reason
    assert "(a, b)" in out.effect.reason
    assert not isinstance(getattr(out.effect, "value", None), ScopeRebinds)


def test_a_callsite_digs_before_it_falls_back_to_the_symbolic_term() -> None:
    """DISCRIMINATING. The arm must CONSULT the dig, not skip to the term.

    An arm that always answered with `SymbolicValue(self.term)` would pass the
    test above -- opaque bodies are the common case -- while throwing away every
    decidable count a projecting callee body hands over. This drives the dig half
    directly: when the floor digs to authenticated finite members, the names bind
    to the members ALREADY IN HAND and no runtime obligation is minted.

    Asserted on the operation's own answer rather than the function outcome,
    because the TREE froze `return a` as an unbound read at substitution time --
    it cannot pair targets with members for a non-display right-hand side, which
    is the whole reason this sugar exists. So the rebinds are correct and the
    tail still reads unbound. That is a separate, pre-existing seam (the one
    `test_binding_state_unbound` documents), not this arm's answer, and this twin
    is careful not to claim otherwise.
    """
    from sugar_lift_py_tests.floor.call_site_value import CallSiteValue
    from sugar_lift_py_tests.floor.term_value import TermValue
    from sugar_lift_py_tests.floor.tuple_literal_value import TupleLiteralValue

    members = (TermValue(4), TermValue(5))
    answers = _answers_when_dig_yields(
        TupleLiteralValue(members), "def A(o):\n a, b = o.split()\n return a\n"
    )

    # The callsite consulted the dig -- the dug display received the demand --
    # and the callsite's own answer is that display's answer.
    assert [name for name, _ in answers] == ["TupleLiteralValue", "CallSiteValue"]
    for _, answer in answers:
        assert isinstance(answer, Complete)
        assert isinstance(answer.value, ScopeRebinds)
        assert tuple(n for n, _ in answer.value.bindings) == ("a", "b")
        # The SAME member objects the dug display was holding.
        assert tuple(v for _, v in answer.value.bindings) == members
    del CallSiteValue


def test_a_dug_display_of_the_wrong_size_stays_the_decidable_gap() -> None:
    """DISCRIMINATING. Digging must not launder a decidable mismatch into the
    runtime obligation: once the count IS known, getting it wrong is a gap."""
    from sugar_lift_py_tests.floor.term_value import TermValue
    from sugar_lift_py_tests.floor.tuple_literal_value import TupleLiteralValue

    with pytest.raises(ConstructionPanic) as raised:
        _answers_when_dig_yields(
            TupleLiteralValue((TermValue(1), TermValue(2), TermValue(3))),
            "def A(o):\n a, b = o.split()\n return a\n",
        )
    assert "too many values" in str(raised.value)
    assert "ground ValueError" in str(raised.value)


# ==========================================================================
# Category: comprehension coordinate -- its own iteration owns the count
# ==========================================================================


def test_comprehension_receiver_retains_the_arity_demand() -> None:
    """POSITIVE. `a, b = (x for x in xs)` used to panic with no arm at all.

    A comprehension over an unknown iterable has no authenticated member
    testimony, so the count is its own iteration's and the demand is retained.
    """
    for source in (
        "def A(xs):\n a, b = (x for x in xs)\n return a\n",
        "def A(xs):\n a, b = [x for x in xs]\n return a\n",
    ):
        seen, out = _receivers(source)
        assert seen == ["ComprehensionValue"], seen
        assert isinstance(out, Incomplete)
        assert isinstance(out.effect, SequenceUnpackRuntimeEffect)
        assert "exactly 2 members" in out.effect.reason


def test_absent_finite_testimony_is_not_read_as_zero_members() -> None:
    """DISCRIMINATING, and the sharp edge of this category.

    `finite_elements is None` means "no member testimony exists". Reading it as
    an empty tuple would make every unknown comprehension a DECIDABLE arity
    mismatch -- "0 members unpacked into 2 targets" -- turning "we do not know"
    into a confident wrong answer. It must route to the runtime arm instead.
    """
    from sugar_lift_py_tests.floor.comprehension_value import ComprehensionValue
    from sugar_lift_py_tests.ir import make_var

    absent = ComprehensionValue(make_var("xs"), finite_elements=None)
    out = _operation("a", "b").submit(absent, None)
    assert isinstance(out, Incomplete)
    assert isinstance(out.effect, SequenceUnpackRuntimeEffect)


def test_present_finite_testimony_binds_and_a_wrong_count_stays_loud() -> None:
    """DISCRIMINATING partner. When the comprehension DID project every member,
    the count is decidable, so it must bind on a match and stay loud on a
    mismatch -- the same two answers a tuple literal gets, never the runtime
    obligation."""
    from sugar_lift_py_tests.floor.comprehension_value import ComprehensionValue
    from sugar_lift_py_tests.floor.term_value import TermValue
    from sugar_lift_py_tests.ir import make_var

    members = (TermValue(1), TermValue(2))
    present = ComprehensionValue(make_var("xs"), finite_elements=members)

    out = _operation("a", "b").submit(present, None)
    assert isinstance(out, Complete)
    assert isinstance(out.value, ScopeRebinds)
    assert tuple(name for name, _ in out.value.bindings) == ("a", "b")

    with pytest.raises(ConstructionPanic):
        _operation("a", "b", "c").submit(present, None)


# ==========================================================================
# Category: constructed list binding -- authenticated members survive a Name
# ==========================================================================


def test_constructed_list_binding_projects_its_authenticated_members() -> None:
    """TRUTHFUL. A guarded list face is still the finite list constructed."""
    from sugar_lift_py_tests.floor.list_value import ListValue
    from sugar_lift_py_tests.floor.term_value import TermValue

    members = (TermValue(4), TermValue(5))
    answer = _operation("left", "right").submit(ListValue(members), None)
    assert isinstance(answer, Complete)
    assert isinstance(answer.value, ScopeRebinds)
    assert answer.value.bindings == (("left", members[0]), ("right", members[1]))

    seen, out = _receivers(
        "def unpack_guarded_list(choose, fallback):\n"
        " pair = [4, 5] if choose else fallback\n"
        " left, right = pair\n"
        " selected = left\n"
        " return selected\n"
    )
    assert seen == ["GuardedValue"], seen
    assert isinstance(out, ExitSet)
    assert len(out.exits) == 2
    assert sum(
        isinstance(exit_.effect, SequenceUnpackRuntimeEffect)
        for exit_ in out.exits
        if isinstance(exit_, Halted)
    ) == 1


def test_constructed_list_binding_does_not_lie_about_its_arity() -> None:
    """LYING. Three authenticated members cannot satisfy two targets."""
    seen, out = _receivers(
        "def unpack_guarded_list(choose, fallback):\n"
        " values = [4, 5, 6] if choose else fallback\n"
        " left, right = values\n"
        " selected = left\n"
        " return selected\n"
    )
    assert seen == ["GuardedValue"], seen
    assert isinstance(out, ConstructionPanic)
    assert "too many values" in str(out)


# ==========================================================================
# Category: conditional value -- the unpack distributes into both faces
# ==========================================================================


def test_conditional_receiver_partitions_into_one_face_per_arm() -> None:
    """POSITIVE. `a, b = (p if c else q)` used to panic with no arm at all.

    Each face answers for itself under its own polarity. They are NOT fused
    back into a conditional value: an answer here is a binding or a halt, and
    those do not fuse.
    """
    seen, out = _receivers("def A(c, p, q):\n a, b = p if c else q\n return a\n")
    assert seen == ["GuardedValue"]
    assert isinstance(out, ExitSet)
    assert len(out.exits) == 2
    for exit_ in out.exits:
        assert isinstance(exit_, Halted)
        assert isinstance(exit_.effect, SequenceUnpackRuntimeEffect)


def test_each_conditional_face_owes_its_own_operand_not_a_shared_one() -> None:
    """DISCRIMINATING. The two faces carry DIFFERENT obligations: under `c` the
    unpack is owed of `p`, under `not c` of `q`. Distributing but reporting one
    shared operand would look identical in arity and be wrong about what the
    caller must satisfy."""
    _, out = _receivers("def A(c, p, q):\n a, b = p if c else q\n return a\n")
    operands = {
        str(exit_.effect.runtime_operand.term.args[0]) for exit_ in out.exits
    }
    assert len(operands) == 2, operands
    assert any("p" in operand for operand in operands)
    assert any("q" in operand for operand in operands)


def test_the_two_conditional_faces_carry_complementary_guards() -> None:
    """DISCRIMINATING. One face rides under the test, the other under its
    negation -- never both under the same guard, which would claim the unpack
    is owed of two different values on the same execution."""
    _, out = _receivers("def A(c, p, q):\n a, b = p if c else q\n return a\n")
    guards = [exit_.guard for exit_ in out.exits]
    assert len(guards) == 2
    negated = [guard for guard in guards if getattr(guard, "kind", None) == "not"]
    assert len(negated) == 1
    assert negated[0].operands[0] in guards
