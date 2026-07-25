"""Assign flat unpack with Attribute store leaves.

These twins do NOT assert "the shape returns an effect". Each one names a LAW
of Python assignment and asserts the *constructed artifact* that carries it,
paired with a discrimination arm that fails when the law is violated:

1. RHS members are constructed ONCE (retained occurrence identity).
2. Tuple elements retain positional correspondence.
3. Multiple store effects retain left-to-right order.
4. Attribute receiver and attribute name retain their exact coordinates.
5. A Name leaf's binding is discharged alongside the store effect.
6/7. Partial assignment (halt between stores) is NOT asserted here, and is
   deliberately NOT pinned here either: a test asserting "there is no halted
   arm" would be a test OF the defect, blessing it as expected behaviour.
   The real laws -- a Halted arm carrying the temporal state reached before
   the failure, and a Completed arm from which the later store is absent --
   live on the foundational store-ExitSet composition branch and start red
   there. #6239 is held until that lands. See the strengthening list in the
   comment at the end of this module for the twins that must gain a second
   exit arm on the rebase.
8. Pure-name ``MultiAssign`` construction is unchanged vs ``origin/main``.
9. Starred opaque unpack stays typed-loud.
10. Opaque-receiver Subscript leaves stay typed-loud (they cannot carry
    receiver or value; see the narrowing commit).

The projection helper below is the shared instrument: it strips the per-run
temp path and the site, leaving exactly the effect class, the reason and the
constructed operand term. Two sources that differ in receiver, in attribute,
in value pairing or in store order MUST project differently.
"""

from __future__ import annotations

import hashlib
import re
from pathlib import Path

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


def _record(tmp_path: Path, source: str, stem: str = "assign_case"):
    return _function_sugar(tmp_path, source, stem).desugar(None).value.record


def _projection(tmp_path: Path, source: str, stem: str = "assign_case"):
    """Ordered, site-free projection of every entry the block record carries.

    Effect entries project (class, reason-without-site, constructed operand
    term). Value entries project their post contribution. This is the artifact
    that any of laws 2, 3 and 4 would have to corrupt to go unnoticed.
    """
    rows = []
    for entry in _record(tmp_path, source, stem).statements:
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


def _post(tmp_path: Path, source: str, stem: str = "assign_case"):
    return _function_sugar(tmp_path, source, stem).desugar(None).value.post()


TWO_ATTRIBUTE = "def f(o, p, q):\n    o.x, o.y = p, q\n    return o\n"


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
    unpack = _unpack(tmp_path, "def f(o, p):\n    o.x, o.y = p, p\n    return o\n")
    first, second = unpack.stores[0].value, unpack.stores[1].value
    assert first is second, (first, second)

    # Discrimination: distinct RHS members must NOT collapse onto one
    # occurrence -- sharing must come from the source, never from the lift.
    distinct = _unpack(tmp_path, TWO_ATTRIBUTE, stem="distinct")
    assert distinct.stores[0].value is not distinct.stores[1].value
    assert distinct.stores[0].value != distinct.stores[1].value


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

    # Discrimination arm: swap the two RHS members. The pairing -- and only the
    # pairing -- changes, so the projection must differ.
    swapped = _projection(
        tmp_path, "def f(o, p, q):\n    o.x, o.y = q, p\n    return o\n", stem="swapped"
    )
    assert swapped != rows
    assert [row[1] for row in swapped] == [row[1] for row in rows]


# ---------------------------------------------------------------------------
# Law 3 -- left-to-right store order.
# ---------------------------------------------------------------------------


def test_store_effects_retain_left_to_right_order(tmp_path: Path) -> None:
    """Three attribute stores appear in source order, not as an unordered bag."""
    rows = _projection(
        tmp_path,
        "def f(o, p, q, r):\n    o.x, o.y, o.z = p, q, r\n    return o\n",
    )
    assert [
        re.search(r"target `\.(\w)`", row[1]).group(1) for row in rows if row[0] != "value"
    ] == ["x", "y", "z"], rows

    # Discrimination arm: the same three stores written in a different order
    # project in that different order -- order is carried, not normalized away.
    reversed_rows = _projection(
        tmp_path,
        "def f(o, p, q, r):\n    o.z, o.y, o.x = r, q, p\n    return o\n",
        stem="reversed",
    )
    assert [
        re.search(r"target `\.(\w)`", row[1]).group(1)
        for row in reversed_rows
        if row[0] != "value"
    ] == ["z", "y", "x"], reversed_rows
    assert reversed_rows != rows


# ---------------------------------------------------------------------------
# Law 4 -- exact receiver coordinates.
# ---------------------------------------------------------------------------


