"""IfExp + spread collection arm: ConstructedTerm, not TypeError / not SNW.

Product shapes like ``[a, *xs] if c else ys`` construct SpreadCollectionSugar
for an arm. SpreadCollectionSugar IS ConstructedTermSugar (to_term admitted) —
the same nested-construction testimony ListSugar owns without stars. #7074
refused with SugarNotWritten while to_term was missing; that was a temporary
membrane, not the type truth. Promotion deletes the SNW for this class.
"""

from __future__ import annotations

import hashlib

from sugar_lift_py_tests.sugar.if_exp_sugar import IfExpSugar
from sugar_lift_py_tests.sugar.spread_sugar import SpreadCollectionSugar
from sugar_lift_py_tests.sugar.sugar_base import ConstructedTermSugar
from sugar_source_tree.nodes import IfExp
from sugar_source_tree.tree import SourceFile


def _cid(source: str) -> str:
    return hashlib.sha256(source.encode("utf-8")).hexdigest()


def test_ifexp_spread_list_arm_constructs_as_constructed_term() -> None:
    """`[1, *xs] if flag else ys` constructs; no TypeError, no SNW."""
    source = "x = [1, *xs] if flag else ys\n"
    sf = SourceFile((source, "ifexp_spread.py", _cid(source)))
    node = next(n for n in sf.root.walk() if isinstance(n, IfExp))
    sugar = node.sugar()
    assert isinstance(sugar, IfExpSugar)
    assert isinstance(sugar.body, SpreadCollectionSugar)
    assert isinstance(sugar.body, ConstructedTermSugar)
    # to_term is the ConstructedTerm admission proof
    term = sugar.body.to_term(owner="test_ifexp_spread")
    assert term is not None


def test_ifexp_plain_arms_still_construct() -> None:
    """Ordinary IfExp arms remain ConstructedTermSugar and construct."""
    source = "x = a if flag else b\n"
    sf = SourceFile((source, "ifexp_plain.py", _cid(source)))
    node = next(n for n in sf.root.walk() if isinstance(n, IfExp))
    sugar = node.sugar()
    assert isinstance(sugar, IfExpSugar)
