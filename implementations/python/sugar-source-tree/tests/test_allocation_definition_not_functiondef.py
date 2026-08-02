"""Allocation definitions are ClassDef only — never FunctionDef.

Regression: recursive Name-calls (def f: ... f(...)) used to make
``source_allocation_definition_for_call`` return the enclosing FunctionDef from
``function_nodes``. Callers then invoked ClassDef-only
``_authenticated_new_constructor_shape`` → AttributeError, blinding recensus
(instrument-defect) and factory_walk on real pandas (e.g. _normalize.py:267).
"""

from __future__ import annotations

from sugar_source_tree.nodes import Call, ClassDef, FunctionDef, Name
from sugar_source_tree.tree import SourceFile


def _source_file(source: str) -> SourceFile:
    from sugar_lift_python_source.canonical import blake3_512_of

    return SourceFile(
        (source, "allocation_fixture.py", blake3_512_of(source.encode("utf-8"))),
    )


def test_recursive_name_call_is_not_an_allocation_definition() -> None:
    """Recursive self-call must not resolve as a ClassDef allocation."""
    source = _source_file(
        "def f(n):\n"
        "    if n:\n"
        "        return f(n - 1)\n"
        "    return 0\n"
        "\n"
        "f(2)\n"
    )
    recursive_calls = [
        node
        for node in source.nodes()
        if isinstance(node, Call)
        and isinstance(node.func, Name)
        and node.func.id == "f"
    ]
    assert recursive_calls, "expected Name-call(s) to f"
    for call in recursive_calls:
        definition = call.unit.source_allocation_definition_for_call(call)
        assert definition is None, (
            f"allocation must not return FunctionDef for recursive call; "
            f"got {type(definition).__name__} "
            f"name={getattr(definition, 'name', None)!r}"
        )
        assert not isinstance(definition, FunctionDef)


def test_source_allocation_definition_never_returns_functiondef() -> None:
    """Codomain law: allocation door is ClassDef | None, never FunctionDef."""
    source = _source_file(
        "def helper(x):\n"
        "    return helper(x) if x else 0\n"
        "\n"
        "class Box:\n"
        "    def __init__(self, value):\n"
        "        self.value = value\n"
        "\n"
        "def outer():\n"
        "    return Box(1)\n"
        "\n"
        "helper(1)\n"
        "outer()\n"
        "Box(2)\n"
    )
    for call in (node for node in source.nodes() if isinstance(node, Call)):
        definition = call.unit.source_allocation_definition_for_call(call)
        assert definition is None or isinstance(definition, ClassDef)
        assert not isinstance(definition, FunctionDef)


def test_module_class_call_still_resolves_classdef_allocation() -> None:
    """Truthful twin: ordinary module ClassDef call remains authenticated."""
    source = _source_file(
        "class Box:\n"
        "    def __init__(self, value):\n"
        "        self.value = value\n"
        "\n"
        "Box(11)\n"
    )
    call = next(
        node
        for node in source.nodes()
        if isinstance(node, Call)
        and isinstance(node.func, Name)
        and node.func.id == "Box"
    )
    definition = call.unit.source_allocation_definition_for_call(call)
    assert isinstance(definition, ClassDef)
    assert definition.name == "Box"
    assert call.unit.source_class_has_authenticated_default_attribute_behavior(
        definition
    )


def test_recursive_name_call_sugar_does_not_raise_authenticated_new_shape() -> None:
    """Integration: Call.sugar on recursive Name-call must not AttributeError.

    This is the path recensus/factory_walk hit (Call.sugar|construction|...).
    Full Module.sugar may still be incomplete for other reasons; the forbidden
    signal is AttributeError: _authenticated_new_constructor_shape.
    """
    source = _source_file(
        "def f(n):\n"
        "    if n:\n"
        "        return f(n - 1)\n"
        "    return 0\n"
        "\n"
        "f(2)\n"
    )
    recursive_calls = [
        node
        for node in source.nodes()
        if isinstance(node, Call)
        and isinstance(node.func, Name)
        and node.func.id == "f"
    ]
    assert recursive_calls
    for call in recursive_calls:
        try:
            call.sugar()
        except AttributeError as exc:
            assert str(exc) != "_authenticated_new_constructor_shape", (
                "recursive Name-call must not trip ClassDef-only method on FunctionDef"
            )
            raise


def test_functiondef_is_not_authenticated_default_attribute_class() -> None:
    """Defense: source_class_has_* refuses non-ClassDef without AttributeError."""
    source = _source_file("def f():\n    return 1\n")
    function = next(node for node in source.nodes() if isinstance(node, FunctionDef))
    # Would AttributeError before the isinstance guard.
    assert (
        function.unit.source_class_has_authenticated_default_attribute_behavior(
            function  # type: ignore[arg-type]
        )
        is False
    )