def test_attribute_receiver_and_name_retain_exact_coordinates(
    tmp_path: Path,
) -> None:
    """Not "an attribute store happened" -- the exact receiver and attr terms."""
    rows = _projection(
        tmp_path, "def f(o, n, p, q):\n    o.x, n.y = p, q\n    return p\n"
    )
    assert "_Var(name='o')" in rows[0][2] and "value='x'" in rows[0][2], rows[0]
    assert "_Var(name='n')" in rows[1][2] and "value='y'" in rows[1][2], rows[1]

    # Discrimination arm 1: swap the receivers, keep everything else.
    other_receiver = _projection(
        tmp_path,
        "def f(o, n, p, q):\n    n.x, o.y = p, q\n    return p\n",
        stem="recv",
    )
    assert other_receiver != rows

    # Discrimination arm 2: keep the receivers, change one attribute name.
    other_attr = _projection(
        tmp_path,
        "def f(o, n, p, q):\n    o.x, n.z = p, q\n    return p\n",
        stem="attr",
    )
    assert other_attr != rows


def test_lying_variants_are_distinguished_on_all_three_axes(tmp_path: Path) -> None:
    """The lying twin must bite on receiver, on attribute AND on store order.

    The class-level ``witnesses()`` pair varies only the attribute (`.z`).
    These are the other two discriminations, asserted on the constructed
    artifact: each perturbation alone changes the projection.
    """
    truthful = _projection(tmp_path, TWO_ATTRIBUTE)
    wrong_receiver = _projection(
        tmp_path,
        "def f(o, n, p, q):\n    n.x, o.y = p, q\n    return o\n",
        stem="wr",
    )
    wrong_attribute = _projection(
        tmp_path,
        "def f(o, p, q):\n    o.x, o.z = p, q\n    return o\n",
        stem="wa",
    )
    reversed_order = _projection(
        tmp_path,
        "def f(o, p, q):\n    o.y, o.x = q, p\n    return o\n",
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
    source = "def f(o, p, q):\n    x, o.a = p, q\n    return x\n"
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
    swapped = "def f(o, p, q):\n    x, o.a = q, p\n    return x\n"
    swapped_rows = _projection(tmp_path, swapped, stem="mixswap")
    assert "_Var(name='p')" in swapped_rows[0][2], swapped_rows[0]
    assert str(_post(tmp_path, swapped, stem="swpost")) == (
        "_Atomic(name='=', args=(_Var(name='out'), _Var(name='q')))"
    )


# ---------------------------------------------------------------------------
# Law 8 -- pure-name MultiAssign is unchanged vs origin/main.
# ---------------------------------------------------------------------------

# Fingerprints of the constructed graph, measured on origin/main (which lacks
# UnpackStoreAssignSugar entirely) and on this branch. Identical on both.
MAIN_FINGERPRINTS = {
    "def f(p, q):\n    a, b = p, q\n    return a + b\n": (
        "a759418749e787d443760eb87874d8be"
    ),
    "def f(p, q, r):\n    a, b, c = p, q, r\n    return a + b + c\n": (
        "c1a84ba04f846dfdb3b908f9ef245627"
    ),
    "def f(p):\n    x = y = p\n    return x + y\n": (
        "cdae1b2a2b67be6ecf2476b3cbc1e1d5"
    ),
}


def _fingerprint(tmp_path: Path, source: str, stem: str) -> str:
    sugar = _function_sugar(tmp_path, source, stem)
    text = "\n".join(
        [
            *(type(stmt).__name__ for stmt in sugar.statements),
            repr(sugar.desugar(None).value.record),
        ]
    )
    text = re.sub(r"/.*?/%s\.py" % re.escape(stem), "CASE", text)
    text = re.sub(r"blake3-512:[0-9a-f]+", "CID", text)
    text = re.sub(r"<SourceFragment[^>]*>", "FRAGMENT", text)
    return hashlib.blake2b(text.encode(), digest_size=16).hexdigest()


def test_pure_name_multi_assign_construction_is_unchanged(tmp_path: Path) -> None:
    """Not "it is a MultiAssignSugar" -- the constructed graph is byte-identical.

    Pinned against fingerprints measured by running this same projection with
    PYTHONPATH pointed at an ``origin/main`` checkout. Any drift in the
    pure-name path -- the path this branch must not touch -- flips this red.
    """
    for index, (source, expected) in enumerate(MAIN_FINGERPRINTS.items()):
        stem = f"pure{index}"
        assert _fingerprint(tmp_path, source, stem) == expected, source

    sugar = _function_sugar(
        tmp_path, "def f(p, q):\n    a, b = p, q\n    return a + b\n", stem="purekind"
    )
    assert any(isinstance(stmt, MultiAssignSugar) for stmt in sugar.statements)
    assert not any(
        isinstance(stmt, UnpackStoreAssignSugar) for stmt in sugar.statements
    )

    # Discrimination arm: the fingerprint is sensitive -- a different pure-name
    # assign does not collide with the pinned one.
    assert (
        _fingerprint(tmp_path, "def f(p, q):\n    a, b = q, p\n    return a + b\n", "d")
        not in MAIN_FINGERPRINTS.values()
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


def test_opaque_receiver_subscript_leaves_stay_loud(tmp_path: Path) -> None:
    """A store that cannot carry its receiver or its value is not admitted.

    ``SubscriptStoreEffectSugar`` holds only ``index_text`` and a site, so
    ``a[i], b[j] = p, q`` and ``a[i], b[j] = q, p`` construct identically --
    positional correspondence, the whole claim of an unpack, would be
    unprovable. Those shapes stay typed-loud.
    """
    _assert_loud(
        tmp_path,
        "def f(a, b, i, j, p, q):\n    a[i], b[j] = p, q\n    return p\n",
        "sub2",
    )
    _assert_loud(
        tmp_path, "def f(a, i, p, q):\n    x, a[i] = p, q\n    return x\n", "namesub"
    )

    # Discrimination arm: the Attribute sibling -- which DOES carry receiver
    # and value -- is still admitted, so this is a coordinate-retention rule,
    # not a blanket refusal of store leaves.
    unpack = _unpack(
        tmp_path, "def f(o, p, q):\n    x, o.a = p, q\n    return x\n", stem="nameattr"
    )
    assert len(unpack.stores) == 1


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
# HANDOFF -- strengthening required when store ExitSet composition lands.
#
# Every twin below currently reads ONE linear exit. Once a store contributes
# a Halted arm (failure, prefix temporal state) beside its Completed arm, the
# single-exit reading is no longer the whole artifact and each of these must
# be restated per arm. This list is the rebase checklist for #6239; it is not
# a licence to edit an expectation to match new behaviour -- re-measure.
#
# The OUTCOME SHAPE itself is not on this list and is not asserted anywhere in
# this module: it is owned by test_assign_unpack_store_outcome_composition,
# whose four twins are red on exactly that law. Nothing here may assert
# `isinstance(out, Complete)` -- that is the defect those twins name, and two
# committed twins must never disagree about it.
#
# SINGLE-ARM HELPERS -- fix these first, the twins follow:
#   _record / _projection / _post  read `.desugar(None).value` as one Complete.
#     They must take an exit arm (or return one projection per arm). This is
#     the highest-priority rewrite: every twin below flows through them.
#
#   Twin                                            what it must become
#   ----------------------------------------------  -----------------------
#   test_dual_attribute_display_unpack_constructs   already arm-independent
#     (sugar-layer only: store count, attrs, bindings). No change needed.
#
#   test_name_leaf_binding_is_discharged_beside_    PRIMARY site for law 6.
#     the_store_effect                              Today asserts one post
#     `out == p`. Must assert the HALTED exit still carries x == p -- the
#     earlier binding is not retroactively erased by the later store's
#     failure. This twin is where "assignment is not transactional" gets
#     proven, and its discrimination arm is a halted exit that lost x.
#
#   test_store_effects_retain_left_to_right_order   law 3 gains real teeth and
#     becomes law 7 as well: the arm halting at store k must contain exactly
#     stores 0..k-1 and NOT store k+1. Today order is only observable inside
#     one record; then it is observable as the arm structure itself.
#
#   test_positional_correspondence_...              per-arm projection: the
#   test_attribute_receiver_and_name_retain_        pairing and the receiver/
#     exact_coordinates                             attr coordinates must hold
#     on the halted prefix too, not only on the fully-completed arm.
#
#   test_lying_variants_are_distinguished_on_all_   a lie that shows up only
#     three_axes                                    in a partial-execution
#     prefix must bite. Extend the three axes across arms.
#
#   test_rhs_member_is_one_retained_occurrence      RHS-once must hold on BOTH
#     arms: the halted arm carries the SAME constructed occurrence, never a
#     re-construction.
#
#   test_pure_name_multi_assign_construction_is_    the three pinned
#     unchanged                                     fingerprints hash
#     repr(record). If the foundational work changes _ReducedBlock or the
#     record repr, RE-MEASURE against origin/main at that time and replace
#     the constants with the measured values. Never edit them to match.
#
#   test_opaque_receiver_subscript_leaves_stay_     the loud set shrinks on
#     loud                                          rebase: subscript leaves
#     are re-enabled wherever receiver, selector AND value are all
#     authenticated. Move those sources out of the loud list and under the
#     coordinate twins; keep loud only what still cannot authenticate all
#     three.
#
#   test_star_against_opaque_iterable_stays_loud    unaffected.
# ---------------------------------------------------------------------------
