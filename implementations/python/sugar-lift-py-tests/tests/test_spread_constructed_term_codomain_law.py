"""L2a — Spread / starred are ConstructedTermSugar; one codomain law.

ONE law at the type: ``require_constructed_term_sugar`` / ``isinstance(...,
ConstructedTermSugar)``. Not four patches at CallSiteSugar.args,
MethodCallSugar.args, IfExp arms, or keywords.

SpreadCollectionSugar, SpreadDictSugar, SpreadCallSugar, and StarredSugar
admit as nested-construction testimony (same judgment as ListSugar without
stars / #7099 promotions). Parent slots that require ConstructedTermSugar
are truthful; the mint must carry the base + to_term.
"""

from __future__ import annotations

import hashlib

from sugar_lift_py_tests.sugar.call_site_sugar import CallSiteSugar
from sugar_lift_py_tests.sugar.if_exp_sugar import IfExpSugar
from sugar_lift_py_tests.sugar.int_literal_sugar import IntLiteralSugar
from sugar_lift_py_tests.sugar.method_call_sugar import MethodCallSugar
from sugar_lift_py_tests.sugar.spread_sugar import (
    SpreadCallSugar,
    SpreadCollectionSugar,
    SpreadDictSugar,
)
from sugar_lift_py_tests.sugar.starred_sugar import StarredSugar
from sugar_lift_py_tests.sugar.sugar_base import (
    ConstructedTermSugar,
    require_constructed_term_sugar,
)
from sugar_source_tree.nodes import Call, IfExp, List
from sugar_source_tree.tree import SourceFile

_OWNERS = (
    "CallSiteSugar.args",
    "CallSiteSugar.keywords",
    "MethodCallSugar.args",
    "MethodCallSugar.keywords",
    "IfExpSugar.body",
    "IfExpSugar.orelse",
)


class _Site:
    def seal(self):
        return type(
            "S",
            (),
            {
                "source_cid": "blake3-512:" + "0" * 128,
                "start": 0,
                "end": 1,
                "cid": "blake3-512:" + "1" * 128,
            },
        )()


def _cid(source: str) -> str:
    return hashlib.sha256(source.encode("utf-8")).hexdigest()


def _sf(source: str, name: str = "t.py") -> SourceFile:
    return SourceFile((source, name, _cid(source)))


def test_spread_family_is_constructed_term_sugar() -> None:
    """Hierarchy law: spread mints are CTS, not bare Sugar."""
    for cls in (
        SpreadCollectionSugar,
        SpreadDictSugar,
        SpreadCallSugar,
        StarredSugar,
    ):
        assert issubclass(cls, ConstructedTermSugar), cls.__name__


def test_one_codomain_door_accepts_spread_and_starred() -> None:
    """require_constructed_term_sugar is the only admission door — all owners."""
    site = _Site()
    inner = IntLiteralSugar(value=1, site=site)
    starred = StarredSugar(value=inner, site=site)
    collection = SpreadCollectionSugar(
        kind="list",
        elements=((None, inner), ("python:starred", starred)),
        site=site,
    )
    for owner in _OWNERS:
        assert require_constructed_term_sugar(starred, owner=owner) is starred
        assert require_constructed_term_sugar(collection, owner=owner) is collection


def test_call_site_and_method_slots_construct_with_starred() -> None:
    """Slots construct without per-site isinstance special cases."""
    site = _Site()
    inner = IntLiteralSugar(value=2, site=site)
    starred = StarredSugar(value=inner, site=site)
    # CallSiteSugar.args / keywords
    CallSiteSugar(target_name="f", args=(starred,), site=site)
    CallSiteSugar(target_name="f", args=(), keywords=(("k", starred),), site=site)
    # MethodCallSugar.args / keywords
    MethodCallSugar(receiver=inner, name="m", args=(starred,), site=site)
    MethodCallSugar(
        receiver=inner, name="m", args=(), keywords=(("k", starred),), site=site
    )


def test_ifexp_arms_accept_spread_collection_via_construction() -> None:
    """Production tree: spread arm is CTS; IfExp constructs (one law at type)."""
    source = "x = [1, *xs] if flag else ys\n"
    sf = _sf(source, "ifexp_spread_l2a.py")
    node = next(n for n in sf.root.walk() if isinstance(n, IfExp))
    sugar = node.sugar()
    assert isinstance(sugar, IfExpSugar)
    assert isinstance(sugar.body, SpreadCollectionSugar)
    assert isinstance(sugar.body, ConstructedTermSugar)
    sugar.body.to_term(owner="l2a_ifexp_spread")


def test_starred_call_and_list_display_construct_as_terms() -> None:
    """Production: f(*xs) and [1, *xs] construct as CTS spread sugars."""
    call_src = "def f(*a): pass\ndef g(xs):\n    return f(*xs)\n"
    sf = _sf(call_src, "star_call_l2a.py")
    call = [n for n in sf.root.walk() if isinstance(n, Call)][-1]
    call_sugar = call.sugar()
    assert isinstance(call_sugar, SpreadCallSugar)
    assert isinstance(call_sugar, ConstructedTermSugar)
    call_sugar.to_term(owner="l2a_star_call")

    list_src = "y = [1, *xs]\n"
    sf2 = _sf(list_src, "list_star_l2a.py")
    for node in sf2.root.walk():
        if not isinstance(node, List):
            continue
        sugar = node.sugar()
        if isinstance(sugar, SpreadCollectionSugar):
            assert isinstance(sugar, ConstructedTermSugar)
            sugar.to_term(owner="l2a_list_star")
            return
    raise AssertionError("expected SpreadCollectionSugar for [1, *xs]")
