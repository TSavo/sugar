"""Call surface: keyword actuals, starred actuals, default formals — construct.

Scope (black door): CallSite / MethodCall / SpreadCall + signature defaults.
Not value floors, not undecided attribution.

Triage: constructs already existed —
  - CallSiteSugar.keywords / MethodCallSugar.keywords (CTS pin L2a)
  - SpreadCallSugar for *args / **kwargs
  - ParamSugar for bare formals
Wrong entrance was Param with a default (or annotation) falling through to
``write more Sugar`` instead of folding the default expression into ParamSugar.
"""

from __future__ import annotations

from sugar_lift_py_tests.outcome import Complete
from sugar_lift_py_tests.sugar.call_site_sugar import CallSiteSugar
from sugar_lift_py_tests.sugar.int_literal_sugar import IntLiteralSugar
from sugar_lift_py_tests.sugar.method_call_sugar import MethodCallSugar
from sugar_lift_py_tests.sugar.param_sugar import ParamSugar
from sugar_lift_py_tests.sugar.spread_sugar import SpreadCallSugar
from sugar_lift_py_tests.sugar.sugar_base import ConstructedTermSugar
from sugar_lift_python_source.canonical import blake3_512_of
from sugar_source_tree.nodes import Call, FunctionDef, Param
from sugar_source_tree.tree import SourceFile


def _cid(source: str) -> str:
    return blake3_512_of(source.encode("utf-8"))


def _sf(source: str, name: str = "t.py") -> SourceFile:
    return SourceFile((source, name, _cid(source)))


def test_named_keyword_actual_constructs_on_call_site() -> None:
    """f(a=1) — keywords ride CallSiteSugar, values are ConstructedTermSugar."""
    call = next(
        n
        for n in _sf("def f(a):\n    return a\nf(a=1)\n", "kw.py").nodes()
        if isinstance(n, Call)
    )
    sugar = call.sugar()
    assert isinstance(sugar, CallSiteSugar)
    assert len(sugar.keywords) == 1
    name, value = sugar.keywords[0]
    assert name == "a"
    assert isinstance(value, ConstructedTermSugar)
    assert isinstance(value, IntLiteralSugar)
    assert isinstance(sugar.desugar(None), Complete)


def test_method_keyword_actual_constructs() -> None:
    """obj.m(x=2) — MethodCallSugar.keywords construct."""
    from sugar_source_tree.nodes import Attribute

    calls = [
        n
        for n in _sf(
            "class C:\n    def m(self, x=1):\n        return x\nC().m(x=2)\n",
            "method_kw.py",
        ).nodes()
        if isinstance(n, Call)
    ]
    method_call = next(
        c for c in calls if c.keywords and isinstance(c.func, Attribute)
    )
    sugar = method_call.sugar()
    assert isinstance(sugar, MethodCallSugar)
    assert sugar.keywords[0][0] == "x"
    assert isinstance(sugar.keywords[0][1], ConstructedTermSugar)
    assert isinstance(sugar.desugar(None), Complete)


def test_starred_positional_actual_constructs_spread_call() -> None:
    """f(*xs) — starred positional is SpreadCallSugar, not a bare gap."""
    from sugar_source_tree.nodes import Starred

    call = next(
        n
        for n in _sf(
            "def f(a, b):\n    return a\nxs = (1, 2)\nf(*xs)\n", "star_call.py"
        ).nodes()
        if isinstance(n, Call) and any(isinstance(a, Starred) for a in n.args)
    )
    sugar = call.sugar()
    assert isinstance(sugar, SpreadCallSugar)
    assert isinstance(sugar.desugar(None), Complete)


def test_double_star_keyword_actual_constructs_spread_call() -> None:
    """f(**d) — double-star keyword is SpreadCallSugar."""
    call = next(
        n
        for n in _sf(
            "def f(a=1):\n    return a\nd = {'a': 2}\nf(**d)\n", "dstar.py"
        ).nodes()
        if isinstance(n, Call) and any(kw.arg is None for kw in n.keywords)
    )
    sugar = call.sugar()
    assert isinstance(sugar, SpreadCallSugar)
    assert isinstance(sugar.desugar(None), Complete)


def test_param_with_default_constructs_param_sugar_not_gap() -> None:
    """def f(a=1): — Param.sugar is ParamSugar with CTS default, not SugarNotWritten."""
    param = next(
        n
        for n in _sf("def f(a=1):\n    return a\n", "default.py").nodes()
        if isinstance(n, Param) and n.default is not None
    )
    sugar = param.sugar()
    assert isinstance(sugar, ParamSugar)
    assert sugar.name == "a"
    assert sugar.default is not None
    assert isinstance(sugar.default, ConstructedTermSugar)
    assert isinstance(sugar.default, IntLiteralSugar)
    assert isinstance(sugar.desugar(None), Complete)


def test_param_with_annotation_only_still_constructs() -> None:
    """def f(a: int): — annotation must not refuse the formal."""
    param = next(
        n
        for n in _sf("def f(a: int):\n    return a\n", "ann.py").nodes()
        if isinstance(n, Param)
    )
    sugar = param.sugar()
    assert isinstance(sugar, ParamSugar)
    assert sugar.default is None


def test_frame_default_sugars_match_param_default_construction() -> None:
    """Source-visible frame and Param.sugar share the same default door."""
    tree = _sf("def f(a=1, b=2):\n    return a\n", "frame_defaults.py")
    function = next(n for n in tree.nodes() if isinstance(n, FunctionDef))
    frame = function.source_visible_call_frame()
    params = [n for n in tree.nodes() if isinstance(n, Param)]
    assert len(params) == 2
    for param, frame_default in zip(params, frame.default_sugars, strict=True):
        sugar = param.sugar()
        assert isinstance(sugar, ParamSugar)
        assert type(sugar.default) is type(frame_default)
        assert isinstance(sugar.default, ConstructedTermSugar)
