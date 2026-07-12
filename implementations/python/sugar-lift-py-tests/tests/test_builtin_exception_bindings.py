from __future__ import annotations

import builtins

import pytest

from sugar_lift_py_tests.factory.factory_gap import FactoryPanic
from sugar_lift_py_tests.floor import ClassValue
from sugar_lift_py_tests.idd.lift_coverage_accounting import account_lift_coverage
from sugar_lift_py_tests.idd.lift_coverage_census import census_source
from sugar_lift_py_tests.lift_rpc import audit_lift_file
import sugar_lift_py_tests.temporal as temporal_module
from sugar_lift_py_tests.temporal import TemporalContext


def test_builtin_exception_names_construct_in_raise_and_isinstance() -> None:
    source = (
        "def warn():\n"
        "    raise FutureWarning('future')\n"
        "\n"
        "def builtin_value():\n"
        "    return FutureWarning\n"
        "\n"
        "def check(x):\n"
        "    assert isinstance(x, ValueError)\n"
        "    return 1\n"
    )

    payload, gaps = audit_lift_file(source, "builtins.py", hold_panic=True)
    assertions = account_lift_coverage(
        census_source(source, file="builtins.py"), payload.to_rpc()
    ).to_json()["assertions"]

    assert not any("observed=FutureWarning requested=value" in gap.message for gap in gaps)
    assert assertions["lifted_cited"] == 1
    assert assertions["refused_loud"] == 0


def test_genuinely_undefined_name_still_panics_loudly() -> None:
    source = "def f():\n    return definitely_not_a_builtin\n"

    with pytest.raises(
        FactoryPanic,
        match="observed=definitely_not_a_builtin requested=value",
    ):
        audit_lift_file(source, "undefined.py", hold_panic=False)


def test_builtin_exception_binding_set_is_derived_from_python() -> None:
    expected = frozenset(
        name
        for name in dir(builtins)
        if isinstance(getattr(builtins, name), type)
        and issubclass(getattr(builtins, name), BaseException)
    )

    assert temporal_module.builtin_exception_names() == expected
    temporal = temporal_module.builtin_exception_temporal()
    lexical = TemporalContext.empty()
    for name in expected:
        bound = temporal.value_for(name)
        assert isinstance(bound, ClassValue)
        assert bound.name == name
        assert lexical.value_for(name) == bound
