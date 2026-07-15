from __future__ import annotations

import builtins
import ast

import pytest

from sugar_lift_py_tests.factory.factory_gap import FactoryPanic
from sugar_lift_py_tests.claim import SugarRole
from sugar_lift_py_tests.context.factory_build_context import FactoryBuildContext
from sugar_lift_py_tests.factory.build import build_node, default_catalog
from sugar_lift_py_tests.floor import (
    CallSiteValue,
    ClassValue,
    ExceptionValue,
    SymbolicValue,
)
from sugar_lift_py_tests.ir import make_var
from sugar_lift_py_tests.idd.lift_coverage_accounting import account_lift_coverage
from sugar_lift_py_tests.idd.lift_coverage_census import census_source
from sugar_lift_py_tests.lift_rpc import audit_lift_file
import sugar_lift_py_tests.temporal as temporal_module
from sugar_lift_py_tests.temporal import TemporalContext
from factory_reduce import reduce_value


def test_builtin_callable_names_construct_as_decorators_and_values() -> None:
    source = (
        "class C:\n"
        "    @property\n"
        "    def value(self):\n"
        "        return 1\n"
        "\n"
        "    @classmethod\n"
        "    def make(cls):\n"
        "        return cls\n"
        "\n"
        "def builtin_values():\n"
        "    return staticmethod\n"
    )

    _payload, gaps = audit_lift_file(source, "builtins.py")

    for name in ("property", "classmethod", "staticmethod"):
        assert not any(
            f"observed={name} requested=value" in gap.message for gap in gaps
        )


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

    payload, gaps = audit_lift_file(source, "builtins.py")
    assertions = account_lift_coverage(
        census_source(source, file="builtins.py"), payload.to_rpc()
    ).to_json()["assertions"]

    assert not any(
        "observed=FutureWarning requested=value" in gap.message for gap in gaps
    )
    assert assertions["lifted_cited"] == 1
    assert assertions["refused_loud"] == 0


def test_builtin_exception_preserves_constructed_symbolic_argument() -> None:
    value = reduce_value(
        "ValueError(message)",
        binds={"message": SymbolicValue(make_var("message"))},
    )

    assert isinstance(value, ExceptionValue)
    assert value.arguments == (SymbolicValue(make_var("message")),)


def test_builtin_exception_preserves_constructed_call_argument() -> None:
    value = reduce_value("ValueError(render(1))")

    assert isinstance(value, ExceptionValue)
    assert len(value.arguments) == 1
    assert isinstance(value.arguments[0], CallSiteValue)
    assert value.arguments[0].target_name == "render"


def test_genuinely_undefined_name_still_panics_loudly() -> None:
    source = "def f():\n    return definitely_not_a_builtin\n"

    with pytest.raises(
        FactoryPanic,
        match="observed=definitely_not_a_builtin requested=value",
    ):
        audit_lift_file(source, "undefined.py")


def test_builtin_callable_binding_set_is_derived_from_python() -> None:
    expected = frozenset(
        name for name in dir(builtins) if callable(getattr(builtins, name))
    )

    assert temporal_module.builtin_callable_names() == expected
    temporal = temporal_module.builtin_name_temporal()
    lexical = TemporalContext.empty()
    for name in expected:
        bound = temporal.value_for(name)
        assert isinstance(bound, ClassValue)
        assert bound.name == name
        assert lexical.value_for(name) == bound


def test_builtin_calls_keep_their_dedicated_sugar_owners() -> None:
    source = (
        "def f(x):\n"
        "    assert isinstance(x, int)\n"
        "    return len([abs(-1), int('2')])\n"
    )

    _payload, gaps = audit_lift_file(source, "calls.py")

    assert not any(
        "observed=len requested=value" in gap.message
        or "observed=isinstance requested=value" in gap.message
        or "observed=abs requested=value" in gap.message
        or "observed=int requested=value" in gap.message
        for gap in gaps
    )
    ctx = FactoryBuildContext(filename="calls.py", catalog=default_catalog())
    expected_owners = {
        "len(x)": "LenCallSugar",
        "abs(x)": "AbsCallSugar",
        "isinstance(x, int)": "IsinstanceCallSugar",
    }
    for expression, owner in expected_owners.items():
        node = ast.parse(expression, mode="eval").body
        result = build_node(node, filename="calls.py", role=SugarRole.TERM, ctx=ctx)
        assert result.audit_row.selected == owner
