"""CallSite / MethodCall codomain leftovers — receiver AND args, one term law.

Triage (Layer-0 discipline): construction already mints SpreadDictSugar,
ComprehensionSugar, IfExpSugar, BinOpSugar, … as ConstructedTermSugar. The
shared door is ``require_constructed_term_sugar`` (hierarchy, not species
tables). L2a/L2b pinned *args/keywords* and IfExp arms; **MethodCallSugar.receiver**
was never enrolled as an owner in those owner lists — so a regression that
refused SpreadDict / comprehension / IfExp only as *receivers* would not red.

This file pins the missing owner and production construction for both doors.
ONE law at the type: do not patch CallSiteSugar.args alone.
"""

from __future__ import annotations

import hashlib

from sugar_lift_py_tests.sugar.call_site_sugar import CallSiteSugar
from sugar_lift_py_tests.sugar.comprehension_sugar import ComprehensionSugar
from sugar_lift_py_tests.sugar.if_exp_sugar import IfExpSugar
from sugar_lift_py_tests.sugar.int_literal_sugar import IntLiteralSugar
from sugar_lift_py_tests.sugar.method_call_sugar import MethodCallSugar
from sugar_lift_py_tests.sugar.spread_sugar import (
    SpreadCollectionSugar,
    SpreadDictSugar,
)
from sugar_lift_py_tests.sugar.sugar_base import (
    ConstructedTermSugar,
    require_constructed_term_sugar,
)
from sugar_source_tree.nodes import Call
from sugar_source_tree.tree import SourceFile

# Owners that refuse nested construction testimony. Receiver is load-bearing:
# it was the hole after L2a/L2b only listed args/keywords.
_OWNERS = (
    "CallSiteSugar.args",
    "CallSiteSugar.keywords",
    "MethodCallSugar.args",
    "MethodCallSugar.keywords",
    "MethodCallSugar.receiver",
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


def _outer_call(source: str, name: str) -> Call:
    sf = _sf(source, name)
    calls = [n for n in sf.root.walk() if isinstance(n, Call)]
    assert calls, f"expected Call in {name}"
    return calls[-1]


def test_one_codomain_door_accepts_receiver_and_arg_shapes() -> None:
    """require_constructed_term_sugar admits spread / ifexp / int for every owner."""
    site = _Site()
    inner = IntLiteralSugar(value=1, site=site)
    # entries: (key-sugar-or-None, value-sugar); None key = **spread
    spread_dict = SpreadDictSugar(
        entries=((None, inner),),
        site=site,
    )
    for owner in _OWNERS:
        assert require_constructed_term_sugar(inner, owner=owner) is inner
        assert require_constructed_term_sugar(spread_dict, owner=owner) is spread_dict


def test_method_call_receiver_slot_constructs_with_spread_dict() -> None:
    """Direct slot: MethodCallSugar.receiver accepts SpreadDictSugar (CTS)."""
    site = _Site()
    inner = IntLiteralSugar(value=0, site=site)
    receiver = SpreadDictSugar(
        entries=((None, inner),),
        site=site,
    )
    assert isinstance(receiver, ConstructedTermSugar)
    MethodCallSugar(receiver=receiver, name="get", args=(inner,), site=site)


def test_production_method_receiver_spread_dict() -> None:
    """{**d}.get('k') — receiver is SpreadDictSugar, not a TypeError at the pin."""
    call = _outer_call(
        "def f(d):\n    return {**d}.get('k')\n",
        "method_recv_spreaddict.py",
    )
    sugar = call.sugar()
    assert isinstance(sugar, MethodCallSugar)
    assert isinstance(sugar.receiver, SpreadDictSugar)
    assert isinstance(sugar.receiver, ConstructedTermSugar)
    sugar.to_term(owner="method_recv_spreaddict")


def test_production_method_receiver_spread_list() -> None:
    """[1, *xs].count(1) — SpreadCollectionSugar as MethodCall receiver."""
    call = _outer_call(
        "def f(xs):\n    return [1, *xs].count(1)\n",
        "method_recv_spreadlist.py",
    )
    sugar = call.sugar()
    assert isinstance(sugar, MethodCallSugar)
    assert isinstance(sugar.receiver, SpreadCollectionSugar)
    assert isinstance(sugar.receiver, ConstructedTermSugar)
    sugar.to_term(owner="method_recv_spreadlist")


def test_production_method_receiver_ifexp() -> None:
    """(a if c else b).bit_length() — IfExpSugar as MethodCall receiver."""
    call = _outer_call(
        "def f(a, b, c):\n    return (a if c else b).bit_length()\n",
        "method_recv_ifexp.py",
    )
    sugar = call.sugar()
    assert isinstance(sugar, MethodCallSugar)
    assert isinstance(sugar.receiver, IfExpSugar)
    assert isinstance(sugar.receiver, ConstructedTermSugar)
    sugar.to_term(owner="method_recv_ifexp")


def test_production_method_receiver_listcomp() -> None:
    """[x for x in xs].count(1) — ComprehensionSugar as MethodCall receiver."""
    call = _outer_call(
        "def f(xs):\n    return [x for x in xs].count(1)\n",
        "method_recv_listcomp.py",
    )
    sugar = call.sugar()
    assert isinstance(sugar, MethodCallSugar)
    assert isinstance(sugar.receiver, ComprehensionSugar)
    assert isinstance(sugar.receiver, ConstructedTermSugar)
    sugar.to_term(owner="method_recv_listcomp")


def test_production_callsite_arg_ifexp_and_listcomp() -> None:
    """g(a if c else b) and g([x for x in xs]) — CallSiteSugar.args CTS."""
    call = _outer_call(
        "def f(a, b, c):\n    return g(a if c else b)\n",
        "call_arg_ifexp.py",
    )
    sugar = call.sugar()
    assert isinstance(sugar, CallSiteSugar)
    assert isinstance(sugar.args[0], IfExpSugar)
    assert isinstance(sugar.args[0], ConstructedTermSugar)
    sugar.to_term(owner="call_arg_ifexp")

    call2 = _outer_call(
        "def f(xs):\n    return g([x for x in xs])\n",
        "call_arg_listcomp.py",
    )
    sugar2 = call2.sugar()
    assert isinstance(sugar2, CallSiteSugar)
    assert isinstance(sugar2.args[0], ComprehensionSugar)
    assert isinstance(sugar2.args[0], ConstructedTermSugar)
    sugar2.to_term(owner="call_arg_listcomp")


def test_production_method_arg_ifexp_and_listcomp() -> None:
    """o.m(a if c else b) and o.m([x for x in xs]) — MethodCallSugar.args CTS."""
    call = _outer_call(
        "def f(o, a, b, c):\n    return o.m(a if c else b)\n",
        "method_arg_ifexp.py",
    )
    sugar = call.sugar()
    assert isinstance(sugar, MethodCallSugar)
    assert isinstance(sugar.args[0], IfExpSugar)
    sugar.to_term(owner="method_arg_ifexp")

    call2 = _outer_call(
        "def f(o, xs):\n    return o.m([x for x in xs])\n",
        "method_arg_listcomp.py",
    )
    sugar2 = call2.sugar()
    assert isinstance(sugar2, MethodCallSugar)
    assert isinstance(sugar2.args[0], ComprehensionSugar)
    sugar2.to_term(owner="method_arg_listcomp")
