"""An unseated ``with`` before an assert refuses at its owner's construction.

#7757 entry 8.  ``temporally_rewritten_assert`` substitutes an assert's owner
without constructing it.  A ``with`` whose manager nobody seated a row for no
longer refuses during substitution (#7966 for ``as name``; ``as (a, b)`` here):
whether a row was seated is construction's question.  So the assert's calls
can still be read, and the owner's one reduction (``owner_reduction``), which
constructs the owner, refuses the ``with`` by name.
"""

from __future__ import annotations

import pytest

NAME_TARGET = "def f(m):\n    with m as x:\n        pass\n    assert x == x\n"
TUPLE_TARGET = "def f(m):\n    with m as (a, b):\n        pass\n    assert a == b\n"


def _tree(source: str):
    from sugar_lift_python_source.canonical import blake3_512_of
    from sugar_lift_py_tests.context_manager_resolution import (
        TreeConstructionContextV1,
    )
    from sugar_source_tree import nodes
    from sugar_source_tree.tree import SourceFile

    # No contract row is seated for any manager.
    tree = SourceFile(
        (source, "unseated_with_assert_owner.py", blake3_512_of(source.encode())),
        construction_context=TreeConstructionContextV1.for_source_call_construction(),
    )
    (function,) = tuple(
        node for node in tree.nodes() if isinstance(node, nodes.FunctionDef)
    )
    (source_assert,) = tuple(
        node for node in tree.nodes() if isinstance(node, nodes.Assert)
    )
    lc = source_assert.line_col_span()
    return tree, function, {"start_line": lc.start_line, "start_col": lc.start_col}


@pytest.mark.parametrize("source", [NAME_TARGET, TUPLE_TARGET], ids=["name", "tuple"])
def test_the_assert_is_read_and_its_owner_construction_refuses(
    source: str, monkeypatch
) -> None:
    from sugar_lift_py_tests import tree_enumerate
    from sugar_source_tree import nodes
    from sugar_source_tree.panic import ContextManagerResolutionConstructionGap

    tree, function, span = _tree(source)
    monkeypatch.setattr(tree_enumerate, "_OWNER_REDUCTIONS", {})

    # Substitution alone does not ask the require door.
    _source, rewritten = tree_enumerate.temporally_rewritten_assert(tree, span)
    assert isinstance(rewritten, nodes.Assert)

    # The owner's construction does, and refuses by name.
    with pytest.raises(ContextManagerResolutionConstructionGap) as refused:
        tree_enumerate.owner_reduction(function)
    assert refused.value.owner == "With._construct_sugar"
