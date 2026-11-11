"""``with ExitStack()``: C objects reached through a second module, and ``sys``.

Enrolling ``contextlib`` (#7570) made ``ExitStack`` construct from its source,
which reaches three things no source stands behind (#7676):

* ``deque()`` in ``ExitStack.__init__``: ``contextlib`` binds ``deque`` from
  ``collections`` (``artifact-module-absent`` in contextlib's artifact), and
  ``collections`` binds it in turn from the interpreter-owned C module
  ``_collections``.  The owning artifact's own export of the name is followed
  and the existing runtime-identity C floor is asked THERE.  A Python object
  behind the hop is still projected, and a name the owner does not define
  keeps ``call-target-source-absent``.
* ``sys.exc_info()`` in ``ExitStack.__exit__``: ``sys`` is compiled into the
  interpreter, so no artifact authenticates it.  A builtin function the module
  itself owns is floored as a C-extension callable; anything else keeps the gap.
* A constructor halt carries its initializer block, whose live reducer context
  is a lookup aid, not testimony: it no longer refuses the constructed value.
"""

from __future__ import annotations

from types import SimpleNamespace

from sugar_lift_py_tests.floor.language_owned_c_type import LanguageOwnedCTypeValue
from sugar_lift_py_tests.floor.language_owned_contextvar import (
    LanguageOwnedCExtensionCallableValue,
)
from sugar_lift_python_source.dependency_artifact import (
    ResolvedPythonObjectV1,
    authenticate_dependency_top_level,
)
from sugar_lift_python_source.dependency_export_adapter import resolve_export
from sugar_lift_python_source.language_owned_c_export import (
    floor_interpreter_module_callable,
)
from sugar_lift_python_source.manager_construction import (
    _follow_into_owning_artifact,
    _resolve_in_owning_artifact,
)
from sugar_lift_python_source.resolution_session import SourceResolutionSession


def _session():
    return SourceResolutionSession(enrolled_distributions=frozenset())


def _absent(module_name, exported_name):
    return SimpleNamespace(
        kind="artifact-module-absent",
        module_name=module_name,
        exported_name=exported_name,
        import_binding_cid="bind-cid",
        distribution_artifact_cid=None,
    )


def test_contextlib_deque_is_floored_where_collections_binds_it_from_c():
    session = _session()
    graph = authenticate_dependency_top_level("contextlib")
    gap = resolve_export(
        graph, "bind-cid", "contextlib", "deque", (), frozenset(), session=session
    )
    assert (gap.kind, gap.module_name) == ("artifact-module-absent", "collections")
    floored = _follow_into_owning_artifact(gap, session=session)
    assert floored == LanguageOwnedCTypeValue(
        module_name="_collections", type_name="deque"
    )
    # The resolved-only door is unchanged: a floor is not a source object.
    assert _resolve_in_owning_artifact(gap, session=session) is None


def test_a_python_object_behind_the_hop_is_projected_not_floored():
    session = _session()
    hopped = _follow_into_owning_artifact(
        _absent("collections", "namedtuple"), session=session
    )
    assert isinstance(hopped, tuple)
    resolved, _graph = hopped
    assert isinstance(resolved, ResolvedPythonObjectV1)
    assert resolved.definition.name == "namedtuple"


def test_a_name_the_owner_does_not_define_keeps_the_gap():
    session = _session()
    assert (
        _follow_into_owning_artifact(
            _absent("collections", "no_such_name_here"), session=session
        )
        is None
    )


def test_a_builtin_function_of_a_compiled_in_module_is_floored():
    assert floor_interpreter_module_callable(
        "python:sys.exc_info"
    ) == LanguageOwnedCExtensionCallableValue(
        module_name="sys", exported_name="exc_info"
    )


def test_a_c_class_of_a_compiled_in_module_is_floored_by_the_type_rule():
    # ``itertools`` is compiled in and ``dropwhile`` is its own C heap type with
    # no Python source: cited, never constructed or looked inside.  Calling it
    # either completes with an opaque instance or raises undetermined.
    from sugar_lift_py_tests.callable_application import CallableApplication
    from sugar_lift_py_tests.effect.raise_effect import UndeterminedRaiseEffect
    from sugar_lift_py_tests.floor.language_owned_c_type import (
        LanguageOwnedCInstanceValue,
    )
    from sugar_lift_py_tests.outcome.exit_set import Completed, Halted

    floored = floor_interpreter_module_callable("python:itertools.dropwhile")
    assert floored == LanguageOwnedCTypeValue(
        module_name="itertools", type_name="dropwhile"
    )
    exits = floored.callable_application_with(
        CallableApplication(
            arguments=(), keyword_names=(), site=None, owner="test"
        ),
        None,
    ).exits
    completed = [exit_ for exit_ in exits if isinstance(exit_, Completed)]
    halted = [exit_ for exit_ in exits if isinstance(exit_, Halted)]
    assert len(completed) == 1 and len(halted) == 1
    assert isinstance(completed[0].value, LanguageOwnedCInstanceValue)
    assert isinstance(halted[0].effect, UndeterminedRaiseEffect)


def test_a_class_that_is_not_a_compiled_in_modules_own_c_heap_type_keeps_the_gap():
    # A static (non-heap) type, a class owned by another module, and a
    # method reached through a deeper chain are not this module's C class.
    assert floor_interpreter_module_callable("python:builtins.object") is None
    assert floor_interpreter_module_callable("python:builtins.int") is None
    assert (
        floor_interpreter_module_callable("python:itertools.chain.from_iterable")
        is None
    )


def test_anything_else_on_a_compiled_in_module_keeps_the_gap():
    # Not a function, not a module export, not compiled in, not a symbol.
    assert floor_interpreter_module_callable("python:sys.maxsize") is None
    assert floor_interpreter_module_callable("python:sys.flags.optimize") is None
    assert floor_interpreter_module_callable("python:json.dumps") is None
    assert floor_interpreter_module_callable("python:sys.no_such_name") is None
    assert floor_interpreter_module_callable("sys.exc_info") is None


def test_a_reduced_block_context_is_not_testimony():
    from sugar_lift_py_tests.context.reduce_context import ReduceContext
    from sugar_lift_py_tests.sugar.function_universe_sugar import _ReducedBlock
    from sugar_lift_py_tests.temporal import TemporalContext
    from sugar_source_tree.binding_state import constructed_value_cid_v2

    live = ReduceContext(temporal=TemporalContext())
    with_context = _ReducedBlock(("a",), True, (), (), live)
    without = _ReducedBlock(("a",), True, (), (), None)
    assert constructed_value_cid_v2(with_context) == constructed_value_cid_v2(without)


def test_a_reduced_block_content_still_changes_its_coordinate():
    from sugar_lift_py_tests.context.reduce_context import ReduceContext
    from sugar_lift_py_tests.sugar.function_universe_sugar import _ReducedBlock
    from sugar_lift_py_tests.temporal import TemporalContext
    from sugar_source_tree.binding_state import constructed_value_cid_v2

    live = ReduceContext(temporal=TemporalContext())
    first = _ReducedBlock(("a",), True, (), (), live)
    other = _ReducedBlock(("b",), True, (), (), live)
    halted_only = _ReducedBlock(("a",), False, (), (), live)
    assert constructed_value_cid_v2(first) != constructed_value_cid_v2(other)
    assert constructed_value_cid_v2(first) != constructed_value_cid_v2(halted_only)
