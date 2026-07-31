from sugar_lift_py_tests.floor import DictValue, GuardedValue, StringValue, TermValue
from sugar_lift_py_tests.ir import atomic, not_
from sugar_lift_py_tests.outcome import ExitSet
from sugar_lift_py_tests.outcome.exit_set import Completed


def _store(receiver, index, value):
    return receiver.setitem(index, value, "store-site")


def _entry_map(value):
    return {key.value: item.value for key, item in value.entries}


def test_guarded_index_distributes_store_under_complementary_guards() -> None:
    guard = atomic("selected", [])
    outcome = _store(
        DictValue(()),
        GuardedValue(guard, StringValue("left"), StringValue("right")),
        TermValue(7),
    )

    assert isinstance(outcome, ExitSet)
    assert len(outcome.exits) == 2
    assert all(isinstance(face, Completed) for face in outcome.exits)
    assert {face.guard for face in outcome.exits} == {guard, not_(guard)}
    assert {
        tuple(sorted(_entry_map(face.value).items())) for face in outcome.exits
    } == {(("left", 7),), (("right", 7),)}


def test_guarded_value_distributes_without_choosing_one_face() -> None:
    guard = atomic("selected", [])
    outcome = _store(
        DictValue(()),
        StringValue("member"),
        GuardedValue(guard, TermValue(1), TermValue(2)),
    )

    assert isinstance(outcome, ExitSet)
    assert len(outcome.exits) == 2
    assert {face.guard for face in outcome.exits} == {guard, not_(guard)}
    assert {_entry_map(face.value)["member"] for face in outcome.exits} == {1, 2}


def test_guarded_index_never_mints_a_runtime_store_effect() -> None:
    guard = atomic("selected", [])
    outcome = _store(
        DictValue(()),
        GuardedValue(guard, StringValue("left"), StringValue("right")),
        TermValue(7),
    )

    assert all(isinstance(face, Completed) for face in outcome.exits)
