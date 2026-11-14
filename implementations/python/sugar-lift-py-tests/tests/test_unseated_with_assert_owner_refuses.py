"""An unseated ``with`` before an assert refuses at its owner's construction.

#7757 entry 8.  A ``with`` whose manager nobody seated a row for does not
refuse during substitution (#7966 for ``as name``; ``as (a, b)`` here):
whether a row was seated is construction's question.  The owner's one
reduction (``owner_reduction``), which constructs the owner, refuses the
``with`` by name.  (The assert-locus rewrite this file also read,
``temporally_rewritten_assert``, fed only the universe seek by a call-site
cue, which had no driver and is deleted; #7757.)
"""

from __future__ import annotations

import pytest

NAME_TARGET = "def f(m):\n    with m as x:\n        pass\n    assert x == x\n"
TUPLE_TARGET = "def f(m):\n    with m as (a, b):\n        pass\n    assert a == b\n"


def _function(source: str):
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
    return function


@pytest.mark.parametrize("source", [NAME_TARGET, TUPLE_TARGET], ids=["name", "tuple"])
def test_the_owner_construction_refuses_the_unseated_with(
    source: str, monkeypatch
) -> None:
    from sugar_lift_py_tests import tree_enumerate
    from sugar_source_tree.panic import ContextManagerResolutionConstructionGap

    function = _function(source)
    monkeypatch.setattr(tree_enumerate, "_OWNER_REDUCTIONS", {})

    with pytest.raises(ContextManagerResolutionConstructionGap) as refused:
        tree_enumerate.owner_reduction(function)
    assert refused.value.owner == "With._construct_sugar"
