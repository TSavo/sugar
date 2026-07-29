from __future__ import annotations


def test_builtin_object_owner_does_not_depend_on_host_callable_enumeration(
    monkeypatch,
) -> None:
    from sugar_lift_py_tests.floor import BuiltinObjectClassValue
    from sugar_lift_py_tests.temporal import builtin_name_bindings as bindings

    monkeypatch.setattr(bindings, "_EMPTY_BUILTIN_TEMPORAL", None)
    monkeypatch.setattr(bindings, "builtin_callable_names", lambda: frozenset())
    try:
        temporal = bindings.builtin_name_temporal()
        assert type(temporal.value_if_bound("object")) is BuiltinObjectClassValue
    finally:
        bindings._EMPTY_BUILTIN_TEMPORAL = None
