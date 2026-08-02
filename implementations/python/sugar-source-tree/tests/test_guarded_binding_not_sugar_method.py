"""L3c: GuardedBinding projection is the door — .sugar() must use it.

Was AttributeError: 'GuardedBinding' object has no attribute 'sugar' when a
caller treated binding state as a Node. Projection already existed as
``_construct_binding_projection`` / GuardedProjection; the door was not on
the state itself. Route .sugar() through that door (orange: fix the door, not
every call site).
"""

from __future__ import annotations

from sugar_lift_py_tests.floor.branch_result_coordinate import BranchResultSlot
from sugar_source_tree.binding_state import (
    GuardedBinding,
    UnboundBinding,
    _project_binding_state_sugar,
)
from sugar_source_tree.live_loop_construction import (
    _initial_value_sugar_for_loop_prestate,
)
from sugar_source_tree.nodes import _construct_binding_projection


def test_guarded_binding_sugar_routes_to_projection_door() -> None:
    slot = BranchResultSlot("test-slot")
    when_true = UnboundBinding("x", "then")
    when_false = UnboundBinding("x", "else")
    state = GuardedBinding(slot=slot, when_true=when_true, when_false=when_false)

    # Wrong-kind call that used to AttributeError:
    sugar = state.sugar()
    assert type(sugar).__name__ == "GuardedProjection"

    # Same door as the explicit projection path and loop prestate helper:
    assert type(_construct_binding_projection(state)).__name__ == "GuardedProjection"
    assert type(_project_binding_state_sugar(state)).__name__ == "GuardedProjection"
    assert type(_initial_value_sugar_for_loop_prestate(state)).__name__ == "GuardedProjection"


def test_unbound_binding_sugar_routes_to_projection_door() -> None:
    state = UnboundBinding("x", "never-bound")
    sugar = state.sugar()
    assert type(sugar).__name__ == "UnboundProjection"
    assert type(_initial_value_sugar_for_loop_prestate(state)).__name__ == "UnboundProjection"


def test_nested_guarded_binding_projects_recursively() -> None:
    """Guarded arms may themselves be GuardedBinding — door recurses."""
    outer = BranchResultSlot("outer")
    inner = BranchResultSlot("inner")
    leaf_t = UnboundBinding("x", "tt")
    leaf_f = UnboundBinding("x", "tf")
    nested = GuardedBinding(slot=inner, when_true=leaf_t, when_false=leaf_f)
    state = GuardedBinding(
        slot=outer,
        when_true=nested,
        when_false=UnboundBinding("x", "f"),
    )
    sugar = state.sugar()
    assert type(sugar).__name__ == "GuardedProjection"
    # Outer when_true is itself a GuardedProjection
    assert type(sugar.when_true).__name__ == "GuardedProjection"
