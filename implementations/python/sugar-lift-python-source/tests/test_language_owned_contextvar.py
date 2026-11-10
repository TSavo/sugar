"""Language-owned ContextVar.set / reset and C-extension call floors (Cut 2)."""

from __future__ import annotations

from types import SimpleNamespace

from sugar_lift_py_tests.floor.language_owned_contextvar import (
    LanguageOwnedCExtensionCallableValue,
    LanguageOwnedCExtensionResultValue,
    LanguageOwnedContextVarToken,
    LanguageOwnedContextVarValue,
)
from sugar_lift_py_tests.floor.none_value import NoneValue
from sugar_lift_py_tests.floor.term_value import TermValue
from sugar_lift_py_tests.outcome import Complete
from sugar_lift_python_source.language_owned_c_export import (
    floor_artifact_module_absent_export,
)


def _method(name: str, *arguments, blame: str = "test"):
    return SimpleNamespace(
        name=name, arguments=arguments, keyword_names=(), blame=blame
    )


def test_contextvar_set_returns_a_token_and_reset_returns_none() -> None:
    var = LanguageOwnedContextVarValue(name="probe")
    token_out = var.call_method_with(_method("set", TermValue(1)), None)
    assert isinstance(token_out, Complete)
    assert isinstance(token_out.value, LanguageOwnedContextVarToken)
    assert token_out.value.variable_name == "probe"
    reset_out = var.call_method_with(_method("reset", token_out.value), None)
    assert isinstance(reset_out, Complete)
    assert isinstance(reset_out.value, NoneValue)




def test_artifact_module_absent_contextvar_instance_floors_by_runtime_identity() -> None:
    import numpy._core._multiarray_umath as umath

    gap = SimpleNamespace(
        kind="artifact-module-absent",
        module_name="numpy._core._multiarray_umath",
        exported_name="_extobj_contextvar",
    )
    floored = floor_artifact_module_absent_export(gap)
    assert isinstance(floored, LanguageOwnedContextVarValue)
    assert floored.name == umath._extobj_contextvar.name


def test_artifact_module_absent_builtin_floors_as_a_typed_c_call() -> None:
    gap = SimpleNamespace(
        kind="artifact-module-absent",
        module_name="numpy._core._multiarray_umath",
        exported_name="_make_extobj",
    )
    floored = floor_artifact_module_absent_export(gap)
    assert isinstance(floored, LanguageOwnedCExtensionCallableValue)
    assert floored.module_name == "numpy._core._multiarray_umath"
    assert floored.exported_name == "_make_extobj"
    result = floored.callable_application_with(
        SimpleNamespace(arguments=(), keyword_names=(), blame="test"), None
    )
    assert isinstance(result, Complete)
    assert isinstance(result.value, LanguageOwnedCExtensionResultValue)
    assert result.value.exported_name == "_make_extobj"


def test_unrecognized_c_export_stays_a_gap() -> None:
    gap = SimpleNamespace(
        kind="artifact-module-absent",
        module_name="numpy._core._multiarray_umath",
        exported_name="__doc__",
    )
    assert floor_artifact_module_absent_export(gap) is None


def test_contextvar_class_floors_from_the_c_module() -> None:
    from sugar_lift_py_tests.floor.language_owned_contextvar import (
        LanguageOwnedContextVarType,
    )

    gap = SimpleNamespace(
        kind="artifact-module-absent",
        module_name="_contextvars",
        exported_name="ContextVar",
    )
    floored = floor_artifact_module_absent_export(gap)
    assert isinstance(floored, LanguageOwnedContextVarType)
