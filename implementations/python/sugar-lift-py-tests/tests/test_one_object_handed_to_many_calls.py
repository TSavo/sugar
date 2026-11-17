"""A reduction that exhausts the interpreter's stack is its owner's refusal
by name, never a file that fails to mint (#7757).

The pandas nine-step lane minted ``tests/frame/methods/test_info.py`` and
``tests/arrays/categorical/test_operators.py`` to ``maximum recursion depth
exceeded`` for the whole file: one function's reduction nested a frame per
state of an object handed to a few hundred calls.  That walk is now an
iterative fold (``nodes._construct_earlier_states``,
``ReceiverAfterCallSugar._prior_outcome``; its twins are in
``sugar-lift-python-source/tests/test_builtin_container_mutation.py``).
Where a reduction still runs out of stack, the owner is refused by name --
the one refusal the universe scan serves as the owner's refused member -- so
the rest of the file mints, as the roll call names a root whose construction
did (``roll_call.discharge``).
"""

from __future__ import annotations

import pytest


def _function(tmp_path):
    from sugar_lift_py_tests import tree_enumerate
    from sugar_lift_py_tests.lift_rpc import open_source_file_for_construction

    tree_enumerate._OWNER_REDUCTIONS.clear()
    producer = tmp_path / "producer.py"
    producer.write_text("def f():\n    return 1\n", encoding="utf-8")
    tree = open_source_file_for_construction(producer, root=tmp_path)
    (function,) = [item for item in tree.functions() if item.name == "f"]
    return function


def test_a_reduction_that_exhausts_the_stack_is_the_owners_refusal(
    tmp_path, monkeypatch
):
    """POSITIVE. Stack exhaustion reducing ``f`` is ``f``'s refusal by name,
    naming where ``f`` is."""
    from sugar_lift_py_tests import tree_enumerate
    from sugar_source_tree.panic import LifterRefusal, SugarNotWritten

    function = _function(tmp_path)

    def exhausted(owner):
        raise RecursionError("maximum recursion depth exceeded")

    monkeypatch.setattr(tree_enumerate, "function_universe_outcome", exhausted)
    with pytest.raises(SugarNotWritten) as refused:
        tree_enumerate.owner_reduction(function)
    assert isinstance(refused.value, LifterRefusal)
    assert refused.value.owner == "tree_enumerate.owner_reduction"
    assert "RecursionError" in refused.value.observed
    assert "producer.py:1:" in refused.value.observed


def test_any_other_failure_of_a_reduction_is_not_a_refusal(tmp_path, monkeypatch):
    """DISCRIMINATING. Only stack exhaustion is named as the owner's
    refusal; any other failure rises as it is, never dressed up as one."""
    from sugar_lift_py_tests import tree_enumerate
    from sugar_source_tree.panic import LifterRefusal

    function = _function(tmp_path)

    def broken(owner):
        raise ValueError("not a refusal")

    monkeypatch.setattr(tree_enumerate, "function_universe_outcome", broken)
    with pytest.raises(ValueError) as raised:
        tree_enumerate.owner_reduction(function)
    assert not isinstance(raised.value, LifterRefusal)
