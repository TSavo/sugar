"""Assign flat unpack with Attribute store leaves.

These twins do NOT assert "the shape returns an effect". Each one names a LAW
of Python assignment and asserts the *constructed artifact* that carries it,
paired with a discrimination arm that fails when the law is violated:

1. RHS members are constructed ONCE (retained occurrence identity).
2. Tuple elements retain positional correspondence.
3. Multiple store effects retain left-to-right order.
4. Attribute receiver and attribute name retain their exact coordinates.
5. A Name leaf's binding is discharged alongside the store effect.
6/7. Partial assignment (halt between stores) is NOT yet representable --
   pinned as a ratchet, see ``test_store_effects_have_no_halted_exit_arm``.
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

from sugar_lift_py_tests.outcome import Complete, Completed, Incomplete
from sugar_lift_py_tests.sugar.assign_sugar import (
    MultiAssignSugar,
    UnpackStoreAssignSugar,
)
from sugar_lift_py_tests.sugar.function_universe_sugar import reduce_block_to_exitset
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
# Laws 6 and 7 -- partial assignment. NOT yet representable: pinned as a ratchet.
# ---------------------------------------------------------------------------


def test_store_effects_have_no_halted_exit_arm(tmp_path: Path) -> None:
    """RATCHET, not a rubber stamp: partial assignment is NOT yet modelled.

    Python assignment is not transactional -- if `o.y = q` raises, `o.x = p`
    stays done and `o.y` never happens. Laws 6 and 7 need an outgoing ExitSet
    with a Halted arm carrying the state reached before the failure, and a
    Completed arm without the later store.

    Measured today: the outgoing ExitSet has exactly ONE arm, Completed, for
    both the unpack shape AND for the already-shipped sequential form
    `o.x = p; o.y = q` -- ``Incomplete.follow`` routes every store effect
    through ``_effect_continues_control_flow``. So this is a tree-wide
    property of the store family, NOT something #6239 introduced; narrowing
    the unpack shape would not reduce it while the two-statement spelling
    stays admitted.

    This twin pins that measurement. When sequential ExitSet composition
    lands, this twin goes RED and must be replaced by real laws 6 and 7 twins
    asserting the halted exit's carried binding state and the absence of the
    later store from the outgoing exit set.
    """
    unpack_exits = reduce_block_to_exitset(
        _function_sugar(tmp_path, TWO_ATTRIBUTE).statements, None
    ).exits
    sequential_exits = reduce_block_to_exitset(
        _function_sugar(
            tmp_path,
            "def f(o, p, q):\n    o.x = p\n    o.y = q\n    return o\n",
            stem="sequential",
        ).statements,
        None,
    ).exits

    for label, exits in (("unpack", unpack_exits), ("sequential", sequential_exits)):
        assert len(exits) == 1, (label, [type(a).__name__ for a in exits])
        assert isinstance(exits[0], Completed), (label, type(exits[0]).__name__)

    # The store effects themselves are the thing that continues -- named, so a
    # change to the follow routing lands here rather than silently elsewhere.
    unpack = _unpack(tmp_path, TWO_ATTRIBUTE, stem="follow")
    for store in unpack.stores:
        outcome = store.desugar(None)
        assert isinstance(outcome, Incomplete)
        assert outcome.follow().continues is True


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
    """The admitted shape still constructs to a Complete universe."""
    out = _function_sugar(tmp_path, TWO_ATTRIBUTE).desugar(None)
    assert isinstance(out, Complete)
    assert len(_unpack(tmp_path, TWO_ATTRIBUTE, stem="dual").stores) == 2
