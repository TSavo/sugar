"""#5568 / #5569 / #5572 — Formula identity is a permanent content coordinate.

Illegal shape (#5477 residual): under ``term_intern_scope``, formula and
callsite identity keyed terms by ``id(_intern_term(term))``. Observed:

  - hash of the *same* Formula changes when the ContextVar flips
  - structural twin inserted under one scope misses dict/set lookup under another
  - two independent intern scopes hash structural twins differently

Replacement (#5568 / #5569): permanent TermTableBuilder content CID for all
dunder hash/eq keys. ``__hash__`` and ``__eq__`` share that ONE coordinate;
it is finite and total by construction (content-address, do not recurse).

#5572 — content-CID memo must not strong-pin terms for process lifetime.
Memo is weak-ref only; eviction must never change identity (recompute is
deterministic). Evict-and-recompute twin below proves that.

Required #5568 twins (must FAIL if identity reverts to term-id; PASS after fix):
  1. Cross-scope dictionary twin + lying non-collision
  2. Cross-scope set twin + distinct formulas stay two
"""

from __future__ import annotations

from sugar_lift_py_tests.floor.call_site_value import CallSiteValue, _term_cycle_key
from sugar_lift_py_tests.ir import (
    TermTableBuilder,
    _evict_term_content_cid,
    _term_content_cid,
    _term_content_cid_memo_size,
    atomic,
    ctor,
    make_var,
    num,
    term_intern_scope,
)


def _deep_term(depth: int = 40):
    term = make_var("leaf")
    for index in range(depth):
        term = ctor(f"ssa:{index}", [term])
    return term


def _same_formula():
    return atomic("eq", [ctor("f", [make_var("x")]), num(1)])


def _lying_formula():
    """Structurally different formula — must never collide with the twin."""
    return atomic("eq", [ctor("f", [make_var("x")]), num(2)])


def _formula_under_scope():
    with term_intern_scope():
        return _same_formula()


def test_content_cid_evict_and_recompute_preserves_identity() -> None:
    """#5572: eviction must not change the permanent content coordinate.

    Compute CID → evict memo entry → recompute. Same term, same CID. Formula
    hash/eq (which share that coordinate) must also be stable across eviction.
    """
    with term_intern_scope():
        term = ctor("f", [make_var("x")])
        formula = atomic("eq", [term, num(1)])
        cid_before = _term_content_cid(term)
        hash_before = hash(formula)
        assert _term_content_cid_memo_size() >= 1
        assert _evict_term_content_cid(term) is True, (
            "R=1 expected a live content-CID memo entry to evict (#5572)."
        )
        # Second evict is a no-op (already gone) — not a soft success for identity.
        assert _evict_term_content_cid(term) is False
        cid_after = _term_content_cid(term)
        hash_after = hash(formula)

    assert cid_before == cid_after, (
        f"R=1 content CID changed after memo eviction "
        f"({cid_before!r} vs {cid_after!r}). Coordinate must be permanent "
        "content-address; recompute is deterministic (#5572)."
    )
    assert hash_before == hash_after, (
        f"R=1 Formula.__hash__ changed after content-CID eviction "
        f"({hash_before!r} vs {hash_after!r}). __hash__/__eq__ must share "
        "the permanent content coordinate (#5568 / #5572)."
    )
    # Lying structural twin still distinct after recompute path.
    with term_intern_scope():
        lying_term = ctor("f", [make_var("x")])
        lying = atomic("eq", [lying_term, num(2)])
        assert _term_content_cid(lying_term) == cid_after  # same term shape
        assert hash(lying) != hash_before


def test_content_cid_memo_does_not_strong_pin_dead_terms() -> None:
    """#5572: dropping the only strong refs must allow memo entries to clear."""
    import gc
    import weakref

    with term_intern_scope():
        term = ctor("ephemeral", [make_var("z")])
        probe = weakref.ref(term)
        _ = _term_content_cid(term)
        size_with = _term_content_cid_memo_size()
        assert size_with >= 1
        del term
    gc.collect()
    assert probe() is None, (
        "R=1 content-CID memo strong-pinned a term after all other refs died "
        "(#5572). Memo must use weakrefs, not strong Term retention."
    )
    # Structural recompute remains the permanent coordinate (no identity drift).
    with term_intern_scope():
        twin = ctor("ephemeral", [make_var("z")])
        cid = _term_content_cid(twin)
    assert cid == TermTableBuilder().reference(
        ctor("ephemeral", [make_var("z")])
    )["cid"]


def test_cross_scope_dictionary_twin() -> None:
    """#5568: intern same formula in two scopes; one as dict key finds the other.

    Lying twin with different structure must not collide.
    """
    with term_intern_scope():
        left = _same_formula()
        table = {left: "scope-1"}

    with term_intern_scope():
        right = _same_formula()
        lying = _lying_formula()
        hit = table.get(right)
        lying_hit = table.get(lying)

    assert left == right, (
        "R=1 structural formula twins from distinct term_intern_scopes "
        "compare unequal. __eq__ must use permanent content coordinates (#5568)."
    )
    assert hash(left) == hash(right), (
        f"R=1 structural formula twins hash differently across scopes "
        f"({hash(left)!r} vs {hash(right)!r}). __hash__/__eq__ must share "
        "one permanent content coordinate (#5568)."
    )
    assert hit == "scope-1", (
        "R=1 cross-scope dictionary twin MISSED. Formula inserted under "
        "term_intern_scope A is not found by the structural twin from scope B. "
        "This is a wrong-answer identity split (#5568). "
        "Replacement: __hash__/__eq__ over content CID, not id(_intern_term)."
    )
    assert lying_hit is None, (
        "R=1 lying twin collided with dictionary entry. Distinct formulas "
        "must not share a content coordinate (#5568)."
    )
    assert left != lying and right != lying


