from __future__ import annotations

import builtins


def builtin_callable_names() -> frozenset[str]:
    """Return callable objects Python exposes in its builtin namespace."""
    return frozenset(
        name for name in dir(builtins) if callable(getattr(builtins, name))
    )


def builtin_constant_names() -> frozenset[str]:
    """Return the non-callable complement of Python's builtin namespace."""
    return frozenset(
        name for name in dir(builtins) if not callable(getattr(builtins, name))
    )


def builtin_name_temporal():
    """Construct lexical coordinates for Python's builtin name values."""
    from sugar_lift_py_tests.floor import BlockValue, ClassValue, SymbolicValue
    from sugar_lift_py_tests.ir import ctor, str_const
    from sugar_lift_py_tests.temporal.temporal_context import TemporalContext

    # Construct the raw root directly. TemporalContext.empty() delegates here
    # so every ordinary lexical scope starts with this one builtin floor.
    temporal = TemporalContext()
    for name in sorted(builtin_callable_names()):
        temporal = temporal.bind_value(
            name,
            ClassValue(name=name, bases=(), record=BlockValue(())),
        )
    for name in sorted(builtin_constant_names()):
        temporal = temporal.bind_value(
            name,
            SymbolicValue(ctor("python:builtin", [str_const(name)])),
        )
    return temporal
