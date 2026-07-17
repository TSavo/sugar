from __future__ import annotations

import inspect

import pytest

import sugar_lift_py_tests.effect as effects
from sugar_lift_py_tests.effect import (
    RuntimeEffect,
    RuntimeEffectWitness,
    SubscriptStoreRuntimeEffect,
)
from sugar_lift_py_tests.factory.source_fragment import SourceFragment
from sugar_lift_py_tests.ir import ctor, make_var


def test_runtime_effect_requires_operation_operand_and_site_witness() -> None:
    site = SourceFragment.from_source("x[i] = 1", "t.py").statements()[0]
    witness = RuntimeEffectWitness(
        operation=ctor("py.setitem", []),
        operand=make_var("runtime_index"),
        site=site,
    )
    assert witness.locus == "t.py:1:0"

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


def test_source_fragment_normalizes_absolute_filename_at_the_door() -> None:
    import os

    fragment = SourceFragment.from_source(
        "x = 1", os.path.join(os.getcwd(), "vendor.py")
    )
    assert fragment.filename == "vendor.py"
    site = fragment.statements()[0]
    witness = RuntimeEffectWitness(
        operation=ctor("py.runtime", []),
        operand=make_var("operand"),
        site=site,
    )
    assert witness.locus == "vendor.py:1:0"


def test_source_fragment_passes_pseudo_filenames_untouched() -> None:
    fragment = SourceFragment.from_source("x = 1", "<contract>")
    assert fragment.filename == "<contract>"


def test_string_locus_cannot_mint_a_runtime_effect_witness() -> None:
    from sugar_lift_py_tests.effect import runtime_effect_witness

    with pytest.raises(TypeError, match="SourceFragment"):
        runtime_effect_witness("py.divide", make_var("x"), "t.py:1:0")


def test_arbitrary_object_operand_cannot_fabricate_a_witness_term() -> None:
    from sugar_lift_py_tests.effect import runtime_effect_witness

    site = SourceFragment.from_source("x = 1", "t.py").statements()[0]
    with pytest.raises(TypeError, match="ground primitive"):
        runtime_effect_witness("py.runtime", object(), site)


def test_operation_carrying_fragment_blame_resolves_as_site() -> None:
    from sugar_lift_py_tests.effect import runtime_effect_witness

    site = SourceFragment.from_source("x.y", "t.py").statements()[0]

    class _Op:
        blame = site
        name = "y"

    witness = runtime_effect_witness("py.getattr", "y", _Op())
    assert witness.site is site
    assert witness.locus == "t.py:1:0"
