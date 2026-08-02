"""Spread/Complex/Ellipsis are ConstructedTermSugar — roster not zero-banked.

122 of 169 seal backend-defects (black checkpoint) were one type-system class:
parent slots require ConstructedTermSugar; Spread/Complex/Ellipsis were only
Sugar. One ``f(*xs)`` / ``g([*xs])`` / ``1+2j`` / ``x[..., :]`` TypeError
aborted sugar.enumerate for the whole file → functionsTotal=0.

Truth: those sugars ARE nested-construction testimony (same as List/None
literals). Promote + to_term; slots were never over-narrow.

Tooth (no stopwatch): a multi-function file containing a spread call arg
enumerates its FULL roster; construction does not TypeError; the spread
site is a constructed term (named, not a silent zero bank).

Part 2 (file-level zero-bank for OTHER failures) is black's restore of the
retired _measure_file law — not duplicated here.
"""

from __future__ import annotations

import hashlib
import sys
from pathlib import Path

from sugar_lift_py_tests.sugar.complex_literal_sugar import ComplexLiteralSugar
from sugar_lift_py_tests.sugar.ellipsis_literal_sugar import EllipsisLiteralSugar
from sugar_lift_py_tests.sugar.spread_sugar import (
    SpreadCallSugar,
    SpreadCollectionSugar,
    SpreadDictSugar,
)
from sugar_lift_py_tests.sugar.sugar_base import ConstructedTermSugar
from sugar_source_tree.nodes import BinOp, Call, List, Subscript
from sugar_source_tree.tree import SourceFile

_SCRIPTS = Path(__file__).resolve().parents[1] / "scripts"
if str(_SCRIPTS) not in sys.path:
    sys.path.insert(0, str(_SCRIPTS))


def _cid(source: str) -> str:
    return hashlib.sha256(source.encode("utf-8")).hexdigest()


def _sf(source: str, name: str = "t.py") -> SourceFile:
    return SourceFile((source, name, _cid(source)))


def test_spread_complex_ellipsis_are_constructed_term_sugar() -> None:
    assert issubclass(SpreadCollectionSugar, ConstructedTermSugar)
    assert issubclass(SpreadDictSugar, ConstructedTermSugar)
    assert issubclass(ComplexLiteralSugar, ConstructedTermSugar)
    assert issubclass(EllipsisLiteralSugar, ConstructedTermSugar)


def test_starred_call_constructs_spread_call_sugar_not_typeerror() -> None:
    """``f(*xs)`` uses SpreadCallSugar (already ConstructedTerm)."""
    source = "def f(*a): pass\ndef g(xs):\n    return f(*xs)\n"
    sf = _sf(source, "star_call.py")
    calls = [n for n in sf.root.walk() if isinstance(n, Call)]
    assert calls, "expected at least one Call"
    # The call inside g
    sugar = calls[-1].sugar()
    assert isinstance(sugar, SpreadCallSugar)
    assert isinstance(sugar, ConstructedTermSugar)
    sugar.to_term(owner="test_starred_call")


def test_list_with_star_is_constructed_term() -> None:
    """``[1, *xs]`` is SpreadCollectionSugar and admits to_term (was slot TypeError)."""
    source = "y = [1, *xs]\n"
    sf = _sf(source, "list_star.py")
    list_sugar = None
    for node in sf.root.walk():
        if not isinstance(node, List):
            continue
        sugar = node.sugar()
        if isinstance(sugar, SpreadCollectionSugar):
            list_sugar = sugar
            break
    assert list_sugar is not None
    assert isinstance(list_sugar, ConstructedTermSugar)
    list_sugar.to_term(owner="test_list_star")


def test_complex_literal_is_constructed_term_in_binop() -> None:
    """``1 + 2j`` — BinOpSugar.right TypeError class from the 169."""
    source = "def g():\n    return 1 + 2j\n"
    sf = _sf(source, "complex_binop.py")
    binops = [n for n in sf.root.walk() if isinstance(n, BinOp)]
    assert binops
    sugar = binops[0].sugar()
    assert isinstance(sugar, ConstructedTermSugar)
    # right arm is the complex
    assert isinstance(sugar.right, ComplexLiteralSugar)
    sugar.right.to_term(owner="test_complex")


def test_ellipsis_literal_is_constructed_term_in_subscript() -> None:
    """``x[..., :]`` — SubscriptSugar.index TypeError class from the 169."""
    source = "def g(x):\n    return x[..., :]\n"
    sf = _sf(source, "ellipsis_sub.py")
    # Constant ... nodes
    constants = [
        n
        for n in sf.root.walk()
        if isinstance(n, Constant) and n.value is Ellipsis
    ]
    # Prefer constructing via subscript which owns the index
    subs = [n for n in sf.root.walk() if isinstance(n, Subscript)]
    assert subs
    sugar = subs[0].sugar()
    assert isinstance(sugar, ConstructedTermSugar)


def test_multi_function_file_with_star_call_enumerates_full_roster() -> None:
    """THE tooth: spread site does not zero-bank the file's function roster.

    Two functions; one uses ``f(*xs)``. D2 functionsTotal must be 2, not 0.
    Construction TypeError of the old class is forbidden.
    """
    from recensus_enumerate_consumer import measure_file_via_enumerate

    root = Path(__file__).resolve().parents[0]  # unused; use tmp via SourceTree walk
    # Build a tiny workspace on disk for enumerate (path_source / SourceTree).
    import tempfile

    with tempfile.TemporaryDirectory() as td:
        workspace = Path(td)
        path = workspace / "mod.py"
        path.write_text(
            "def helper(*a):\n"
            "    return a\n"
            "def body(xs):\n"
            "    return helper(*xs)\n"
            "def other():\n"
            "    return 1\n",
            encoding="utf-8",
        )
        row = measure_file_via_enumerate(
            workspace_root=workspace,
            file_rel="mod.py",
        )
    assert row.get("category") != "backend-defect", (
        f"spread call zero-banked the file: {row.get('defect') or row}"
    )
    # Full roster: helper, body, other
    assert int(row.get("functionsTotal") or 0) == 3, (
        f"expected functionsTotal=3 (full roster), got {row!r}"
    )
    # Not a TypeError residual dressed as clean zero
    defect_msg = str((row.get("defect") or {}).get("message") or "")
    assert "ConstructedTermSugar" not in defect_msg
    assert "TypeError" not in defect_msg or row.get("category") == "completed"
