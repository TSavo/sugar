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
  the arity demand is RETAINED as the completes atom of the unpack's layout:
  under its complement the unpack raises something undetermined
  (`UndeterminedRaiseEffect`) and nothing binds -- exactly as CPython binds
  nothing when `UNPACK_SEQUENCE` raises -- and under the atom each name binds
  its position's projection.  The halt is never the whole answer.
- **callsite coordinate**. A call is its coordinate (#7757 step 6): it
  answers as a symbolic receiver does, over the call's own term.

Every twin states its arity exactly. None asserts `!= 1`.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from tempfile import mkdtemp

from sugar_lift_py_tests.effect import RaiseEffect, UndeterminedRaiseEffect
from sugar_lift_py_tests.floor.scope_rebind import ScopeRebinds
from sugar_lift_py_tests.ir import _Atomic, _Connective, _Var
from sugar_lift_py_tests.lift_rpc import open_source_file_for_construction
from sugar_lift_py_tests.outcome import Completed, ExitSet, Halted
from sugar_source_tree.panic import SugarNotWritten


def _source_file(source: str):
    # The one door a file is opened by, seated in its own workspace: every
    # locus it cites is a re-readable, workspace-relative fragment.
    directory = Path(mkdtemp())
    path = directory / "twin.py"
    path.write_text(source)
    return open_source_file_for_construction(path, root=directory)


def _out(source: str):
    return next(_source_file(source).functions()).sugar().desugar()


def _assign_fragment():
    """A real unpack site: the fragment of ``a, b = p`` in a seated file,
    the blame production hands a decided unpack's ground exit."""
    from sugar_source_tree.nodes import Assign

    tree = _source_file("def A(p):\n    a, b = p\n    return a\n")
    return next(node for node in tree.nodes() if isinstance(node, Assign)).fragment


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
class _TwinSpan:
    start_line: int = 1
    start_col: int = 0
    end_line: int = 1
    end_col: int = 4


@dataclass(frozen=True)
class _TwinLocus:
    """A genuine runtime locus. `RuntimeEffectSite` is a runtime-checkable
    Protocol, so structure is the whole requirement -- and a locus STRING is
    correctly refused, which is why this is a real object and not prose.
    It also carries a fragment's two coordinates (its unit's source CID and
    its span): the unpack's occurrence and its owed ``undecided`` member are
    keyed on them."""

    filename: str = "twin.py"
    line: int = 1
    col: int = 0
    source_cid: str = "blake3-512:" + "cd" * 64
    line_col_span: _TwinSpan = _TwinSpan()


def _assert_arity(halt, arity: int) -> None:
    """The halt is the complement of the completes atom over the layout
    ``python:unpack.destructure(term, arity)``: the arity the source spells."""
    from sugar_lift_py_tests.ir import num

    guard = str(halt.guard)
    assert "python:unpack.destructure" in guard, guard
    assert str(num(arity)) in guard, guard


def _unpack_halts(out):
    """The runtime unpack's own halts: those its producer names
    (``runtime_unpack_faces``: ``<owner>.unpack``).  The right-hand side's
    own halts (an attribute read, an opaque call, a generator's pull) are
    kept beside them, and are not the unpack's."""
    assert isinstance(out, ExitSet), out
    return [
        halt
        for halt in out.halts()
        if isinstance(halt.effect, UndeterminedRaiseEffect)
        and str(halt.effect.producer_node_owner).endswith(".unpack")
    ]


def _unpack_halt(out):
    """The runtime unpack's one halt, beside the completed arm it never
    claims away."""
    (halt,) = _unpack_halts(out)
    assert halt.effect.exception_type_coordinate is None
    assert any(isinstance(exit_, Completed) for exit_ in out.exits), out
    return halt


def _walk(formula):
    """Every node of ``formula``, itself first."""
    yield formula
    for child in (*getattr(formula, "operands", ()), *getattr(formula, "args", ())):
        yield from _walk(child)


def _disjuncts(guard):
    if isinstance(guard, _Connective) and guard.kind == "or":
        return guard.operands
    return (guard,)


def _conjuncts(guard):
    if isinstance(guard, _Connective) and guard.kind == "and":
        return guard.operands
    return (guard,)


def _unpack_arms(out):
    """One guard per path the unpack halts on: each unpack halt's guard, a
    disjunction split into its disjuncts (equal halts are merged by
    disjoining their guards, ``ExitSet.normalize``)."""
    return [arm for halt in _unpack_halts(out) for arm in _disjuncts(halt.guard)]


def _unpacked_operands(arm):
    """The names whose unpack ``arm`` says did not complete: the variables
    under its ``python:unpack.completes`` atoms."""
    return frozenset(
        node.name
        for atom in _walk(arm)
        if isinstance(atom, _Atomic) and atom.name == "python:unpack.completes"
        for node in _walk(atom)
        if isinstance(node, _Var)
    )


def _ground_value_error(out):
    """A decided unpack mismatch: Python's own ``ValueError``, raised at the
    unpack's site, nothing bound and no completion beside it."""
    assert isinstance(out, ExitSet), out
    (halt,) = out.halts()
    assert out.halts() == out.exits, out
    assert isinstance(halt.effect, RaiseEffect)
    assert halt.effect.exception_name == "ValueError"
    return halt


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
    halt = _unpack_halt(out)
    _assert_arity(halt, 2)
    # CPython binds nothing when UNPACK_SEQUENCE raises. Neither does this.
    assert not isinstance(getattr(halt.effect, "value", None), ScopeRebinds)


def test_the_retained_arity_is_the_targets_own_count_not_a_constant() -> None:
    """DISCRIMINATING. The demand must carry the arity the source spells.

    An obligation that always said "2" would satisfy the test above while
    stating a count the program never demanded.
    """
    _, two = _receivers("def A(p):\n a, b = p\n return a\n")
    _, three = _receivers("def A(p):\n a, b, c = p\n return a\n")
    _assert_arity(_unpack_halt(two), 2)
    _assert_arity(_unpack_halt(three), 3)
    assert str(_unpack_halt(two).guard) != str(_unpack_halt(three).guard)


def test_an_attribute_receiver_is_the_same_category_as_a_name() -> None:
    """DISCRIMINATING (category, not spelling). `o.pair` and `p` reduce to the
    same symbolic category, so they must get the same answer -- the dispatch
    must not be reading the source shape."""
    seen, out = _receivers("def A(o):\n a, b = o.pair\n return a\n")
    assert seen == ["SymbolicValue"]
    _assert_arity(_unpack_halt(out), 2)


def test_the_obligation_survives_a_guard_as_one_halted_face() -> None:
    """DISCRIMINATING. Under an `if`, the demand is one HALTED face and the
    complementary face still completes. A refusal could not coexist with the
    guard; a retained obligation can, which is the whole point of the rung.
    The function completes on the branch not taken and on the unpack that
    completed (one function value whose record holds the guarded return, its
    guard the disjunction of the two)."""
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
    assert isinstance(halted[0].effect, UndeterminedRaiseEffect)
    _assert_arity(halted[0], 2)
    assert completed, out.exits
    completes = [
        node
        for exit_ in completed
        for node in _walk(exit_.guard)
        if isinstance(node, _Atomic)
    ]
    # Completed where the branch was taken and the unpack completed ...
    assert any(atom.name == "python:unpack.completes" for atom in completes)
    # ... and where it was not taken at all.
    assert any(
        isinstance(node, _Connective)
        and node.kind == "not"
        and isinstance(node.operands[0], _Atomic)
        and node.operands[0].name == "adt.is_python_type"
        for exit_ in completed
        for node in _walk(exit_.guard)
    ), [exit_.guard for exit_ in completed]


# ==========================================================================
# Category: authenticated finite members -- the count is decidable
# ==========================================================================


def test_matching_arity_binds_each_name_to_the_member_already_in_hand() -> None:
    """POSITIVE. Members are handed over, never re-derived or fabricated."""
    from sugar_lift_py_tests.floor.tuple_literal_value import TupleLiteralValue
    from sugar_lift_py_tests.floor.term_value import TermValue

    members = (TermValue(7), TermValue(9))
    out = _operation("a", "b").submit(TupleLiteralValue(members), None)
    rebinds = out.completed_value()
    assert isinstance(rebinds, ScopeRebinds)
    assert len(rebinds.bindings) == 2
    names = tuple(name for name, _ in rebinds.bindings)
    bound = tuple(value for _, value in rebinds.bindings)
    assert names == ("a", "b")
    # The SAME objects, not equal reconstructions.
    assert bound[0] is members[0]
    assert bound[1] is members[1]


def _operation_at_source(*names: str):
    """One unpack demand blamed on a real, seated unpack site: the blame a
    decided mismatch's ground exit cites (``ground_exceptional_exit``)."""
    from sugar_lift_py_tests.operations import SequenceProjectionOperation

    return SequenceProjectionOperation(
        target_names=names, owner="twin", blame=_assign_fragment()
    )


def test_a_decidable_arity_mismatch_is_pythons_value_error_not_softened() -> None:
    """DISCRIMINATING. This is the one that keeps the runtime-cardinality arm
    honest: a count the lift CAN decide, and got wrong, must NOT be routed to
    the "belongs to __iter__" effect. Only an undecidable count is an
    obligation; a decided-and-wrong one is what CPython does with it: the
    ground ``ValueError``, raised at the unpack, with nothing bound and no
    completion beside it -- never the undetermined two faces."""
    from sugar_lift_py_tests.floor.tuple_literal_value import TupleLiteralValue
    from sugar_lift_py_tests.floor.term_value import TermValue

    out = _operation_at_source("a", "b").submit(
        TupleLiteralValue((TermValue(1), TermValue(2), TermValue(3))), None
    )
    halt = _ground_value_error(out)
    assert not isinstance(halt.effect, UndeterminedRaiseEffect)


def test_too_few_members_is_the_same_ground_value_error() -> None:
    """DISCRIMINATING partner: too few members is decided too, and is the
    same ground ``ValueError``, never a completion with a name left unbound."""
    from sugar_lift_py_tests.floor.tuple_literal_value import TupleLiteralValue
    from sugar_lift_py_tests.floor.term_value import TermValue

    out = _operation_at_source("a", "b", "c").submit(
        TupleLiteralValue((TermValue(1), TermValue(2))), None
    )
    _ground_value_error(out)


def test_a_display_right_hand_side_never_reaches_this_operation() -> None:
    """DISCRIMINATING, and the reason the two tests above are unit-level.

    `a, b = (1, 2)` is paired by the TREE (`Assign._destructured_binding` zips
    displays), so no dynamic unpack is ever constructed and the operation is not
    submitted. If a display ever did start arriving here, these twins would be
    asserting a path the source cannot reach, and this test would say so.
    """
    seen, out = _receivers("def A():\n a, b = (1, 2)\n return a\n")
    assert seen == []
    assert out.completed_value() is not None

    seen, out = _receivers("def A():\n a, b = [1, 2]\n return a\n")
    assert seen == []
    assert out.completed_value() is not None

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
    answer a symbolic receiver gets: the arity obligation retained as one arm,
    nothing bound on it. That it arrives through a callsite changes how the
    answer is reached, never what the answer is.
    """
    seen, out = _receivers("def A(o):\n a, b = o.split()\n return a\n")
    # The call is its coordinate: the callsite hands itself to the runtime
    # unpack (``CallSiteValue.project_sequence_with`` ->
    # ``project_symbolic``), never re-submitted as another value.
    assert seen == ["CallSiteValue"], seen
    # The opaque call raises something undetermined too; the unpack's own
    # raise is the one its producer names (``runtime_unpack_faces``).
    (halt,) = _unpack_halts(out)
    assert any(isinstance(exit_, Completed) for exit_ in out.exits), out
    _assert_arity(halt, 2)
    assert not isinstance(getattr(halt.effect, "value", None), ScopeRebinds)


# ==========================================================================
# Category: comprehension coordinate -- its own iteration owns the count
# ==========================================================================


def test_comprehension_receiver_retains_the_arity_demand() -> None:
    """POSITIVE. `a, b = (x for x in xs)` used to panic with no arm at all.

    A comprehension over an unknown iterable has no authenticated member
    testimony, so the count is its own iteration's and the demand is retained.
    A generator expression is a generator object (``GeneratorValue``): the
    unpack pulls it, so the pull's halts are kept beside the unpack's own
    (``GeneratorValue.project_sequence_with``); a list comprehension over an
    undecided iterable is its symbolic fold (``ComprehensionValue``).
    """
    for source, receiver in (
        ("def A(xs):\n a, b = (x for x in xs)\n return a\n", "GeneratorValue"),
        ("def A(xs):\n a, b = [x for x in xs]\n return a\n", "ComprehensionValue"),
    ):
        seen, out = _receivers(source)
        assert seen == [receiver], (source, seen, out)
        halts = _unpack_halts(out)
        assert halts, out
        for halt in halts:
            _assert_arity(halt, 2)
        assert any(isinstance(exit_, Completed) for exit_ in out.exits), out


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
    _unpack_halt(out)
    # The completed face binds each name to its projection, never a member.
    (completed,) = [exit_ for exit_ in out.exits if isinstance(exit_, Completed)]
    assert isinstance(completed.value, ScopeRebinds)
    assert tuple(name for name, _ in completed.value.bindings) == ("a", "b")
    assert all(
        "python:unpack.project" in str(member.to_term(owner="twin"))
        for _, member in completed.value.bindings
    )


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
    value = out.completed_value()
    assert isinstance(value, ScopeRebinds)
    assert tuple(name for name, _ in value.bindings) == ("a", "b")

    # The decided wrong count is Python's ``ValueError`` at the unpack's
    # site, the same answer a tuple literal gets, never the runtime
    # obligation.
    _ground_value_error(_operation_at_source("a", "b", "c").submit(present, None))


# ==========================================================================
# Category: conditional value -- the unpack distributes into both faces
# ==========================================================================


def test_conditional_receiver_partitions_into_one_face_per_arm() -> None:
    """POSITIVE. `a, b = (p if c else q)` used to panic with no arm at all.

    Each face answers for itself under its own polarity. They are NOT fused
    back into a conditional value: an answer here is a binding or a halt, and
    those do not fuse.  Each arm's runtime unpack has both faces: a halt and
    a completion per arm, none dropped for the other arm's.
    """
    seen, out = _receivers("def A(c, p, q):\n a, b = p if c else q\n return a\n")
    assert seen == ["GuardedValue"]
    assert isinstance(out, ExitSet)
    halts = out.halts()
    assert len(halts) == 2
    for exit_ in halts:
        assert isinstance(exit_.effect, UndeterminedRaiseEffect)
    assert len([exit_ for exit_ in out.exits if isinstance(exit_, Completed)]) == 2


def test_each_conditional_face_owes_its_own_operand_not_a_shared_one() -> None:
    """DISCRIMINATING. The two faces carry DIFFERENT obligations: under `c` the
    unpack is owed of `p`, under `not c` of `q`. Distributing but reporting one
    shared operand would look identical in arity and be wrong about what the
    caller must satisfy."""
    _, out = _receivers("def A(c, p, q):\n a, b = p if c else q\n return a\n")
    # Each path the unpack halts on conjoins its branch with the complement
    # of its own unpack's completes atom; the atom names the operand
    # unpacked.  (The two halts are one effect at one site, so they may be
    # one halt whose guard disjoins the two paths.)
    arms = _unpack_arms(out)
    assert len(arms) == 2, arms
    assert {_unpacked_operands(arm) for arm in arms} == {
        frozenset({"p"}),
        frozenset({"q"}),
    }, arms


def test_the_two_conditional_faces_carry_complementary_guards() -> None:
    """DISCRIMINATING. One face rides under the test, the other under its
    negation -- never both under the same guard, which would claim the unpack
    is owed of two different values on the same execution."""
    from sugar_lift_py_tests.ir import not_

    _, out = _receivers("def A(c, p, q):\n a, b = p if c else q\n return a\n")
    arms = _unpack_arms(out)
    assert len(arms) == 2, arms
    first, second = (set(_conjuncts(arm)) for arm in arms)
    assert any(not_(conjunct) in second for conjunct in first) or any(
        not_(conjunct) in first for conjunct in second
    )
