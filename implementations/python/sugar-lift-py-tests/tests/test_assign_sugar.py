"""AssignSugar is a statement sugar: it composes its RHS and binds the target name
into block scope, so LATER statements resolve it. The block threads the binding; a
comment never disturbs it."""
from __future__ import annotations

from factory_reduce import compose_block

from sugar_lift_py_tests.floor import BlockValue, ReturnValue, TermValue


def test_assign_binds_a_name_resolved_by_a_later_return():
    # y = 5; return y -> the return resolves y to 5 via the threaded binding.
    assert compose_block("    y = 5\n    return y\n") == BlockValue(
        (ReturnValue(TermValue(5)),)
    )


def test_comment_then_assign_then_return():
    assert compose_block('    "doc"\n    y = 5\n    return y\n') == BlockValue(
        (ReturnValue(TermValue(5)),)
    )


def test_assign_with_no_later_use_is_a_scope_only_block():
    # a block of just a binding has no return outcome -- the binding is scope-local.
    assert compose_block("    y = 5\n") == BlockValue(())
