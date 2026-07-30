from sugar_lift_py_tests.floor import SymbolicValue
from sugar_lift_py_tests.ir import atomic, make_var


def test_symbolic_support_keeps_one_identity_under_a_guard() -> None:
    value = SymbolicValue(make_var("value"))
    guarded = value.guarded(atomic("path", []))

    assert guarded is value
    assert guarded.to_term(owner="test") == make_var("value")


def test_guard_does_not_become_symbolic_value_content_identity() -> None:
    value = SymbolicValue(make_var("value"))

    assert value.guarded(atomic("left", [])) is value.guarded(
        atomic("right", [])
    )
    assert value.inv_contribution() == ()
    assert value.post_contribution() == ()
