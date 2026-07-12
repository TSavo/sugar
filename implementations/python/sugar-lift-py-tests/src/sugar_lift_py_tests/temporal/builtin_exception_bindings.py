from __future__ import annotations

import builtins


def builtin_exception_names() -> frozenset[str]:
    """Return the exception classes Python exposes in its builtin namespace."""
    return frozenset(
        name
        for name in dir(builtins)
        if isinstance(getattr(builtins, name), type)
        and issubclass(getattr(builtins, name), BaseException)
    )


def builtin_exception_temporal():
    """Construct the always-present lexical bindings for builtin exceptions."""
    from sugar_lift_py_tests.floor import BlockValue, ClassValue
    from sugar_lift_py_tests.temporal.temporal_context import TemporalContext

    # Construct the raw root directly. TemporalContext.empty() delegates here
    # so every ordinary lexical scope starts with this one builtin floor.
    temporal = TemporalContext()
    for name in sorted(builtin_exception_names()):
        temporal = temporal.bind_value(
            name,
            ClassValue(name=name, bases=(), record=BlockValue(())),
        )
    return temporal
