"""Assign flat unpack with Attribute store leaves.

These twins do NOT assert "the shape returns an effect". Each one names a LAW
of Python assignment and asserts the *constructed artifact* that carries it,
paired with a discrimination arm that fails when the law is violated:

1. RHS members are constructed ONCE (retained occurrence identity).
2. Tuple elements retain positional correspondence.
3. Multiple store effects retain left-to-right order.
4. Attribute receiver and attribute name retain their exact coordinates.
5. A Name leaf's binding is discharged alongside the store effect.
6/7. Partial assignment: nothing established before a store is erased by that
   store's halt, and no target after it runs. Every projection twin below is
   restated PER ARM against the real ``ExitSet``: the arm halting at store k
   carries exactly stores 0..k-1. The generic success/halt algebra itself is
   owned by ``test_store_outcome_composition``; the unpack's flow through it
   is owned by ``test_assign_unpack_store_outcome_composition``. The OUTCOME
   SHAPE is asserted in neither of those two places from here -- this module
   reads arms, it does not claim how many exits a store body has.
8. Pure-name unpack is the reduce-time unpack, never an unpack store.
9. Starred opaque unpack stays typed-loud.
10. Source-visible Subscript leaves construct (post-#6599 coordinates); formal
    receivers stay undischarged at desugar via the store law.

The arm reader below (``_arm_stores``) is the shared instrument: each store
here is the one undecided attribute mutation (#7757 NEW-4), so an arm's guard
states which stores completed on it and which one it halted at, as
``(receiver, attribute)``.  Two sources that differ in receiver, in attribute
or in store order MUST read differently.  An undecided store states nothing
about the value it stores, so value pairing (law 2) is read on the
statement's construction, where it is decided.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from sugar_lift_py_tests.outcome.exit_set import (
    Completed,
    Halted,
    sole_completed_value,
)
from sugar_lift_py_tests.sugar.assign_sugar import DynamicUnpackStoreAssignSugar
from sugar_lift_py_tests.sugar.unpack_projection_targets import (
    NameUnpackTarget,
    StoreUnpackTarget,
)
from sugar_lift_python_source.source_oracle import path_source
from sugar_source_tree.panic import SugarNotWritten
from sugar_source_tree.tree import SourceFile
from sugar_lift_py_tests.context_manager_resolution import TreeConstructionContextV1


# The receivers these twins store into (``o``, ``n``) are names only a star
# import the lifter cannot read may bind: free operands whose runtime type
# nothing decides, so each store is two-faced (the one undecided attribute
# mutation, ``undecided_attribute_mutation_faces``).  A name the
# module binds nowhere is no free operand: its read halts with ``NameError``
# (``NameSugar``, #7854) and no store runs -- that is the honest answer for
# ``o.x, o.y = p, q`` in a module that binds ``o`` nowhere, not the
# receiver these laws are about.
_UNREAD_STAR_IMPORT = "from unread_module import *\n"


def _function(tmp_path: Path, source: str, stem: str = "assign_case"):
    path = tmp_path / f"{stem}.py"
    path.write_text(_UNREAD_STAR_IMPORT + source, encoding="utf-8")
    return next(
        SourceFile(
            path_source(str(path)),
            construction_context=TreeConstructionContextV1.for_test_without_workspace(),
        ).functions()
    )


def _function_sugar(tmp_path: Path, source: str, stem: str = "assign_case"):
    return _function(tmp_path, source, stem).sugar()


def _unpack(tmp_path: Path, source: str, stem: str = "assign_case"):
    """The statement's one unpack: a display right-hand side is evaluated
    once and unpacked at reduce, as any other is (#7757 S2)."""
    sugar = _function_sugar(tmp_path, source, stem)
    return next(
        stmt
        for stmt in sugar.statements
        if isinstance(stmt, DynamicUnpackStoreAssignSugar)
    )


def _store_targets(unpack) -> tuple:
    return tuple(t for t in unpack.targets if isinstance(t, StoreUnpackTarget))


def _stores(unpack) -> tuple:
    """Each store leaf's own statement's sugar, left to right."""
    return tuple(target.store for target in _store_targets(unpack))


def _member_keys(unpack) -> tuple:
    """The key each store leaf's member is bound under, left to right."""
    return tuple(target.evaluation for target in _store_targets(unpack))


def _name_targets(unpack) -> tuple:
    return tuple(t.name for t in unpack.targets if isinstance(t, NameUnpackTarget))


def _outcome(tmp_path: Path, source: str, stem: str = "assign_case"):
    """The constructed outcome, an ``ExitSet``.

    A body containing a store no longer reduces to one unconditional exit: the
    store partitions it into a completed arm and one halted arm per store. A
    body with no store reduces to the one-exit set, so every twin below reads
    the same instrument.
    """
    return _function_sugar(tmp_path, source, stem).desugar(None)


def _completed_value(tmp_path: Path, source: str, stem: str = "assign_case"):
    """The value on the SOLE completed arm.

    ``sole_completed_value`` is the sanctioned door: it refuses loudly when a
    success face was dropped or duplicated instead of quietly projecting one of
    several. It is not a way to discard the halted arms -- those are read by
    ``_arm_stores`` and asserted per arm.
    """
    return sole_completed_value(_outcome(tmp_path, source, stem))


def _store_atoms(guard) -> tuple:
    """``(completed, halted)``: the attribute stores an arm's guard states.

    An undecided ``o.x = v`` is the one undecided attribute mutation
    (``store_effect_sugar.undecided_attribute_mutation_faces``, #7757
    NEW-4): it completes only under ``python:setattr.completes(python:
    setattr(<receiver>, "<attr>", <key>))`` and halts under its complement.
    So an arm's guard names, read through ``and`` and ``not``, each store
    that completed on it (the atom under an even number of ``not``) and the
    store it halted at (under an odd number).  Each is projected as
    ``(<receiver name>, <attr>)``; the key is per evaluation and not read.
    """
    completed: list = []
    halted: list = []

    def walk(node, positive: bool) -> None:
        kind = getattr(node, "kind", None)
        if kind == "and":
            for operand in node.operands:
                walk(operand, positive)
        elif kind == "not":
            walk(node.operands[0], not positive)
        elif getattr(node, "name", None) == "python:setattr.completes":
            (operation,) = node.args
            receiver, attr, _key = operation.args
            store = (getattr(receiver, "name", repr(receiver)), attr.value)
            (completed if positive else halted).append(store)

    walk(guard, True)
    return tuple(completed), tuple(halted)


def _arm_stores(tmp_path: Path, source: str, stem: str = "assign_case"):
    """One ``_store_atoms`` projection per exit arm, the arm that completed
    fewest stores first, the completed arm last.

    Arm ``k`` (for ``k`` store targets) is the arm on which store ``k``
    halted: it states stores ``0..k-1`` completed and store ``k`` halted,
    and nothing after it.  The completed arm states every store completed.
    """
    exits = _outcome(tmp_path, source, stem).exits
    halted = sorted(
        (_store_atoms(e.guard) for e in exits if isinstance(e, Halted)),
        key=lambda stores: len(stores[0]),
    )
    completed = [e for e in exits if isinstance(e, Completed)]
    assert len(completed) == 1, completed
    return tuple(halted) + (_store_atoms(completed[0].guard),)


def _targets(stores) -> list:
    """The attributes an arm's completed stores name, in guard order."""
    return [attr for _receiver, attr in stores[0]]


def _post(tmp_path: Path, source: str, stem: str = "assign_case"):
    return _completed_value(tmp_path, source, stem).post()


# Free undecided ``o`` (``_UNREAD_STAR_IMPORT``): each store is the one
# undecided attribute mutation, as a formal receiver's is
# (``store_effect_sugar.attribute_mutation``, #7757 NEW-4).
TWO_ATTRIBUTE = "def f(p, q):\n    o.x, o.y = p, q\n    return p\n"


# ---------------------------------------------------------------------------
# Law 1 -- the RHS is constructed once.
# ---------------------------------------------------------------------------


def test_rhs_member_is_one_retained_occurrence(tmp_path: Path) -> None:
    """`o.x, o.y = p, p` evaluates each RHS member ONCE, never once per target.

    Proven at the layer that owns it: the statement evaluates its one
    right-hand side display, one element per member, and each store leaf
    reads the member the unpack binds under its own key. ``p, p`` is two
    reads of one formal (Python loads ``p`` twice): two occurrences, each at
    its own source site, of the same coordinate.
    """
    shared = "def f(p):\n    o.x, o.y = p, p\n    return p\n"
    unpack = _unpack(tmp_path, shared)
    first, second = unpack.value.elements
    assert first == second, (first, second)
    assert first.coordinate == second.coordinate
    assert first.site != second.site, (first.site, second.site)
    first_key, second_key = _member_keys(unpack)
    assert first_key != second_key
    # Each store leaf reads its member through its member key.
    stores = _stores(unpack)
    assert stores[0].value.evaluation == first_key
    assert stores[1].value.evaluation == second_key

    # One store per target on the arms too: the arm that halted at the
    # second store states the first one completed, never a second evaluation
    # of it.
    arms = _arm_stores(tmp_path, shared, stem="shared")
    assert len(arms) == 3, arms
    assert [len(arm[0]) for arm in arms] == [0, 1, 2], arms
    assert [len(arm[1]) for arm in arms] == [1, 1, 0], arms

    # Discrimination: distinct RHS members must NOT collapse onto one
    # occurrence -- sharing must come from the source, never from the lift.
    distinct = _unpack(tmp_path, TWO_ATTRIBUTE, stem="distinct")
    left, right = distinct.value.elements
    assert left is not right
    assert left != right
    # Each store reads its own member's key, never another leaf's.
    stores, keys = _stores(distinct), _member_keys(distinct)
    assert stores[0].value.evaluation == keys[0]
    assert stores[1].value.evaluation == keys[1]


# ---------------------------------------------------------------------------
# Law 2 -- positional correspondence.
# ---------------------------------------------------------------------------


def test_positional_correspondence_binds_each_target_to_its_own_member(
    tmp_path: Path,
) -> None:
    """`o.x, o.y = p, q` stores p into `.x` and q into `.y` -- a swap must bite.

    The pairing is the unpack's, by position: store ``k`` is the ``k``-th
    target and reads the member the unpack binds under the ``k``-th member
    key.  An undecided store states nothing about the value it stores (its
    receiver's ``__setattr__`` is not decided here), so the pairing is read
    where it is constructed, never off a store testimony."""
    unpack = _unpack(tmp_path, TWO_ATTRIBUTE)
    assert [store.store.attr for store in _stores(unpack)] == ["x", "y"]
    assert [store.value.evaluation for store in _stores(unpack)] == list(
        _member_keys(unpack)
    )

    # Discrimination arm: swap the targets, keep the members.  The first
    # member now pairs with `.y`.
    swapped_source = "def f(p, q):\n    o.y, o.x = p, q\n    return p\n"
    swapped = _unpack(tmp_path, swapped_source, stem="swapped")
    assert [store.store.attr for store in _stores(swapped)] == ["y", "x"]
    assert _stores(swapped)[0].value.evaluation == _member_keys(swapped)[0]


# ---------------------------------------------------------------------------
# Law 3 -- left-to-right store order.
# ---------------------------------------------------------------------------


def test_store_effects_retain_left_to_right_order(tmp_path: Path) -> None:
    """Three attribute stores run in source order -- and the ARM STRUCTURE
    says so.

    The arm halting at store ``k`` states stores ``0..k-1`` completed and
    store ``k`` halted, so ``k+1`` cannot have run.  That is law 3 and law 7
    in one artifact.
    """
    three = "def f(p, q, r):\n    o.x, o.y, o.z = p, q, r\n    return p\n"
    arms = _arm_stores(tmp_path, three, stem="order")
    assert [sorted(_targets(arm)) for arm in arms] == [
        [],
        ["x"],
        ["x", "y"],
        ["x", "y", "z"],
    ], arms
    assert [[attr for _receiver, attr in arm[1]] for arm in arms] == [
        ["x"],
        ["y"],
        ["z"],
        [],
    ], arms

    # Discrimination arm: the same three stores written in a different order
    # halt in that different order -- order is carried, not normalized away.
    reversed_source = "def f(p, q, r):\n    o.z, o.y, o.x = r, q, p\n    return p\n"
    reversed_arms = _arm_stores(tmp_path, reversed_source, stem="revorder")
    assert [[attr for _receiver, attr in arm[1]] for arm in reversed_arms] == [
        ["z"],
        ["y"],
        ["x"],
        [],
    ], reversed_arms
    assert [sorted(_targets(arm)) for arm in reversed_arms] == [
        [],
        ["z"],
        ["y", "z"],
        ["x", "y", "z"],
    ], reversed_arms


# ---------------------------------------------------------------------------
# Law 4 -- exact receiver coordinates.
# ---------------------------------------------------------------------------


def test_attribute_receiver_and_name_retain_exact_coordinates(
    tmp_path: Path,
) -> None:
    """Not "an attribute store happened" -- the exact receiver and attr terms."""
    source = "def f(p, q):\n    o.x, n.y = p, q\n    return p\n"
    arms = _arm_stores(tmp_path, source, stem="coordarms")
    assert arms[-1][0] and set(arms[-1][0]) == {("o", "x"), ("n", "y")}, arms

    # The coordinates are retained on the halted arms, not only once the
    # whole statement completed: the arm that halts at `n.y` names `o.x` as
    # completed and `n.y` as halted, exactly.
    (partial,) = (arm for arm in arms if len(arm[0]) == 1)
    assert partial == ((("o", "x"),), (("n", "y"),)), partial

    # Discrimination arm 1: swap the receivers, keep everything else.
    recv_source = "def f(p, q):\n    n.x, o.y = p, q\n    return p\n"
    recv_arms = _arm_stores(tmp_path, recv_source, stem="recvarms")
    (recv_partial,) = (arm for arm in recv_arms if len(arm[0]) == 1)
    assert recv_partial != partial

    # Discrimination arm 2: keep the receivers, change one attribute name.
    # This lie perturbs only the second store, so the first store's
    # completion reads the same and the second's halt does not.
    attr_source = "def f(p, q):\n    o.x, n.z = p, q\n    return p\n"
    attr_arms = _arm_stores(tmp_path, attr_source, stem="attrarms")
    (attr_partial,) = (arm for arm in attr_arms if len(arm[0]) == 1)
    assert attr_partial[0] == partial[0]
    assert attr_partial[1] != partial[1]


def test_lying_variants_are_distinguished_on_all_three_axes(tmp_path: Path) -> None:
    """The lying twin must bite on receiver, on attribute AND on store order.

    The class-level ``witnesses()`` pair varies only the attribute (`.z`).
    These are the other two discriminations, asserted on the constructed
    arms: each perturbation alone changes what the arms state, and the two
    that perturb the first store already bite on the arm that halted at it.
    """
    truthful = _arm_stores(tmp_path, TWO_ATTRIBUTE, stem="tarm")
    lying = {
        "wrong receiver": _arm_stores(
            tmp_path,
            "def f(p, q):\n    n.x, o.y = p, q\n    return p\n",
            stem="wrarm",
        ),
        "wrong attribute": _arm_stores(
            tmp_path,
            "def f(p, q):\n    o.x, o.z = p, q\n    return p\n",
            stem="waarm",
        ),
        "reversed store order": _arm_stores(
            tmp_path,
            "def f(p, q):\n    o.y, o.x = q, p\n    return p\n",
            stem="roarm",
        ),
    }
    for label, arms in lying.items():
        assert arms != truthful, label
    assert len(set(lying.values())) == 3
    for label in ("wrong receiver", "reversed store order"):
        assert lying[label][0] != truthful[0], label


# ---------------------------------------------------------------------------
# Law 5 -- a Name leaf's binding is discharged alongside the store.
# ---------------------------------------------------------------------------


def test_name_leaf_binding_is_discharged_beside_the_store_effect(
    tmp_path: Path,
) -> None:
    """`x, o.a = p, q` binds x to p AND runs the `.a` store.

    The Name leaf is bound by the unpack under its projection of the
    statement's evaluation, and every later reference reads it there.  The
    store is the statement's one store leaf, reading the second member, and
    the continuation's post reads `p`.
    """
    source = "def f(p, q):\n    x, o.a = p, q\n    return x\n"
    unpack = _unpack(tmp_path, source)
    assert _name_targets(unpack) == ("x",)
    assert len(_stores(unpack)) == 1
    assert _stores(unpack)[0].store.attr == "a"
    assert _stores(unpack)[0].value.evaluation == _member_keys(unpack)[0]
    assert _arm_stores(tmp_path, source, stem="mix")[-1][0] == (("o", "a"),)
    assert str(_post(tmp_path, source, stem="post")) == (
        "_Atomic(name='=', args=(_Var(name='out'), _Var(name='p')))"
    )

    # Discrimination arm: swap the members. x must now carry q.
    swapped = "def f(p, q):\n    x, o.a = q, p\n    return x\n"
    assert str(_post(tmp_path, swapped, stem="swpost")) == (
        "_Atomic(name='=', args=(_Var(name='out'), _Var(name='q')))"
    )

    # ------------------------------------------------------------------
    # Law 6 -- assignment is NOT transactional. Nothing established before a
    # store is erased by that store's halt.
    #
    # A Name target is spent by substitute: it materializes no entry on EITHER
    # arm, so "x survives the halt" has no artifact of its own to assert -- it
    # is true by construction, not by retention. What the law is really about
    # is a store established before the halting one: here a preceding store on
    # `o.z`. The arm where the later store halted states it completed.
    # ------------------------------------------------------------------
    partial = "def f(p, q):\n    o.z = p\n    x, o.a = p, q\n    return x\n"
    arms = _arm_stores(tmp_path, partial, stem="partial")
    assert [sorted(_targets(arm)) for arm in arms] == [[], ["z"], ["a", "z"]], arms

    # Discrimination arm: a halted exit that lost the earlier store is exactly
    # what a transactional (rolled-back) reading would produce, and it is not
    # what this construction produces.
    assert _targets(arms[1]) != [], "the earlier store was rolled back"
    assert arms[1][1] == (("o", "a"),), "the halted store ran anyway"


# ---------------------------------------------------------------------------
# Law 8 -- a pure-name unpack is the reduce-time unpack, never a store unpack.
# ---------------------------------------------------------------------------

# Statement shapes for the pure-name path, each with the one assign statement
# kind it constructs. Returns avoid BinOp so binary dispatch has no face here.
PURE_NAME_SHAPES = (
    ("def f(p, q):\n    a, b = p, q\n    return a\n", "DynamicUnpackAssignSugar"),
    (
        "def f(p, q, r):\n    a, b, c = p, q, r\n    return a\n",
        "DynamicUnpackAssignSugar",
    ),
    ("def f(p):\n    x = y = p\n    return x\n", "ChainedAssignSugar"),
)


def _assign_kinds(tmp_path: Path, source: str, stem: str) -> list:
    """The kind of each assignment statement, read by name off the
    statement roster, so a pure-name shape built as any other assignment
    kind (a store unpack) shows up as that kind here."""
    sugar = _function_sugar(tmp_path, source, stem)
    return [
        type(stmt).__name__
        for stmt in sugar.statements
        if "Assign" in type(stmt).__name__
    ]


def test_pure_name_unpack_is_the_reduce_time_unpack(tmp_path: Path) -> None:
    """A pure-name unpack of a display is the one reduce-time unpack, a chain
    is ChainedAssign -- neither is a store unpack (#7757 S2).

    Each shape constructs exactly one assignment statement, of the named
    kind, and the function has no halt: unpacking a display of the right
    arity, or binding names to formals, cannot raise.
    """
    for index, (source, expected_kind) in enumerate(PURE_NAME_SHAPES):
        assert _assign_kinds(tmp_path, source, f"pure{index}") == [
            expected_kind
        ], source
        outcome = _outcome(tmp_path, source, f"pureout{index}")
        assert outcome.halts() == (), (source, outcome)
        assert any(isinstance(exit_, Completed) for exit_ in outcome.exits), source

    # Discrimination arm: an unpack-with-store shape is a different sugar kind.
    assert _assign_kinds(
        tmp_path, "def f(p, q):\n    x, o.a = p, q\n    return x\n", stem="disc"
    ) == ["DynamicUnpackStoreAssignSugar"]


# ---------------------------------------------------------------------------
# Laws 9 and 10 -- what stays typed-loud.
# ---------------------------------------------------------------------------


def _assert_loud(tmp_path: Path, source: str, stem: str) -> None:
    fn = _function(tmp_path, source, stem)
    try:
        fn.sugar()
    except SugarNotWritten as gap:
        assert "Assign" in gap.owner or "Assign" in str(gap), gap
        return
    raise AssertionError(f"expected SugarNotWritten [Assign.sugar] for: {source!r}")


def test_star_against_opaque_iterable_stays_loud(tmp_path: Path) -> None:
    """Starred opaque unpack retains typed obligation — never an unguarded
    completion.

    Post-starred-unpack: ``DynamicUnpackAssignSugar`` constructs for
    ``a, *rest = xs``; desugar keeps an undetermined raise as one arm,
    binding nothing, and completes only under the starred unpack's
    completes atom, ``a`` its first member's projection. A display is the
    same reduce-time unpack, over a decided tuple (#7757 S2).
    """
    from sugar_lift_py_tests.effect import UndeterminedRaiseEffect
    outcome = _function_sugar(
        tmp_path, "def f(xs):\n    a, *rest = xs\n    return a\n", "star"
    ).desugar(None)
    (halt,) = outcome.halts()
    assert isinstance(halt.effect, UndeterminedRaiseEffect)
    assert outcome.completed_value() is None
    (completed,) = [arm for arm in outcome.exits if arm not in outcome.halts()]
    assert "python:unpack.destructure_starred" in str(completed.guard)

    # Discrimination arm: a starred unpack against a CONCRETE display is a
    # different shape and must still construct -- "loud" is about the opaque
    # iterable, not about the star.
    display = "def f(p, q, r):\n    a, *rest = p, q, r\n    return a\n"
    assert _assign_kinds(tmp_path, display, stem="stardisplay") == [
        "DynamicUnpackAssignSugar"
    ]


def test_source_visible_subscript_leaves_construct_after_store_coordinate_law(
    tmp_path: Path,
) -> None:
    """#6599 gave ``SubscriptStoreEffectSugar`` receiver, index, and value.

    Flat unpack therefore admits source-visible subscript leaves the same way
    it admits Attribute leaves. Formal/undecided receivers stay loud at
    *desugar* (store law), not by refusing leaf admission. Pairing is retained:
    swapped RHS members construct different store sugars.
    """
    dual = _unpack(
        tmp_path,
        "def f(a, b, i, j, p, q):\n    a[i], b[j] = p, q\n    return p\n",
        "sub2",
    )
    assert len(_stores(dual)) == 2
    namesub = _unpack(
        tmp_path, "def f(a, i, p, q):\n    x, a[i] = p, q\n    return x\n", "namesub"
    )
    assert len(_name_targets(namesub)) == 1
    assert len(_stores(namesub)) == 1

    # Discrimination arm: Attribute sibling remains admitted.
    unpack = _unpack(
        tmp_path, "def f(p, q):\n    x, o.a = p, q\n    return x\n", stem="nameattr"
    )
    assert len(_stores(unpack)) == 1


def test_formal_subscript_unpack_desugar_stays_undischarged(tmp_path: Path) -> None:
    """A formal receiver's store stays undischarged (not Completed).

    Runtime-selected non-formal receivers still refuse at the store door
    (#6599 SugarNotWritten).  Expected shape changed (#8925): ``a``'s class
    is an input of ``f``'s contract (an unpack leaf store is read as ``a[i]
    = v`` is), so the store is the dispatched ``__setitem__`` edge, owed as
    the one member ``python:dispatch:__setitem__`` with its halt kept until
    prove binds the class a caller supplies -- no longer the ``setitem``
    carrier, which stands only where the class is no input.
    """
    from sugar_lift_py_tests.unanswered_calls import owed_calls

    sugar = _function_sugar(
        tmp_path, "def f(a, i, p, q):\n    x, a[i] = p, q\n    return x\n", "formal_sub"
    )
    outcome = sugar.desugar(None)
    assert "python:dispatch:__setitem__" in {
        call.symbol for call in owed_calls(outcome)
    }
    assert outcome.halts()
    assert outcome.completed_value() is None


def test_dual_attribute_display_unpack_constructs(tmp_path: Path) -> None:
    """The admitted shape constructs: two store leaves, both authenticated.

    This asserts nothing about the OUTCOME shape. It used to assert
    a sole completed value, which is the current single-unconditional-
    exit behaviour -- i.e. it asserted that a store cannot fail, the very
    thing ``test_assign_unpack_store_outcome_composition`` names as the
    remaining defect. Two committed twins cannot disagree about whether a
    store body reduces to one exit or to guarded exits; the outcome shape is
    owned there, so it is not restated here.
    """
    from sugar_lift_py_tests.sugar.assign_sugar import KeyedStoreSugar

    unpack = _unpack(tmp_path, TWO_ATTRIBUTE, stem="dual")
    stores = _stores(unpack)
    assert len(stores) == 2
    # Each store target is its own keyed statement around the one field
    # store, as a chained assignment's store target is.
    assert all(isinstance(store, KeyedStoreSugar) for store in stores)
    assert [store.store.attr for store in stores] == ["x", "y"]
    assert _name_targets(unpack) == ()


# ---------------------------------------------------------------------------
# STRENGTHENING -- done, and what is deliberately NOT here.
#
# Every arm twin above reads the constructed ExitSet arm by arm
# (`_arm_stores`), so laws 3, 4 and 5 are asserted on partial-execution
# prefixes as well as on the completed arm, and law 7 (no later target after an
# earlier halt) is the arm structure itself.
#
# Still deliberately absent:
#
#   * the OUTCOME SHAPE. How many exits a store body has is owned by
#     test_assign_unpack_store_outcome_composition. Asserting the current shape
#     here -- in either direction -- is asserting whatever that shape currently
#     is, which is how asserting a sole completed value came to state that a store
#     cannot fail. Two committed twins must never disagree about it.
#
#   * a retained artifact for a Name target on the halted arm. substitute spends
#     a Name binding before desugar, so it materializes no entry on ANY arm;
#     "x survives the halt" is true by construction, not by retention. The
#     non-rollback law is therefore proven where it has an artifact: on a store
#     established before the halting one (see the law-6 block in
#     test_name_leaf_binding_is_discharged_beside_the_store_effect).
#
#   * formal/undecided Subscript receivers. Construction admits the leaf after
#     #6599; desugar still refuses runtime-selected setitem pending the n-ary
#     carrier (store law, not a second unpack door). See
#     test_unpack_sequencing_law for the sequencing faces.
# ---------------------------------------------------------------------------


# ---------------------------------------------------------------------------
# Every store target's receiver and key are substituted (#7757 item 7):
# a chain's, and a nested unpack level's, as a single store's are -- never
# read by name at reduce.
# ---------------------------------------------------------------------------


def _statement(tmp_path: Path, source: str, stem: str, kind: str):
    sugar = _function_sugar(tmp_path, source, stem)
    return next(stmt for stmt in sugar.statements if type(stmt).__name__ == kind)


def test_a_chained_attribute_store_reads_a_formal_receiver_through_its_key(
    tmp_path: Path,
) -> None:
    from sugar_lift_py_tests.sugar.assign_sugar import KeyedStoreSugar
    from sugar_lift_py_tests.sugar.formal_ref_sugar import FormalRefSugar
    from sugar_lift_py_tests.sugar.name_sugar import NameSugar
    from sugar_lift_py_tests.sugar.receiver_field_store_sugar import (
        ReceiverFieldStoreSugar,
    )

    chained = _statement(
        tmp_path,
        "def f(o):\n    a = o.x = 5\n    return a\n",
        "chain_formal",
        "ChainedAssignSugar",
    )
    (store,) = chained.stores
    # The store target's own statement: the one field store, keyed.
    assert isinstance(store, KeyedStoreSugar)
    assert isinstance(store.store, ReceiverFieldStoreSugar)
    # The formal's coordinate, as ``o.x = 5`` alone reads it; the name
    # ``o`` is never looked up at reduce.
    assert isinstance(store.store.receiver, FormalRefSugar)
    assert not isinstance(store.store.receiver, NameSugar)

    # Discrimination arm: the single store reads the same receiver.
    single = _function_sugar(tmp_path, "def f(o):\n    o.x = 5\n    return o\n", "one")
    assert any(
        isinstance(
            getattr(getattr(stmt, "store", None), "receiver", None), FormalRefSugar
        )
        for stmt in single.statements
    )


def test_a_chained_subscript_store_reads_its_receiver_and_key_through_their_keys(
    tmp_path: Path,
) -> None:
    """A chain's subscript target is the one item store (``d[k] = v`` alone
    is the same statement): the receiver's ``__setitem__`` with the key and
    the value, the receiver and the key each read through their formal's
    coordinate, never a name looked up at reduce."""
    from sugar_lift_py_tests.sugar.builtin_container_call_sugar import (
        ContainerMutationStatementSugar,
        PathContainerCallSugar,
    )
    from sugar_lift_py_tests.sugar.formal_ref_sugar import FormalRefSugar
    from sugar_lift_py_tests.sugar.name_sugar import NameSugar

    chained = _statement(
        tmp_path,
        "def f(d, k):\n    a = d[k] = 5\n    return a\n",
        "chain_subscript",
        "ChainedAssignSugar",
    )
    (store,) = chained.stores
    assert isinstance(store, ContainerMutationStatementSugar)
    call = store.evaluated[0]
    assert isinstance(call, PathContainerCallSugar)
    assert call.method == "__setitem__"
    key, _value = call.args
    assert isinstance(call.receiver, FormalRefSugar)
    assert isinstance(key, FormalRefSugar)
    assert not isinstance(call.receiver, NameSugar)
    assert not isinstance(key, NameSugar)
    assert call.receiver.coordinate != key.coordinate


def test_a_chained_receiver_reads_a_name_an_earlier_target_bound(
    tmp_path: Path,
) -> None:
    """``a = a[0] = v`` binds ``a`` first, then stores into the new ``a``:
    the receiver reads ``a``'s projection of the chain's evaluation, the
    list ``[None]``, so the store is that list's mutation, as ``a[0] = v``
    alone is on a decided local list.  In ``a[0] = a = v`` the receiver is
    evaluated before ``a`` is bound and reads the formal."""
    from sugar_lift_py_tests.sugar.builtin_container_call_sugar import (
        ContainerMutationStatementSugar,
    )
    from sugar_lift_py_tests.sugar.evaluation_ref_sugar import EvaluationRefSugar
    from sugar_lift_py_tests.sugar.formal_ref_sugar import FormalRefSugar

    after = _statement(
        tmp_path,
        "def f(a):\n    a = a[0] = [None]\n    return a\n",
        "chain_after",
        "ChainedAssignSugar",
    )
    (store,) = after.stores
    assert isinstance(store, ContainerMutationStatementSugar)
    receiver = store.evaluated[0].receiver
    assert isinstance(receiver, EvaluationRefSugar)
    assert receiver.evaluation == dict(after.evaluations)["a"]

    before = _statement(
        tmp_path,
        "def f(a):\n    a[0] = a = [None]\n    return a\n",
        "chain_before",
        "ChainedAssignSugar",
    )
    (store,) = before.stores
    assert isinstance(store, ContainerMutationStatementSugar)
    assert isinstance(store.evaluated[0].receiver, FormalRefSugar)


def test_a_nested_unpack_store_leaf_is_one_unpack_with_its_receiver_substituted(
    tmp_path: Path,
) -> None:
    """``a, (b, o.x) = xs``: the nested level unpacks its member through the
    same positional unpack, then stores on the formal ``o`` read through its
    coordinate.  It used to be refused (``Assign.sugar``) with ``o`` never
    substituted."""
    from sugar_lift_py_tests.sugar.assign_sugar import (
        DynamicUnpackStoreAssignSugar,
        KeyedStoreSugar,
    )
    from sugar_lift_py_tests.sugar.formal_ref_sugar import FormalRefSugar
    from sugar_lift_py_tests.sugar.receiver_field_store_sugar import (
        ReceiverFieldStoreSugar,
    )
    from sugar_lift_py_tests.sugar.unpack_projection_targets import (
        NameUnpackTarget,
        NestedUnpackTarget,
        StoreUnpackTarget,
    )

    unpack = _statement(
        tmp_path,
        "def f(o, xs):\n    a, (b, o.x) = xs\n    return a\n",
        "nested_store",
        "DynamicUnpackStoreAssignSugar",
    )
    assert isinstance(unpack, DynamicUnpackStoreAssignSugar)
    first, nested = unpack.targets
    assert isinstance(first, NameUnpackTarget) and first.name == "a"
    assert isinstance(nested, NestedUnpackTarget)
    inner_name, leaf = nested.targets
    assert isinstance(inner_name, NameUnpackTarget) and inner_name.name == "b"
    # The leaf is ``o.x = <member>``'s own store, as ``o.x = v`` alone is.
    assert isinstance(leaf, StoreUnpackTarget)
    assert isinstance(leaf.store, KeyedStoreSugar)
    assert isinstance(leaf.store.store, ReceiverFieldStoreSugar)
    assert leaf.store.store.attr == "x"
    assert isinstance(leaf.store.store.receiver, FormalRefSugar)
    assert leaf.store.value.evaluation == leaf.evaluation
    # Every Name leaf binds under its projection of the one evaluation.
    assert first.evaluation is not None
    assert inner_name.evaluation == first.evaluation