def test_cross_scope_set_twin() -> None:
    """#5568: same formula from two scopes dedupes to ONE; distinct stay two.

    Membership is established *under* each scope so the hash recorded into the
    set is the live dunder hash of that session (the product failure mode).
    """
    with term_intern_scope():
        left = _same_formula()
        bucket = {left}

    with term_intern_scope():
        right = _same_formula()
        lying = _lying_formula()
        bucket.add(right)
        bucket.add(lying)

    assert left == right, (
        "R=1 structural formula twins compare unequal across scopes (#5568)."
    )
    assert hash(left) == hash(right), (
        f"R=1 structural formula twins hash differently "
        f"({hash(left)!r} vs {hash(right)!r}) (#5568)."
    )
    assert len(bucket) == 2, (
        f"R=1 cross-scope set twin failed: after adding equal twins from two "
        f"term_intern_scopes plus one lying distinct formula, set size is "
        f"{len(bucket)} (expected 2 = one equal class + one lying). "
        f"Equal formulas must dedupe to ONE element (#5568)."
    )
    assert left in bucket and right in bucket
    assert lying in bucket
    assert left != lying and right != lying


def test_formula_hash_stable_across_term_intern_scope() -> None:
    """Hash of one Formula object must not depend on active intern scope."""
    with term_intern_scope():
        formula = atomic("eq", [ctor("f", [make_var("x")]), num(1)])
        hash_inside = hash(formula)
    hash_outside = hash(formula)
    assert hash_inside == hash_outside, (
        f"R=1 Formula.__hash__ changed across term_intern_scope "
        f"(inside={hash_inside!r} outside={hash_outside!r}). "
        "Replacement: key atomic args by permanent content CID, never "
        "id(_intern_term(...)). Do not soft-complete or mint RuntimeEffect."
    )


def test_formula_dict_cross_scope_lookup_hits() -> None:
    """Insert under scope; structural twin outside must hit the dict."""
    with term_intern_scope():
        formula = atomic("eq", [ctor("f", [make_var("x")]), num(1)])
        table = {formula: "in-scope"}
    twin = atomic("eq", [ctor("f", [make_var("x")]), num(1)])
    assert formula == twin
    assert table.get(twin) == "in-scope", (
        "R=1 structural formula twin misses dict after leaving term_intern_scope. "
        "Formula.__hash__/__eq__ must use permanent content coordinates."
    )


def test_formula_set_cross_scope_membership() -> None:
    with term_intern_scope():
        formula = atomic("eq", [ctor("f", [make_var("x")]), num(1)])
        bucket = {formula}
    twin = atomic("eq", [ctor("f", [make_var("x")]), num(1)])
    assert twin in bucket, (
        "R=1 structural formula twin not in set after leaving term_intern_scope. "
        "Set membership requires scope-stable dunder hash."
    )


def test_formula_hash_equal_across_independent_intern_scopes() -> None:
    with term_intern_scope():
        left = atomic("eq", [ctor("f", [make_var("x")]), num(1)])
        hash_left = hash(left)
    with term_intern_scope():
        right = atomic("eq", [ctor("f", [make_var("x")]), num(1)])
        hash_right = hash(right)
    assert left == right
    assert hash_left == hash_right, (
        f"R=1 independent term_intern_scope sessions hash structural twins "
        f"differently ({hash_left!r} vs {hash_right!r}). Identity must be "
        "content CID, not per-scope object id."
    )
    assert {left: "a"}.get(right) == "a"


def test_callsite_dict_cross_scope_lookup_hits() -> None:
    with term_intern_scope():
        term = ctor("f", [make_var("x")])
        site = CallSiteValue("op", (), (), term, None)
        table = {site: "in-scope"}
    twin = CallSiteValue("op", (), (), ctor("f", [make_var("x")]), None)
    assert site == twin
    assert table.get(twin) == "in-scope", (
        "R=1 CallSiteValue structural twin misses dict across term_intern_scope. "
        "_term_cycle_key must be permanent content CID (#5569)."
    )


def test_term_cycle_key_is_content_cid_under_and_outside_scope() -> None:
    content = TermTableBuilder().reference(_deep_term(30))["cid"]
    with term_intern_scope():
        under = _term_cycle_key(_deep_term(30))
    outside = _term_cycle_key(_deep_term(30))
    assert under == outside == content, (
        f"R=1 _term_cycle_key not permanent content CID "
        f"(under={under!r} outside={outside!r} content={content!r})."
    )


def test_formula_and_callsite_keys_match_wire_cid_prefix() -> None:
    """Content coordinates are blake3 wire CIDs, never term-id: object tags."""
    with term_intern_scope():
        term = _deep_term(20)
        key = _term_cycle_key(term)
    assert key.startswith("blake3-512:"), (
        f"R=1 cycle key must be wire CID, not intern object id; got {key!r}"
    )
    assert not key.startswith("term-id:"), (
        "R=1 term-id: keys are the #5477 scope-dependent bug (#5569)."
    )
