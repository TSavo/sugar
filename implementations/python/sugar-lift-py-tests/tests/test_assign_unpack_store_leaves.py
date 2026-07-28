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
8. Pure-name ``MultiAssign`` construction is unchanged vs ``origin/main``.
9. Starred opaque unpack stays typed-loud.
10. Source-visible Subscript leaves construct (post-#6599 coordinates); formal
    receivers stay undischarged at desugar via the store law.

The projection helper below is the shared instrument: it strips the per-run
temp path and the site, leaving exactly the effect class, the reason and the
constructed operand term. Two sources that differ in receiver, in attribute,
in value pairing or in store order MUST project differently.
"""

from __future__ import annotations

import hashlib
import re
from pathlib import Path

from sugar_lift_py_tests.outcome.exit_set import (
    Completed,
    Halted,
    outcome_to_exitset,
    sole_completed_outcome,
)
from sugar_lift_py_tests.sugar.assign_sugar import (
    MultiAssignSugar,
    UnpackStoreAssignSugar,
)
from sugar_lift_python_source.source_oracle import path_source
from sugar_source_tree.panic import SugarNotWritten
from sugar_source_tree.tree import SourceFile


def _function(tmp_path: Path, source: str, stem: str = "assign_case"):
    path = tmp_path / f"{stem}.py"
    path.write_text(source, encoding="utf-8")
    return next(SourceFile(path_source(str(path))).functions())


def _function_sugar(tmp_path: Path, source: str, stem: str = "assign_case"):
    return _function(tmp_path, source, stem).sugar()


def _unpack(tmp_path: Path, source: str, stem: str = "assign_case"):
    sugar = _function_sugar(tmp_path, source, stem)
    return next(
        stmt for stmt in sugar.statements if isinstance(stmt, UnpackStoreAssignSugar)
    )


def _outcome(tmp_path: Path, source: str, stem: str = "assign_case"):
    """The constructed outcome, ALWAYS as an ``ExitSet``.

    A body containing a store no longer reduces to one unconditional exit: the
    store partitions it into a completed arm and one halted arm per store. A
    body with no store still reduces linearly, and ``outcome_to_exitset`` lifts
    that to the one-exit set, so every twin below reads the same instrument.
    """
    return outcome_to_exitset(_function_sugar(tmp_path, source, stem).desugar(None))


def _completed_value(tmp_path: Path, source: str, stem: str = "assign_case"):
    """The value on the SOLE completed arm.

    ``sole_completed_outcome`` is the sanctioned door: it refuses loudly when a
    success face was dropped or duplicated instead of quietly projecting one of
    several. It is not a way to discard the halted arms -- those are read by
    ``_arm_projections`` and asserted per arm.
    """
    return sole_completed_outcome(_outcome(tmp_path, source, stem)).value


def _record(tmp_path: Path, source: str, stem: str = "assign_case"):
    return _completed_value(tmp_path, source, stem).record


def _entries(payload) -> tuple:
    """The ordered temporal entries an exit arm carries.

    A completed arm carries a ``UniverseValue`` (record + post); a halted arm
    carries the reduced block PREFIX reached before the halt. Both are read
    through the same projection so a claim proven on the completed arm can be
    restated, unchanged, on a partial-execution prefix.
    """
    record = getattr(payload, "record", None)
    if record is not None:
        return tuple(record.statements)
    return tuple(getattr(payload, "entries", ()))


def _rows(entries) -> tuple:
    rows = []
    for entry in entries:
        effect = getattr(entry, "effect", None)
        if effect is None:
            rows.append(("value", type(entry).__name__, str(entry.post_contribution())))
            continue
        rows.append(
            (
                type(effect).__name__,
                re.sub(r" site=.*$", "", effect.reason),
                str(getattr(effect.runtime_operand, "term", None)),
            )
        )
    return tuple(rows)


def _projection(tmp_path: Path, source: str, stem: str = "assign_case"):
    """Ordered, site-free projection of every entry the completed arm carries.

    Effect entries project (class, reason-without-site, constructed operand
    term). Value entries project their post contribution. This is the artifact
    that any of laws 2, 3 and 4 would have to corrupt to go unnoticed.
    """
    return _rows(_record(tmp_path, source, stem).statements)


def _arm_projections(tmp_path: Path, source: str, stem: str = "assign_case"):
    """One projection per exit arm, shortest prefix first, completed arm last.

    Arm ``k`` (for ``k`` store targets) is the arm on which store ``k`` halted:
    it must carry stores ``0..k-1`` and nothing after them. The final entry is
    the completed arm, on which every store's testimony is present.
    """
    exits = _outcome(tmp_path, source, stem).exits
    halted = sorted(
        (e for e in exits if isinstance(e, Halted)),
        key=lambda e: len(_entries(e.state)),
    )
    completed = [e for e in exits if isinstance(e, Completed)]
    assert len(completed) == 1, completed
    return tuple(_rows(_entries(e.state)) for e in halted) + (
        _rows(_entries(completed[0].value)),
    )


def _store_rows(rows) -> tuple:
    return tuple(row for row in rows if row[0] != "value")


def _targets(rows) -> list:
    return [re.search(r"target `\.(\w)`", row[1]).group(1) for row in _store_rows(rows)]


def _post(tmp_path: Path, source: str, stem: str = "assign_case"):
    return _completed_value(tmp_path, source, stem).post()


# Free undecided ``o`` keeps dual-face AttributeStoreRuntimeEffect arms.
# Formal receivers mint setattr_named (vertical completion).
TWO_ATTRIBUTE = "def f(p, q):\n    o.x, o.y = p, q\n    return p\n"


# ---------------------------------------------------------------------------
# Law 1 -- the RHS is constructed once.
# ---------------------------------------------------------------------------


def test_rhs_member_is_one_retained_occurrence(tmp_path: Path) -> None:
    """`o.x, o.y = p, p` must retain ONE constructed occurrence of `p`.

    Proven at the layer that owns it: construction identity of the retained
    occurrence. No counter, no instrumented call tally -- if the RHS were
    re-evaluated (reconstructed) per target, the two stores would hold two
    distinct constructed objects.
    """
    shared = "def f(p):\n    o.x, o.y = p, p\n    return p\n"
    unpack = _unpack(tmp_path, shared)
    first, second = unpack.stores[0].value, unpack.stores[1].value
    assert first is second, (first, second)

    # ...and RHS-once holds on BOTH arms: the arm that halted at the second
    # store carries the SAME projected occurrence for the first store as the
    # fully-completed arm does. A re-construction per arm would differ, and a
    # dropped one would shorten the prefix.
    arms = _arm_projections(tmp_path, shared, stem="shared")
    assert len(arms) == 3, arms
    completed = arms[-1]
    for index, arm in enumerate(arms):
        assert _store_rows(arm) == _store_rows(completed)[: len(_store_rows(arm))], (
            index,
            arm,
        )
    assert [len(_store_rows(arm)) for arm in arms] == [0, 1, 2]

    # Discrimination: distinct RHS members must NOT collapse onto one
    # occurrence -- sharing must come from the source, never from the lift.
    distinct = _unpack(tmp_path, TWO_ATTRIBUTE, stem="distinct")
    assert distinct.stores[0].value is not distinct.stores[1].value
    assert distinct.stores[0].value != distinct.stores[1].value

    # Discrimination: the prefix reading is not vacuous -- `p, p` and `p, q`
    # project the same FIRST store but different second stores, so the arm
    # structure is sensitive to the member, not just to the count.
    other = _arm_projections(tmp_path, TWO_ATTRIBUTE, stem="distinctarms")
    assert _store_rows(other[1]) == _store_rows(arms[1])
    assert _store_rows(other[2]) != _store_rows(arms[2])


# ---------------------------------------------------------------------------
# Law 2 -- positional correspondence.
# ---------------------------------------------------------------------------


def test_positional_correspondence_binds_each_target_to_its_own_member(
    tmp_path: Path,
) -> None:
    """`o.x, o.y = p, q` stores p into `.x` and q into `.y` -- a swap must bite."""
    rows = _projection(tmp_path, TWO_ATTRIBUTE)
    assert rows[0][2] == (
        "_Ctor(name='python:attribute_store', args=(_Var(name='o'), "
        "_ConstStr(value='x', sort=PrimitiveSort(name='String')), _Var(name='p')))"
    ), rows[0]
    assert rows[1][2] == (
        "_Ctor(name='python:attribute_store', args=(_Var(name='o'), "
        "_ConstStr(value='y', sort=PrimitiveSort(name='String')), _Var(name='q')))"
    ), rows[1]

    # The pairing holds on the PARTIAL arm too: the arm that halted at `.y`
    # carries the `.x` store already paired with `p`, not re-paired or dropped.
    arms = _arm_projections(tmp_path, TWO_ATTRIBUTE, stem="posarms")
    (partial,) = (arm for arm in arms if len(_store_rows(arm)) == 1)
    assert _store_rows(partial)[0][2] == rows[0][2], partial

    # Discrimination arm: swap the two RHS members. The pairing -- and only the
    # pairing -- changes, so the projection must differ.
    swapped_source = "def f(p, q):\n    o.x, o.y = q, p\n    return p\n"
    swapped = _projection(tmp_path, swapped_source, stem="swapped")
    assert swapped != rows
    assert [row[1] for row in swapped] == [row[1] for row in rows]

    # ...and the swap is visible on the partial arm alone: a lie that only ever
    # showed up once both stores completed would escape a halted execution.
    swapped_arms = _arm_projections(tmp_path, swapped_source, stem="swappedarms")
    (swapped_partial,) = (arm for arm in swapped_arms if len(_store_rows(arm)) == 1)
    assert _store_rows(swapped_partial) != _store_rows(partial)


# ---------------------------------------------------------------------------
# Law 3 -- left-to-right store order.
# ---------------------------------------------------------------------------


def test_store_effects_retain_left_to_right_order(tmp_path: Path) -> None:
    """Three attribute stores appear in source order -- and the ARM STRUCTURE
    says so too.

    Order used to be observable only inside one record. With the store
    partition it is observable as the exits themselves: the arm halting at
    store ``k`` carries exactly stores ``0..k-1``, so ``k+1`` cannot have run.
    That is law 3 and law 7 in one artifact.
    """
    three = "def f(p, q, r):\n    o.x, o.y, o.z = p, q, r\n    return p\n"
    rows = _projection(tmp_path, three)
    assert _targets(rows) == ["x", "y", "z"], rows

    arms = _arm_projections(tmp_path, three, stem="order")
    assert [_targets(arm) for arm in arms] == [
        [],
        ["x"],
        ["x", "y"],
        ["x", "y", "z"],
    ], [_targets(arm) for arm in arms]

    # Stated as the prohibition as well as the prefix: no arm carries a store
    # that comes after the one it halted on.
    for index, arm in enumerate(arms[:-1]):
        assert "z" not in _targets(arm) or index == 3, arm
        assert len(_targets(arm)) == index

    # Discrimination arm: the same three stores written in a different order
    # project in that different order -- order is carried, not normalized away.
    reversed_source = "def f(p, q, r):\n    o.z, o.y, o.x = r, q, p\n    return p\n"
    reversed_rows = _projection(tmp_path, reversed_source, stem="reversed")
    assert _targets(reversed_rows) == ["z", "y", "x"], reversed_rows
    assert reversed_rows != rows

    # ...and the arm structure follows the source order, so the prefixes are
    # not a fixed alphabetical artifact of the reader.
    reversed_arms = _arm_projections(tmp_path, reversed_source, stem="revorder")
    assert [_targets(arm) for arm in reversed_arms] == [
        [],
        ["z"],
        ["z", "y"],
        ["z", "y", "x"],
    ]


# ---------------------------------------------------------------------------
# Law 4 -- exact receiver coordinates.
# ---------------------------------------------------------------------------


def test_attribute_receiver_and_name_retain_exact_coordinates(
    tmp_path: Path,
) -> None:
    """Not "an attribute store happened" -- the exact receiver and attr terms."""
    source = "def f(p, q):\n    o.x, n.y = p, q\n    return p\n"
    rows = _projection(tmp_path, source)
    assert "_Var(name='o')" in rows[0][2] and "value='x'" in rows[0][2], rows[0]
    assert "_Var(name='n')" in rows[1][2] and "value='y'" in rows[1][2], rows[1]

    # The coordinates are retained on the halted PREFIX, not only once the
    # whole statement completed: an arm that halts at `n.y` still names `o`
    # and `x` exactly.
    arms = _arm_projections(tmp_path, source, stem="coordarms")
    (partial,) = (arm for arm in arms if len(_store_rows(arm)) == 1)
    partial_row = _store_rows(partial)[0]
    assert "_Var(name='o')" in partial_row[2] and "value='x'" in partial_row[2], partial

    # Discrimination arm 1: swap the receivers, keep everything else.
    recv_source = "def f(p, q):\n    n.x, o.y = p, q\n    return p\n"
    other_receiver = _projection(tmp_path, recv_source, stem="recv")
    assert other_receiver != rows

    # ...and the receiver swap already bites on the one-store prefix.
    recv_arms = _arm_projections(tmp_path, recv_source, stem="recvarms")
    (recv_partial,) = (arm for arm in recv_arms if len(_store_rows(arm)) == 1)
    assert _store_rows(recv_partial) != _store_rows(partial)

    # Discrimination arm 2: keep the receivers, change one attribute name.
    attr_source = "def f(p, q):\n    o.x, n.z = p, q\n    return p\n"
    other_attr = _projection(tmp_path, attr_source, stem="attr")
    assert other_attr != rows

    # This second lie is deliberately INVISIBLE on the first prefix -- it
    # perturbs only the second store -- which is what makes the first
    # discrimination's prefix bite evidence about the receiver specifically.
    attr_arms = _arm_projections(tmp_path, attr_source, stem="attrarms")
    (attr_partial,) = (arm for arm in attr_arms if len(_store_rows(arm)) == 1)
    assert _store_rows(attr_partial) == _store_rows(partial)
    assert _store_rows(attr_arms[-1]) != _store_rows(arms[-1])


def test_lying_variants_are_distinguished_on_all_three_axes(tmp_path: Path) -> None:
    """The lying twin must bite on receiver, on attribute AND on store order.

    The class-level ``witnesses()`` pair varies only the attribute (`.z`).
    These are the other two discriminations, asserted on the constructed
    artifact: each perturbation alone changes the projection.
    """
    truthful = _projection(tmp_path, TWO_ATTRIBUTE)
    wrong_receiver = _projection(
        tmp_path,
        "def f(p, q):\n    n.x, o.y = p, q\n    return p\n",
        stem="wr",
    )
    wrong_attribute = _projection(
        tmp_path,
        "def f(p, q):\n    o.x, o.z = p, q\n    return p\n",
        stem="wa",
    )
    reversed_order = _projection(
        tmp_path,
        "def f(p, q):\n    o.y, o.x = q, p\n    return p\n",
        stem="ro",
    )
    for label, lying in (
        ("wrong receiver", wrong_receiver),
        ("wrong attribute", wrong_attribute),
        ("reversed store order", reversed_order),
    ):
        assert lying != truthful, label
    # ...and the three lies are distinct from one another, so no single
    # perturbation is standing in for all three.
    assert len({wrong_receiver, wrong_attribute, reversed_order}) == 3

    # Now across arms. A lie is not allowed to hide in a partial execution: for
    # each axis, the FULL per-arm reading differs, and for the two axes that
    # perturb the first store (receiver, order) the difference is already there
    # on the one-store prefix -- i.e. it bites on a run that halted early.
    truthful_arms = _arm_projections(tmp_path, TWO_ATTRIBUTE, stem="tarm")
    lying_arms = {
        "wrong receiver": _arm_projections(
            tmp_path,
            "def f(p, q):\n    n.x, o.y = p, q\n    return p\n",
            stem="wrarm",
        ),
        "wrong attribute": _arm_projections(
            tmp_path,
            "def f(p, q):\n    o.x, o.z = p, q\n    return p\n",
            stem="waarm",
        ),
        "reversed store order": _arm_projections(
            tmp_path,
            "def f(p, q):\n    o.y, o.x = q, p\n    return p\n",
            stem="roarm",
        ),
    }
    for label, arms in lying_arms.items():
        assert arms != truthful_arms, label
    prefix = _store_rows(truthful_arms[1])
    for label in ("wrong receiver", "reversed store order"):
        assert _store_rows(lying_arms[label][1]) != prefix, label


# ---------------------------------------------------------------------------
# Law 5 -- a Name leaf's binding is discharged alongside the store.
# ---------------------------------------------------------------------------


def test_name_leaf_binding_is_discharged_beside_the_store_effect(
    tmp_path: Path,
) -> None:
    """`x, o.a = p, q` binds x to p AND emits the `.a` store carrying q.

    The Name leaf has no ordered record entry: substitute spends it before
    desugar, threading `p` into every later reference. So "x = p occurs before
    the store" is carried as: the store is the first record entry, and the
    continuation's post already reads `p`.
    """
    source = "def f(p, q):\n    x, o.a = p, q\n    return x\n"
    unpack = _unpack(tmp_path, source)
    assert [name for name, _ in unpack.bindings] == ["x"]
    assert len(unpack.stores) == 1

    rows = _projection(tmp_path, source, stem="mix")
    assert rows[0][0] == "AttributeStoreRuntimeEffect"
    assert "_Var(name='o')" in rows[0][2] and "_Var(name='q')" in rows[0][2], rows[0]
    assert str(_post(tmp_path, source, stem="post")) == (
        "_Atomic(name='=', args=(_Var(name='out'), _Var(name='p')))"
    )

    # Discrimination arm: swap the members. x must now carry q, and the store
    # must now carry p -- both halves flip together.
    swapped = "def f(p, q):\n    x, o.a = q, p\n    return x\n"
    swapped_rows = _projection(tmp_path, swapped, stem="mixswap")
    assert "_Var(name='p')" in swapped_rows[0][2], swapped_rows[0]
    assert str(_post(tmp_path, swapped, stem="swpost")) == (
        "_Atomic(name='=', args=(_Var(name='out'), _Var(name='q')))"
    )

    # ------------------------------------------------------------------
    # Law 6 -- assignment is NOT transactional. Nothing established before a
    # store is erased by that store's halt.
    #
    # A Name target is spent by substitute: it materializes no entry on EITHER
    # arm, so "x survives the halt" has no artifact of its own to assert -- it
    # is true by construction, not by retention. What DOES materialize, and
    # what the law is really about, is testimony established before the store:
    # here a preceding store on `o.z`. It must be present, in full, on the arm
    # where the later store halted.
    # ------------------------------------------------------------------
    partial = "def f(p, q):\n    o.z = p\n    x, o.a = p, q\n    return x\n"
    arms = _arm_projections(tmp_path, partial, stem="partial")
    assert [_targets(arm) for arm in arms] == [[], ["z"], ["z", "a"]], [
        _targets(arm) for arm in arms
    ]
    surviving = _store_rows(arms[1])[0]
    assert surviving == _store_rows(arms[-1])[0], (surviving, arms[-1])

    # Discrimination arm: a halted exit that lost the earlier store is exactly
    # what a transactional (rolled-back) reading would produce, and it is not
    # what this construction produces.
    assert _targets(arms[1]) != [], "the earlier store was rolled back"
    assert _targets(arms[1]) != ["z", "a"], "the halted store ran anyway"


# ---------------------------------------------------------------------------
# Law 8 -- pure-name MultiAssign is unchanged vs origin/main.
# ---------------------------------------------------------------------------

# Statement-shape fingerprints for the pure-name path. Returns avoid BinOp so
# binary-dispatch ExitSet growth cannot re-pin this as a false unpack regression.
PURE_NAME_SHAPES = (
    (
        "def f(p, q):\n    a, b = p, q\n    return a\n",
        "226ca945216c831f574a9b28697fc4f1",  # MultiAssignSugar + Complete
    ),
    (
        "def f(p, q, r):\n    a, b, c = p, q, r\n    return a\n",
        "226ca945216c831f574a9b28697fc4f1",  # same inert MultiAssign face
    ),
    (
        "def f(p):\n    x = y = p\n    return x\n",
        "821c4398b70779143e38f47459ea4be3",  # ChainedAssignSugar + Complete
    ),
)


def _shape_fingerprint(tmp_path: Path, source: str, stem: str) -> str:
    sugar = _function_sugar(tmp_path, source, stem)
    # Pure-name MultiAssign/ChainedAssign are inert at desugar; pin the sugar
    # roster and each assign statement's own Complete face only.
    assign_faces = []
    for stmt in sugar.statements:
        if type(stmt).__name__ in (
            "MultiAssignSugar",
            "ChainedAssignSugar",
            "AssignSugar",
        ):
            face = stmt.desugar(None)
            assign_faces.append(f"{type(stmt).__name__}:{type(face).__name__}")
    text = "\n".join(
        [*(type(stmt).__name__ for stmt in sugar.statements), *assign_faces]
    )
    return hashlib.blake2b(text.encode(), digest_size=16).hexdigest()


def test_pure_name_multi_assign_construction_is_unchanged(tmp_path: Path) -> None:
    """Pure-name destructure/chain stays MultiAssign/ChainedAssign — not unpack stores.

    This branch must not convert name-only targets into UnpackStoreAssignSugar.
    Fingerprints pin statement kinds and inert assign desugar faces.
    """
    for index, (source, expected) in enumerate(PURE_NAME_SHAPES):
        stem = f"pure{index}"
        assert _shape_fingerprint(tmp_path, source, stem) == expected, source

    sugar = _function_sugar(tmp_path, PURE_NAME_SHAPES[0][0], stem="purekind")
    assert any(isinstance(stmt, MultiAssignSugar) for stmt in sugar.statements)
    assert not any(
        isinstance(stmt, UnpackStoreAssignSugar) for stmt in sugar.statements
    )
    chained = _function_sugar(tmp_path, PURE_NAME_SHAPES[2][0], stem="purechain")
    assert any(
        type(stmt).__name__ == "ChainedAssignSugar" for stmt in chained.statements
    )
    assert not any(
        isinstance(stmt, UnpackStoreAssignSugar) for stmt in chained.statements
    )

    # Discrimination arm: an unpack-with-store shape is a different sugar kind.
    store_shape = _function_sugar(
        tmp_path, "def f(p, q):\n    x, o.a = p, q\n    return x\n", stem="disc"
    )
    assert any(
        isinstance(stmt, UnpackStoreAssignSugar) for stmt in store_shape.statements
    )
    assert not any(
        isinstance(stmt, MultiAssignSugar) for stmt in store_shape.statements
    )


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
    """Starred opaque unpack is not a replacement binding door (#6078)."""
    _assert_loud(tmp_path, "def f(xs):\n    a, *rest = xs\n    return a\n", "star")

    # Discrimination arm: a starred unpack against a CONCRETE display is a
    # different shape and must still construct -- "loud" is about the opaque
    # iterable, not about the star.
    sugar = _function_sugar(
        tmp_path,
        "def f(p, q, r):\n    a, *rest = p, q, r\n    return a\n",
        stem="stardisplay",
    )
    assert any(isinstance(stmt, MultiAssignSugar) for stmt in sugar.statements)


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
    assert len(dual.stores) == 2
    namesub = _unpack(
        tmp_path, "def f(a, i, p, q):\n    x, a[i] = p, q\n    return x\n", "namesub"
    )
    assert len(namesub.bindings) == 1
    assert len(namesub.stores) == 1

    # Discrimination arm: Attribute sibling remains admitted.
    unpack = _unpack(
        tmp_path, "def f(p, q):\n    x, o.a = p, q\n    return x\n", stem="nameattr"
    )
    assert len(unpack.stores) == 1


def test_formal_subscript_unpack_desugar_stays_undischarged(tmp_path: Path) -> None:
    """Runtime-selected receivers still refuse at the store door (#6599)."""
    sugar = _function_sugar(
        tmp_path, "def f(a, i, p, q):\n    x, a[i] = p, q\n    return x\n", "formal_sub"
    )
    try:
        sugar.desugar(None)
    except SugarNotWritten as gap:
        assert "undischarged subscript store" in gap.observed
        return
    raise AssertionError("expected undischarged subscript store for formal receiver")


def test_dual_attribute_display_unpack_constructs(tmp_path: Path) -> None:
    """The admitted shape constructs: two store leaves, both authenticated.

    This asserts nothing about the OUTCOME shape. It used to assert
    ``isinstance(out, Complete)``, which is the current single-unconditional-
    exit behaviour -- i.e. it asserted that a store cannot fail, the very
    thing ``test_assign_unpack_store_outcome_composition`` names as the
    remaining defect. Two committed twins cannot disagree about whether a
    store body reduces to one exit or to guarded exits; the outcome shape is
    owned there, so it is not restated here.
    """
    unpack = _unpack(tmp_path, TWO_ATTRIBUTE, stem="dual")
    assert len(unpack.stores) == 2
    assert [store.attr for store in unpack.stores] == ["x", "y"]
    assert unpack.bindings == ()


# ---------------------------------------------------------------------------
# STRENGTHENING -- done, and what is deliberately NOT here.
#
# Every projection twin above now reads the constructed ExitSet arm by arm
# (`_arm_projections`), so laws 2, 3, 4 and 5 are asserted on partial-execution
# prefixes as well as on the completed arm, and law 7 (no later target after an
# earlier halt) is the arm structure itself.
#
# Still deliberately absent:
#
#   * the OUTCOME SHAPE. How many exits a store body has is owned by
#     test_assign_unpack_store_outcome_composition. Asserting the current shape
#     here -- in either direction -- is asserting whatever that shape currently
#     is, which is how `isinstance(out, Complete)` came to state that a store
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
