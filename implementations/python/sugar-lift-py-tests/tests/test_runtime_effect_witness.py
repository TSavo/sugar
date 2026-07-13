from __future__ import annotations

import inspect

import pytest

import sugar_lift_py_tests.effect as effects
from sugar_lift_py_tests.effect import (
    RuntimeEffect,
    RuntimeEffectWitness,
    SubscriptStoreRuntimeEffect,
)
from sugar_lift_py_tests.ir import ctor, make_var


def test_runtime_effect_requires_operation_operand_and_locus_witness() -> None:
    witness = RuntimeEffectWitness(
        operation=ctor("py.setitem", []),
        operand=make_var("runtime_index"),
        locus="t.py:1:0",
    )

    effect = SubscriptStoreRuntimeEffect("runtime store", witness=witness)

    assert effect.witness == witness


def test_no_runtime_effect_subclass_is_instantiable_without_a_witness() -> None:
    subclasses = {
        value
        for _name, value in inspect.getmembers(effects, inspect.isclass)
        if issubclass(value, RuntimeEffect) and value is not RuntimeEffect
    }
    assert subclasses
    for effect_type in subclasses:
        with pytest.raises(TypeError, match="required positional argument: 'witness'"):
            effect_type("unwitnessed runtime claim")


def test_statically_known_global_scope_cannot_mint_a_runtime_witness() -> None:
    assert not hasattr(effects, "GlobalScopeRuntimeEffect")


def test_runtime_effect_witness_refuses_absolute_workspace_identity() -> None:
    from sugar_lift_py_tests.factory.factory_gap import FactoryPanic

    with pytest.raises(FactoryPanic, match="workspace-relative source locus"):
        RuntimeEffectWitness(
            operation=ctor("py.runtime", []),
            operand=make_var("operand"),
            locus="/tmp/checkout/vendor.py:1:0",
        )
