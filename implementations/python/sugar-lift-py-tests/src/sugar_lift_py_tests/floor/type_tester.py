from __future__ import annotations


def native_type_tester(value, type_term, site, *, type_callsites=()):
    """Emit the reserved Python type tester over an already-cited coordinate."""
    from sugar_lift_py_tests.floor.predicate_value import PredicateValue
    from sugar_lift_py_tests.ir import atomic
    from sugar_lift_py_tests.outcome import Complete

    return Complete(
        PredicateValue(
            atomic(
                "adt.is_python_type",
                [value.to_term(owner="native_type_tester"), type_term],
            ),
            site,
            operand_callsites=(*value.callsites(), *type_callsites),
        )
    )
