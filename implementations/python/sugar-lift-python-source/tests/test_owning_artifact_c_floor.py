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
* ``sys.exc_info()`` in ``ExitStack.__exit__``: no artifact authenticates
  ``sys``, so the lifter does not have it: the call is not bridged and is cited
  as such (``call-target-off-population``), whatever it is implemented in.
* A constructor halt carries its initializer block, whose live reducer context
  is a lookup aid, not testimony: it no longer refuses the constructed value.
"""

from __future__ import annotations

from types import SimpleNamespace

from sugar_lift_py_tests.floor.language_owned_c_type import LanguageOwnedCTypeValue
from sugar_lift_python_source.dependency_artifact import (
    ResolvedPythonObjectV1,
    authenticate_dependency_top_level,
)
from sugar_lift_python_source.dependency_export_adapter import resolve_export
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
