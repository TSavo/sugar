"""GeneratorConstructionV1.to_term — producer-owned manager binding testimony.

ManagerBinding.to_facts() projects manager_value.to_term unchanged. Generator
managers must supply a content-addressed term from authenticated construction
and lifecycle state — never object identity, class spelling, or a fabricated
generic manager DTO.
"""

from __future__ import annotations

from sugar_lift_py_tests.generator_construction import (
    GeneratorConstructionV1,
    ReturnStepV1,
    YieldStepV1,
)
from sugar_lift_py_tests.ir import ctor, num, str_const
from sugar_lift_py_tests.outcome.resource_bindings import ManagerBinding


def _machine(
    *, allocation="call:m:1", frame="frame:m", binding=("bound:x",), steps=None
):
    if steps is None:
        steps = (YieldStepV1(num(7)), ReturnStepV1(num(9)))
    return GeneratorConstructionV1.allocate(
        allocation_coordinate=allocation,
        frame_coordinate=frame,
        binding_state=binding,
        steps=steps,
    )


def test_identical_construction_preimages_yield_identical_terms():
    left = _machine()
    right = _machine()
    assert left is not right
    assert left.to_term(owner="test") == right.to_term(owner="test")
    assert left.construction_term_cid() == right.construction_term_cid()


def test_changed_frame_coordinate_changes_term():
    left = _machine(frame="frame:a")
    right = _machine(frame="frame:b")
    assert left.to_term(owner="test") != right.to_term(owner="test")


def test_changed_allocation_coordinate_changes_term():
    left = _machine(allocation="call:a:1")
    right = _machine(allocation="call:b:1")
    assert left.to_term(owner="test") != right.to_term(owner="test")


def test_changed_binding_state_changes_term():
    left = _machine(binding=("bound:x",))
    right = _machine(binding=("bound:y",))
    assert left.to_term(owner="test") != right.to_term(owner="test")


def test_lifecycle_cursor_after_resume_changes_term():
    machine = _machine()
    before = machine.to_term(owner="test")
    yielded = machine.resume()
    after = yielded.machine.to_term(owner="test")
    assert before != after
    assert yielded.machine.cursor == 1


def test_lifecycle_suspended_resume_is_in_term_preimage():
    machine = _machine()
    yielded = machine.resume()
    preimage = yielded.machine.construction_term_preimage()
    assert preimage["cursor"] == 1
    assert preimage["suspendedResumeCoordinate"] == yielded.resume_coordinate
    assert preimage["instanceCoordinate"] == machine.instance_coordinate


def test_manager_binding_to_facts_carries_exact_generator_term():
    machine = _machine()
    facts = ManagerBinding(slot_id="M0", manager_value=machine).to_facts()
    assert len(facts) == 1
    formula = facts[0].formula
    # eq(manager_slot_value(M0), generator_term)
    assert formula.args[0] == ctor("manager_slot_value", [str_const("M0")])
    assert formula.args[1] == machine.to_term(owner="ManagerBinding")


def test_term_is_coordinate_not_object_identity_or_class_spelling():
    machine = _machine()
    term = machine.to_term(owner="test")
    assert term == ctor(
        "python:generator-construction",
        [str_const(machine.construction_term_cid())],
        symbol_kind="coordinate",
    )
    # Reject twins that would key on object identity or class name spelling.
    rendered = repr(term)
    assert str(id(machine)) not in rendered
    assert "GeneratorConstructionV1" not in rendered
    assert "option_context" not in rendered
    assert "contextmanager" not in rendered


def test_fabricated_generic_manager_term_is_not_the_generator_term():
    """Lying twin: a generic manager DTO cannot impersonate generator testimony."""
    machine = _machine()
    genuine = machine.to_term(owner="test")
    fabricated = ctor(
        "python:manager",
        [str_const(machine.instance_coordinate)],
        symbol_kind="coordinate",
    )
    assert genuine != fabricated
    facts = ManagerBinding(slot_id="M0", manager_value=machine).to_facts()
    assert facts[0].formula.args[1] != fabricated


def test_omitted_lifecycle_state_is_not_the_live_term():
    """Lying twin: instance coordinate alone omits cursor/suspension lifecycle."""
    machine = _machine().resume().machine
    live = machine.to_term(owner="test")
    omitted = ctor(
        "python:generator-construction",
        [str_const(machine.instance_coordinate)],
        symbol_kind="coordinate",
    )
    assert live != omitted


def test_ordinary_object_manager_to_term_unchanged():
    """Ordinary Floor managers still project through their own to_term."""
    from sugar_lift_py_tests.floor.object_value import ObjectValue

    obj = ObjectValue("Guard", (), (), (), "identity:guard")
    term = obj.to_term(owner="ManagerBinding")
    assert term == ctor(
        "py.object.identity",
        [str_const("Guard"), str_const("identity:guard")],
    )
    facts = ManagerBinding(slot_id="M1", manager_value=obj).to_facts()
    assert facts[0].formula.args[1] == term
