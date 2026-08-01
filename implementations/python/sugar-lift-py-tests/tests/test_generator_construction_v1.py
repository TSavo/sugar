import importlib.util

from sugar_lift_py_tests.effect import RaiseEffect
from sugar_lift_py_tests.ir import num
from sugar_lift_py_tests.outcome import Halted


def _api():
    from sugar_lift_py_tests import generator_construction

    return generator_construction


def _machine(*steps):
    return _api().GeneratorConstructionV1.allocate(
        allocation_coordinate="call:renamed_manager:1",
        frame_coordinate="frame:renamed_manager",
        binding_state=("bound:x",),
        steps=steps,
    )


def test_call_allocates_suspended_machine_and_resume_yields_exact_value():
    api = _api()
    machine = _machine(api.YieldStepV1(num(7)), api.ReturnStepV1(num(9)))

    assert machine.binding_state == ("bound:x",)
    yielded = machine.resume()

    assert isinstance(yielded, api.YieldEffect)
    assert yielded.value == num(7)
    assert yielded.resume_coordinate == f"{machine.instance_coordinate}:resume:1"


def test_send_continues_from_the_same_resume_coordinate_to_termination():
    api = _api()
    yielded = _machine(api.YieldStepV1(num(7)), api.ReturnStepV1(num(9))).resume()

    terminated = yielded.machine.send(num(11))

    assert isinstance(terminated, api.GeneratorTerminationV1)
    assert terminated.return_value == num(9)
    assert terminated.binding_state[-1].resume_value == num(11)


def test_throw_routes_the_exact_incoming_effect_as_a_halted_face():
    api = _api()
    yielded = _machine(api.YieldStepV1(num(7)), api.ReturnStepV1(num(9))).resume()
    incoming = RaiseEffect.for_builtin("RenamedError", occurrence="body:3")

    exits = yielded.machine.throw(incoming)

    assert len(exits.exits) == 1
    assert isinstance(exits.exits[0], Halted)
    assert exits.exits[0].effect is incoming


def test_close_terminates_the_suspended_machine_without_fabricated_return():
    api = _api()
    yielded = _machine(api.YieldStepV1(num(7)), api.ReturnStepV1(num(9))).resume()

    terminated = yielded.machine.close()

    assert isinstance(terminated, api.GeneratorTerminationV1)
    assert terminated.return_value is None


def test_opaque_transition_is_typed_loud():
    api = _api()
    gap = _machine(
        api.OpaqueStepV1("try-star"),
    ).resume()

    assert isinstance(gap, api.GeneratorTransitionGapV1)
    assert gap.observed == "try-star"
    assert gap.requested == "resume"


def test_instance_coordinate_depends_on_allocation_frame_and_binding_state():
    api = _api()
    left = _machine(api.YieldStepV1(num(7)))
    renamed_same = _machine(api.YieldStepV1(num(7)))
    other = api.GeneratorConstructionV1.allocate(
        allocation_coordinate="call:other:1",
        frame_coordinate="frame:renamed_manager",
        binding_state=("bound:x",),
        steps=(api.YieldStepV1(num(7)),),
    )

    assert left.instance_coordinate == renamed_same.instance_coordinate
    assert left.instance_coordinate != other.instance_coordinate


def test_generator_construction_module_is_the_named_replacement_shape():
    assert importlib.util.find_spec("sugar_lift_py_tests.generator_construction")


def test_throw_runs_constructed_finally_and_restores_exact_incoming_effect():
    api = _api()
    from sugar_lift_py_tests.sugar.inert_sugar import InertSugar

    yielded = _machine(
        api.YieldStepV1(num(7)),
        api.FinallyStepV1((InertSugar(site="cleanup"),)),
        api.ReturnStepV1(),
    ).resume()
    incoming = RaiseEffect.for_builtin("RenamedError", occurrence="body:8")

    exits = yielded.machine.throw(incoming)

    halted = [exit_ for exit_ in exits.exits if isinstance(exit_, Halted)]
    assert len(halted) == 1
    assert halted[0].effect is incoming


def test_close_runs_constructed_finally_and_returns_termination_face():
    api = _api()
    from sugar_lift_py_tests.outcome import Completed, ExitSet
    from sugar_lift_py_tests.sugar.inert_sugar import InertSugar

    yielded = _machine(
        api.YieldStepV1(num(7)),
        api.FinallyStepV1((InertSugar(site="cleanup"),)),
        api.ReturnStepV1(num(9)),
    ).resume()

    exits = yielded.machine.close()

    assert isinstance(exits, ExitSet)
    assert len(exits.exits) == 1
    assert isinstance(exits.exits[0], Completed)
    assert isinstance(exits.exits[0].value, api.GeneratorTerminationV1)
    assert exits.exits[0].value.return_value is None
