"""A recursive call is never read as an allocation of a class.

Regression: recursive Name-calls (def f: ... f(...)) used to make the
allocation resolver return the enclosing FunctionDef. Callers then invoked a
ClassDef-only method (the ``__new__`` allocation-shape probe, since deleted)
-> AttributeError, blinding recensus (instrument-defect) and factory_walk on
real pandas (e.g. _normalize.py:267). The allocation resolver itself is
deleted (#7757): an assignment of a call is one object state whatever the
callee, so nothing asks it.
"""

from __future__ import annotations

from sugar_source_tree.nodes import Call, FunctionDef, Name
from sugar_lift_py_tests.context_manager_resolution import TreeConstructionContextV1
from sugar_source_tree.tree import SourceFile


def _source_file(source: str) -> SourceFile:
    from sugar_lift_python_source.canonical import blake3_512_of

    return SourceFile(
        (source, "allocation_fixture.py", blake3_512_of(source.encode("utf-8"))), construction_context=TreeConstructionContextV1.for_test_without_workspace()
    )


def test_recursive_name_call_sugar_does_not_raise_attribute_error() -> None:
    """Integration: Call.sugar on recursive Name-call must not AttributeError.

    This is the path recensus/factory_walk hit (Call.sugar|construction|...).
    Full Module.sugar may still be incomplete for other reasons; the forbidden
    signal is an AttributeError from a ClassDef-only method reached on a
    FunctionDef (the ``__new__`` allocation-shape probe this was written
    against is gone, #7757 A4).
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
            raise AssertionError(
                "recursive Name-call must not trip a ClassDef-only method on "
                f"FunctionDef: {exc}"
            ) from exc


def test_functiondef_is_not_a_plain_source_class_body() -> None:
    """Defense: the one class-body rule refuses non-ClassDef without
    AttributeError (the default-attribute rule it subsumed is deleted)."""
    source = _source_file("def f():\n    return 1\n")
    function = next(node for node in source.nodes() if isinstance(node, FunctionDef))
    # Would AttributeError before the isinstance guard.
    assert (
        function.unit.source_class_has_plain_source_body(
            function  # type: ignore[arg-type]
        )
        is False
    )
