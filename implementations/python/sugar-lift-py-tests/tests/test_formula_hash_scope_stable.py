"""#5569 — Formula / CallSiteValue dunder hash must be scope-stable content coords.

Illegal shape (#5477 residual): under ``term_intern_scope``, formula and
callsite identity keyed terms by ``id(_intern_term(term))``. Observed:

  - hash of the *same* Formula changes when the ContextVar flips
  - structural twin inserted under scope misses dict/set lookup outside
  - two independent intern scopes hash structural twins differently

Replacement: permanent TermTableBuilder content CID for all dunder hash/eq
keys. Volume may memoize CID under the intern table; never use ``id()`` as
the identity.

These instruments stay red while identity is scope-dependent.
"""

from __future__ import annotations

from sugar_lift_py_tests.floor.call_site_value import CallSiteValue, _term_cycle_key
from sugar_lift_py_tests.ir import (
    TermTableBuilder,
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


def _formula_under_scope():
    with term_intern_scope():
        return atomic("eq", [ctor("f", [make_var("x")]), num(1)])


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
