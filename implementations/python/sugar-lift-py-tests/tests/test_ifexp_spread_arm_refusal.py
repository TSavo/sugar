"""IfExp + spread collection arm: named gap, never raw TypeError.

Product shapes like ``[a, *xs] if c else ys`` construct SpreadCollectionSugar
for an arm. IfExpSugar requires ConstructedTermSugar for to_term. Until that
composition is written, the coordinate must refuse with SugarNotWritten —
not surprise the constructor with a TypeError.
"""

from __future__ import annotations

import hashlib

import pytest

from sugar_lift_py_tests.sugar.if_exp_sugar import IfExpSugar
from sugar_source_tree.nodes import IfExp
from sugar_source_tree.panic import SugarNotWritten
from sugar_source_tree.tree import SourceFile


def _cid(source: str) -> str:
    return hashlib.sha256(source.encode("utf-8")).hexdigest()


def test_ifexp_spread_list_arm_is_sugar_not_written_not_typeerror() -> None:
    """`[1, *xs] if flag else ys` must not raise TypeError at construction."""
    source = "x = [1, *xs] if flag else ys\n"
    sf = SourceFile((source, "ifexp_spread.py", _cid(source)))
    node = next(n for n in sf.root.walk() if isinstance(n, IfExp))
    with pytest.raises(SugarNotWritten) as caught:
        node.sugar()
    err = caught.value
    assert type(err).__name__ == "SugarNotWritten"
    observed = str(getattr(err, "observed", err))
    assert "SpreadCollectionSugar" in observed
    assert getattr(err, "owner", "") == "IfExp._construct_sugar"
    fix = str(getattr(err, "fix", ""))
    assert "TypeError" in fix or "ConstructedTermSugar" in fix


def test_ifexp_plain_arms_still_construct() -> None:
    """Ordinary IfExp arms remain ConstructedTermSugar and construct."""
    source = "x = a if flag else b\n"
    sf = SourceFile((source, "ifexp_plain.py", _cid(source)))
    node = next(n for n in sf.root.walk() if isinstance(n, IfExp))
    sugar = node.sugar()
    assert isinstance(sugar, IfExpSugar)
