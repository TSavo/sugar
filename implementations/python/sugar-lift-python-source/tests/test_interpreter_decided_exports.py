"""Exports the source binds twice or dynamically, decided by the interpreter.

``warnings.warn`` is ``ambiguous-static-export`` (``from _warnings import
warn`` in a ``try``, a pure-Python ``def warn`` in its ``except``) and
``os.path.dirname`` is ``target-outside-binding`` through the dynamic
``os.path`` binding.  The running, pin-authenticated interpreter decides both
by runtime identity: the C ``warn`` stands, and ``os.path`` IS ``posixpath``.
Neither citation is inert: the C call completes only under its opaque atom and
otherwise raises undetermined; ``posixpath.dirname`` resolves to its stdlib
source, which the population membrane then cites off-population.
"""

from __future__ import annotations

from types import SimpleNamespace

from sugar_lift_py_tests.callable_application import CallableApplication
from sugar_lift_py_tests.effect.raise_effect import UndeterminedRaiseEffect
from sugar_lift_py_tests.floor.language_owned_contextvar import (
    LanguageOwnedCExtensionCallableValue,
)
from sugar_lift_py_tests.floor.warning_observation_value import WarningObservationValue
from sugar_lift_py_tests.ir import ctor, str_const
from sugar_lift_py_tests.outcome.exit_set import Completed, Halted
from sugar_lift_py_tests.sugar.warning_observation_producer import (
    project_warning_observation,
)
from sugar_lift_python_source.language_owned_c_export import (
    floor_artifact_module_absent_export,
)

_CID = "blake3-512:" + "0" * 128


def _ambiguous(module_name, exported_name):
    return SimpleNamespace(
        kind="ambiguous-static-export",
        module_name=module_name,
        exported_name=exported_name,
    )


def _category(name):
    identity = ctor(
        "python:exception_type_identity", (str_const("builtins"), str_const(name))
    )
    return SimpleNamespace(exception_type_identity=lambda: identity)


def _faces(callable_value, arguments, keyword_names=()):
    exits = callable_value.callable_application_with(
        CallableApplication(
            arguments=tuple(arguments), keyword_names=tuple(keyword_names), site=None
        ),
        None,
    )
    return exits.exits


def test_interpreter_c_warn_floors_as_language_owned_callable():
    floored = floor_artifact_module_absent_export(_ambiguous("warnings", "warn"))
    assert isinstance(floored, LanguageOwnedCExtensionCallableValue)
    assert floored.warning_occurrence is True


def test_python_fallback_that_stands_keeps_the_gap():
    # ``warnings.showwarning`` is a Python function: no C binding won.
    assert floor_artifact_module_absent_export(_ambiguous("warnings", "showwarning")) is None


def test_warn_completes_with_its_typed_warning_or_raises_undetermined():
    floored = floor_artifact_module_absent_export(_ambiguous("warnings", "warn"))
    faces = _faces(floored, (SimpleNamespace(), _category("FutureWarning")))
    completed = [face for face in faces if isinstance(face, Completed)]
    halted = [face for face in faces if isinstance(face, Halted)]
    assert len(completed) == 1 and len(halted) == 1
    # A warnings filter set to ``error`` makes the same call raise.
    assert isinstance(halted[0].effect, UndeterminedRaiseEffect)
    observation = project_warning_observation(completed[0].value)
    assert isinstance(observation, WarningObservationValue)
    assert observation.effect.category_name == "FutureWarning"


def test_warn_category_moves_with_the_source_operand():
    floored = floor_artifact_module_absent_export(_ambiguous("warnings", "warn"))
    faces = _faces(
        floored, (SimpleNamespace(), _category("DeprecationWarning")), ()
    )
    completed = next(face for face in faces if isinstance(face, Completed))
    assert (
        project_warning_observation(completed.value).effect.category_name
        == "DeprecationWarning"
    )


def test_warn_without_explicit_category_names_no_warning():
    # ``UserWarning`` is CPython's default, not testimony in the source.
    floored = floor_artifact_module_absent_export(_ambiguous("warnings", "warn"))
    faces = _faces(floored, (SimpleNamespace(),))
    completed = next(face for face in faces if isinstance(face, Completed))
    assert project_warning_observation(completed.value) is None
    assert any(isinstance(face, Halted) for face in faces)


def test_other_c_callables_carry_no_warning():
    floored = floor_artifact_module_absent_export(
        SimpleNamespace(
            kind="artifact-module-absent", module_name="os", exported_name="getcwd"
        )
    )
    faces = _faces(floored, (SimpleNamespace(), _category("FutureWarning")))
    completed = next(face for face in faces if isinstance(face, Completed))
    assert project_warning_observation(completed.value) is None


def _session():
    from sugar_lift_python_source.resolution_session import SourceResolutionSession

    return SourceResolutionSession(enrolled_distributions=frozenset({"pandas"}))


def _outside(target):
    from sugar_lift_python_source.manager_construction import (
        _resolve_through_runtime_module_alias,
    )

    return _resolve_through_runtime_module_alias(
        SimpleNamespace(
            kind="target-outside-binding", module_name="os", import_binding_cid=_CID
        ),
        SimpleNamespace(target_symbol=target),
        session=_session(),
    )


def test_os_path_member_resolves_in_the_module_the_interpreter_bound():
    from sugar_lift_python_source.manager_construction import _graph_is_off_population

    resolved, graph = _outside("python:os.path.dirname")
    assert resolved.module_name == "posixpath"
    # Stdlib source: the projection door cites it off-population.
    assert _graph_is_off_population(graph, session=_session())


def test_alias_hop_needs_a_module_and_a_real_export():
    assert _outside("python:os.getcwd") is None  # no module alias on the path
    assert _outside("python:os.path.no_such_export") is None
