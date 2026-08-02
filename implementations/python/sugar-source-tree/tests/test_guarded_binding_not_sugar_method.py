"""GuardedBinding is a binding state, not a Node — never call .sugar() on it.

F class from black seal (6 files): AttributeError
  'GuardedBinding' object has no attribute 'sugar'

LiveForRuntimeV1 pre-state projection assumed every state was a Node.
``_construct_binding_projection`` already owns every binding-state species;
route through that door instead of ``state.sugar()``.
"""

from __future__ import annotations

from sugar_source_tree.binding_state import GuardedBinding, UnboundBinding
from sugar_source_tree.live_loop_construction import (
    _initial_value_sugar_for_loop_prestate,
)
from sugar_lift_py_tests.floor.branch_result_coordinate import BranchResultSlot


def test_guarded_binding_projects_without_sugar_method() -> None:
    slot = BranchResultSlot("test-slot")
    when_true = UnboundBinding("x", "then")
    when_false = UnboundBinding("x", "else")
    state = GuardedBinding(slot=slot, when_true=when_true, when_false=when_false)
    # Must not AttributeError
    sugar = _initial_value_sugar_for_loop_prestate(state)
    assert sugar is not None
    # Projection product, not a Node.sugar() result from GuardedBinding
    assert not hasattr(state, "sugar")
    assert type(sugar).__name__ == "GuardedProjection"


def test_unbound_binding_projects_without_sugar_method() -> None:
    state = UnboundBinding("x", "never-bound")
    sugar = _initial_value_sugar_for_loop_prestate(state)
    assert type(sugar).__name__ == "UnboundProjection"
