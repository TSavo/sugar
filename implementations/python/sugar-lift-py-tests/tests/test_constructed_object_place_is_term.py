"""ConstructedObjectPlaceSugar IS ConstructedTermSugar — AttributeSugar.receiver.

Sealed board (fifth hierarchy lie, dynamic discharge):
  tests/frame/test_arithmetic.py
  RuntimeError: AttributeSugar.receiver requires ConstructedTermSugar,
  got ConstructedObjectPlaceSugar

Same class as the 122: construction produces a type the ConstructedTerm slot
refuses. Static codomain law reported R=0 because ObjectPlace was Sugar-not-term
— a DYNAMIC path the isinstance-family scan could not see as a sibling gap
once require_constructed_term_sugar already accepts the base.

Judgment (parallel #7099): AttributeSugar.receiver requiring ConstructedTermSugar
is truthful. An object place projects authenticated construction testimony of an
object — same ontology as ConstructedReceiverRefSugar. Promote the mint class;
do not widen the slot.

AST-only tooth: full sugar imports hang in some agent shells (exit 143); the
hierarchy law is source geometry — base class + to_term — and the instrument
self-test plants the pre-promote shape red then green after promote.
"""

from __future__ import annotations

import ast
from pathlib import Path

from sugar_lift_py_tests.repo_root import sugar_lift_py_tests_package_root

_KIT = sugar_lift_py_tests_package_root()
_PLACE = (
    _KIT / "src" / "sugar_lift_py_tests" / "sugar" / "constructed_object_place_sugar.py"
)
_ATTR = _KIT / "src" / "sugar_lift_py_tests" / "sugar" / "attribute_sugar.py"
_NODES = (
    _KIT.parent  # implementations/python
    / "sugar-source-tree"
    / "src"
    / "sugar_source_tree"
    / "nodes.py"
)


def _base_names(cls: ast.ClassDef) -> set[str]:
    names: set[str] = set()
    for b in cls.bases:
        if isinstance(b, ast.Name):
            names.add(b.id)
        elif isinstance(b, ast.Attribute):
            names.add(b.attr)
    return names


def test_constructed_object_place_bases_constructed_term_sugar() -> None:
    """Promote geometry: class extends ConstructedTermSugar (not bare Sugar)."""
    tree = ast.parse(_PLACE.read_text(encoding="utf-8"))
    cls = next(
        n
        for n in tree.body
        if isinstance(n, ast.ClassDef) and n.name == "ConstructedObjectPlaceSugar"
    )
    bases = _base_names(cls)
    assert "ConstructedTermSugar" in bases, bases
    assert "Sugar" not in bases or "ConstructedTermSugar" in bases
    methods = {
        n.name
        for n in cls.body
        if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef))
    }
    assert "to_term" in methods, methods
    assert "desugar" in methods, methods


def test_attribute_receiver_still_requires_constructed_term() -> None:
    """Slot stays truthful — do not widen AttributeSugar.receiver."""
    tree = ast.parse(_ATTR.read_text(encoding="utf-8"))
    src = ast.dump(tree)
    assert "require_constructed_term_sugar" in src
    assert "AttributeSugar.receiver" in _ATTR.read_text(encoding="utf-8")


def test_object_place_state_still_mints_promoted_class() -> None:
    """ObjectPlaceStateV1._construct_sugar still returns ConstructedObjectPlaceSugar."""
    text = _NODES.read_text(encoding="utf-8")
    tree = ast.parse(text)
    cls = next(
        n
        for n in ast.walk(tree)
        if isinstance(n, ast.ClassDef) and n.name == "ObjectPlaceStateV1"
    )
    construct = next(
        n
        for n in cls.body
        if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef))
        and n.name == "_construct_sugar"
    )
    returns: set[str] = set()
    for sub in ast.walk(construct):
        if isinstance(sub, ast.Return) and isinstance(sub.value, ast.Call):
            func = sub.value.func
            if isinstance(func, ast.Name):
                returns.add(func.id)
            elif isinstance(func, ast.Attribute):
                returns.add(func.attr)
    assert "ConstructedObjectPlaceSugar" in returns, returns
