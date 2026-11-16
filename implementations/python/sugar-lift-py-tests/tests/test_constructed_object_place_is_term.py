"""An object state reads its assignment's key; AttributeSugar.receiver stays
ConstructedTermSugar.

``ConstructedObjectPlaceSugar`` (a value constructed at substitution, sealed
by its testimony) is deleted: the object reads its assignment's key (#7757
item 7), and a subscript key is decided by its ground value
(``ground_subscript_key``), never a value constructed at substitution.

AST-only tooth: full sugar imports hang in some agent shells (exit 143); the
law is source geometry.
"""

from __future__ import annotations

import ast

from sugar_lift_py_tests.repo_root import sugar_lift_py_tests_package_root

_KIT = sugar_lift_py_tests_package_root()
_ATTR = _KIT / "src" / "sugar_lift_py_tests" / "sugar" / "attribute_sugar.py"
_NODES = (
    _KIT.parent  # implementations/python
    / "sugar-source-tree"
    / "src"
    / "sugar_source_tree"
    / "nodes.py"
)


def test_attribute_receiver_still_requires_constructed_term() -> None:
    """Slot stays truthful — do not widen AttributeSugar.receiver."""
    tree = ast.parse(_ATTR.read_text(encoding="utf-8"))
    src = ast.dump(tree)
    assert "require_constructed_term_sugar" in src
    assert "AttributeSugar.receiver" in _ATTR.read_text(encoding="utf-8")


def _construct_sugar_returns(
    class_name: str, method: str = "_construct_sugar"
) -> set[str]:
    text = _NODES.read_text(encoding="utf-8")
    tree = ast.parse(text)
    cls = next(
        n
        for n in ast.walk(tree)
        if isinstance(n, ast.ClassDef) and n.name == class_name
    )
    construct = next(
        n
        for n in cls.body
        if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef))
        and n.name == method
    )
    returns: set[str] = set()
    for sub in ast.walk(construct):
        if isinstance(sub, ast.Return) and isinstance(sub.value, ast.Call):
            func = sub.value.func
            if isinstance(func, ast.Name):
                returns.add(func.id)
            elif isinstance(func, ast.Attribute):
                returns.add(func.attr)
    return returns


def test_no_value_constructed_at_substitution_is_a_node() -> None:
    """No node carries a value constructed at substitution: the projection
    class that did is deleted."""
    tree = ast.parse(_NODES.read_text(encoding="utf-8"))
    names = {n.name for n in ast.walk(tree) if isinstance(n, ast.ClassDef)}
    assert "ConstructedValueProjectionV1" not in names


def test_object_state_reads_its_assignment_key() -> None:
    """The object an assignment's call made (``OpaqueObjectStateV1``, the one
    object state whatever the callee, #7757) reads the value the call
    completed with at the assignment, through the assignment's key (#7757
    item 7): never a value constructed at substitution.  A read of the
    object folds every field store on it over that read
    (``ReceiverFieldStoreStateSugar``)."""
    construct = _construct_sugar_returns("OpaqueObjectStateV1")
    assert "EvaluationRefSugar" in construct, construct
    assert "ConstructedObjectPlaceSugar" not in construct, construct


def test_one_object_state() -> None:
    """The second object state, chosen by a second answer to what the callee
    denotes, is deleted (#7757 audit 4 L1)."""
    tree = ast.parse(_NODES.read_text(encoding="utf-8"))
    names = {n.name for n in ast.walk(tree) if isinstance(n, ast.ClassDef)}
    assert "ObjectPlaceStateV1" not in names
