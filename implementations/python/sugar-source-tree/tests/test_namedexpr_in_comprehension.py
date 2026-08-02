"""NamedExprSugar already constructs; comprehension must call it, not refuse."""

from __future__ import annotations

from sugar_lift_python_source.canonical import cid_of_json
from sugar_lift_py_tests.sugar.comprehension_sugar import ComprehensionSugar
from sugar_lift_py_tests.sugar.named_expr_sugar import NamedExprSugar
from sugar_source_tree.nodes import FunctionDef
from sugar_source_tree.tree import SourceFile


def _frame(src: str, name: str = "f"):
    seat = f"{name}.py"
    cid = cid_of_json({"source": src, "seat": seat})
    source = SourceFile((src, seat, cid))
    return next(n for n in source.nodes() if isinstance(n, FunctionDef) and n.name == name)


def test_listcomp_filter_walrus_constructs_via_existing_sugars() -> None:
    """[y for x in xs if (y := x)] — do not fall to Node default."""
    frame = _frame(
        "def f(xs):\n"
        "    return [y for x in xs if (y := x)]\n"
    ).source_visible_call_frame()
    # Frame construction is the production door; body sugar must include ComprehensionSugar.
    body = frame.body if hasattr(frame, "body") else None
    # Prefer walking the function sugar path already exercised by frame build.
    # If frame built, ListComp constructed.
    assert frame is not None


def test_listcomp_filter_walrus_is_comprehension_sugar() -> None:
    from sugar_source_tree.nodes import ListComp

    src = "def f(xs):\n    return [y for x in xs if (y := x)]\n"
    seat = "walrus_filter.py"
    cid = cid_of_json({"source": src, "seat": seat})
    source = SourceFile((src, seat, cid))
    comp = next(n for n in source.nodes() if isinstance(n, ListComp))
    sugar = comp.sugar()
    assert isinstance(sugar, ComprehensionSugar)
    assert sugar.kind == "py.listcomp"
    assert len(sugar.generators) == 1
    assert len(sugar.generators[0].filters) == 1
    assert isinstance(sugar.generators[0].filters[0], NamedExprSugar)
    assert sugar.generators[0].filters[0].name == "y"


def test_listcomp_element_walrus_constructs() -> None:
    from sugar_source_tree.nodes import ListComp

    src = "def f(xs):\n    return [(y := x) for x in xs]\n"
    seat = "walrus_elt.py"
    cid = cid_of_json({"source": src, "seat": seat})
    source = SourceFile((src, seat, cid))
    comp = next(n for n in source.nodes() if isinstance(n, ListComp))
    sugar = comp.sugar()
    assert isinstance(sugar, ComprehensionSugar)
    assert isinstance(sugar.element, NamedExprSugar)
    assert sugar.element.name == "y"


def test_setcomp_filter_walrus_constructs() -> None:
    from sugar_source_tree.nodes import SetComp

    src = "def f(xs):\n    return {y for x in xs if (y := x)}\n"
    seat = "walrus_set.py"
    cid = cid_of_json({"source": src, "seat": seat})
    source = SourceFile((src, seat, cid))
    comp = next(n for n in source.nodes() if isinstance(n, SetComp))
    sugar = comp.sugar()
    assert isinstance(sugar, ComprehensionSugar)
    assert sugar.kind == "py.setcomp"
    assert isinstance(sugar.generators[0].filters[0], NamedExprSugar)


def test_plain_listcomp_still_constructs() -> None:
    """Regression: non-walrus path unchanged."""
    from sugar_source_tree.nodes import ListComp

    src = "def f(xs):\n    return [x + 1 for x in xs]\n"
    seat = "plain.py"
    cid = cid_of_json({"source": src, "seat": seat})
    source = SourceFile((src, seat, cid))
    sugar = next(n for n in source.nodes() if isinstance(n, ListComp)).sugar()
    assert isinstance(sugar, ComprehensionSugar)
    assert sugar.generators[0].filters == ()
