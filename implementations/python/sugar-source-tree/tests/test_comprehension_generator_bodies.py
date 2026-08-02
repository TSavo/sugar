"""Comprehension / generator bodies: call existing ComprehensionSugar + NamedExprSugar.

Triage: ComprehensionSugar and NamedExprSugar already construct. ListComp (and
siblings) short-circuited on NamedExpr and fell to Node default. This door owns
reaching those sugars for list/set/dict/generator bodies.
"""

from __future__ import annotations

from sugar_lift_python_source.canonical import cid_of_json
from sugar_lift_py_tests.sugar.comprehension_sugar import ComprehensionSugar
from sugar_lift_py_tests.sugar.named_expr_sugar import NamedExprSugar
from sugar_source_tree.nodes import DictComp, GeneratorExp, ListComp, SetComp
from sugar_source_tree.tree import SourceFile


def _nodes(src: str, seat: str):
    cid = cid_of_json({"source": src, "seat": seat})
    return SourceFile((src, seat, cid))


def test_listcomp_body_constructs() -> None:
    src = "def f(xs):\n    return [x + 1 for x in xs]\n"
    sugar = next(n for n in _nodes(src, "lc.py").nodes() if isinstance(n, ListComp)).sugar()
    assert isinstance(sugar, ComprehensionSugar)
    assert sugar.kind == "py.listcomp"


def test_setcomp_body_constructs() -> None:
    src = "def f(xs):\n    return {x for x in xs}\n"
    sugar = next(n for n in _nodes(src, "sc.py").nodes() if isinstance(n, SetComp)).sugar()
    assert isinstance(sugar, ComprehensionSugar)
    assert sugar.kind == "py.setcomp"


def test_dictcomp_body_constructs() -> None:
    src = "def f(xs):\n    return {x: x for x in xs}\n"
    sugar = next(n for n in _nodes(src, "dc.py").nodes() if isinstance(n, DictComp)).sugar()
    assert isinstance(sugar, ComprehensionSugar)
    assert sugar.kind == "py.dictcomp"


def test_generatorexp_body_constructs() -> None:
    src = "def f(xs):\n    return (x for x in xs)\n"
    sugar = next(
        n for n in _nodes(src, "ge.py").nodes() if isinstance(n, GeneratorExp)
    ).sugar()
    assert isinstance(sugar, ComprehensionSugar)
    assert sugar.kind == "py.generatorexp"


def test_listcomp_filter_walrus_reaches_named_expr_sugar() -> None:
    """NamedExprSugar already exists — comprehension must call it."""
    src = "def f(xs):\n    return [y for x in xs if (y := x)]\n"
    sugar = next(n for n in _nodes(src, "w.py").nodes() if isinstance(n, ListComp)).sugar()
    assert isinstance(sugar, ComprehensionSugar)
    assert isinstance(sugar.generators[0].filters[0], NamedExprSugar)
    assert sugar.generators[0].filters[0].name == "y"


def test_listcomp_element_walrus_reaches_named_expr_sugar() -> None:
    src = "def f(xs):\n    return [(y := x) for x in xs]\n"
    sugar = next(n for n in _nodes(src, "we.py").nodes() if isinstance(n, ListComp)).sugar()
    assert isinstance(sugar, ComprehensionSugar)
    assert isinstance(sugar.element, NamedExprSugar)


def test_nested_generator_body_constructs() -> None:
    src = "def f(xss):\n    return [y for xs in xss for y in xs]\n"
    sugar = next(n for n in _nodes(src, "ng.py").nodes() if isinstance(n, ListComp)).sugar()
    assert isinstance(sugar, ComprehensionSugar)
    assert len(sugar.generators) == 2
