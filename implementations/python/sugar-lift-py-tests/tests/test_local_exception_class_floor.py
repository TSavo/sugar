from __future__ import annotations

import ast
import importlib
from dataclasses import replace

import pytest

from factory_reduce import compose_block

from sugar_lift_py_tests.factory import FactoryPanic
from sugar_lift_py_tests.factory.build import default_catalog
from sugar_lift_py_tests.factory.source_fragment import SourceFragment
from sugar_lift_py_tests.context import FactoryBuildContext
from sugar_lift_py_tests.floor import ExceptionValue, RaiseValue, SymbolicValue
from sugar_lift_py_tests.ir import make_var
from sugar_lift_py_tests.temporal import TemporalContext
from sugar_lift_py_tests import lift_rpc
from sugar_lift_py_tests.claim import SugarRole
from sugar_lift_py_tests.outcome import complete_value
from sugar_lift_py_tests.sugar.install_source_dig import resolve_install_source_value
from sugar_lift_py_tests.sugar.constructor_call_sugar import ConstructorCallSugar
from sugar_lift_py_tests.sugar.constructor_strategy import RuntimeConstructorStrategy


def test_local_exception_subclass_constructs_routeable_raise() -> None:
    block = compose_block(
        "    class OpError(Exception):\n" "        pass\n" "    raise OpError('bad')\n"
    )

    raised = block.statements[-1]
    assert isinstance(raised, RaiseValue)
    assert isinstance(raised.exception, ExceptionValue)
    assert raised.effect.exception_name == "OpError"


def test_transitive_local_exception_ancestry_constructs_routeable_raise() -> None:
    block = compose_block(
        "    class PackageError(Exception):\n"
        "        pass\n"
        "    class OpError(PackageError):\n"
        "        pass\n"
        "    raise OpError('bad')\n"
    )

    raised = block.statements[-1]
    assert isinstance(raised, RaiseValue)
    assert isinstance(raised.exception, ExceptionValue)
    assert raised.effect.exception_name == "OpError"


def test_local_ordinary_class_wrong_twin_stays_named_raise_gap() -> None:
    with pytest.raises(FactoryPanic) as raised:
        compose_block(
            "    class Payload:\n" "        pass\n" "    raise Payload('bad')\n"
        )

    assert raised.value.info.owner == "RaiseSugar"
    assert raised.value.info.observed == "CallSiteValue"
    assert raised.value.info.requested == "constructed exception floor"


def test_resolved_ordinary_constructor_stays_a_named_runtime_effect() -> None:
    module = ast.parse("class Payload:\n    pass\nPayload('bad')\n")
    ctx = replace(
        FactoryBuildContext(filename="t.py", catalog=default_catalog()),
        name_resolver={"Payload": module.body[0]},
    )
    site = SourceFragment.from_node(module.body[1].value, "t.py")

    sugar = ConstructorCallSugar.new(site, ctx)
    assert isinstance(sugar.strategy, RuntimeConstructorStrategy)
    assert "inherited" not in sugar.strategy.reason


def test_shadowed_exception_base_stays_a_named_runtime_effect() -> None:
    module = ast.parse("class Payload(Exception):\n    pass\nPayload('bad')\n")
    temporal = TemporalContext.empty().bind_value(
        "Exception", SymbolicValue(make_var("local_Exception"))
    )
    ctx = replace(
        FactoryBuildContext(filename="t.py", catalog=default_catalog()),
        temporal=temporal,
        name_resolver={"Payload": module.body[0]},
    )
    site = SourceFragment.from_node(module.body[1].value, "t.py")

    sugar = ConstructorCallSugar.new(site, ctx)
    assert isinstance(sugar.strategy, RuntimeConstructorStrategy)
    assert "inherited constructor runtime boundary" in sugar.strategy.reason


def test_module_temporal_seeds_exact_local_exception_identity() -> None:
    source = (
        "class OpError(Exception):\n"
        "    pass\n\n"
        "def as_number(obj):\n"
        "    raise OpError(f'cannot convert {obj}')\n"
    )
    source_root = SourceFragment.from_source(source, "symbolic.py")
    module = source_root.statements()[0]

    temporal = lift_rpc._module_import_temporal(module, default_catalog())

    from sugar_lift_py_tests.floor import LocalExceptionClassValue

    assert type(temporal.value_for("OpError")) is LocalExceptionClassValue

    call = ast.parse("OpError('bad')", mode="eval").body
    ctx = FactoryBuildContext(
        filename="symbolic.py",
        catalog=default_catalog(),
        temporal=TemporalContext.empty(),
        module_temporal=temporal,
    )
    constructed = complete_value(
        ctx.build_body(call, SugarRole.TERM).reduce(ctx), owner="test"
    )
    assert isinstance(constructed, ExceptionValue)
    assert constructed.exception_name == "OpError"


def test_module_temporal_does_not_seed_shadowed_exception_ancestry() -> None:
    source = "Exception = factory\n" "class Payload(Exception):\n" "    pass\n"
    source_root = SourceFragment.from_source(source, "shadowed.py")
    module = source_root.statements()[0]

    temporal = lift_rpc._module_import_temporal(module, default_catalog())

    from sugar_lift_py_tests.floor import LocalExceptionClassValue

    assert not isinstance(temporal.value_for("Payload"), LocalExceptionClassValue)


def test_install_source_callable_captures_local_exception_prerequisite(
    tmp_path, monkeypatch
) -> None:
    (tmp_path / "source_local_exception.py").write_text(
        "class OpError(Exception):\n"
        "    pass\n\n"
        "def as_number(obj):\n"
        "    raise OpError(f'cannot convert {obj}')\n",
        encoding="utf-8",
    )
    monkeypatch.syspath_prepend(str(tmp_path))
    importlib.invalidate_caches()
    ctx = FactoryBuildContext(filename="consumer.py", catalog=default_catalog())

    resolved = resolve_install_source_value("source_local_exception.as_number", ctx)

    from sugar_lift_py_tests.floor import FunctionCallable, LocalExceptionClassValue

    assert isinstance(resolved, FunctionCallable)
    base_context = resolved.body.sugar.base_context
    assert type(base_context.temporal.value_for("OpError")) is LocalExceptionClassValue
