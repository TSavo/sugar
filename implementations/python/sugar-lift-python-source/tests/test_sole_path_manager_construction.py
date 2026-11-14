from __future__ import annotations

import csv
import importlib.metadata
import textwrap
from pathlib import Path

import pytest

from sugar_lift_py_tests.floor import BlockValue, CallSiteValue, ReturnValue, TermValue
from sugar_lift_py_tests.import_binding import authenticated_import_use_receipts
from sugar_lift_python_source.canonical import blake3_512_of
from sugar_lift_python_source.dependency_artifact import (
    DependencyArtifactGraph,
    ResolvedPythonObjectV1,
    resolve_import_binding as _resolve_import_binding,
)
from sugar_lift_python_source.manager_construction import (
    CALL_TARGET_GAP_KINDS as _CALL_TARGET_GAP_KINDS,
    ConstructedCallActualV1,
    ConstructedManagerBehaviorV1,
    ManagerConstructionGapV1,
    _call_coordinate,
    _install_opaque_call_obligation,
    _install_source_call_frame,
    construct_manager_behavior as _construct_manager_behavior,
    resolve_source_visible_frame as _resolve_source_visible_frame,
)
from sugar_lift_python_source.manager_protocol_construction import (
    ConstructedManagerProtocolV1,
    ManagerProtocolConstructionGapV1,
    construct_manager_protocol,
)
from sugar_lift_python_source.manager_summary_derivation import (
    DerivedManagerSummaryGapV1,
    DerivedManagerSummaryV1,
    derive_manager_summary,
    populate_source_derived_resource_refs,
)
from sugar_lift_python_source.resolution_session import SourceResolutionSession
from sugar_source_tree.binding_provenance import ConstructedValueTestimonyV1
from sugar_source_tree.binding_state import BindingEntryV1
from sugar_source_tree.nodes import Call, ClassDef, Constant, Name
from sugar_source_tree.tree import SourceFile


def _session_enrolling_graph(graph) -> SourceResolutionSession:
    return SourceResolutionSession(
        enrolled_distributions=frozenset({graph.distribution_name})
    )


def resolve_import_binding(*args, graph, session=None, **kwargs):
    return _resolve_import_binding(
        *args,
        graph=graph,
        session=_session_enrolling_graph(graph) if session is None else session,
        **kwargs,
    )


def resolve_source_visible_frame(*args, graph, session=None, **kwargs):
    return _resolve_source_visible_frame(
        *args,
        graph=graph,
        session=_session_enrolling_graph(graph) if session is None else session,
        **kwargs,
    )


def construct_manager_behavior(*args, graph, session=None, **kwargs):
    return _construct_manager_behavior(
        *args,
        graph=graph,
        session=_session_enrolling_graph(graph) if session is None else session,
        **kwargs,
    )


def _distribution(
    root: Path, source: str, *, exported: str = "make_guard"
) -> importlib.metadata.Distribution:
    package = root / "arbitrary"
    package.mkdir()
    (package / "__init__.py").write_text(
        f"from arbitrary.manager import {exported}\n", encoding="utf-8"
    )
    (package / "manager.py").write_text(source, encoding="utf-8")
    metadata = root / "arbitrary_dist-1.0.dist-info"
    metadata.mkdir()
    (metadata / "METADATA").write_text(
        "Metadata-Version: 2.1\nName: arbitrary-dist\nVersion: 1.0\n",
        encoding="utf-8",
    )
    files = (
        "arbitrary/__init__.py",
        "arbitrary/manager.py",
        "arbitrary_dist-1.0.dist-info/METADATA",
        "arbitrary_dist-1.0.dist-info/RECORD",
    )
    with (metadata / "RECORD").open("w", newline="", encoding="utf-8") as stream:
        writer = csv.writer(stream)
        for file in files:
            writer.writerow((file, "", ""))
    return importlib.metadata.Distribution.at(metadata)



def _sole_completed_receiver(behavior):
    """The one receiver the construction completed with.

    A construction that can also raise (#7756: its halts are carried, never
    dropped) is a partition of those halts and the completed receiver.
    """
    from sugar_lift_python_source.manager_protocol_construction import (
        _completed_object_receivers,
    )

    (receiver,) = _completed_object_receivers(behavior.receiver_state)
    return receiver

def _resolved(root: Path, source: str, *, exported: str = "make_guard"):
    graph = DependencyArtifactGraph.authenticate(
        _distribution(root, source, exported=exported)
    )
    consumer = f"import arbitrary\narbitrary.{exported}(23)\n"
    path = root / "consumer.py"
    path.write_text(consumer, encoding="utf-8")
    source_cid = blake3_512_of(consumer.encode())
    receipts, _ = authenticated_import_use_receipts(root, path, consumer, source_cid)
    resolved = resolve_import_binding(receipts[0], graph=graph)
    assert isinstance(resolved, ResolvedPythonObjectV1)
    source_file = SourceFile((consumer, str(path), source_cid))
    call = next(item for item in source_file.nodes() if isinstance(item, Call))
    literal = next(item for item in call.args if isinstance(item, Constant))
    actual = TermValue(23)
    # Testimony uses the canonical term address, never repr spelling.
    from sugar_lift_py_tests.ir import _term_content_cid

    testimony = ConstructedValueTestimonyV1.mint(
        literal.fragment, _term_content_cid(actual.to_term(owner="test"))
    )
    return (
        graph,
        resolved,
        ConstructedCallActualV1(literal, actual, testimony),
        call.fragment,
    )


def _resolved_type_actual(root: Path, source: str, *, exported: str = "make_guard"):
    graph = DependencyArtifactGraph.authenticate(
        _distribution(root, source, exported=exported)
    )
    consumer = f"import arbitrary\narbitrary.{exported}(ValueError)\n"
    path = root / "consumer.py"
    path.write_text(consumer, encoding="utf-8")
    source_cid = blake3_512_of(consumer.encode())
    receipts, _ = authenticated_import_use_receipts(root, path, consumer, source_cid)
    resolved = resolve_import_binding(receipts[0], graph=graph)
    assert isinstance(resolved, ResolvedPythonObjectV1)
    source_file = SourceFile((consumer, str(path), source_cid))
    call = next(item for item in source_file.nodes() if isinstance(item, Call))
    from sugar_source_tree.nodes import Name

    node = next(item for item in call.args if isinstance(item, Name))
    from sugar_lift_py_tests.temporal.builtin_name_bindings import builtin_name_temporal

    actual = builtin_name_temporal().value_for("ValueError")
    from sugar_lift_py_tests.ir import _term_content_cid

    testimony = ConstructedValueTestimonyV1.mint(
        node.fragment, _term_content_cid(actual.to_term(owner="test"))
    )
    return (
        graph,
        resolved,
        ConstructedCallActualV1(node, actual, testimony),
        call.fragment,
    )


def test_renamed_factory_constructs_returned_receiver_state_through_one_door(tmp_path):
    graph, resolved, actual, call_site = _resolved(
        tmp_path,
        "class UnprivilegedGuard:\n"
        "    def __init__(self, expected):\n"
        "        self.expected = expected\n\n"
        "def make_guard(expected):\n"
        "    return UnprivilegedGuard(expected)\n",
    )

    result = construct_manager_behavior(
        resolved, graph=graph, actuals=(actual,), call_site=call_site
    )

    assert isinstance(result, ConstructedManagerBehaviorV1)
    fields = {field.name: field.value for field in result.receiver_state.fields}
    assert fields == {"expected": actual.value}
    entry = result.formal_actual_bindings[0]
    assert isinstance(entry, BindingEntryV1)
    assert entry.state is actual.node
    assert entry.coordinate.projection_path == ("formal", 0)
    assert "node" not in repr(entry.wire()).lower()
    assert result.manager_construction_cid.startswith("blake3-512:")


def test_free_name_call_stays_typed_loud(tmp_path):
    """A free (non-local, non-builtin) name the export door declines.

    The condition is artifact coverage: there is no defining source for this
    name in the artifact.  That is the KEY; the spelling is the row.
    """
    graph, resolved, actual, call_site = _resolved(
        tmp_path, "def make_guard(expected):\n    return missing_helper(expected)\n"
    )

    from sugar_source_tree.panic import SugarNotWritten

    with pytest.raises(
        SugarNotWritten, match="call-target-source-absent:missing_helper"
    ):
        construct_manager_behavior(
            resolved, graph=graph, actuals=(actual,), call_site=call_site
        )


def test_unresolved_source_call_is_parked_at_its_exact_coordinate(tmp_path):
    graph, resolved, _, _ = _resolved(
        tmp_path,
        "def make_guard(expected):\n"
        "    if expected:\n"
        "        return expected\n"
        "    return missing_helper(expected)\n",
    )

    projected = resolve_source_visible_frame(resolved, graph=graph)

    assert isinstance(projected, tuple), projected
    _, target = projected
    context = target.unit.construction_context
    missing_call = next(
        node
        for node in target.walk()
        if isinstance(node, Call)
        and isinstance(node.func, Name)
        and node.func.id == "missing_helper"
    )
    coordinate = _call_coordinate(missing_call)
    roster = context.opaque_source_call_obligations[coordinate]
    assert roster.coordinate == coordinate
    assert roster.target_name == "missing_helper"
    assert roster.resolution_kind == "call-target-source-absent"
    obligation = roster.owner(resolved.cid)
    assert obligation is not None
    assert obligation.coordinate == coordinate
    assert obligation.target_name == "missing_helper"
    assert obligation.resolved_object_cid == resolved.cid
    assert obligation.resolution_kind == "call-target-source-absent"


@pytest.mark.parametrize("binding", ("import re", "import re as regex"))
def test_module_import_attribute_call_preserves_authenticated_stdlib_frame(
    tmp_path, binding
):
    """The exact call/value pair parks the inner call and preserves the frame."""
    local = "re" if binding == "import re" else "regex"
    graph, resolved, _, _ = _resolved(
        tmp_path,
        f"{binding}\n"
        "def make_guard(expected):\n"
        f"    return {local}.search('', expected)\n",
    )

    projected = resolve_source_visible_frame(resolved, graph=graph)

    assert isinstance(projected, tuple)
    frame, target = projected
    assert frame.owner is target
    assert target.name == "make_guard"


def test_source_call_coordinate_rejects_conflicting_testimony():
    source = "missing_helper(1)\n"
    from sugar_lift_py_tests.context_manager_resolution import (
        OpaqueSourceCallObligationV1,
        TreeConstructionContextV1,
    )

    context = TreeConstructionContextV1.for_source_call_construction()
    tree = SourceFile(
        (source, "conflict.py", blake3_512_of(source.encode("utf-8"))),
        construction_context=context,
    )
    call = next(node for node in tree.nodes() if isinstance(node, Call))
    coordinate = _call_coordinate(call)
    from sugar_source_tree.panic import BackendDefect

    obligation = OpaqueSourceCallObligationV1(
        coordinate,
        "missing_helper",
        "blake3-512:" + "1" * 128,
    )
    _install_opaque_call_obligation(context, call, obligation)
    _install_opaque_call_obligation(context, call, obligation)

    # SAME authenticated owner, different testimony: still byte-identity or
    # nothing. This is the arm the law was always about.
    with pytest.raises(BackendDefect, match="conflicting opaque-call obligation"):
        _install_opaque_call_obligation(
            context,
            call,
            OpaqueSourceCallObligationV1(
                coordinate,
                "other_helper",
                "blake3-512:" + "1" * 128,
            ),
        )
    with pytest.raises(BackendDefect, match="frame/obligation collision"):
        _install_source_call_frame(context, call, object())

    context.opaque_source_call_obligations.clear()
    frame = object()
    _install_source_call_frame(context, call, frame)
    _install_source_call_frame(context, call, frame)
    with pytest.raises(BackendDefect, match="frame/obligation collision"):
        _install_opaque_call_obligation(context, call, obligation)
    with pytest.raises(BackendDefect, match="conflicting source-call frame"):
        _install_source_call_frame(context, call, object())


def _opaque_probe_call(source: str = "missing_helper(1)\n"):
    """A construction context plus one Call node to park obligations against."""
    from sugar_lift_py_tests.context_manager_resolution import (
        TreeConstructionContextV1,
    )

    context = TreeConstructionContextV1.for_source_call_construction()
    tree = SourceFile(
        (source, "owners.py", blake3_512_of(source.encode("utf-8"))),
        construction_context=context,
    )
    call = next(node for node in tree.nodes() if isinstance(node, Call))
    return context, call, _call_coordinate(call)


def test_second_authenticated_owner_seats_beside_the_first():
    """One call coordinate, two owners: an ADDITIONAL seat, never a duplicate.

    A helper reached from two exported definitions is parked twice, once per
    owner. Before the roster this refused as `conflicting opaque-call
    obligation` and voided the whole file at
    `phase=context-manager-resolutions` — a BackendDefect where the callee
    testimony did not differ at all.
    """
    from sugar_lift_py_tests.context_manager_resolution import (
        OpaqueSourceCallObligationV1,
    )

    context, call, coordinate = _opaque_probe_call()
    first = OpaqueSourceCallObligationV1(
        coordinate,
        "missing_helper",
        "blake3-512:" + "1" * 128,
        resolution_kind="call-target-source-absent",
    )
    second = OpaqueSourceCallObligationV1(
        coordinate,
        "missing_helper",
        "blake3-512:" + "2" * 128,
        resolution_kind="call-target-source-absent",
    )
    _install_opaque_call_obligation(context, call, first)
    _install_opaque_call_obligation(context, call, second)

    roster = context.opaque_source_call_obligations[coordinate]
    assert roster.obligations == (first, second)
    assert roster.owner(first.resolved_object_cid) is first
    assert roster.owner(second.resolved_object_cid) is second
    # Absence is None and nothing else.
    assert roster.owner("blake3-512:" + "9" * 128) is None
    # The consumed classification is unchanged by the extra seat.
    assert roster.target_name == "missing_helper"
    assert roster.resolution_kind == "call-target-source-absent"


def test_owners_are_seated_in_owner_order_whatever_the_install_order():
    from sugar_lift_py_tests.context_manager_resolution import (
        OpaqueSourceCallObligationV1,
    )

    context, call, coordinate = _opaque_probe_call()
    low = OpaqueSourceCallObligationV1(
        coordinate, "missing_helper", "blake3-512:" + "1" * 128
    )
    high = OpaqueSourceCallObligationV1(
        coordinate, "missing_helper", "blake3-512:" + "2" * 128
    )
    _install_opaque_call_obligation(context, call, high)
    _install_opaque_call_obligation(context, call, low)
    assert context.opaque_source_call_obligations[coordinate].obligations == (
        low,
        high,
    )


def test_disagreeing_owners_panic_rather_than_void_the_file():
    """Two owners, two classifications: a countable panic, NOT a BackendDefect.

    A BackendDefect at this coordinate is an instrument failure — the file
    produces no terminal a reader can judge. A genuine disagreement about what
    the callee is must land as a construction panic, which the census counts.
    """
    from sugar_lift_py_tests.context_manager_resolution import (
        OpaqueSourceCallObligationV1,
    )
    from sugar_lift_py_tests.gap import ConstructionPanic
    from sugar_source_tree.panic import BackendDefect

    context, call, coordinate = _opaque_probe_call()
    _install_opaque_call_obligation(
        context,
        call,
        OpaqueSourceCallObligationV1(
            coordinate,
            "missing_helper",
            "blake3-512:" + "1" * 128,
            resolution_kind="call-target-source-absent",
        ),
    )
    with pytest.raises(ConstructionPanic) as caught:
        _install_opaque_call_obligation(
            context,
            call,
            OpaqueSourceCallObligationV1(
                coordinate,
                "missing_helper",
                "blake3-512:" + "2" * 128,
                resolution_kind="call-graph-cycle",
            ),
        )
    assert not isinstance(caught.value, BackendDefect)
    message = str(caught.value)
    assert "authenticated owners disagree about one opaque call" in message
    assert "call-target-source-absent:missing_helper" in message
    assert "call-graph-cycle:missing_helper" in message
    # The panic is refusal, not mutation: the first owner's seat is intact and
    # no half-written roster is left behind.
    roster = context.opaque_source_call_obligations[coordinate]
    assert roster.resolution_kind == "call-target-source-absent"
    assert len(roster.obligations) == 1


def test_roster_refuses_a_repeated_owner():
    from sugar_lift_py_tests.context_manager_resolution import (
        OpaqueSourceCallObligationV1,
        OpaqueSourceCallRosterV1,
    )

    _context, _call, coordinate = _opaque_probe_call()
    row = OpaqueSourceCallObligationV1(
        coordinate, "missing_helper", "blake3-512:" + "1" * 128
    )
    with pytest.raises(ValueError, match="seats one owner twice"):
        OpaqueSourceCallRosterV1(
            coordinate, "missing_helper", "opaque-call-target", (row, row)
        )


def test_roster_refuses_unordered_owners():
    from sugar_lift_py_tests.context_manager_resolution import (
        OpaqueSourceCallObligationV1,
        OpaqueSourceCallRosterV1,
    )

    _context, _call, coordinate = _opaque_probe_call()
    low = OpaqueSourceCallObligationV1(
        coordinate, "missing_helper", "blake3-512:" + "1" * 128
    )
    high = OpaqueSourceCallObligationV1(
        coordinate, "missing_helper", "blake3-512:" + "2" * 128
    )
    with pytest.raises(ValueError, match="not owner-ordered"):
        OpaqueSourceCallRosterV1(
            coordinate, "missing_helper", "opaque-call-target", (high, low)
        )


def test_roster_refuses_cross_wired_testimony():
    from sugar_lift_py_tests.context_manager_resolution import (
        OpaqueSourceCallObligationV1,
        OpaqueSourceCallRosterV1,
    )

    _context, _call, coordinate = _opaque_probe_call()
    row = OpaqueSourceCallObligationV1(
        coordinate, "missing_helper", "blake3-512:" + "1" * 128
    )
    with pytest.raises(ValueError, match="testimony is cross-wired"):
        OpaqueSourceCallRosterV1(
            coordinate, "other_helper", "opaque-call-target", (row,)
        )


def test_roster_refuses_to_name_no_owner():
    from sugar_lift_py_tests.context_manager_resolution import (
        OpaqueSourceCallRosterV1,
    )

    _context, _call, coordinate = _opaque_probe_call()
    with pytest.raises(ValueError, match="names no authenticated owner"):
        OpaqueSourceCallRosterV1(
            coordinate, "missing_helper", "opaque-call-target", ()
        )


def test_second_owner_does_not_change_what_the_call_constructs():
    """The consumer entrance: CallSiteSugar still reads one kind:name.

    ``Call._construct_sugar`` looks the coordinate up and projects
    ``contract_resolution_gap``. Seating a second owner must not change that
    projection, and must not make the lookup ambiguous.
    """
    from sugar_lift_py_tests.context_manager_resolution import (
        OpaqueSourceCallObligationV1,
    )

    context, call, coordinate = _opaque_probe_call()
    _install_opaque_call_obligation(
        context,
        call,
        OpaqueSourceCallObligationV1(
            coordinate,
            "missing_helper",
            "blake3-512:" + "1" * 128,
            resolution_kind="call-target-source-absent",
        ),
    )
    before = call.sugar()
    # Not bridged, never renamed: the call stays its own edge (item 18).
    assert before.target_name == "missing_helper"
    assert (
        before.contract_resolution_gap
        == "call-target-source-absent:missing_helper"
    )

    _install_opaque_call_obligation(
        context,
        call,
        OpaqueSourceCallObligationV1(
            coordinate,
            "missing_helper",
            "blake3-512:" + "2" * 128,
            resolution_kind="call-target-source-absent",
        ),
    )
    after = call.sugar()
    assert after.target_name == "missing_helper"
    assert (
        after.contract_resolution_gap == "call-target-source-absent:missing_helper"
    )


def test_builtin_named_call_is_not_false_opaque_call_target(tmp_path):
    """Python builtin names are not free-name opaques at frame resolution.

    ``len`` is in the builtin temporal. Frame scan must not abort as a
    call-target gap; construction may still refuse later when the builtin is
    not yet a reducible force_floor (stage-keyed gap).
    """
    graph, resolved, actual, call_site = _resolved(
        tmp_path, "def make_guard(expected):\n    return len(expected)\n"
    )

    result = construct_manager_behavior(
        resolved, graph=graph, actuals=(actual,), call_site=call_site
    )

    assert isinstance(result, ManagerConstructionGapV1)
    assert result.kind not in _CALL_TARGET_GAP_KINDS, result
    assert result.kind in {"non-manager-result", "force-floor"}, result


def test_raises_style_if_not_args_factory_projects_guarded_return(tmp_path):
    """Dual-mode EffectBoundary factory: ``if not args: return CM(x)`` constructs.

    Residual without GuardedReturn unwrap was non-manager-result:BlockValue or
    force-floor:truth:RaiseValue / unspecialized formal. Vendor-neutral shape —
    no pytest/pandas name branch.
    """
    implementation = (
        "class RaisesExc:\n"
        "    def __init__(self, expected_exception=None):\n"
        "        self.expected_exception = expected_exception\n"
        "    def __enter__(self):\n"
        "        return self\n"
        "    def __exit__(self, effect_type, effect, traceback):\n"
        "        return effect_type is self.expected_exception\n\n"
        "def raises(expected_exception=None, *args):\n"
        "    if not args:\n"
        "        return RaisesExc(expected_exception)\n"
    )
    graph, resolved, actual, call_site = _resolved(
        tmp_path, implementation, exported="raises"
    )

    result = construct_manager_behavior(
        resolved, graph=graph, actuals=(actual,), call_site=call_site
    )

    detail = getattr(result, "detail", None) or ""
    assert "BindingCoordinateRefSugar" not in detail, result
    assert "unspecialized source-call formal" not in detail, result
    assert "truth:RaiseValue" not in detail, result
    assert not (
        isinstance(result, ManagerConstructionGapV1)
        and result.kind == "non-manager-result"
        and result.detail == "BlockValue"
    ), result
    assert isinstance(result, ConstructedManagerBehaviorV1), (
        f"expected ConstructedManagerBehaviorV1, got {type(result).__name__}"
        f" kind={getattr(result, 'kind', None)} detail={detail!r}"
    )
    fields = {field.name: field.value for field in result.receiver_state.fields}
    assert fields["expected_exception"] is actual.value


def test_raises_style_kwargs_return_attaches_constructor_body(tmp_path):
    """General ``return CM(x, **kwargs)`` is not bodyless CallSiteValue."""
    implementation = (
        "class RaisesExc:\n"
        "    def __init__(self, expected_exception=None, match=None, check=None):\n"
        "        self.expected_exception = expected_exception\n"
        "        self.match = match\n"
        "        self.check = check\n"
        "    def __enter__(self):\n"
        "        return self\n"
        "    def __exit__(self, effect_type, effect, traceback):\n"
        "        return False\n\n"
        "def raises(expected_exception=None, *args, **kwargs):\n"
        "    if not args:\n"
        "        return RaisesExc(expected_exception, **kwargs)\n"
    )
    graph, resolved, actual, call_site = _resolved(
        tmp_path, implementation, exported="raises"
    )

    result = construct_manager_behavior(
        resolved, graph=graph, actuals=(actual,), call_site=call_site
    )

    detail = getattr(result, "detail", None) or ""
    assert not (
        isinstance(result, ManagerConstructionGapV1)
        and result.kind == "non-manager-result"
        and result.detail == "CallSiteValue"
    ), result
    assert "missing callsite body" not in detail, result
    assert isinstance(result, ConstructedManagerBehaviorV1), (
        f"expected ConstructedManagerBehaviorV1, got {type(result).__name__}"
        f" kind={getattr(result, 'kind', None)} detail={detail!r}"
    )
    fields = {field.name: field.value for field in result.receiver_state.fields}
    assert fields["expected_exception"] is actual.value


def test_raises_style_kwargs_return_stores_match_from_factory_keyword(tmp_path):
    """Factory ``raises(x, match="boom")`` stores match via ``return CM(x, **kwargs)``."""
    implementation = (
        "class RaisesExc:\n"
        "    def __init__(self, expected_exception=None, match=None, check=None):\n"
        "        self.expected_exception = expected_exception\n"
        "        self.match = match\n"
        "        self.check = check\n"
        "    def __enter__(self):\n"
        "        return self\n"
        "    def __exit__(self, effect_type, effect, traceback):\n"
        "        return False\n\n"
        "def raises(expected_exception=None, *args, **kwargs):\n"
        "    if not args:\n"
        "        return RaisesExc(expected_exception, **kwargs)\n"
    )
    graph = DependencyArtifactGraph.authenticate(
        _distribution(tmp_path, implementation, exported="raises")
    )
    consumer = 'import arbitrary\narbitrary.raises(23, match="boom")\n'
    path = tmp_path / "consumer.py"
    path.write_text(consumer, encoding="utf-8")
    source_cid = blake3_512_of(consumer.encode())
    receipts, _ = authenticated_import_use_receipts(tmp_path, path, consumer, source_cid)
    resolved = resolve_import_binding(receipts[0], graph=graph)
    assert isinstance(resolved, ResolvedPythonObjectV1)
    source_file = SourceFile((consumer, str(path), source_cid))
    call = next(item for item in source_file.nodes() if isinstance(item, Call))
    literal = next(item for item in call.args if isinstance(item, Constant))
    keyword = next(item for item in call.keywords if item.arg == "match")
    from sugar_lift_py_tests.floor import StringValue
    from sugar_lift_py_tests.ir import _term_content_cid

    exception_actual = TermValue(23)
    match_value = StringValue("boom")
    result = construct_manager_behavior(
        resolved,
        graph=graph,
        actuals=(
            ConstructedCallActualV1(
                literal,
                exception_actual,
                ConstructedValueTestimonyV1.mint(
                    literal.fragment,
                    _term_content_cid(exception_actual.to_term(owner="test")),
                ),
            ),
        ),
        keyword_actuals=(
            (
                "match",
                ConstructedCallActualV1(
                    keyword.value,
                    match_value,
                    ConstructedValueTestimonyV1.mint(
                        keyword.value.fragment,
                        _term_content_cid(match_value.to_term(owner="test")),
                    ),
                ),
            ),
        ),
        call_site=call.fragment,
    )
    detail = getattr(result, "detail", None) or ""
    assert isinstance(result, ConstructedManagerBehaviorV1), (
        f"expected ConstructedManagerBehaviorV1, got {type(result).__name__}"
        f" kind={getattr(result, 'kind', None)} detail={detail!r}"
    )
    fields = {field.name: field.value for field in result.receiver_state.fields}
    assert fields["expected_exception"] is exception_actual
    assert fields["match"] == match_value


def test_factory_kwargs_return_applies_super_init_field_stores(tmp_path):
    """Factory ``return CM(x, **kwargs)`` runs ``super().__init__`` field stores."""
    implementation = (
        "class AbstractRaises:\n"
        "    def __init__(self, match=None, check=None):\n"
        "        self.match = match\n"
        "        self.check = check\n"
        "        self._fail_reason = None\n"
        "class RaisesExc(AbstractRaises[object]):\n"
        "    def __init__(self, expected_exception=None, match=None, check=None):\n"
        "        super().__init__(match=match, check=check)\n"
        "        self.expected_exceptions = expected_exception\n"
        "    def __enter__(self):\n"
        "        return self\n"
        "    def __exit__(self, effect_type, effect, traceback):\n"
        "        return False\n\n"
        "def raises(expected_exception=None, *args, **kwargs):\n"
        "    if not args:\n"
        "        return RaisesExc(expected_exception, **kwargs)\n"
    )
    graph = DependencyArtifactGraph.authenticate(
        _distribution(tmp_path, implementation, exported="raises")
    )
    consumer = 'import arbitrary\narbitrary.raises(23, match="boom")\n'
    path = tmp_path / "consumer.py"
    path.write_text(consumer, encoding="utf-8")
    source_cid = blake3_512_of(consumer.encode())
    receipts, _ = authenticated_import_use_receipts(tmp_path, path, consumer, source_cid)
    resolved = resolve_import_binding(receipts[0], graph=graph)
    assert isinstance(resolved, ResolvedPythonObjectV1)
    source_file = SourceFile((consumer, str(path), source_cid))
    call = next(item for item in source_file.nodes() if isinstance(item, Call))
    literal = next(item for item in call.args if isinstance(item, Constant))
    keyword = next(item for item in call.keywords if item.arg == "match")
    from sugar_lift_py_tests.floor import NoneValue, StringValue
    from sugar_lift_py_tests.ir import _term_content_cid

    exception_actual = TermValue(23)
    match_value = StringValue("boom")
    result = construct_manager_behavior(
        resolved,
        graph=graph,
        actuals=(
            ConstructedCallActualV1(
                literal,
                exception_actual,
                ConstructedValueTestimonyV1.mint(
                    literal.fragment,
                    _term_content_cid(exception_actual.to_term(owner="test")),
                ),
            ),
        ),
        keyword_actuals=(
            (
                "match",
                ConstructedCallActualV1(
                    keyword.value,
                    match_value,
                    ConstructedValueTestimonyV1.mint(
                        keyword.value.fragment,
                        _term_content_cid(match_value.to_term(owner="test")),
                    ),
                ),
            ),
        ),
        call_site=call.fragment,
    )
    detail = getattr(result, "detail", None) or ""
    assert isinstance(result, ConstructedManagerBehaviorV1), (
        f"expected ConstructedManagerBehaviorV1, got {type(result).__name__}"
        f" kind={getattr(result, 'kind', None)} detail={detail!r}"
    )
    fields = {field.name: field.value for field in result.receiver_state.fields}
    assert fields["expected_exceptions"] is exception_actual
    assert fields["match"] == match_value
    assert isinstance(fields["_fail_reason"], NoneValue)


def test_factory_kwargs_return_applies_super_init_stores_after_string_match_branch(tmp_path):
    """Factory ``return CM(x, **kwargs)`` keeps unguarded tail stores after a folded str match."""
    implementation = (
        "class AbstractRaises:\n"
        "    def __init__(self, match=None, check=None):\n"
        "        if isinstance(match, str):\n"
        "            self.match = match\n"
        "        else:\n"
        "            self.match = match\n"
        "        self.check = check\n"
        "        self._fail_reason: str | None = None\n"
        "class RaisesExc(AbstractRaises[object]):\n"
        "    def __init__(self, expected_exception=None, match=None, check=None):\n"
        "        super().__init__(match=match, check=check)\n"
        "        self.expected_exceptions = expected_exception\n"
        "    def __enter__(self):\n"
        "        return self\n"
        "    def __exit__(self, effect_type, effect, traceback):\n"
        "        return False\n\n"
        "def raises(expected_exception=None, *args, **kwargs):\n"
        "    if not args:\n"
        "        return RaisesExc(expected_exception, **kwargs)\n"
    )
    graph = DependencyArtifactGraph.authenticate(
        _distribution(tmp_path, implementation, exported="raises")
    )
    consumer = 'import arbitrary\narbitrary.raises(23, match="boom")\n'
    path = tmp_path / "consumer.py"
    path.write_text(consumer, encoding="utf-8")
    source_cid = blake3_512_of(consumer.encode())
    receipts, _ = authenticated_import_use_receipts(tmp_path, path, consumer, source_cid)
    resolved = resolve_import_binding(receipts[0], graph=graph)
    assert isinstance(resolved, ResolvedPythonObjectV1)
    source_file = SourceFile((consumer, str(path), source_cid))
    call = next(item for item in source_file.nodes() if isinstance(item, Call))
    literal = next(item for item in call.args if isinstance(item, Constant))
    keyword = next(item for item in call.keywords if item.arg == "match")
    from sugar_lift_py_tests.floor import NoneValue, StringValue
    from sugar_lift_py_tests.ir import _term_content_cid

    exception_actual = TermValue(23)
    match_value = StringValue("boom")
    result = construct_manager_behavior(
        resolved,
        graph=graph,
        actuals=(
            ConstructedCallActualV1(
                literal,
                exception_actual,
                ConstructedValueTestimonyV1.mint(
                    literal.fragment,
                    _term_content_cid(exception_actual.to_term(owner="test")),
                ),
            ),
        ),
        keyword_actuals=(
            (
                "match",
                ConstructedCallActualV1(
                    keyword.value,
                    match_value,
                    ConstructedValueTestimonyV1.mint(
                        keyword.value.fragment,
                        _term_content_cid(match_value.to_term(owner="test")),
                    ),
                ),
            ),
        ),
        call_site=call.fragment,
    )
    detail = getattr(result, "detail", None) or ""
    assert isinstance(result, ConstructedManagerBehaviorV1), (
        f"expected ConstructedManagerBehaviorV1, got {type(result).__name__}"
        f" kind={getattr(result, 'kind', None)} detail={detail!r}"
    )
    fields = {field.name: field.value for field in result.receiver_state.fields}
    assert fields["expected_exceptions"] is exception_actual
    assert isinstance(fields["_fail_reason"], NoneValue)
    assert fields["match"] == match_value


def test_typing_cast_returns_the_value_argument(tmp_path):
    """``from typing import cast; cast(T, value)`` returns value unchanged."""
    implementation = (
        "from typing import cast\n"
        "class RaisesExc:\n"
        "    def __init__(self):\n"
        '        self.payload = cast(object, "boom")\n'
        "    def __enter__(self):\n"
        "        return self\n"
        "    def __exit__(self, effect_type, effect, traceback):\n"
        "        return False\n\n"
        "def raises():\n"
        "    return RaisesExc()\n"
    )
    graph = DependencyArtifactGraph.authenticate(
        _distribution(tmp_path, implementation, exported="raises")
    )
    consumer = "import arbitrary\narbitrary.raises()\n"
    path = tmp_path / "consumer.py"
    path.write_text(consumer, encoding="utf-8")
    source_cid = blake3_512_of(consumer.encode())
    receipts, _ = authenticated_import_use_receipts(tmp_path, path, consumer, source_cid)
    resolved = resolve_import_binding(receipts[0], graph=graph)
    assert isinstance(resolved, ResolvedPythonObjectV1)
    source_file = SourceFile((consumer, str(path), source_cid))
    call = next(item for item in source_file.nodes() if isinstance(item, Call))
    from sugar_lift_py_tests.floor import StringValue

    result = construct_manager_behavior(
        resolved,
        graph=graph,
        actuals=(),
        keyword_actuals=(),
        call_site=call.fragment,
    )
    detail = getattr(result, "detail", None) or ""
    assert isinstance(result, ConstructedManagerBehaviorV1), (
        f"expected ConstructedManagerBehaviorV1, got {type(result).__name__}"
        f" kind={getattr(result, 'kind', None)} detail={detail!r}"
    )
    fields = {field.name: field.value for field in result.receiver_state.fields}
    assert fields["payload"] == StringValue("boom")


def test_factory_kwargs_match_cites_variadic_keyword_entry(tmp_path):
    """Factory ``raises(x, match="boom")`` cites match as a ``**kwargs`` entry."""
    implementation = (
        "class RaisesExc:\n"
        "    def __init__(self, expected_exception=None, match=None, check=None):\n"
        "        self.expected_exceptions = expected_exception\n"
        "        self.match = match\n"
        "        self.check = check\n"
        "    def __enter__(self):\n"
        "        return self\n"
        "    def __exit__(self, effect_type, effect, traceback):\n"
        "        if effect_type is None:\n"
        "            raise RuntimeError()\n"
        "        return (effect_type is self.expected_exceptions) and (\n"
        "            effect.message == self.match\n"
        "        )\n\n"
        "def raises(expected_exception=None, *args, **kwargs):\n"
        "    if not args:\n"
        "        return RaisesExc(expected_exception, **kwargs)\n"
    )
    distribution = _distribution(tmp_path, implementation, exported="raises")
    consumer = (
        "import arbitrary\n"
        "def use_raises():\n"
        '    with arbitrary.raises(ValueError, match="boom"):\n'
        "        raise ValueError(\"boom\")\n"
    )
    path = tmp_path / "consumer.py"
    path.write_text(consumer, encoding="utf-8")
    from sugar_lift_py_tests.context_manager_contract import (
        EffectBoundarySemanticsV1,
        ExpectsModeV1,
        VariadicKeywordEntryProjectionV1,
    )
    from sugar_lift_py_tests.context_manager_resolution import (
        SourceDerivedContextManagerRefV1,
        TreeConstructionContextV1,
    )

    context = TreeConstructionContextV1.for_source_call_construction()
    tree = SourceFile(
        (consumer, str(path), blake3_512_of(consumer.encode("utf-8"))),
        construction_context=context,
    )
    populate_source_derived_resource_refs(
        tree,
        root=tmp_path,
        path=path,
        distribution_index={"arbitrary": distribution},
        session=SourceResolutionSession(
            enrolled_distributions=frozenset({distribution.metadata["Name"]})
        ),
    )
    assert context.source_derived_contract_refs, context.source_derived_gaps
    reference = next(iter(context.source_derived_contract_refs.values()))
    assert isinstance(reference, SourceDerivedContextManagerRefV1), reference
    assert isinstance(reference.semantics, EffectBoundarySemanticsV1), reference.semantics
    assert isinstance(reference.semantics.mode, ExpectsModeV1)
    assert reference.semantics.message_pattern_operand == (
        VariadicKeywordEntryProjectionV1(2, "match")
    )


def test_factory_nested_same_module_with_derives_before_frame_projection(tmp_path):
    """A callee nested ``with LocalClass()`` uses the same-module derivation door.

    ``source_visible_call_frame`` sugars every body statement, including a
    nested With that consumer populate never walked. The inner constructor
    is a same-module ClassDef, so the factory frame must read a published
    contract — not a missing-derivation panic and not a soft unresolved With.
    """
    implementation = (
        "class RaisesExc:\n"
        "    def __init__(self, expected_exception=None):\n"
        "        self.expected_exception = expected_exception\n"
        "    def __enter__(self):\n"
        "        return self\n"
        "    def __exit__(self, effect_type, effect, traceback):\n"
        "        if effect_type is None:\n"
        "            raise RuntimeError()\n"
        "        return effect_type is self.expected_exception\n\n"
        "def raises(expected_exception=None):\n"
        "    with RaisesExc(ValueError):\n"
        "        raise ValueError('nested')\n"
        "    return RaisesExc(expected_exception)\n"
    )
    graph, resolved, actual, call_site = _resolved(
        tmp_path, implementation, exported="raises"
    )

    result = construct_manager_behavior(
        resolved, graph=graph, actuals=(actual,), call_site=call_site
    )

    detail = getattr(result, "detail", None) or ""
    assert "no context-manager derivation" not in detail, result
    assert getattr(result, "kind", None) != "source-body-gap", result
    assert isinstance(result, ConstructedManagerBehaviorV1), (
        f"expected ConstructedManagerBehaviorV1, got {type(result).__name__}"
        f" kind={getattr(result, 'kind', None)} detail={detail!r}"
    )
    fields = {field.name: field.value for field in result.receiver_state.fields}
    assert fields["expected_exception"] is actual.value


def test_factory_nested_formal_singleton_tuple_derives_installed_like_exit(tmp_path):
    """A nested ``RaisesExc(expected_exception)`` stored as ``(expected,)`` derives.

    The matching formula is ``exc_type is self.expected_exceptions[0]``. The
    absent-effect diagnostic reads ``[0].__name__``. When the constructor
    actual is the enclosing formal rather than a class, that attribute must
    stand as a named coordinate so FormalArgumentProjection can seal; it
    must not invent a concrete type name.
    """
    implementation = (
        "class RaisesExc:\n"
        "    def __init__(self, expected_exception=None):\n"
        "        self.expected_exceptions = (expected_exception,)\n"
        "    def __enter__(self):\n"
        "        return self\n"
        "    def __exit__(self, exc_type, exc_val, exc_tb):\n"
        "        if exc_type is None:\n"
        "            if not self.expected_exceptions:\n"
        "                raise RuntimeError('DID NOT RAISE any exception')\n"
        "            if len(self.expected_exceptions) == 1:\n"
        "                raise RuntimeError(self.expected_exceptions[0].__name__)\n"
        "            raise RuntimeError('several')\n"
        "        return exc_type is self.expected_exceptions[0]\n\n"
        "def raises(expected_exception=None):\n"
        "    with RaisesExc(expected_exception):\n"
        "        raise ValueError('nested')\n"
        "    return RaisesExc(expected_exception)\n"
    )
    graph, resolved, actual, call_site = _resolved_type_actual(
        tmp_path, implementation, exported="raises"
    )

    result = construct_manager_behavior(
        resolved, graph=graph, actuals=(actual,), call_site=call_site
    )

    detail = getattr(result, "detail", None) or ""
    assert "no context-manager derivation" not in detail, result
    assert getattr(result, "kind", None) != "source-body-gap", result
    assert isinstance(result, ConstructedManagerBehaviorV1), (
        f"expected ConstructedManagerBehaviorV1, got {type(result).__name__}"
        f" kind={getattr(result, 'kind', None)} detail={detail!r}"
    )


def test_dual_mode_effect_boundary_installs_with_effect_boundary_sugar(tmp_path):
    """Vendor-neutral dual-mode factory populates EffectBoundary With sugar."""
    implementation = (
        "class RenamedBoundary:\n"
        "    def __init__(self, expected):\n"
        "        self.expected = expected\n"
        "    def __enter__(self):\n"
        "        return self\n"
        "    def __exit__(self, effect_type, effect, traceback):\n"
        "        if effect_type is None:\n"
        "            raise RuntimeError()\n"
        "        return effect_type is self.expected\n\n"
        "def make_boundary(expected, *args):\n"
        "    if not args:\n"
        "        return RenamedBoundary(expected)\n"
    )
    distribution = _distribution(tmp_path, implementation, exported="make_boundary")
    consumer = (
        "import arbitrary\n"
        "def use_boundary():\n"
        "    with arbitrary.make_boundary(ValueError):\n"
        "        pass\n"
    )
    path = tmp_path / "consumer.py"
    path.write_text(consumer, encoding="utf-8")
    from sugar_lift_py_tests.context_manager_resolution import (
        SourceDerivedContextManagerRefV1,
        TreeConstructionContextV1,
    )
    from sugar_lift_py_tests.context_manager_contract import (
        EffectBoundarySemanticsV1,
        ExpectsModeV1,
    )
    from sugar_lift_py_tests.sugar.with_effect_boundary_sugar import (
        WithEffectBoundarySugar,
    )
    from sugar_lift_py_tests.effect import ExpectationNotMetEffect
    from sugar_lift_py_tests.outcome import Halted, outcome_to_exitset

    context = TreeConstructionContextV1.for_source_call_construction()
    tree = SourceFile(
        (consumer, str(path), blake3_512_of(consumer.encode("utf-8"))),
        construction_context=context,
    )
    populate_source_derived_resource_refs(
        tree,
        root=tmp_path,
        path=path,
        distribution_index={"arbitrary": distribution},
        session=SourceResolutionSession(
            enrolled_distributions=frozenset({distribution.metadata["Name"]})
        ),
    )

    reference = next(iter(context.source_derived_contract_refs.values()))
    assert isinstance(reference, SourceDerivedContextManagerRefV1), reference
    assert isinstance(reference.semantics, EffectBoundarySemanticsV1)
    assert isinstance(reference.semantics.mode, ExpectsModeV1)
    with_node = next(node for node in tree.nodes() if node.kind == "With")
    boundary = with_node.sugar()
    assert isinstance(boundary, WithEffectBoundarySugar)
    # Empty body when expects-raise: red ExpectationNotMet (normal completion
    # while an effect was required). Matching raise is a separate shape.
    exits = outcome_to_exitset(boundary.desugar()).exits
    assert len(exits) == 1
    assert isinstance(exits[0], Halted)
    assert isinstance(exits[0].effect, ExpectationNotMetEffect)


def test_renamed_manager_protocol_retains_ordinary_method_call_frames(tmp_path):
    graph, resolved, actual, call_site = _resolved(
        tmp_path,
        "class ArbitraryGuard:\n"
        "    def __init__(self, marker):\n"
        "        self.marker = marker\n\n"
        "    def __enter__(self):\n"
        "        return self.marker\n\n"
        "    def __exit__(self, effect_type, effect, traceback):\n"
        "        return self.marker\n\n"
        "def make_guard(marker):\n"
        "    return ArbitraryGuard(marker)\n",
    )
    behavior = construct_manager_behavior(
        resolved, graph=graph, actuals=(actual,), call_site=call_site
    )
    assert isinstance(behavior, ConstructedManagerBehaviorV1)

    protocol = construct_manager_protocol(behavior, exit_face_id="fixture-face")

    assert isinstance(protocol, ConstructedManagerProtocolV1)
    assert protocol.enter_call.body is not None
    assert protocol.exit_call.body is not None
    assert protocol.enter_frame_cid.startswith("blake3-512:")
    assert protocol.exit_frame_cid.startswith("blake3-512:")
    assert protocol.protocol_construction_cid.startswith("blake3-512:")
    assert protocol.enter_call.formal_coordinate_cids
    enter_block = protocol.enter_call.force_floor(
        None, owner="renamed enter", project_callsite=False
    )
    exit_block = protocol.exit_call.force_floor(
        None, owner="renamed exit", project_callsite=False
    )
    assert isinstance(enter_block, BlockValue)
    assert isinstance(exit_block, BlockValue)
    assert enter_block.statements == (ReturnValue(actual.value),)
    assert exit_block.statements == (ReturnValue(actual.value),)


def test_enter_receiver_store_populates_same_identity_for_exit_read(tmp_path):
    graph, resolved, actual, call_site = _resolved(
        tmp_path,
        "class RenamedGuard:\n"
        "    def __init__(self, marker):\n"
        "        ...\n\n"
        "    def __init__(self, marker):\n"
        "        self.marker = marker\n\n"
        "    def __enter__(self):\n"
        "        self.after_enter = self.marker\n"
        "        return self.after_enter\n\n"
        "    def __exit__(self, effect_type, effect, traceback):\n"
        "        return self.after_enter\n\n"
        "def make_guard(marker):\n"
        "    return RenamedGuard(marker)\n",
    )
    behavior = construct_manager_behavior(
        resolved, graph=graph, actuals=(actual,), call_site=call_site
    )
    assert isinstance(behavior, ConstructedManagerBehaviorV1)
    protocol = construct_manager_protocol(behavior, exit_face_id="renamed-state-face")
    assert isinstance(protocol, ConstructedManagerProtocolV1)

    from sugar_lift_py_tests.outcome import Completed, outcome_to_exitset

    exit_ = outcome_to_exitset(protocol.exit_outcome())

    assert len(exit_.exits) == 1
    assert isinstance(exit_.exits[0], Completed)
    block = exit_.exits[0].value
    assert isinstance(block, BlockValue)
    assert block.statements[-1] == ReturnValue(actual.value)


def test_unwritten_receiver_field_stays_typed_loud_across_method_lifetimes(
    tmp_path,
):
    graph, resolved, actual, call_site = _resolved(
        tmp_path,
        "class RenamedGuard:\n"
        "    def __init__(self, marker):\n"
        "        self.marker = marker\n\n"
        "    def __enter__(self):\n"
        "        return self.marker\n\n"
        "    def __exit__(self, effect_type, effect, traceback):\n"
        "        return self.never_written\n\n"
        "def make_guard(marker):\n"
        "    return RenamedGuard(marker)\n",
    )
    behavior = construct_manager_behavior(
        resolved, graph=graph, actuals=(actual,), call_site=call_site
    )
    assert isinstance(behavior, ConstructedManagerBehaviorV1)
    protocol = construct_manager_protocol(behavior, exit_face_id="missing-state-face")
    assert isinstance(protocol, ConstructedManagerProtocolV1)

    from sugar_lift_py_tests.gap.panic import ConstructionPanic

    with pytest.raises(ConstructionPanic) as raised:
        protocol.exit_outcome()

    assert raised.value.info.owner == "ObjectValue.attribute"
    assert raised.value.info.observed == "ObjectValue.never_written"


def test_constructor_partition_does_not_inherit_store_across_guarded_faces(
    tmp_path,
):
    graph, resolved, actual, call_site = _resolved(
        tmp_path,
        "class RenamedGuard:\n"
        "    def __init__(self, marker):\n"
        "        if marker:\n"
        "            self.maybe_written = marker\n\n"
        "    def __enter__(self):\n"
        "        return self\n\n"
        "    def __exit__(self, effect_type, effect, traceback):\n"
        "        return self.maybe_written\n\n"
        "def make_guard(marker):\n"
        "    return RenamedGuard(marker)\n",
    )
    from sugar_lift_py_tests.floor import (
        ReceiverStatePartitionValue,
        SymbolicValue,
    )
    from sugar_lift_py_tests.ir import _term_content_cid, make_var

    symbolic = SymbolicValue(make_var("constructor-guard"))
    actual = ConstructedCallActualV1(
        actual.node,
        symbolic,
        ConstructedValueTestimonyV1.mint(
            actual.node.fragment,
            _term_content_cid(symbolic.to_term(owner="partition-lying-twin")),
        ),
    )
    behavior = construct_manager_behavior(
        resolved, graph=graph, actuals=(actual,), call_site=call_site
    )
    assert isinstance(behavior, ConstructedManagerBehaviorV1)
    assert isinstance(behavior.receiver_state, ReceiverStatePartitionValue)
    from sugar_lift_py_tests.outcome import Completed

    field_sets = {
        tuple(field.name for field in face.value.fields)
        for face in behavior.receiver_state.exits.exits
        if isinstance(face, Completed)
    }
    assert field_sets == {(), ("maybe_written",)}
    assert (
        len(
            {
                face.value.identity
                for face in behavior.receiver_state.exits.exits
                if isinstance(face, Completed)
            }
        )
        == 1
    )

    protocol = construct_manager_protocol(behavior, exit_face_id="partition-lying-face")
    assert isinstance(protocol, ConstructedManagerProtocolV1)
    from sugar_lift_py_tests.gap.panic import ConstructionPanic

    with pytest.raises(ConstructionPanic):
        protocol.exit_outcome()


def test_resource_enter_partition_does_not_inherit_unacquired_state(tmp_path):
    graph, resolved, actual, call_site = _resolved(
        tmp_path,
        "class RenamedResource:\n"
        "    def __init__(self, marker):\n"
        "        self.marker = marker\n\n"
        "    def __enter__(self):\n"
        "        if self.marker:\n"
        "            self.acquired = self.marker\n"
        "        return self\n\n"
        "    def __exit__(self, effect_type, effect, traceback):\n"
        "        return self.acquired\n\n"
        "def make_resource(marker):\n"
        "    return RenamedResource(marker)\n",
        exported="make_resource",
    )
    from sugar_lift_py_tests.floor import SymbolicValue
    from sugar_lift_py_tests.ir import _term_content_cid, make_var
    from sugar_lift_py_tests.outcome import Completed, outcome_to_exitset

    symbolic = SymbolicValue(make_var("resource-acquisition-guard"))
    actual = ConstructedCallActualV1(
        actual.node,
        symbolic,
        ConstructedValueTestimonyV1.mint(
            actual.node.fragment,
            _term_content_cid(symbolic.to_term(owner="resource-lying-twin")),
        ),
    )
    behavior = construct_manager_behavior(
        resolved, graph=graph, actuals=(actual,), call_site=call_site
    )
    assert isinstance(behavior, ConstructedManagerBehaviorV1)
    protocol = construct_manager_protocol(behavior, exit_face_id="resource-face")
    assert isinstance(protocol, ConstructedManagerProtocolV1)

    transitions = outcome_to_exitset(protocol.enter_resource_outcome())
    completed = tuple(face for face in transitions.exits if isinstance(face, Completed))
    assert {
        tuple(field.name for field in face.value.receiver_state.fields)
        for face in completed
    } == {("marker",), ("acquired", "marker")}

    written = next(
        face.value
        for face in completed
        if any(field.name == "acquired" for field in face.value.receiver_state.fields)
    )
    unwritten = next(
        face.value
        for face in completed
        if all(field.name != "acquired" for field in face.value.receiver_state.fields)
    )
    assert protocol.exit_outcome_for(written) is not None

    from sugar_lift_py_tests.gap.panic import ConstructionPanic

    with pytest.raises(ConstructionPanic) as raised:
        protocol.exit_outcome_for(unwritten)
    assert raised.value.info.owner == "ObjectValue.attribute"
    assert raised.value.info.observed == "ObjectValue.acquired"


def test_resource_enter_state_reaches_exit_without_second_enter(tmp_path):
    graph, resolved, actual, call_site = _resolved(
        tmp_path,
        "class RenamedResource:\n"
        "    def __init__(self, marker):\n"
        "        self.marker = marker\n\n"
        "    def __enter__(self):\n"
        "        self.acquired = self.marker\n"
        "        return self.acquired\n\n"
        "    def __exit__(self, effect_type, effect, traceback):\n"
        "        return self.acquired\n\n"
        "def make_resource(marker):\n"
        "    return RenamedResource(marker)\n",
        exported="make_resource",
    )
    from sugar_lift_py_tests.outcome import Completed, outcome_to_exitset

    behavior = construct_manager_behavior(
        resolved, graph=graph, actuals=(actual,), call_site=call_site
    )
    assert isinstance(behavior, ConstructedManagerBehaviorV1)
    protocol = construct_manager_protocol(behavior, exit_face_id="resource-face")
    assert isinstance(protocol, ConstructedManagerProtocolV1)

    transitions = outcome_to_exitset(protocol.enter_resource_outcome())
    assert len(transitions.exits) == 1
    transition = transitions.exits[0]
    assert isinstance(transition, Completed)
    assert transition.value.enter_value.statements[-1] == ReturnValue(actual.value)

    exit_ = outcome_to_exitset(protocol.exit_outcome_for(transition.value))
    assert len(exit_.exits) == 1
    assert isinstance(exit_.exits[0], Completed)
    assert exit_.exits[0].value.statements[-1] == ReturnValue(actual.value)


def test_ellipsis_only_initializer_stays_typed_loud(tmp_path):
    graph, resolved, actual, call_site = _resolved(
        tmp_path,
        "class RenamedGuard:\n"
        "    def __init__(self, marker):\n"
        "        ...\n\n"
        "    def __enter__(self):\n"
        "        return self\n\n"
        "    def __exit__(self, effect_type, effect, traceback):\n"
        "        return False\n\n"
        "def make_guard(marker):\n"
        "    return RenamedGuard(marker)\n",
    )

    behavior = construct_manager_behavior(
        resolved, graph=graph, actuals=(actual,), call_site=call_site
    )

    assert isinstance(behavior, ManagerConstructionGapV1)
    assert behavior.kind == "force-floor"
    assert "EllipsisValue only" in behavior.detail


def test_manager_missing_source_protocol_method_stays_typed_loud(tmp_path):
    graph, resolved, actual, call_site = _resolved(
        tmp_path,
        "class ArbitraryObject:\n"
        "    def __init__(self, marker):\n"
        "        self.marker = marker\n\n"
        "def make_guard(marker):\n"
        "    return ArbitraryObject(marker)\n",
    )
    behavior = construct_manager_behavior(
        resolved, graph=graph, actuals=(actual,), call_site=call_site
    )
    assert isinstance(behavior, ConstructedManagerBehaviorV1)

    protocol = construct_manager_protocol(behavior, exit_face_id="fixture-face")

    assert isinstance(protocol, ManagerProtocolConstructionGapV1)
    assert protocol.kind == "enter-missing"


def test_renamed_enter_and_exit_halts_remain_method_exitsets(tmp_path):
    graph, resolved, actual, call_site = _resolved(
        tmp_path,
        "class ArbitraryFailingGuard:\n"
        "    def __init__(self, marker):\n"
        "        self.marker = marker\n\n"
        "    def __enter__(self):\n"
        "        raise ValueError('enter')\n\n"
        "    def __exit__(self, effect_type, effect, traceback):\n"
        "        raise TypeError('exit')\n\n"
        "def make_guard(marker):\n"
        "    return ArbitraryFailingGuard(marker)\n",
    )
    behavior = construct_manager_behavior(
        resolved, graph=graph, actuals=(actual,), call_site=call_site
    )
    assert isinstance(behavior, ConstructedManagerBehaviorV1)
    protocol = construct_manager_protocol(behavior, exit_face_id="fixture-face")
    assert isinstance(protocol, ConstructedManagerProtocolV1)

    from sugar_lift_py_tests.outcome import ExitSet, Halted, outcome_to_exitset

    enter = outcome_to_exitset(protocol.enter_outcome())
    exit_ = outcome_to_exitset(protocol.exit_outcome())
    assert isinstance(enter, ExitSet)
    assert isinstance(exit_, ExitSet)
    assert all(isinstance(face, Halted) for face in enter.exits)
    assert all(isinstance(face, Halted) for face in exit_.exits)


def test_fixture_manager_class_bodies_construct_docstrings_and_class_fields():
    from sugar_lift_python_source.source_oracle import path_source
    from sugar_source_tree.nodes import ClassDef

    fixture = (
        Path(__file__).parents[2]
        / "sugar-lift-py-tests/tests/fixtures/with_source_derivation"
        / "arbitrary_manager_module.py"
    )
    source = SourceFile(path_source(str(fixture)))
    classes = {
        item.name: item for item in source.root.body if isinstance(item, ClassDef)
    }

    some_guard = classes["SomeGuard"].sugar().desugar().value
    some_resource = classes["SomeResource"].sugar().desugar().value
    lying_guard = classes["LyingGuard"].sugar().desugar().value
    observation = classes["ObservationSlot"].sugar().desugar().value

    assert some_guard.docstring_cid.startswith("blake3-512:")
    assert some_resource.docstring_cid.startswith("blake3-512:")
    assert lying_guard.docstring_cid.startswith("blake3-512:")
    fields = {field.name: field.value for field in lying_guard.class_fields}
    assert type(fields["claimed_suppression"]).__name__ == "TrueBoolLiteralSugar"
    assert observation.annotation_cids
    assert observation.decorator_cids


def test_nested_class_member_constructs_as_exact_class_field_through_same_door():
    source = SourceFile(
        (
            "class Outer:\n    class Inner:\n        marker = 17\n",
            "nested-class.py",
            "blake3-512:" + ("34" * 64),
        )
    )
    outer = next(item for item in source.root.body if isinstance(item, ClassDef))

    outcome = outer.sugar().desugar()

    from sugar_lift_py_tests.floor import ClassDefinitionValue
    from sugar_lift_py_tests.outcome import Complete

    assert isinstance(outcome, Complete)
    assert isinstance(outcome.value, ClassDefinitionValue)
    nested = {field.name: field.value for field in outcome.value.class_fields}["Inner"]
    assert isinstance(nested, ClassDefinitionValue)
    assert nested.class_name == "Inner"
    assert nested.class_definition_cid.startswith("blake3-512:")


def test_decorated_method_retains_decorator_testimony_in_class_method_frame():
    source = SourceFile(
        (
            "class Renamed:\n"
            "    @wrapper\n"
            "    def operation(self):\n"
            "        return 1\n",
            "decorated-method.py",
            "blake3-512:" + ("35" * 64),
        )
    )
    renamed = next(item for item in source.root.body if isinstance(item, ClassDef))

    outcome = renamed.sugar().desugar()

    from sugar_lift_py_tests.floor import ClassDefinitionValue
    from sugar_lift_py_tests.outcome import Complete

    assert isinstance(outcome, Complete)
    assert isinstance(outcome.value, ClassDefinitionValue)
    method = next(item for item in outcome.value.methods if item.name == "operation")
    assert method.source_call_frame.owner.decorators


def test_local_inherited_manager_methods_follow_authenticated_mro(tmp_path):
    graph, resolved, actual, call_site = _resolved(
        tmp_path,
        "class Ancestor:\n"
        "    def __init__(self, marker):\n"
        "        self.marker = marker\n\n"
        "    def __enter__(self):\n"
        "        return self.marker\n\n"
        "    def __exit__(self, effect_type, effect, traceback):\n"
        "        return False\n\n"
        "class Descendant(Ancestor):\n"
        "    def __init__(self, marker):\n"
        "        self.marker = marker\n\n"
        "def make_guard(marker):\n"
        "    return Descendant(marker)\n",
    )

    behavior = construct_manager_behavior(
        resolved, graph=graph, actuals=(actual,), call_site=call_site
    )

    assert isinstance(behavior, ConstructedManagerBehaviorV1)
    assert behavior.receiver_state.has_method("__enter__")
    assert behavior.receiver_state.has_method("__exit__")
    protocol = construct_manager_protocol(behavior, exit_face_id="inherited-face")
    assert isinstance(protocol, ConstructedManagerProtocolV1)
    assert protocol.enter_outcome() is not None
    assert protocol.exit_outcome() is not None


def test_subscripted_local_base_supplies_inherited_constructor_method(tmp_path):
    """Truthful twin: ``Base[T]`` names Base; its method body is testimony."""
    graph, resolved, actual, call_site = _resolved(
        tmp_path,
        "class Ancestor:\n"
        "    def project(self, value):\n"
        "        return value\n\n"
        "class Descendant(Ancestor[Marker]):\n"
        "    def __init__(self, marker):\n"
        "        self.marker = marker\n\n"
        "    def __enter__(self):\n"
        "        return self.marker\n\n"
        "    def __exit__(self, effect_type, effect, traceback):\n"
        "        return False\n\n"
        "def make_guard(marker):\n"
        "    return Descendant(marker)\n",
    )

    behavior = construct_manager_behavior(
        resolved, graph=graph, actuals=(actual,), call_site=call_site
    )

    assert isinstance(behavior, ConstructedManagerBehaviorV1)
    assert behavior.receiver_state.has_method("project")
    fields = {field.name: field.value for field in behavior.receiver_state.fields}
    assert fields["marker"] is actual.value


def test_computed_base_does_not_supply_inherited_constructor_method(tmp_path):
    """Lying twin: ``base_factory()[T]`` states no source class coordinate."""
    graph, resolved, actual, call_site = _resolved(
        tmp_path,
        "class Ancestor:\n"
        "    def project(self, value):\n"
        "        return value\n\n"
        "class Descendant(base_factory()[Marker]):\n"
        "    def __init__(self, marker):\n"
        "        self.marker = marker\n\n"
        "    def __enter__(self):\n"
        "        return self.marker\n\n"
        "    def __exit__(self, effect_type, effect, traceback):\n"
        "        return False\n\n"
        "def make_guard(marker):\n"
        "    return Descendant(marker)\n",
    )

    behavior = construct_manager_behavior(
        resolved, graph=graph, actuals=(actual,), call_site=call_site
    )

    assert isinstance(behavior, ConstructedManagerBehaviorV1)
    receiver = _sole_completed_receiver(behavior)
    assert not receiver.has_method("project")
    from sugar_lift_py_tests.gap.panic import ConstructionPanic

    with pytest.raises(ConstructionPanic) as caught:
        receiver.call_method_value(
            "project", (actual.value,), owner="computed-base liar", blame=call_site
        )
    assert "Descendant.project" in str(caught.value)


def test_opaque_base_never_fabricates_inherited_manager_methods(tmp_path):
    graph, resolved, actual, call_site = _resolved(
        tmp_path,
        "class Descendant(OpaqueAncestor):\n"
        "    def __init__(self, marker):\n"
        "        self.marker = marker\n\n"
        "def make_guard(marker):\n"
        "    return Descendant(marker)\n",
    )
    behavior = construct_manager_behavior(
        resolved, graph=graph, actuals=(actual,), call_site=call_site
    )

    assert isinstance(behavior, ConstructedManagerBehaviorV1)
    protocol = construct_manager_protocol(behavior, exit_face_id="opaque-base")
    assert isinstance(protocol, ManagerProtocolConstructionGapV1)
    assert protocol.kind == "enter-missing"


def test_renamed_manager_inter_method_call_uses_constructed_method_frame(tmp_path):
    graph, resolved, actual, call_site = _resolved(
        tmp_path,
        "class RenamedGuard:\n"
        "    def __init__(self, marker):\n"
        "        self.marker = marker\n\n"
        "    def project(self):\n"
        "        return self.marker\n\n"
        "    def __enter__(self):\n"
        "        return self.project()\n\n"
        "    def __exit__(self, effect_type, effect, traceback):\n"
        "        return False\n\n"
        "def make_guard(marker):\n"
        "    return RenamedGuard(marker)\n",
    )
    behavior = construct_manager_behavior(
        resolved, graph=graph, actuals=(actual,), call_site=call_site
    )
    assert isinstance(behavior, ConstructedManagerBehaviorV1)
    protocol = construct_manager_protocol(behavior, exit_face_id="fixture-face")
    assert isinstance(protocol, ConstructedManagerProtocolV1)

    enter_block = protocol.enter_call.force_floor(
        None, owner="inter-method enter", project_callsite=False
    )
    assert isinstance(enter_block, BlockValue)
    returned = enter_block.statements[0]
    assert isinstance(returned, ReturnValue)
    assert isinstance(returned.value, CallSiteValue)
    helper_block = returned.value.force_floor(None, owner="inter-method")
    assert isinstance(helper_block, BlockValue)
    assert helper_block.statements == (ReturnValue(actual.value),)


def test_source_factory_default_gets_authenticated_binding_testimony(tmp_path):
    graph, resolved, actual, call_site = _resolved(
        tmp_path,
        "class DefaultedGuard:\n"
        "    def __init__(self, marker, enabled):\n"
        "        self.marker = marker\n"
        "        self.enabled = enabled\n\n"
        "def make_guard(marker, *, enabled=False):\n"
        "    return DefaultedGuard(marker, enabled)\n",
    )

    behavior = construct_manager_behavior(
        resolved, graph=graph, actuals=(actual,), call_site=call_site
    )

    assert isinstance(behavior, ConstructedManagerBehaviorV1)
    assert len(behavior.formal_actual_bindings) == 2
    assert all(
        entry.constructed_value_testimony is not None
        for entry in behavior.formal_actual_bindings
    )


def test_merged_renamed_some_guard_factory_constructs_through_sole_door(tmp_path):
    fixture = (
        Path(__file__).parents[2]
        / "sugar-lift-py-tests/tests/fixtures/with_source_derivation"
        / "arbitrary_manager_module.py"
    )
    graph, resolved, actual, call_site = _resolved(
        tmp_path, fixture.read_text(encoding="utf-8"), exported="some_manager"
    )

    behavior = construct_manager_behavior(
        resolved, graph=graph, actuals=(actual,), call_site=call_site
    )

    assert isinstance(behavior, ConstructedManagerBehaviorV1)
    receiver = _sole_completed_receiver(behavior)
    assert receiver.class_name == "SomeGuard"
    assert receiver.has_method("__enter__")
    assert receiver.has_method("__exit__")
    protocol = construct_manager_protocol(behavior, exit_face_id="fixture-face")
    assert isinstance(protocol, ConstructedManagerProtocolV1)
    assert protocol.enter_outcome() is not None
    assert protocol.exit_outcome() is not None


def test_renamed_resource_derives_never_suppresses_from_constructed_protocol(tmp_path):
    fixture = (
        Path(__file__).parents[2]
        / "sugar-lift-py-tests/tests/fixtures/with_source_derivation"
        / "arbitrary_manager_module.py"
    )
    graph, resolved, _actual, call_site = _resolved(
        tmp_path, fixture.read_text(encoding="utf-8"), exported="some_resource"
    )
    behavior = construct_manager_behavior(
        resolved, graph=graph, actuals=(), call_site=call_site
    )
    assert isinstance(behavior, ConstructedManagerBehaviorV1)
    protocol = construct_manager_protocol(behavior, exit_face_id="resource-face")
    assert isinstance(protocol, ConstructedManagerProtocolV1)

    summary = derive_manager_summary(protocol)

    from sugar_lift_py_tests.context_manager_contract import (
        NeverSuppressesDispositionV1,
        ProtocolResourceSemanticsV1,
    )

    assert isinstance(summary, DerivedManagerSummaryV1)
    assert isinstance(summary.semantics, ProtocolResourceSemanticsV1)
    assert isinstance(summary.semantics.exit.disposition, NeverSuppressesDispositionV1)
    assert summary.summary_cid.startswith("blake3-512:")


def test_renamed_multistatement_implicit_none_exit_derives_never_suppresses(
    tmp_path,
):
    fixture = (
        Path(__file__).parents[2]
        / "sugar-lift-py-tests/tests/fixtures/with_source_derivation"
        / "arbitrary_manager_module.py"
    )
    graph, resolved, _actual, call_site = _resolved(
        tmp_path,
        fixture.read_text(encoding="utf-8"),
        exported="implicit_none_resource",
    )
    behavior = construct_manager_behavior(
        resolved, graph=graph, actuals=(), call_site=call_site
    )
    assert isinstance(behavior, ConstructedManagerBehaviorV1)
    protocol = construct_manager_protocol(behavior, exit_face_id="implicit-none-face")
    assert isinstance(protocol, ConstructedManagerProtocolV1)

    summary = derive_manager_summary(protocol)

    from sugar_lift_py_tests.context_manager_contract import (
        NeverSuppressesDispositionV1,
        ProtocolResourceSemanticsV1,
    )

    assert isinstance(summary, DerivedManagerSummaryV1)
    assert isinstance(summary.semantics, ProtocolResourceSemanticsV1)
    assert isinstance(summary.semantics.exit.disposition, NeverSuppressesDispositionV1)


def test_opaque_suppression_predicate_stays_summary_gap(tmp_path):
    graph, resolved, actual, call_site = _resolved(
        tmp_path,
        "class OpaqueBoundary:\n"
        "    def __init__(self, expected):\n"
        "        self.expected = expected\n"
        "    def __enter__(self):\n"
        "        return self\n"
        "    def __exit__(self, effect_type, effect, traceback):\n"
        "        return issubclass(effect_type, self.expected)\n"
        "def make_guard(expected):\n"
        "    return OpaqueBoundary(expected)\n",
    )

    behavior = construct_manager_behavior(
        resolved, graph=graph, actuals=(actual,), call_site=call_site
    )
    assert isinstance(behavior, ConstructedManagerBehaviorV1)
    protocol = construct_manager_protocol(behavior, exit_face_id="boundary-face")
    assert isinstance(protocol, ConstructedManagerProtocolV1)

    # TermValue expected is not a typed class operand: summary stays a typed gap
    # (force-floor membrane), never a bare ConstructionPanic or green resource.
    summary = derive_manager_summary(protocol)
    assert isinstance(summary, DerivedManagerSummaryGapV1)
    assert summary.kind in {
        "exit-may-halt",
        "opaque-exit-truthiness",
        "enter-may-halt",
    }, summary


def test_renamed_issubclass_boundary_derives_through_authenticated_floor(tmp_path):
    graph, resolved, actual, call_site = _resolved_type_actual(
        tmp_path,
        "class RenamedBoundary:\n"
        "    def __init__(self, expected):\n"
        "        self.expected = expected\n"
        "    def __enter__(self):\n"
        "        return self\n"
        "    def __exit__(self, effect_type, effect, traceback):\n"
        "        return issubclass(effect_type, self.expected)\n"
        "def make_guard(expected):\n"
        "    return RenamedBoundary(expected)\n",
    )
    behavior = construct_manager_behavior(
        resolved, graph=graph, actuals=(actual,), call_site=call_site
    )
    assert isinstance(behavior, ConstructedManagerBehaviorV1)
    protocol = construct_manager_protocol(behavior, exit_face_id="subtype-face")
    assert isinstance(protocol, ConstructedManagerProtocolV1)

    summary = derive_manager_summary(protocol, behavior=behavior)

    from sugar_lift_py_tests.context_manager_contract import (
        EffectBoundarySemanticsV1,
        FormalArgumentProjectionV1,
        SuppressesModeV1,
    )

    assert isinstance(summary, DerivedManagerSummaryV1)
    assert isinstance(summary.semantics, EffectBoundarySemanticsV1)
    assert isinstance(summary.semantics.mode, SuppressesModeV1)
    assert summary.semantics.expected_type_operand == FormalArgumentProjectionV1(0)


def test_renamed_source_visible_exit_derives_expects_raise_boundary(tmp_path):
    graph, resolved, actual, call_site = _resolved(
        tmp_path,
        "class ArbitraryBoundary:\n"
        "    def __init__(self, expected):\n"
        "        self.expected = expected\n"
        "    def __enter__(self):\n"
        "        return self\n"
        "    def __exit__(self, effect_type, effect, traceback):\n"
        "        if effect_type is None:\n"
        "            raise RuntimeError()\n"
        "        return effect_type is self.expected\n"
        "def make_guard(expected):\n"
        "    return ArbitraryBoundary(expected)\n",
    )
    behavior = construct_manager_behavior(
        resolved, graph=graph, actuals=(actual,), call_site=call_site
    )
    assert isinstance(behavior, ConstructedManagerBehaviorV1)
    protocol = construct_manager_protocol(behavior, exit_face_id="renamed-effect-face")
    assert isinstance(protocol, ConstructedManagerProtocolV1)

    summary = derive_manager_summary(protocol, behavior=behavior)

    from sugar_lift_py_tests.context_manager_contract import (
        EffectBoundarySemanticsV1,
        ExpectsModeV1,
        FormalArgumentProjectionV1,
        RaiseEffectKindV1,
    )

    assert isinstance(summary, DerivedManagerSummaryV1)
    assert isinstance(summary.semantics, EffectBoundarySemanticsV1)
    assert isinstance(summary.semantics.mode, ExpectsModeV1)
    assert isinstance(summary.semantics.effect_kind, RaiseEffectKindV1)
    assert summary.semantics.expected_type_operand == FormalArgumentProjectionV1(0)


def test_external_error_raised_spelling_cannot_replace_native_return_shape(tmp_path):
    """A deferred assertion import cannot override the returned manager.

    This is the lying twin for the returned-manager reproducer. It binds the
    assertion provider at call time but returns an ordinary resource manager;
    native return testimony must keep it out of the EffectBoundary arm.
    """
    graph, resolved, actual, call_site = _resolved_type_actual(
        tmp_path,
        "class OrdinaryResource:\n"
        "    def __init__(self, expected):\n"
        "        self.expected = expected\n"
        "    def __enter__(self):\n"
        "        return self\n"
        "    def __exit__(self, effect_type, effect, traceback):\n"
        "        return False\n"
        "def external_error_raised(expected):\n"
        "    import pytest\n"
        "    return OrdinaryResource(expected)\n",
        exported="external_error_raised",
    )
    behavior = construct_manager_behavior(
        resolved, graph=graph, actuals=(actual,), call_site=call_site
    )
    assert isinstance(behavior, ConstructedManagerBehaviorV1)
    protocol = construct_manager_protocol(behavior, exit_face_id="lying-name-face")
    assert isinstance(protocol, ConstructedManagerProtocolV1)

    summary = derive_manager_summary(protocol, behavior=behavior)

    from sugar_lift_py_tests.context_manager_contract import EffectBoundarySemanticsV1

    assert not (
        isinstance(summary, DerivedManagerSummaryV1)
        and isinstance(summary.semantics, EffectBoundarySemanticsV1)
    ), summary


def test_renamed_returned_assertion_manager_is_derived_from_protocol(tmp_path):
    """A source-authenticated returned manager is the truthful native twin."""
    graph, resolved, actual, call_site = _resolved_type_actual(
        tmp_path,
        "class RenamedBoundary:\n"
        "    def __init__(self, expected):\n"
        "        self.expected = expected\n"
        "    def __enter__(self):\n"
        "        return self\n"
        "    def __exit__(self, effect_type, effect, traceback):\n"
        "        if effect_type is None:\n"
        "            raise RuntimeError()\n"
        "        return effect_type is self.expected\n"
        "def returned_boundary(expected):\n"
        "    return RenamedBoundary(expected)\n",
        exported="returned_boundary",
    )
    behavior = construct_manager_behavior(
        resolved, graph=graph, actuals=(actual,), call_site=call_site
    )
    assert isinstance(behavior, ConstructedManagerBehaviorV1)
    protocol = construct_manager_protocol(behavior, exit_face_id="truthful-return-face")
    assert isinstance(protocol, ConstructedManagerProtocolV1)

    summary = derive_manager_summary(protocol, behavior=behavior)

    from sugar_lift_py_tests.context_manager_contract import EffectBoundarySemanticsV1

    assert isinstance(summary, DerivedManagerSummaryV1)
    assert isinstance(summary.semantics, EffectBoundarySemanticsV1)


def test_renamed_source_visible_exit_derives_suppresses_mode(tmp_path):
    graph, resolved, actual, call_site = _resolved(
        tmp_path,
        "class ArbitraryBoundary:\n"
        "    def __init__(self, expected):\n"
        "        self.expected = expected\n"
        "    def __enter__(self):\n"
        "        return self\n"
        "    def __exit__(self, effect_type, effect, traceback):\n"
        "        return effect_type is self.expected\n"
        "def make_guard(expected):\n"
        "    return ArbitraryBoundary(expected)\n",
    )
    behavior = construct_manager_behavior(
        resolved, graph=graph, actuals=(actual,), call_site=call_site
    )
    assert isinstance(behavior, ConstructedManagerBehaviorV1)
    protocol = construct_manager_protocol(behavior, exit_face_id="suppresses-face")
    assert isinstance(protocol, ConstructedManagerProtocolV1)

    summary = derive_manager_summary(protocol, behavior=behavior)

    from sugar_lift_py_tests.context_manager_contract import (
        EffectBoundarySemanticsV1,
        SuppressesModeV1,
    )

    assert isinstance(summary, DerivedManagerSummaryV1)
    assert isinstance(summary.semantics, EffectBoundarySemanticsV1)
    assert isinstance(summary.semantics.mode, SuppressesModeV1)


def test_renamed_effect_boundary_derives_message_operand_from_real_formal(tmp_path):
    graph, resolved, expected, call_site = _resolved(
        tmp_path,
        "class ArbitraryBoundary:\n"
        "    def __init__(self, expected, pattern):\n"
        "        self.expected = expected\n"
        "        self.pattern = pattern\n"
        "    def __enter__(self):\n"
        "        return self\n"
        "    def __exit__(self, effect_type, effect, traceback):\n"
        "        if effect_type is None:\n"
        "            raise RuntimeError()\n"
        "        return (effect_type is self.expected) and (effect.message == self.pattern)\n"
        "def make_guard(expected, pattern):\n"
        "    return ArbitraryBoundary(expected, pattern)\n",
    )
    from sugar_lift_py_tests.floor import StringValue
    from sugar_source_tree.binding_provenance import ConstructedValueTestimonyV1
    from sugar_lift_py_tests.ir import _term_content_cid

    pattern_source = SourceFile(
        ('"needle"\n', str(tmp_path / "pattern.py"), "blake3-512:" + ("91" * 64))
    )
    pattern_node = next(
        node for node in pattern_source.nodes() if isinstance(node, Constant)
    )
    pattern_value = StringValue("needle")
    pattern = ConstructedCallActualV1(
        pattern_node,
        pattern_value,
        ConstructedValueTestimonyV1.mint(
            pattern_node.fragment,
            _term_content_cid(pattern_value.to_term(owner=resolved.cid)),
        ),
    )
    behavior = construct_manager_behavior(
        resolved,
        graph=graph,
        actuals=(expected, pattern),
        call_site=call_site,
    )
    assert isinstance(behavior, ConstructedManagerBehaviorV1)
    protocol = construct_manager_protocol(behavior, exit_face_id="message-face")
    assert isinstance(protocol, ConstructedManagerProtocolV1)

    summary = derive_manager_summary(protocol, behavior=behavior)

    from sugar_lift_py_tests.context_manager_contract import (
        EffectBoundarySemanticsV1,
        OptionalFormalArgumentProjectionV1,
    )

    assert isinstance(summary, DerivedManagerSummaryV1)
    assert isinstance(summary.semantics, EffectBoundarySemanticsV1)
    assert summary.semantics.message_pattern_operand == (
        OptionalFormalArgumentProjectionV1(1)
    )


def _factored_boundary_faces():
    """Two guarded EffectBoundary faces: NoMessagePattern + pattern obligation."""
    from sugar_lift_py_tests.context_manager_contract import (
        EffectBoundarySemanticsV1,
        ExceptionInfoBindingV1,
        ExpectsModeV1,
        FormalArgumentProjectionV1,
        NoMessagePatternV1,
        OptionalFormalArgumentProjectionV1,
        RaiseEffectKindV1,
    )
    from sugar_lift_py_tests.ir import _Atomic
    from sugar_lift_py_tests.outcome import Completed, ExitSet

    none_face = EffectBoundarySemanticsV1(
        ExpectsModeV1(),
        RaiseEffectKindV1(),
        FormalArgumentProjectionV1(0),
        NoMessagePatternV1(),
        ExceptionInfoBindingV1(),
    )
    pattern_face = EffectBoundarySemanticsV1(
        ExpectsModeV1(),
        RaiseEffectKindV1(),
        FormalArgumentProjectionV1(0),
        OptionalFormalArgumentProjectionV1(1),
        ExceptionInfoBindingV1(),
    )
    return ExitSet(
        (
            Completed(_Atomic("match-none-face", ()), none_face),
            Completed(_Atomic("match-pattern-face", ()), pattern_face),
        )
    )


def _factored_import_signature():
    from sugar_lift_py_tests.context_manager_contract import (
        CallParameterV1,
        ImportSignatureV2,
        LiteralDefaultV1,
        NoDefaultV1,
        PositionalOrKeywordV1,
    )
    from sugar_lift_py_tests.ir import PrimitiveSort

    return ImportSignatureV2(
        (
            CallParameterV1(
                "expected",
                PrimitiveSort("Value"),
                PositionalOrKeywordV1(),
                True,
                NoDefaultV1(),
            ),
            CallParameterV1(
                "match",
                PrimitiveSort("Value"),
                PositionalOrKeywordV1(),
                False,
                LiteralDefaultV1({"kind": "ctor", "name": "None", "args": []}),
            ),
        )
    )


def test_factored_summary_installs_factored_ref_not_no_derived_contract():
    """Positive: FactoredEffectBoundarySummary publishes both faces, never a gap."""
    from types import SimpleNamespace

    from sugar_lift_py_tests.context_manager_contract import (
        NoMessagePatternV1,
        OptionalFormalArgumentProjectionV1,
    )
    from sugar_lift_py_tests.context_manager_resolution import (
        ContextManagerResolutionGapV1,
        FactoredSourceDerivedContextManagerRefV1,
        SourceFragmentCoordinateV1,
        TreeConstructionContextV1,
    )
    from sugar_lift_py_tests.outcome import Completed
    from sugar_lift_python_source.manager_summary_derivation import (
        FactoredEffectBoundarySummaryV1,
    )

    coordinate = SourceFragmentCoordinateV1("blake3-512:" + ("ab" * 64), 2, 9, 2, 40)
    faces = _factored_boundary_faces()
    signature = _factored_import_signature()
    protocol = SimpleNamespace()
    summary = FactoredEffectBoundarySummaryV1(
        "factored-protocol",
        "enter-cid",
        "exit-cid",
        faces,
        signature,
    )
    context = TreeConstructionContextV1.for_source_call_construction()
    # Same arm as populate_source_derived_resource_refs for factored summaries.
    assert isinstance(summary, FactoredEffectBoundarySummaryV1)
    context.source_derived_contract_refs[coordinate] = (
        FactoredSourceDerivedContextManagerRefV1(
            coordinate,
            summary.protocol_construction_cid,
            summary.enter_testimony_cid,
            summary.exit_testimony_cid,
            summary.boundary_faces,
            summary.import_signature,
            protocol,
        )
    )
    installed = context.source_derived_contract_refs[coordinate]
    assert isinstance(installed, FactoredSourceDerivedContextManagerRefV1)
    assert not isinstance(installed, ContextManagerResolutionGapV1)
    assert getattr(installed, "kind", None) != "no-derived-contract"
    completed = [
        face for face in installed.boundary_faces.exits if isinstance(face, Completed)
    ]
    assert len(completed) == 2
    operands = {face.value.message_pattern_operand for face in completed}
    assert operands == {
        NoMessagePatternV1(),
        OptionalFormalArgumentProjectionV1(1),
    }


def test_factored_ref_tree_construction_retains_both_faces(tmp_path):
    """Tree construction keeps both edges; sugar carries boundary_faces."""
    from types import SimpleNamespace

    from sugar_lift_py_tests.context_manager_contract import (
        NoMessagePatternV1,
        OptionalFormalArgumentProjectionV1,
    )
    from sugar_lift_py_tests.context_manager_resolution import (
        FactoredSourceDerivedContextManagerRefV1,
        SourceFragmentCoordinateV1,
        TreeConstructionContextV1,
    )
    from sugar_lift_py_tests.outcome import Completed
    from sugar_lift_py_tests.sugar.with_effect_boundary_sugar import (
        WithEffectBoundarySugar,
    )
    from sugar_source_tree.nodes import With

    consumer = (
        "def use_boundary():\n"
        "    with boundary(ValueError, 'needle'):\n"
        "        raise ValueError('needle')\n"
    )
    path = tmp_path / "factored-consumer.py"
    path.write_text(consumer, encoding="utf-8")
    context = TreeConstructionContextV1.for_source_call_construction()
    tree = SourceFile(
        (consumer, str(path), blake3_512_of(consumer.encode("utf-8"))),
        construction_context=context,
    )
    node = next(item for item in tree.nodes() if isinstance(item, With))
    expr = node.items[0].context_expr
    span = expr.line_col_span()
    coordinate = SourceFragmentCoordinateV1(
        node.unit.source_cid,
        span.start_line,
        span.start_col,
        span.end_line,
        span.end_col,
    )
    context.source_derived_contract_refs[coordinate] = (
        FactoredSourceDerivedContextManagerRefV1(
            coordinate,
            "factored-protocol",
            "enter-cid",
            "exit-cid",
            _factored_boundary_faces(),
            _factored_import_signature(),
            SimpleNamespace(),
        )
    )

    sugar = node.sugar()

    assert isinstance(sugar, WithEffectBoundarySugar)
    assert sugar.boundary_faces is not None
    completed = [
        face for face in sugar.boundary_faces.exits if isinstance(face, Completed)
    ]
    assert len(completed) == 2
    operands = {face.value.message_pattern_operand for face in completed}
    assert operands == {
        NoMessagePatternV1(),
        OptionalFormalArgumentProjectionV1(1),
    }
    assert sugar.semantics is None


def test_factored_raise_routing_uses_none_and_pattern_message_faces():
    """Routing faces: NoMessagePatternV1 on one edge, pattern obligation on other."""
    from types import SimpleNamespace

    from sugar_lift_py_tests.context_manager_contract import (
        AuthenticatedRaiseMatcher,
        EffectBoundaryDisposition,
        ExpectsModeV1,
        NoMessagePatternV1,
        OptionalFormalArgumentProjectionV1,
    )
    from sugar_lift_py_tests.context_manager_resolution import (
        FactoredSourceDerivedContextManagerRefV1,
        SourceFragmentCoordinateV1,
    )
    from sugar_lift_py_tests.effect import ExpectationNotMetEffect
    from sugar_lift_py_tests.effect.raise_effect import RaiseEffect
    from sugar_lift_py_tests.floor import StringValue
    from sugar_lift_py_tests.ir import ctor, str_const
    from sugar_lift_py_tests.outcome import Completed, ExitSet, Halted, true_guard
    from sugar_lift_py_tests.sugar.with_effect_boundary_sugar import (
        WithEffectBoundarySugar,
    )

    faces = _factored_boundary_faces()
    coordinate = SourceFragmentCoordinateV1("blake3-512:" + ("cd" * 64), 1, 0, 1, 10)
    contract_ref = FactoredSourceDerivedContextManagerRefV1(
        coordinate,
        "factored-protocol",
        "enter-cid",
        "exit-cid",
        faces,
        _factored_import_signature(),
        SimpleNamespace(),
    )
    sugar = WithEffectBoundarySugar(
        manager=SimpleNamespace(),  # unused: we exercise guarded faces + disposition
        body=(),
        semantics=None,
        contract_ref=contract_ref,
        context_manager_edge=None,
        boundary_faces=faces,
        site=SimpleNamespace(filename="t.py", line=1),
    )
    guarded = sugar._guarded_semantics()
    assert len(guarded) == 2
    by_name = {guard.name: semantics for guard, semantics in guarded}
    assert isinstance(
        by_name["match-none-face"].message_pattern_operand, NoMessagePatternV1
    )
    assert by_name["match-pattern-face"].message_pattern_operand == (
        OptionalFormalArgumentProjectionV1(1)
    )

    # Disposition law: None-pattern matcher has no message obligation; pattern
    # face carries the projected formal as message_pattern.
    type_term = ctor(
        "python:exception_type_identity",
        [str_const("builtins"), str_const("ValueError")],
    )
    raise_face = Halted(
        true_guard(),
        RaiseEffect.for_builtin(
            "ValueError",
            blame="t.py:2:8",
            exception_type_mro=(type_term,),
            raised_value=StringValue("needle"),
            occurrence="t.py:2:8",
        ),
        None,
    )
    assert raise_face.effect.exception_type_coordinate == type_term
    body = ExitSet((raise_face,))
    for guard, semantics in guarded:
        pattern = None
        if not isinstance(semantics.message_pattern_operand, NoMessagePatternV1):
            pattern = StringValue("needle")
        disposition = EffectBoundaryDisposition(
            matcher=AuthenticatedRaiseMatcher(
                expected=SimpleNamespace(
                    exception_type_identity=lambda: type_term,
                ),
                message_pattern=pattern,
            ),
            unmet=(
                ExpectationNotMetEffect("raise", "site")
                if isinstance(semantics.mode, ExpectsModeV1)
                else None
            ),
        )
        # Matcher construction is the routing face content: both arms exist.
        assert disposition.matcher.message_pattern is (
            None
            if isinstance(semantics.message_pattern_operand, NoMessagePatternV1)
            else pattern
        )
        assert body.exits and isinstance(body.exits[0], Halted)


def test_uniform_none_source_derived_ref_stays_single_sealed_summary():
    """Discrimination: uniform None remains SourceDerivedContextManagerRefV1."""
    from types import SimpleNamespace

    from sugar_lift_py_tests.context_manager_contract import (
        EffectBoundarySemanticsV1,
        ExceptionInfoBindingV1,
        ExpectsModeV1,
        FormalArgumentProjectionV1,
        NoMessagePatternV1,
        RaiseEffectKindV1,
    )
    from sugar_lift_py_tests.context_manager_resolution import (
        FactoredSourceDerivedContextManagerRefV1,
        SourceDerivedContextManagerRefV1,
        SourceFragmentCoordinateV1,
    )

    semantics = EffectBoundarySemanticsV1(
        ExpectsModeV1(),
        RaiseEffectKindV1(),
        FormalArgumentProjectionV1(0),
        NoMessagePatternV1(),
        ExceptionInfoBindingV1(),
    )
    coordinate = SourceFragmentCoordinateV1("blake3-512:" + ("ef" * 64), 1, 0, 1, 10)
    sealed = SourceDerivedContextManagerRefV1(
        coordinate,
        "summary-cid",
        semantics,
        _factored_import_signature(),
        SimpleNamespace(),
    )
    assert isinstance(sealed, SourceDerivedContextManagerRefV1)
    assert not isinstance(sealed, FactoredSourceDerivedContextManagerRefV1)
    assert isinstance(sealed.semantics.message_pattern_operand, NoMessagePatternV1)
    # Factored path is a different type — never silent collapse of dual faces.
    factored = FactoredSourceDerivedContextManagerRefV1(
        coordinate,
        "factored-protocol",
        "enter-cid",
        "exit-cid",
        _factored_boundary_faces(),
        _factored_import_signature(),
        SimpleNamespace(),
    )
    assert type(factored) is not type(sealed)


def test_factored_ref_as_clause_authenticates_observation_slot(tmp_path):
    """Production join: factored ref + ``as info`` grants the observation slot."""
    from types import SimpleNamespace

    from sugar_lift_py_tests.context_manager_resolution import (
        FactoredSourceDerivedContextManagerRefV1,
        SourceFragmentCoordinateV1,
        TreeConstructionContextV1,
    )
    from sugar_lift_py_tests.sugar.with_effect_boundary_sugar import (
        WithEffectBoundarySugar,
    )
    from sugar_source_tree.nodes import With

    consumer = (
        "def use_boundary():\n"
        "    with boundary(ValueError, 'needle') as info:\n"
        "        raise ValueError('needle')\n"
    )
    path = tmp_path / "factored-as-consumer.py"
    path.write_text(consumer, encoding="utf-8")
    context = TreeConstructionContextV1.for_source_call_construction()
    tree = SourceFile(
        (consumer, str(path), blake3_512_of(consumer.encode("utf-8"))),
        construction_context=context,
    )
    node = next(item for item in tree.nodes() if isinstance(item, With))
    expr = node.items[0].context_expr
    span = expr.line_col_span()
    coordinate = SourceFragmentCoordinateV1(
        node.unit.source_cid,
        span.start_line,
        span.start_col,
        span.end_line,
        span.end_col,
    )
    context.source_derived_contract_refs[coordinate] = (
        FactoredSourceDerivedContextManagerRefV1(
            coordinate,
            "factored-protocol",
            "enter-cid",
            "exit-cid",
            _factored_boundary_faces(),
            _factored_import_signature(),
            SimpleNamespace(),
        )
    )

    sugar = node.sugar()

    assert isinstance(sugar, WithEffectBoundarySugar)
    assert sugar.observation_slot_id is not None
    assert sugar.observation_slot_id.endswith("#observation")
    assert sugar.boundary_faces is not None
    # Both faces still present after as-clause construction.
    from sugar_lift_py_tests.context_manager_contract import (
        NoMessagePatternV1,
        OptionalFormalArgumentProjectionV1,
    )
    from sugar_lift_py_tests.outcome import Completed

    operands = {
        face.value.message_pattern_operand
        for face in sugar.boundary_faces.exits
        if isinstance(face, Completed)
    }
    assert operands == {
        NoMessagePatternV1(),
        OptionalFormalArgumentProjectionV1(1),
    }


def test_factored_ref_without_as_clause_has_no_observation_slot(tmp_path):
    """Discrimination: no ``as`` name means factored sugar carries no slot."""
    from types import SimpleNamespace

    from sugar_lift_py_tests.context_manager_resolution import (
        FactoredSourceDerivedContextManagerRefV1,
        SourceFragmentCoordinateV1,
        TreeConstructionContextV1,
    )
    from sugar_lift_py_tests.sugar.with_effect_boundary_sugar import (
        WithEffectBoundarySugar,
    )
    from sugar_source_tree.nodes import With

    consumer = (
        "def use_boundary():\n"
        "    with boundary(ValueError, 'needle'):\n"
        "        raise ValueError('needle')\n"
    )
    path = tmp_path / "factored-no-as-consumer.py"
    path.write_text(consumer, encoding="utf-8")
    context = TreeConstructionContextV1.for_source_call_construction()
    tree = SourceFile(
        (consumer, str(path), blake3_512_of(consumer.encode("utf-8"))),
        construction_context=context,
    )
    node = next(item for item in tree.nodes() if isinstance(item, With))
    expr = node.items[0].context_expr
    span = expr.line_col_span()
    coordinate = SourceFragmentCoordinateV1(
        node.unit.source_cid,
        span.start_line,
        span.start_col,
        span.end_line,
        span.end_col,
    )
    context.source_derived_contract_refs[coordinate] = (
        FactoredSourceDerivedContextManagerRefV1(
            coordinate,
            "factored-protocol",
            "enter-cid",
            "exit-cid",
            _factored_boundary_faces(),
            _factored_import_signature(),
            SimpleNamespace(),
        )
    )

    sugar = node.sugar()

    assert isinstance(sugar, WithEffectBoundarySugar)
    assert sugar.observation_slot_id is None


def test_factored_ref_disagreeing_binding_refuses_at_with_construction(tmp_path):
    """Lying twin: With construction never authorizes all faces from face zero."""
    from types import SimpleNamespace

    from sugar_lift_py_tests.context_manager_contract import (
        EffectBoundarySemanticsV1,
        ExceptionInfoBindingV1,
        ExpectsModeV1,
        FormalArgumentProjectionV1,
        NoBindingV1,
        NoMessagePatternV1,
        OptionalFormalArgumentProjectionV1,
        RaiseEffectKindV1,
    )
    from sugar_lift_py_tests.context_manager_resolution import (
        FactoredSourceDerivedContextManagerRefV1,
        SourceFragmentCoordinateV1,
        TreeConstructionContextV1,
    )
    from sugar_lift_py_tests.ir import _Atomic
    from sugar_lift_py_tests.outcome import Completed, ExitSet
    from sugar_source_tree.nodes import With
    from sugar_source_tree.panic import SugarNotWritten

    consumer = (
        "def use_boundary():\n"
        "    with boundary(ValueError, 'needle') as info:\n"
        "        raise ValueError('needle')\n"
    )
    path = tmp_path / "factored-disagree-binding.py"
    path.write_text(consumer, encoding="utf-8")
    context = TreeConstructionContextV1.for_source_call_construction()
    tree = SourceFile(
        (consumer, str(path), blake3_512_of(consumer.encode("utf-8"))),
        construction_context=context,
    )
    node = next(item for item in tree.nodes() if isinstance(item, With))
    expr = node.items[0].context_expr
    span = expr.line_col_span()
    coordinate = SourceFragmentCoordinateV1(
        node.unit.source_cid,
        span.start_line,
        span.start_col,
        span.end_line,
        span.end_col,
    )
    disagreeing = ExitSet(
        (
            Completed(
                _Atomic("bind-zero", ()),
                EffectBoundarySemanticsV1(
                    ExpectsModeV1(),
                    RaiseEffectKindV1(),
                    FormalArgumentProjectionV1(0),
                    NoMessagePatternV1(),
                    ExceptionInfoBindingV1(),
                ),
            ),
            Completed(
                _Atomic("bind-one", ()),
                EffectBoundarySemanticsV1(
                    ExpectsModeV1(),
                    RaiseEffectKindV1(),
                    FormalArgumentProjectionV1(0),
                    OptionalFormalArgumentProjectionV1(1),
                    NoBindingV1(),
                ),
            ),
        )
    )
    context.source_derived_contract_refs[coordinate] = (
        FactoredSourceDerivedContextManagerRefV1(
            coordinate,
            "disagree-binding-protocol",
            "enter-cid",
            "exit-cid",
            disagreeing,
            _factored_import_signature(),
            SimpleNamespace(),
        )
    )

    with pytest.raises(SugarNotWritten) as caught:
        node.sugar()

    assert "binding" in caught.value.observed
    assert "first completed face" in caught.value.fix or "face zero" in (
        caught.value.fix
    )


def test_source_derived_resource_ref_selects_projection_only_with_arm(tmp_path):
    fixture = (
        Path(__file__).parents[2]
        / "sugar-lift-py-tests/tests/fixtures/with_source_derivation"
        / "arbitrary_manager_module.py"
    )
    graph, resolved, _actual, call_site = _resolved(
        tmp_path, fixture.read_text(encoding="utf-8"), exported="some_resource"
    )
    behavior = construct_manager_behavior(
        resolved, graph=graph, actuals=(), call_site=call_site
    )
    protocol = construct_manager_protocol(behavior, exit_face_id="with-resource-face")
    summary = derive_manager_summary(protocol)
    assert isinstance(summary, DerivedManagerSummaryV1)

    from sugar_lift_py_tests.context_manager_resolution import (
        SourceDerivedContextManagerRefV1,
        SourceFragmentCoordinateV1,
        TreeConstructionContextV1,
    )
    from sugar_lift_py_tests.sugar.with_source_resource_sugar import (
        WithSourceResourceSugar,
    )
    from sugar_source_tree.nodes import With

    context = TreeConstructionContextV1.for_source_call_construction()
    consumer = (
        "def use_resource():\n"
        "    with resource_factory():\n"
        "        raise ValueError('body')\n"
    )
    tree = SourceFile(
        (consumer, "resource-consumer.py", "blake3-512:" + ("46" * 64)),
        construction_context=context,
    )
    node = next(item for item in tree.nodes() if isinstance(item, With))
    expr = node.items[0].context_expr
    span = expr.line_col_span()
    coordinate = SourceFragmentCoordinateV1(
        node.unit.source_cid,
        span.start_line,
        span.start_col,
        span.end_line,
        span.end_col,
    )
    context.source_derived_contract_refs[coordinate] = SourceDerivedContextManagerRefV1(
        coordinate,
        summary.summary_cid,
        summary.semantics,
        summary.import_signature,
        protocol,
    )

    sugar = node.sugar()

    assert isinstance(sugar, WithSourceResourceSugar)
    assert sugar.protocol is protocol
    assert sugar.summary.summary_cid == summary.summary_cid
    from sugar_lift_py_tests.outcome import Halted, outcome_to_exitset

    routed = outcome_to_exitset(sugar.desugar())
    assert routed.exits
    assert any(isinstance(face, Halted) for face in routed.exits), [
        (type(face).__name__, repr(face.guard)) for face in routed.exits
    ]


def test_preconstruction_populates_resource_ref_from_authenticated_import(tmp_path):
    implementation = (
        "class RenamedResource:\n"
        "    def __enter__(self):\n"
        "        return 9\n"
        "    def __exit__(self, effect_type, effect, traceback):\n"
        "        return False\n\n"
        "def make_resource():\n"
        "    return RenamedResource()\n"
    )
    distribution = _distribution(tmp_path, implementation, exported="make_resource")
    consumer = (
        "import arbitrary\n"
        "def use_resource():\n"
        "    with arbitrary.make_resource():\n"
        "        pass\n"
    )
    path = tmp_path / "consumer.py"
    path.write_text(consumer, encoding="utf-8")
    source_cid = blake3_512_of(consumer.encode("utf-8"))
    from sugar_lift_py_tests.context_manager_resolution import TreeConstructionContextV1

    context = TreeConstructionContextV1.for_source_call_construction()
    tree = SourceFile((consumer, str(path), source_cid), construction_context=context)

    populate_source_derived_resource_refs(
        tree,
        root=tmp_path,
        path=path,
        distribution_index={"arbitrary": distribution},
        session=SourceResolutionSession(
            enrolled_distributions=frozenset({distribution.metadata["Name"]})
        ),
    )

    from sugar_lift_py_tests.context_manager_resolution import (
        SourceDerivedContextManagerRefV1,
    )

    assert len(context.source_derived_contract_refs) == 1
    assert isinstance(
        next(iter(context.source_derived_contract_refs.values())),
        SourceDerivedContextManagerRefV1,
    )


def test_preconstruction_can_bound_derivation_to_one_authenticated_use(tmp_path):
    """A family probe must not construct unrelated managers in the same file."""
    implementation = (
        "class Resource:\n"
        "    def __enter__(self):\n"
        "        return self\n"
        "    def __exit__(self, effect_type, effect, traceback):\n"
        "        return False\n\n"
        "def make_resource():\n"
        "    return Resource()\n"
    )
    distribution = _distribution(tmp_path, implementation, exported="make_resource")
    consumer = (
        "import arbitrary\n"
        "with arbitrary.make_resource():\n"
        "    pass\n"
        "with arbitrary.make_resource():\n"
        "    pass\n"
    )
    path = tmp_path / "consumer.py"
    path.write_text(consumer, encoding="utf-8")
    from sugar_lift_py_tests.context_manager_resolution import (
        SourceFragmentCoordinateV1,
        TreeConstructionContextV1,
    )

    context = TreeConstructionContextV1.for_source_call_construction()
    tree = SourceFile(
        (consumer, str(path), blake3_512_of(consumer.encode("utf-8"))),
        construction_context=context,
    )
    selected_call = tuple(node for node in tree.nodes() if node.kind == "Call")[1]
    span = selected_call.line_col_span()
    selected = SourceFragmentCoordinateV1(
        tree.unit.source_cid,
        span.start_line,
        span.start_col,
        span.end_line,
        span.end_col,
    )

    populate_source_derived_resource_refs(
        tree,
        root=tmp_path,
        path=path,
        distribution_index={"arbitrary": distribution},
        selected_coordinates=frozenset({selected}),
        session=SourceResolutionSession(
            enrolled_distributions=frozenset({distribution.metadata["Name"]})
        ),
    )

    assert tuple(context.source_derived_contract_refs) == (selected,)


def test_preconstruction_populates_renamed_effect_boundary_from_source(tmp_path):
    implementation = (
        "class RenamedBoundary:\n"
        "    def __init__(self, expected):\n"
        "        self.expected = expected\n"
        "    def __enter__(self):\n"
        "        return self\n"
        "    def __exit__(self, effect_type, effect, traceback):\n"
        "        if effect_type is None:\n"
        "            raise RuntimeError()\n"
        "        return effect_type is self.expected\n\n"
        "def make_boundary(expected):\n"
        "    return RenamedBoundary(expected)\n"
    )
    distribution = _distribution(tmp_path, implementation, exported="make_boundary")
    consumer = (
        "import arbitrary\n"
        "def use_boundary():\n"
        "    with arbitrary.make_boundary(ValueError):\n"
        "        pass\n"
    )
    path = tmp_path / "consumer.py"
    path.write_text(consumer, encoding="utf-8")
    from sugar_lift_py_tests.context_manager_resolution import (
        SourceDerivedContextManagerRefV1,
        TreeConstructionContextV1,
    )
    from sugar_lift_py_tests.context_manager_contract import (
        EffectBoundarySemanticsV1,
        ExpectsModeV1,
        FormalArgumentProjectionV1,
    )

    context = TreeConstructionContextV1.for_source_call_construction()
    tree = SourceFile(
        (consumer, str(path), blake3_512_of(consumer.encode("utf-8"))),
        construction_context=context,
    )
    populate_source_derived_resource_refs(
        tree,
        root=tmp_path,
        path=path,
        distribution_index={"arbitrary": distribution},
        session=SourceResolutionSession(
            enrolled_distributions=frozenset({distribution.metadata["Name"]})
        ),
    )

    reference = next(iter(context.source_derived_contract_refs.values()))
    assert isinstance(reference, SourceDerivedContextManagerRefV1)
    assert isinstance(reference.semantics, EffectBoundarySemanticsV1)
    assert isinstance(reference.semantics.mode, ExpectsModeV1)
    assert reference.semantics.expected_type_operand == FormalArgumentProjectionV1(0)
    with_node = next(node for node in tree.nodes() if node.kind == "With")
    from sugar_lift_py_tests.sugar.with_effect_boundary_sugar import (
        WithEffectBoundarySugar,
    )

    boundary = with_node.sugar()
    assert isinstance(boundary, WithEffectBoundarySugar)
    from sugar_lift_py_tests.effect import ExpectationNotMetEffect
    from sugar_lift_py_tests.outcome import Halted, outcome_to_exitset

    exits = outcome_to_exitset(boundary.desugar()).exits
    assert len(exits) == 1
    assert isinstance(exits[0], Halted)
    assert isinstance(exits[0].effect, ExpectationNotMetEffect)


def test_call_result_attribute_keeps_the_exact_constructed_call_coordinate():
    from sugar_lift_py_tests.floor import CallSiteValue
    from sugar_lift_py_tests.ir import ctor
    from sugar_lift_py_tests.outcome import Complete

    call = CallSiteValue("renamed", (), (), ctor("python:call", ()), None)
    projected = call.attribute("__name__", None)

    assert isinstance(projected, Complete)
    assert projected.value.term.args[0] is call.term
    assert projected.value.term.args[1].value == "__name__"


def _installed_pytest_boundary(tmp_path, manager_call: str, body: str):
    consumer = (
        "import pytest\n"
        "def use_boundary():\n"
        f"    with {manager_call}:\n"
        f"        {body}\n"
    )
    path = tmp_path / "consumer.py"
    path.write_text(consumer, encoding="utf-8")
    from sugar_lift_py_tests.context_manager_resolution import TreeConstructionContextV1

    context = TreeConstructionContextV1.for_source_call_construction()
    tree = SourceFile(
        (consumer, str(path), blake3_512_of(consumer.encode("utf-8"))),
        construction_context=context,
    )
    pytest_distribution = importlib.metadata.distribution("pytest")
    populate_source_derived_resource_refs(
        tree,
        root=tmp_path,
        path=path,
        session=SourceResolutionSession(
            enrolled_distributions=frozenset({pytest_distribution.metadata["Name"]})
        ),
    )
    return tree, context


def _without_pytest_raises_construction_halts(exits):
    """The With's body-route faces after ``AbstractRaises.__init__``'s own halts.

    pytest's ``re.compile(match)`` is an off-population call inside the
    enrolled pytest body, so it may raise. Python evaluates
    ``pytest.raises(...)`` before anything is entered, so each such halt is the
    With's own face: the body never runs and ``__exit__`` never runs. pytest's
    ``except re.error`` route reaches ``fail(...)`` (``Failed``); any other
    exception propagates undetermined. Formatting that ``re.error`` into
    ``fail``'s message (``f"...{re_error}"``) runs its class's ``__format__``,
    which the lift does not know is CPython's own, so it may raise too. Every
    remaining face is reached only where that call completed.
    """
    from sugar_lift_py_tests.outcome import Halted

    construction = [
        face
        for face in exits
        if isinstance(face, Halted)
        and _negates_off_population_call(face.guard, "python:re.compile")
    ]
    kinds = sorted(
        (
            type(face.effect).__name__,
            getattr(face.effect, "exception_name", None)
            or getattr(face.effect, "producer_node_owner", None),
        )
        for face in construction
    )
    assert kinds == [
        ("RaiseEffect", "Failed"),
        ("UndeterminedRaiseEffect", "BuiltinDunderCall:format"),
        ("UndeterminedRaiseEffect", "OffPopulationCall:python:re.compile"),
    ], kinds
    (failed,) = [face for face in construction if face.effect.exception_name == "Failed"]
    assert "re.error" in repr(failed.guard)
    rest = tuple(face for face in exits if all(face is not c for c in construction))
    for face in rest:
        assert not _negates_off_population_call(face.guard, "python:re.compile")
    return rest


def _negates_off_population_call(guard, target):
    """``guard`` conjoins ``not python:off_population_call.completes(target, _)``."""
    kind = getattr(guard, "kind", None)
    if kind == "not":
        (operand,) = guard.operands
        if getattr(operand, "name", None) != "python:off_population_call.completes":
            return False
        (call,) = operand.args
        return getattr(call.args[0], "value", None) == target
    if kind == "and":
        return any(_negates_off_population_call(op, target) for op in guard.operands)
    return False


def _installed_pytest_raises_boundary(tmp_path, manager_call, body):
    from sugar_lift_py_tests.context_manager_contract import (
        EffectBoundarySemanticsV1,
        ExpectsModeV1,
        FormalArgumentProjectionV1,
        VariadicKeywordEntryProjectionV1,
    )
    from sugar_lift_py_tests.context_manager_resolution import (
        SourceDerivedContextManagerRefV1,
    )
    from sugar_lift_py_tests.sugar.with_effect_boundary_sugar import (
        WithEffectBoundarySugar,
    )

    tree, context = _installed_pytest_boundary(tmp_path, manager_call, body)
    assert len(context.source_derived_contract_refs) == 1
    reference = next(iter(context.source_derived_contract_refs.values()))
    assert isinstance(reference, SourceDerivedContextManagerRefV1), reference
    assert isinstance(reference.semantics, EffectBoundarySemanticsV1)
    assert isinstance(reference.semantics.mode, ExpectsModeV1)
    assert reference.semantics.expected_type_operand == FormalArgumentProjectionV1(0)
    assert reference.semantics.message_pattern_operand == (
        VariadicKeywordEntryProjectionV1(3, "match")
    )
    with_node = next(node for node in tree.nodes() if node.kind == "With")
    boundary = with_node.sugar()
    assert isinstance(boundary, WithEffectBoundarySugar)
    assert boundary.semantics == reference.semantics
    return boundary


def test_installed_pytest_raises_truthful_route_cites_kwargs_match(
    tmp_path,
):
    """Installed ``pytest.raises(ValueError, match="boom")`` absorbs a match."""
    from sugar_lift_py_tests.outcome import Completed, outcome_to_exitset

    boundary = _installed_pytest_raises_boundary(
        tmp_path,
        'pytest.raises(ValueError, match="boom")',
        'raise ValueError("boom")',
    )
    exits = _without_pytest_raises_construction_halts(
        outcome_to_exitset(boundary.desugar()).exits
    )
    assert len(exits) == 1
    assert isinstance(exits[0], Completed)
    # Absorbed wherever the manager was constructed: re.compile completed.
    assert "python:off_population_call.completes" in repr(exits[0].guard)


def test_installed_pytest_raises_wrong_message_is_not_absorbed(tmp_path):
    """A ValueError whose text is not the cited pattern stays a raise halt."""
    from sugar_lift_py_tests.effect import RaiseEffect
    from sugar_lift_py_tests.outcome import Halted, outcome_to_exitset

    boundary = _installed_pytest_raises_boundary(
        tmp_path,
        'pytest.raises(ValueError, match="boom")',
        'raise ValueError("other")',
    )
    exits = _without_pytest_raises_construction_halts(
        outcome_to_exitset(boundary.desugar()).exits
    )
    assert len(exits) == 1
    assert isinstance(exits[0], Halted)
    assert isinstance(exits[0].effect, RaiseEffect)
    assert exits[0].effect.exception_name == "ValueError"


def test_installed_pytest_raises_empty_body_is_expectation_not_met(tmp_path):
    """A body that does not raise is ExpectationNotMet, not a completed with."""
    from sugar_lift_py_tests.effect import ExpectationNotMetEffect
    from sugar_lift_py_tests.outcome import Halted, outcome_to_exitset

    boundary = _installed_pytest_raises_boundary(
        tmp_path,
        'pytest.raises(ValueError, match="boom")',
        "pass",
    )
    exits = _without_pytest_raises_construction_halts(
        outcome_to_exitset(boundary.desugar()).exits
    )
    assert len(exits) == 1
    assert isinstance(exits[0], Halted)
    assert isinstance(exits[0].effect, ExpectationNotMetEffect)


def test_installed_pytest_raises_lying_legacy_callable_route_stays_typed_loud(
    tmp_path,
):
    """Function-form ``pytest.raises(ValueError, int, "bad")`` is not a CM."""
    from sugar_lift_py_tests.context_manager_resolution import (
        ContextManagerResolutionGapV1,
    )
    from sugar_source_tree.panic import ContextManagerResolutionConstructionGap

    tree, context = _installed_pytest_boundary(
        tmp_path,
        'pytest.raises(ValueError, int, "bad")',
        "pass",
    )

    assert len(context.source_derived_contract_refs) == 1
    reference = next(iter(context.source_derived_contract_refs.values()))
    assert isinstance(reference, ContextManagerResolutionGapV1)
    assert reference.kind == "source-body-contract-error"
    assert "does not fit authenticated signature" in reference.detail
    with_node = next(node for node in tree.nodes() if node.kind == "With")
    with pytest.raises(ContextManagerResolutionConstructionGap) as caught:
        with_node.sugar()

    assert caught.value.kind == "source-body-contract-error"
    assert "does not fit authenticated signature" in caught.value.observed
    site = caught.value.args[0]
    assert (site.start_line, site.start_col, site.end_line, site.end_col) == (
        3,
        9,
        3,
        46,
    )


def test_installed_pytest_raises_excinfo_type_is_the_raised_class(tmp_path):
    """``as excinfo`` later projects ``.type`` as the language-owned class."""
    from sugar_lift_py_tests.context_manager_resolution import (
        TreeConstructionContextV1,
    )
    from sugar_lift_py_tests.floor.builtin_exception_class_value import (
        BuiltinExceptionClassValue,
    )
    from sugar_lift_py_tests.floor.return_value import ReturnValue
    from sugar_lift_py_tests.outcome import Completed, outcome_to_exitset
    from sugar_lift_py_tests.temporal.builtin_name_bindings import builtin_name_temporal

    consumer = (
        "import pytest\n"
        "def use_boundary():\n"
        "    with pytest.raises(ValueError) as excinfo:\n"
        '        raise ValueError("boom")\n'
        "    return excinfo.type\n"
    )
    path = tmp_path / "consumer.py"
    path.write_text(consumer, encoding="utf-8")
    context = TreeConstructionContextV1.for_source_call_construction()
    tree = SourceFile(
        (consumer, str(path), blake3_512_of(consumer.encode("utf-8"))),
        construction_context=context,
    )
    pytest_distribution = importlib.metadata.distribution("pytest")
    populate_source_derived_resource_refs(
        tree,
        root=tmp_path,
        path=path,
        session=SourceResolutionSession(
            enrolled_distributions=frozenset({pytest_distribution.metadata["Name"]})
        ),
    )
    fn = next(node for node in tree.nodes() if node.kind == "FunctionDef")
    exits = _without_pytest_raises_construction_halts(
        outcome_to_exitset(fn.sugar().desugar()).exits
    )
    assert len(exits) == 1
    assert isinstance(exits[0], Completed)
    record = exits[0].value.record
    returned = next(
        entry.value
        for entry in record.statements
        if isinstance(entry, ReturnValue)
    )
    assert isinstance(returned, BuiltinExceptionClassValue)
    assert returned.name == "ValueError"
    assert returned is builtin_name_temporal().value_if_bound("ValueError")


def test_installed_pytest_raises_excinfo_value_is_the_raised_instance(tmp_path):
    """``excinfo.value`` is the already-authenticated raised instance."""
    from sugar_lift_py_tests.context_manager_resolution import (
        TreeConstructionContextV1,
    )
    from sugar_lift_py_tests.floor.call_site_value import CallSiteValue
    from sugar_lift_py_tests.floor.return_value import ReturnValue
    from sugar_lift_py_tests.floor.string_value import StringValue
    from sugar_lift_py_tests.outcome import Completed, outcome_to_exitset

    consumer = (
        "import pytest\n"
        "def use_boundary():\n"
        "    with pytest.raises(ValueError) as excinfo:\n"
        '        raise ValueError("boom")\n'
        "    return excinfo.value\n"
    )
    path = tmp_path / "consumer.py"
    path.write_text(consumer, encoding="utf-8")
    context = TreeConstructionContextV1.for_source_call_construction()
    tree = SourceFile(
        (consumer, str(path), blake3_512_of(consumer.encode("utf-8"))),
        construction_context=context,
    )
    pytest_distribution = importlib.metadata.distribution("pytest")
    populate_source_derived_resource_refs(
        tree,
        root=tmp_path,
        path=path,
        session=SourceResolutionSession(
            enrolled_distributions=frozenset({pytest_distribution.metadata["Name"]})
        ),
    )
    fn = next(node for node in tree.nodes() if node.kind == "FunctionDef")
    exits = _without_pytest_raises_construction_halts(
        outcome_to_exitset(fn.sugar().desugar()).exits
    )
    assert len(exits) == 1
    assert isinstance(exits[0], Completed)
    record = exits[0].value.record
    returned = next(
        entry.value
        for entry in record.statements
        if isinstance(entry, ReturnValue)
    )
    assert isinstance(returned, CallSiteValue)
    assert returned.target_name == "ValueError"
    assert returned.arg_values == (StringValue("boom"),)


def test_installed_pytest_raises_excinfo_value_args_are_the_constructor_arguments(
    tmp_path,
):
    """``excinfo.value.args`` is the raised instance's constructor arguments."""
    from sugar_lift_py_tests.context_manager_resolution import (
        TreeConstructionContextV1,
    )
    from sugar_lift_py_tests.floor.return_value import ReturnValue
    from sugar_lift_py_tests.floor.string_value import StringValue
    from sugar_lift_py_tests.floor.tuple_value import TupleValue
    from sugar_lift_py_tests.outcome import Completed, outcome_to_exitset

    consumer = (
        "import pytest\n"
        "def use_boundary():\n"
        "    with pytest.raises(ValueError) as excinfo:\n"
        '        raise ValueError("boom")\n'
        "    return excinfo.value.args\n"
    )
    path = tmp_path / "consumer.py"
    path.write_text(consumer, encoding="utf-8")
    context = TreeConstructionContextV1.for_source_call_construction()
    tree = SourceFile(
        (consumer, str(path), blake3_512_of(consumer.encode("utf-8"))),
        construction_context=context,
    )
    pytest_distribution = importlib.metadata.distribution("pytest")
    populate_source_derived_resource_refs(
        tree,
        root=tmp_path,
        path=path,
        session=SourceResolutionSession(
            enrolled_distributions=frozenset({pytest_distribution.metadata["Name"]})
        ),
    )
    fn = next(node for node in tree.nodes() if node.kind == "FunctionDef")
    exits = _without_pytest_raises_construction_halts(
        outcome_to_exitset(fn.sugar().desugar()).exits
    )
    assert len(exits) == 1
    assert isinstance(exits[0], Completed)
    record = exits[0].value.record
    returned = next(
        entry.value
        for entry in record.statements
        if isinstance(entry, ReturnValue)
    )
    assert returned == TupleValue(elements=(StringValue("boom"),))


def _contextmanager_decorated(source: str, name: str = "make_guard") -> str:
    """Decorate the fixture generator with ``@contextlib.contextmanager``.

    A bare generator function is not a context manager: ``with g():`` raises
    TypeError (``GeneratorObjectWithSugar``). These fixtures exercise the
    generator-manager machine, so they state the decorator that makes one.
    contextlib stays off the enrolled roster, so the head is consumed by
    ``GeneratorWithSugar`` under the same law.
    """
    marker = f"def {name}("
    assert source.count(marker) == 1, source
    return "import contextlib\n" + source.replace(
        marker, f"@contextlib.contextmanager\n{marker}"
    )


def _installed_generator_with(tmp_path, source: str, consumer: str):
    distribution = _distribution(tmp_path, _contextmanager_decorated(source))
    path = tmp_path / "consumer.py"
    path.write_text(consumer, encoding="utf-8")
    from sugar_lift_py_tests.context_manager_resolution import (
        TreeConstructionContextV1,
    )

    context = TreeConstructionContextV1.for_source_call_construction()
    tree = SourceFile(
        (consumer, str(path), blake3_512_of(consumer.encode("utf-8"))),
        construction_context=context,
    )
    populate_source_derived_resource_refs(
        tree,
        root=tmp_path,
        path=path,
        distribution_index={"arbitrary": distribution},
        session=SourceResolutionSession(
            enrolled_distributions=frozenset({distribution.metadata["Name"]})
        ),
    )
    return next(node for node in tree.nodes() if node.kind == "With").sugar()



def _without_catch_warnings_construction_halt(faces, constructions=1):
    """The halted faces after ``warnings.catch_warnings(...)``'s own construction.

    That construction is an off-population call inside the enrolled body, so
    it completes only under its opaque atom and halts with an
    ``UndeterminedRaiseEffect`` under the complement, before ``__enter__`` is
    ever called. Asserting it here keeps every test's remaining halt count
    about the entered manager.
    """
    from sugar_lift_py_tests.effect.raise_effect import UndeterminedRaiseEffect
    from sugar_lift_py_tests.outcome import Halted

    halted = [face for face in faces if isinstance(face, Halted)]
    construction = [
        face
        for face in halted
        if isinstance(face.effect, UndeterminedRaiseEffect)
        and face.effect.producer_node_owner
        == "OffPopulationCall:python:warnings.catch_warnings"
    ]
    assert len(construction) == constructions, construction
    for face in construction:
        assert _negates_off_population_completion(face.guard), face.guard
    return [face for face in halted if all(face is not c for c in construction)]


def _negates_off_population_completion(guard):
    """``guard`` conjoins ``not python:off_population_call.completes(...)``."""
    kind = getattr(guard, "kind", None)
    if kind == "not":
        operand = guard.operands[0]
        return getattr(operand, "name", None) == "python:off_population_call.completes"
    if kind == "and":
        return any(_negates_off_population_completion(op) for op in guard.operands)
    return False


def test_installed_cited_opaque_nested_with_yields_open_enter_result(tmp_path):
    """A nameable ``with warnings.catch_warnings() as w: yield w`` keeps both enter faces.

    Enter is not invented as success, and ``w`` is the open enter-result
    coordinate, not a fabricated warning list.
    """
    from sugar_lift_py_tests.effect import (
        ContextManagerEnterRuntimeEffect,
        ContextManagerExitRuntimeEffect,
    )
    from sugar_lift_py_tests.floor.block_value import BlockValue
    from sugar_lift_py_tests.floor.opaque_manager_protocol_coordinate import (
        OpaqueManagerProtocolCoordinate,
    )
    from sugar_lift_py_tests.generator_construction import (
        NestedCitedOpaqueManagerStepV1,
        YieldEffect,
    )
    from sugar_lift_py_tests.outcome import Complete, Completed, Halted, Incomplete
    from sugar_lift_py_tests.sugar.exit_set_routing import sugar_outcome_to_exitset
    from sugar_lift_py_tests.sugar.generator_with_sugar import GeneratorWithSugar

    boundary = _installed_generator_with(
        tmp_path,
        (
            "import warnings\n"
            "def make_guard():\n"
            "    with warnings.catch_warnings(record=True) as w:\n"
            "        yield w\n"
        ),
        "import arbitrary\ndef use():\n    with arbitrary.make_guard():\n        pass\n",
    )
    assert isinstance(boundary, GeneratorWithSugar)
    machine = sugar_outcome_to_exitset(boundary.manager.desugar()).exits[0].value
    assert any(
        isinstance(step, NestedCitedOpaqueManagerStepV1) for step in machine.steps
    )
    entered = machine.resume()
    faces = list(entered.exits)
    halted = _without_catch_warnings_construction_halt(faces)
    completed = [face for face in faces if isinstance(face, Completed)]
    assert len(halted) == 1
    assert isinstance(halted[0].effect, ContextManagerEnterRuntimeEffect)
    assert "warnings.catch_warnings" in halted[0].effect.reason
    assert len(completed) == 1
    assert isinstance(completed[0].value, YieldEffect)
    assert isinstance(completed[0].value.value, OpaqueManagerProtocolCoordinate)
    assert completed[0].value.value.symbol == "python:cm_enter_result"
    constructed = boundary.desugar()
    assert isinstance(constructed, Complete)
    assert isinstance(constructed.value, BlockValue)
    effects = [
        statement.effect
        for statement in constructed.value.statements
        if isinstance(statement, Incomplete)
    ]
    assert any(
        isinstance(effect, ContextManagerEnterRuntimeEffect)
        and "warnings.catch_warnings" in effect.reason
        for effect in effects
    )
    assert any(
        isinstance(effect, ContextManagerExitRuntimeEffect)
        and "warnings.catch_warnings" in effect.reason
        for effect in effects
    )


def test_installed_cited_opaque_nested_with_try_finally_pass_yields_open_enter_result(tmp_path):
    """A handler-free ``try: yield w; finally: pass`` composes FinallyStepV1.

    Cleanup is empty terms, not invented success. Enter still keeps both
    open faces, and ``w`` is still the open enter-result coordinate.
    """
    from sugar_lift_py_tests.effect import (
        ContextManagerEnterRuntimeEffect,
        ContextManagerExitRuntimeEffect,
    )
    from sugar_lift_py_tests.floor.block_value import BlockValue
    from sugar_lift_py_tests.floor.opaque_manager_protocol_coordinate import (
        OpaqueManagerProtocolCoordinate,
    )
    from sugar_lift_py_tests.generator_construction import (
        FinallyStepV1,
        NestedCitedOpaqueManagerStepV1,
        YieldEffect,
        YieldStepV1,
    )
    from sugar_lift_py_tests.outcome import Complete, Completed, Halted, Incomplete
    from sugar_lift_py_tests.sugar.exit_set_routing import sugar_outcome_to_exitset
    from sugar_lift_py_tests.sugar.generator_with_sugar import GeneratorWithSugar

    boundary = _installed_generator_with(
        tmp_path,
        (
            "import warnings\n"
            "def make_guard():\n"
            "    with warnings.catch_warnings(record=True) as w:\n"
            "        try:\n"
            "            yield w\n"
            "        finally:\n"
            "            pass\n"
        ),
        "import arbitrary\ndef use():\n    with arbitrary.make_guard():\n        pass\n",
    )
    assert isinstance(boundary, GeneratorWithSugar)
    machine = sugar_outcome_to_exitset(boundary.manager.desugar()).exits[0].value
    step = next(
        item
        for item in machine.steps
        if isinstance(item, NestedCitedOpaqueManagerStepV1)
    )
    assert any(isinstance(item, YieldStepV1) for item in step.body_steps)
    assert any(
        isinstance(item, FinallyStepV1) and item.statements == () and item.cleanup_steps == ()
        for item in step.body_steps
    )
    entered = machine.resume()
    faces = list(entered.exits)
    halted = _without_catch_warnings_construction_halt(faces)
    completed = [face for face in faces if isinstance(face, Completed)]
    assert len(halted) == 1
    assert isinstance(halted[0].effect, ContextManagerEnterRuntimeEffect)
    assert "warnings.catch_warnings" in halted[0].effect.reason
    assert len(completed) == 1
    assert isinstance(completed[0].value, YieldEffect)
    assert isinstance(completed[0].value.value, OpaqueManagerProtocolCoordinate)
    assert completed[0].value.value.symbol == "python:cm_enter_result"
    constructed = boundary.desugar()
    assert isinstance(constructed, Complete)
    assert isinstance(constructed.value, BlockValue)
    effects = [
        statement.effect
        for statement in constructed.value.statements
        if isinstance(statement, Incomplete)
    ]
    assert any(
        isinstance(effect, ContextManagerEnterRuntimeEffect)
        and "warnings.catch_warnings" in effect.reason
        for effect in effects
    )
    assert any(
        isinstance(effect, ContextManagerExitRuntimeEffect)
        and "warnings.catch_warnings" in effect.reason
        for effect in effects
    )


def test_installed_cited_opaque_nested_with_simplefilter_is_term_step(tmp_path):
    """``warnings.simplefilter(...)`` in a nameable cited-opaque body is TermStepV1.

    The term is the constructed call, not an invented filter application.
    Enter still keeps both open faces, and ``w`` is still the enter-result
    coordinate when the term completes.
    """
    from sugar_lift_py_tests.effect import ContextManagerEnterRuntimeEffect
    from sugar_lift_py_tests.floor.opaque_manager_protocol_coordinate import (
        OpaqueManagerProtocolCoordinate,
    )
    from sugar_lift_py_tests.generator_construction import (
        FinallyStepV1,
        NestedCitedOpaqueManagerStepV1,
        TermStepV1,
        YieldEffect,
        YieldStepV1,
    )
    from sugar_lift_py_tests.outcome import Completed, Halted
    from sugar_lift_py_tests.sugar.exit_set_routing import sugar_outcome_to_exitset
    from sugar_lift_py_tests.sugar.generator_with_sugar import GeneratorWithSugar
    from sugar_lift_py_tests.sugar.sugar_base import ConstructedTermSugar

    boundary = _installed_generator_with(
        tmp_path,
        (
            "import warnings\n"
            "def make_guard():\n"
            "    with warnings.catch_warnings(record=True) as w:\n"
            "        warnings.simplefilter(\"always\")\n"
            "        try:\n"
            "            yield w\n"
            "        finally:\n"
            "            pass\n"
        ),
        "import arbitrary\ndef use():\n    with arbitrary.make_guard():\n        pass\n",
    )
    assert isinstance(boundary, GeneratorWithSugar)
    machine = sugar_outcome_to_exitset(boundary.manager.desugar()).exits[0].value
    step = next(
        item
        for item in machine.steps
        if isinstance(item, NestedCitedOpaqueManagerStepV1)
    )
    terms = [item for item in step.body_steps if isinstance(item, TermStepV1)]
    assert len(terms) == 1
    assert isinstance(terms[0].term, ConstructedTermSugar)
    assert any(isinstance(item, YieldStepV1) for item in step.body_steps)
    assert any(isinstance(item, FinallyStepV1) for item in step.body_steps)
    entered = machine.resume()
    faces = list(entered.exits)
    halted = _without_catch_warnings_construction_halt(faces)
    completed = [face for face in faces if isinstance(face, Completed)]
    # ``warnings.simplefilter`` is an off-population call: it may raise. That
    # raise leaves the with body before the yield, so the cited manager's
    # __exit__ still runs over it: the exit may itself halt, may re-raise the
    # filter's exception, or may suppress it (the generator continues after
    # the with). Inventing that the filter ran is not honest; neither is
    # letting its raise skip __exit__.
    from sugar_lift_py_tests.effect.raise_effect import UndeterminedRaiseEffect
    from sugar_lift_py_tests.generator_construction import GeneratorConstructionV1

    by_kind = {}
    for face in halted:
        by_kind.setdefault(type(face.effect).__name__, []).append(face.effect)
    assert sorted(by_kind) == [
        "ContextManagerEnterRuntimeEffect",
        "ContextManagerExitRuntimeEffect",
        "UndeterminedRaiseEffect",
    ]
    assert all(len(effects) == 1 for effects in by_kind.values())
    (enter,) = by_kind["ContextManagerEnterRuntimeEffect"]
    assert "warnings.catch_warnings" in enter.reason
    (exit_,) = by_kind["ContextManagerExitRuntimeEffect"]
    assert "warnings.catch_warnings" in exit_.reason
    (filtered,) = by_kind["UndeterminedRaiseEffect"]
    assert isinstance(filtered, UndeterminedRaiseEffect)
    assert filtered.producer_node_owner == "OffPopulationCall:python:warnings.simplefilter"
    assert len(completed) == 2
    (yielded,) = [face.value for face in completed if isinstance(face.value, YieldEffect)]
    assert isinstance(yielded.value, OpaqueManagerProtocolCoordinate)
    assert yielded.value.symbol == "python:cm_enter_result"
    (suppressed,) = [
        face.value
        for face in completed
        if isinstance(face.value, GeneratorConstructionV1)
    ]
    assert not any(
        isinstance(step, NestedCitedOpaqueManagerStepV1)
        for step in suppressed.steps[suppressed.cursor :]
    )


def test_installed_cited_opaque_nested_with_except_handler_stays_opaque(tmp_path):
    """An except-handler inside cited-opaque catch_warnings stays a loud With."""
    from sugar_lift_py_tests.sugar.generator_with_sugar import GeneratorWithSugar
    from sugar_source_tree.panic import SugarNotWritten

    boundary = _installed_generator_with(
        tmp_path,
        (
            "import warnings\n"
            "def make_guard():\n"
            "    with warnings.catch_warnings(record=True) as w:\n"
            "        try:\n"
            "            yield w\n"
            "        except Exception:\n"
            "            pass\n"
        ),
        "import arbitrary\ndef use():\n    with arbitrary.make_guard():\n        pass\n",
    )
    assert isinstance(boundary, GeneratorWithSugar)
    with pytest.raises(SugarNotWritten) as caught:
        boundary.desugar()
    assert caught.value.owner == "GeneratorWithSugar.desugar"
    assert caught.value.observed == "opaque generator transition: With carrying a suspension"


def test_installed_cited_opaque_nested_with_structured_finally_assign(tmp_path):
    """A finally assign is structured cleanup_steps, not a term payload.

    The assign is named, not invented as a performed store beyond AssignStepV1.
    Enter still keeps both open faces, and ``w`` is still the enter-result
    coordinate.
    """
    from sugar_lift_py_tests.effect import (
        ContextManagerEnterRuntimeEffect,
        ContextManagerExitRuntimeEffect,
    )
    from sugar_lift_py_tests.floor.block_value import BlockValue
    from sugar_lift_py_tests.floor.opaque_manager_protocol_coordinate import (
        OpaqueManagerProtocolCoordinate,
    )
    from sugar_lift_py_tests.generator_construction import (
        AssignStepV1,
        FinallyStepV1,
        NestedCitedOpaqueManagerStepV1,
        YieldEffect,
        YieldStepV1,
    )
    from sugar_lift_py_tests.outcome import Complete, Completed, Halted, Incomplete
    from sugar_lift_py_tests.sugar.exit_set_routing import sugar_outcome_to_exitset
    from sugar_lift_py_tests.sugar.generator_with_sugar import GeneratorWithSugar

    boundary = _installed_generator_with(
        tmp_path,
        (
            "import warnings\n"
            "def make_guard():\n"
            "    with warnings.catch_warnings(record=True) as w:\n"
            "        try:\n"
            "            yield w\n"
            "        finally:\n"
            "            leftover = 1\n"
        ),
        "import arbitrary\ndef use():\n    with arbitrary.make_guard():\n        pass\n",
    )
    assert isinstance(boundary, GeneratorWithSugar)
    machine = sugar_outcome_to_exitset(boundary.manager.desugar()).exits[0].value
    step = next(
        item
        for item in machine.steps
        if isinstance(item, NestedCitedOpaqueManagerStepV1)
    )
    cleanup = next(item for item in step.body_steps if isinstance(item, FinallyStepV1))
    assert cleanup.statements == ()
    assert any(
        isinstance(item, AssignStepV1) and item.name == "leftover"
        for item in cleanup.cleanup_steps
    )
    assert any(isinstance(item, YieldStepV1) for item in step.body_steps)
    entered = machine.resume()
    faces = list(entered.exits)
    halted = _without_catch_warnings_construction_halt(faces)
    completed = [face for face in faces if isinstance(face, Completed)]
    assert len(halted) == 1
    assert isinstance(halted[0].effect, ContextManagerEnterRuntimeEffect)
    assert "warnings.catch_warnings" in halted[0].effect.reason
    assert len(completed) == 1
    assert isinstance(completed[0].value, YieldEffect)
    assert isinstance(completed[0].value.value, OpaqueManagerProtocolCoordinate)
    assert completed[0].value.value.symbol == "python:cm_enter_result"
    constructed = boundary.desugar()
    assert isinstance(constructed, Complete)
    assert isinstance(constructed.value, BlockValue)
    effects = [
        statement.effect
        for statement in constructed.value.statements
        if isinstance(statement, Incomplete)
    ]
    assert any(
        isinstance(effect, ContextManagerEnterRuntimeEffect)
        and "warnings.catch_warnings" in effect.reason
        for effect in effects
    )
    assert any(
        isinstance(effect, ContextManagerExitRuntimeEffect)
        and "warnings.catch_warnings" in effect.reason
        for effect in effects
    )


def test_installed_cited_opaque_nested_with_structured_finally_for(tmp_path):
    """A finally for is ForStepV1 cleanup, using existing iter/next transition.

    The loop is seated, not invented as performed items. Enter still keeps
    both open faces, and ``w`` is still the enter-result coordinate.
    """
    from sugar_lift_py_tests.effect import (
        ContextManagerEnterRuntimeEffect,
        ContextManagerExitRuntimeEffect,
    )
    from sugar_lift_py_tests.floor.block_value import BlockValue
    from sugar_lift_py_tests.floor.opaque_manager_protocol_coordinate import (
        OpaqueManagerProtocolCoordinate,
    )
    from sugar_lift_py_tests.generator_construction import (
        AssignStepV1,
        FinallyStepV1,
        ForStepV1,
        NestedCitedOpaqueManagerStepV1,
        YieldEffect,
        YieldStepV1,
    )
    from sugar_lift_py_tests.outcome import Complete, Completed, Halted, Incomplete
    from sugar_lift_py_tests.sugar.exit_set_routing import sugar_outcome_to_exitset
    from sugar_lift_py_tests.sugar.generator_with_sugar import GeneratorWithSugar

    boundary = _installed_generator_with(
        tmp_path,
        (
            "import warnings\n"
            "def make_guard():\n"
            "    with warnings.catch_warnings(record=True) as w:\n"
            "        try:\n"
            "            yield w\n"
            "        finally:\n"
            "            for leftover, other in ((1, 2),):\n"
            "                seen = leftover\n"
        ),
        "import arbitrary\ndef use():\n    with arbitrary.make_guard():\n        pass\n",
    )
    assert isinstance(boundary, GeneratorWithSugar)
    machine = sugar_outcome_to_exitset(boundary.manager.desugar()).exits[0].value
    step = next(
        item
        for item in machine.steps
        if isinstance(item, NestedCitedOpaqueManagerStepV1)
    )
    cleanup = next(item for item in step.body_steps if isinstance(item, FinallyStepV1))
    loop = next(item for item in cleanup.cleanup_steps if isinstance(item, ForStepV1))
    assert len(loop.target_coordinates) == 2
    assert any(
        isinstance(item, AssignStepV1) and item.name == "seen"
        for item in loop.body_steps
    )
    assert any(isinstance(item, YieldStepV1) for item in step.body_steps)
    entered = machine.resume()
    faces = list(entered.exits)
    halted = _without_catch_warnings_construction_halt(faces)
    completed = [face for face in faces if isinstance(face, Completed)]
    assert len(halted) == 1
    assert isinstance(halted[0].effect, ContextManagerEnterRuntimeEffect)
    assert "warnings.catch_warnings" in halted[0].effect.reason
    assert len(completed) == 1
    assert isinstance(completed[0].value, YieldEffect)
    assert isinstance(completed[0].value.value, OpaqueManagerProtocolCoordinate)
    assert completed[0].value.value.symbol == "python:cm_enter_result"
    constructed = boundary.desugar()
    assert isinstance(constructed, Complete)
    assert isinstance(constructed.value, BlockValue)
    effects = [
        statement.effect
        for statement in constructed.value.statements
        if isinstance(statement, Incomplete)
    ]
    assert any(
        isinstance(effect, ContextManagerEnterRuntimeEffect)
        and "warnings.catch_warnings" in effect.reason
        for effect in effects
    )
    assert any(
        isinstance(effect, ContextManagerExitRuntimeEffect)
        and "warnings.catch_warnings" in effect.reason
        for effect in effects
    )


def test_installed_cited_opaque_nested_with_structured_finally_for_bare_name(tmp_path):
    """A finally ``for leftover in [1]`` is ForStepV1 cleanup.

    The bare name binds the iterated item, not an unpack demand. Enter
    still keeps both open faces. Does not treat the enter result as a list.
    """
    from sugar_lift_py_tests.effect import (
        ContextManagerEnterRuntimeEffect,
        ContextManagerExitRuntimeEffect,
    )
    from sugar_lift_py_tests.floor.block_value import BlockValue
    from sugar_lift_py_tests.floor.opaque_manager_protocol_coordinate import (
        OpaqueManagerProtocolCoordinate,
    )
    from sugar_lift_py_tests.generator_construction import (
        AssignStepV1,
        FinallyStepV1,
        ForStepV1,
        NestedCitedOpaqueManagerStepV1,
        YieldEffect,
        YieldStepV1,
    )
    from sugar_lift_py_tests.outcome import Complete, Completed, Halted, Incomplete
    from sugar_lift_py_tests.sugar.exit_set_routing import sugar_outcome_to_exitset
    from sugar_lift_py_tests.sugar.generator_with_sugar import GeneratorWithSugar

    boundary = _installed_generator_with(
        tmp_path,
        (
            "import warnings\n"
            "def make_guard():\n"
            "    with warnings.catch_warnings(record=True) as w:\n"
            "        try:\n"
            "            yield w\n"
            "        finally:\n"
            "            for leftover in [1]:\n"
            "                seen = leftover\n"
        ),
        "import arbitrary\ndef use():\n    with arbitrary.make_guard():\n        pass\n",
    )
    assert isinstance(boundary, GeneratorWithSugar)
    machine = sugar_outcome_to_exitset(boundary.manager.desugar()).exits[0].value
    step = next(
        item
        for item in machine.steps
        if isinstance(item, NestedCitedOpaqueManagerStepV1)
    )
    cleanup = next(item for item in step.body_steps if isinstance(item, FinallyStepV1))
    loop = next(item for item in cleanup.cleanup_steps if isinstance(item, ForStepV1))
    assert len(loop.target_coordinates) == 1
    assert tuple(loop.target_coordinates[0].projection_path) == ("target",)
    assert any(
        isinstance(item, AssignStepV1) and item.name == "seen"
        for item in loop.body_steps
    )
    assert any(isinstance(item, YieldStepV1) for item in step.body_steps)
    entered = machine.resume()
    faces = list(entered.exits)
    halted = _without_catch_warnings_construction_halt(faces)
    completed = [face for face in faces if isinstance(face, Completed)]
    assert len(halted) == 1
    assert isinstance(halted[0].effect, ContextManagerEnterRuntimeEffect)
    assert "warnings.catch_warnings" in halted[0].effect.reason
    assert len(completed) == 1
    assert isinstance(completed[0].value, YieldEffect)
    assert isinstance(completed[0].value.value, OpaqueManagerProtocolCoordinate)
    assert completed[0].value.value.symbol == "python:cm_enter_result"
    constructed = boundary.desugar()
    assert isinstance(constructed, Complete)
    assert isinstance(constructed.value, BlockValue)
    effects = [
        statement.effect
        for statement in constructed.value.statements
        if isinstance(statement, Incomplete)
    ]
    assert any(
        isinstance(effect, ContextManagerEnterRuntimeEffect)
        and "warnings.catch_warnings" in effect.reason
        for effect in effects
    )
    assert any(
        isinstance(effect, ContextManagerExitRuntimeEffect)
        and "warnings.catch_warnings" in effect.reason
        for effect in effects
    )










def test_installed_cited_opaque_with_inside_cited_opaque_with(tmp_path):
    """An inner cited-opaque With is the already-written nested step.

    First resume cites both open enter faces and yields the inner enter
    result. Desugar also cites both exits. This does not invent a warning
    list or enter success.
    """
    from sugar_lift_py_tests.effect import (
        ContextManagerEnterRuntimeEffect,
        ContextManagerExitRuntimeEffect,
    )
    from sugar_lift_py_tests.floor.block_value import BlockValue
    from sugar_lift_py_tests.floor.opaque_manager_protocol_coordinate import (
        OpaqueManagerProtocolCoordinate,
    )
    from sugar_lift_py_tests.generator_construction import (
        NestedCitedOpaqueManagerStepV1,
        YieldEffect,
        YieldStepV1,
    )
    from sugar_lift_py_tests.outcome import Complete, Completed, Halted, Incomplete
    from sugar_lift_py_tests.sugar.exit_set_routing import sugar_outcome_to_exitset
    from sugar_lift_py_tests.sugar.generator_with_sugar import GeneratorWithSugar

    boundary = _installed_generator_with(
        tmp_path,
        (
            "import warnings\n"
            "def make_guard():\n"
            "    with warnings.catch_warnings(record=True) as w:\n"
            "        with warnings.catch_warnings(record=True) as inner:\n"
            "            yield inner\n"
        ),
        "import arbitrary\ndef use():\n    with arbitrary.make_guard():\n        pass\n",
    )
    assert isinstance(boundary, GeneratorWithSugar)
    machine = sugar_outcome_to_exitset(boundary.manager.desugar()).exits[0].value
    outer = next(
        item
        for item in machine.steps
        if isinstance(item, NestedCitedOpaqueManagerStepV1)
    )
    inner_steps = [
        item
        for item in outer.body_steps
        if isinstance(item, NestedCitedOpaqueManagerStepV1)
    ]
    assert len(inner_steps) == 1
    assert inner_steps[0].as_name == "inner"
    assert any(isinstance(item, YieldStepV1) for item in inner_steps[0].body_steps)
    entered = machine.resume()
    faces = list(entered.exits)
    halted = _without_catch_warnings_construction_halt(faces, constructions=2)
    completed = [face for face in faces if isinstance(face, Completed)]
    enter_effects = [
        face.effect
        for face in halted
        if isinstance(face.effect, ContextManagerEnterRuntimeEffect)
        and "warnings.catch_warnings" in face.effect.reason
    ]
    assert len(enter_effects) == 2
    assert len(completed) == 1
    assert isinstance(completed[0].value, YieldEffect)
    assert isinstance(completed[0].value.value, OpaqueManagerProtocolCoordinate)
    assert completed[0].value.value.symbol == "python:cm_enter_result"
    constructed = boundary.desugar()
    assert isinstance(constructed, Complete)
    assert isinstance(constructed.value, BlockValue)
    effects = [
        statement.effect
        for statement in constructed.value.statements
        if isinstance(statement, Incomplete)
    ]
    assert (
        sum(
            isinstance(effect, ContextManagerEnterRuntimeEffect)
            and "warnings.catch_warnings" in effect.reason
            for effect in effects
        )
        == 2
    )
    assert (
        sum(
            isinstance(effect, ContextManagerExitRuntimeEffect)
            and "warnings.catch_warnings" in effect.reason
            for effect in effects
        )
        == 2
    )


def test_installed_cited_opaque_nested_with_yield_from_tuple(tmp_path):
    """A nested ``yield from (1,)`` is YieldFromStepV1 cleanup-adjacent body.

    The already-written yield-from law delegates the item. First resume
    yields 1 with the open enter face still cited; desugar also cites
    exit. This does not invent further items or a warning list.
    """
    from sugar_lift_py_tests.effect import (
        ContextManagerEnterRuntimeEffect,
        ContextManagerExitRuntimeEffect,
    )
    from sugar_lift_py_tests.floor.block_value import BlockValue
    from sugar_lift_py_tests.floor.term_value import TermValue
    from sugar_lift_py_tests.generator_construction import (
        AssignStepV1,
        FinallyStepV1,
        NestedCitedOpaqueManagerStepV1,
        YieldEffect,
        YieldFromStepV1,
    )
    from sugar_lift_py_tests.outcome import Complete, Completed, Halted, Incomplete
    from sugar_lift_py_tests.sugar.exit_set_routing import sugar_outcome_to_exitset
    from sugar_lift_py_tests.sugar.generator_with_sugar import GeneratorWithSugar

    boundary = _installed_generator_with(
        tmp_path,
        (
            "import warnings\n"
            "def make_guard():\n"
            "    with warnings.catch_warnings(record=True) as w:\n"
            "        try:\n"
            "            yield from (1,)\n"
            "        finally:\n"
            "            leftover = 1\n"
        ),
        "import arbitrary\ndef use():\n    with arbitrary.make_guard():\n        pass\n",
    )
    assert isinstance(boundary, GeneratorWithSugar)
    machine = sugar_outcome_to_exitset(boundary.manager.desugar()).exits[0].value
    step = next(
        item
        for item in machine.steps
        if isinstance(item, NestedCitedOpaqueManagerStepV1)
    )
    assert any(isinstance(item, YieldFromStepV1) for item in step.body_steps)
    cleanup = next(item for item in step.body_steps if isinstance(item, FinallyStepV1))
    assert any(
        isinstance(item, AssignStepV1) and item.name == "leftover"
        for item in cleanup.cleanup_steps
    )
    entered = machine.resume()
    faces = list(entered.exits)
    halted = _without_catch_warnings_construction_halt(faces)
    completed = [face for face in faces if isinstance(face, Completed)]
    assert len(halted) == 1
    assert isinstance(halted[0].effect, ContextManagerEnterRuntimeEffect)
    assert "warnings.catch_warnings" in halted[0].effect.reason
    assert len(completed) == 1
    assert isinstance(completed[0].value, YieldEffect)
    assert completed[0].value.value == TermValue(1)
    constructed = boundary.desugar()
    assert isinstance(constructed, Complete)
    assert isinstance(constructed.value, BlockValue)
    effects = [
        statement.effect
        for statement in constructed.value.statements
        if isinstance(statement, Incomplete)
    ]
    assert any(
        isinstance(effect, ContextManagerEnterRuntimeEffect)
        and "warnings.catch_warnings" in effect.reason
        for effect in effects
    )
    assert any(
        isinstance(effect, ContextManagerExitRuntimeEffect)
        and "warnings.catch_warnings" in effect.reason
        for effect in effects
    )


def test_installed_cited_opaque_nested_with_structured_finally_attribute_assign(tmp_path):
    """A finally ``holder.hidden = True`` is AttributeAssignStepV1 cleanup.

    First resume still yields the open enter result. Desugar cites the
    already-written ``None.setattr`` AttributeError and the still-open
    enter face. This does not invent that the attribute was stored or
    that exit swallowed the raise.
    """
    from sugar_lift_py_tests.effect import (
        ContextManagerEnterRuntimeEffect,
        RaiseEffect,
    )
    from sugar_lift_py_tests.floor.block_value import BlockValue
    from sugar_lift_py_tests.floor.opaque_manager_protocol_coordinate import (
        OpaqueManagerProtocolCoordinate,
    )
    from sugar_lift_py_tests.generator_construction import (
        AssignStepV1,
        AttributeAssignStepV1,
        FinallyStepV1,
        NestedCitedOpaqueManagerStepV1,
        YieldEffect,
        YieldStepV1,
    )
    from sugar_lift_py_tests.outcome import Complete, Completed, Halted, Incomplete
    from sugar_lift_py_tests.sugar.exit_set_routing import sugar_outcome_to_exitset
    from sugar_lift_py_tests.sugar.generator_with_sugar import GeneratorWithSugar

    boundary = _installed_generator_with(
        tmp_path,
        (
            "import warnings\n"
            "def make_guard():\n"
            "    with warnings.catch_warnings(record=True) as w:\n"
            "        try:\n"
            "            yield w\n"
            "        finally:\n"
            "            holder = None\n"
            "            holder.hidden = True\n"
        ),
        "import arbitrary\ndef use():\n    with arbitrary.make_guard():\n        pass\n",
    )
    assert isinstance(boundary, GeneratorWithSugar)
    machine = sugar_outcome_to_exitset(boundary.manager.desugar()).exits[0].value
    step = next(
        item
        for item in machine.steps
        if isinstance(item, NestedCitedOpaqueManagerStepV1)
    )
    cleanup = next(item for item in step.body_steps if isinstance(item, FinallyStepV1))
    assert any(
        isinstance(item, AssignStepV1) and item.name == "holder"
        for item in cleanup.cleanup_steps
    )
    store = next(
        item for item in cleanup.cleanup_steps if isinstance(item, AttributeAssignStepV1)
    )
    assert store.attr == "hidden"
    assert any(isinstance(item, YieldStepV1) for item in step.body_steps)
    entered = machine.resume()
    faces = list(entered.exits)
    halted = _without_catch_warnings_construction_halt(faces)
    completed = [face for face in faces if isinstance(face, Completed)]
    assert len(halted) == 1
    assert isinstance(halted[0].effect, ContextManagerEnterRuntimeEffect)
    assert "warnings.catch_warnings" in halted[0].effect.reason
    assert len(completed) == 1
    assert isinstance(completed[0].value, YieldEffect)
    assert isinstance(completed[0].value.value, OpaqueManagerProtocolCoordinate)
    assert completed[0].value.value.symbol == "python:cm_enter_result"
    constructed = boundary.desugar()
    assert isinstance(constructed, Complete)
    assert isinstance(constructed.value, BlockValue)
    assert constructed.value.can_fall_through is False
    effects = [
        statement.effect
        for statement in constructed.value.statements
        if isinstance(statement, Incomplete)
    ]
    raised = next(effect for effect in effects if isinstance(effect, RaiseEffect))
    assert raised.exception_name == "AttributeError"
    assert raised.producer_node_owner == "NoneValue.setattr"
    assert any(
        isinstance(effect, ContextManagerEnterRuntimeEffect)
        and "warnings.catch_warnings" in effect.reason
        for effect in effects
    )


def test_installed_cited_opaque_nested_with_structured_finally_import_from(tmp_path):
    """A finally ``from math import sqrt`` is ImportFromStepV1 cleanup.

    The already-written import-from law advances and continues. Enter
    still keeps both open faces. This does not invent that the name was bound.
    """
    from sugar_lift_py_tests.effect import (
        ContextManagerEnterRuntimeEffect,
        ContextManagerExitRuntimeEffect,
    )
    from sugar_lift_py_tests.floor.block_value import BlockValue
    from sugar_lift_py_tests.floor.opaque_manager_protocol_coordinate import (
        OpaqueManagerProtocolCoordinate,
    )
    from sugar_lift_py_tests.generator_construction import (
        FinallyStepV1,
        ImportFromStepV1,
        NestedCitedOpaqueManagerStepV1,
        YieldEffect,
        YieldStepV1,
    )
    from sugar_lift_py_tests.outcome import Complete, Completed, Halted, Incomplete
    from sugar_lift_py_tests.sugar.exit_set_routing import sugar_outcome_to_exitset
    from sugar_lift_py_tests.sugar.generator_with_sugar import GeneratorWithSugar

    boundary = _installed_generator_with(
        tmp_path,
        (
            "import warnings\n"
            "def make_guard():\n"
            "    with warnings.catch_warnings(record=True) as w:\n"
            "        try:\n"
            "            yield w\n"
            "        finally:\n"
            "            from math import sqrt\n"
        ),
        "import arbitrary\ndef use():\n    with arbitrary.make_guard():\n        pass\n",
    )
    assert isinstance(boundary, GeneratorWithSugar)
    machine = sugar_outcome_to_exitset(boundary.manager.desugar()).exits[0].value
    step = next(
        item
        for item in machine.steps
        if isinstance(item, NestedCitedOpaqueManagerStepV1)
    )
    cleanup = next(item for item in step.body_steps if isinstance(item, FinallyStepV1))
    assert any(isinstance(item, ImportFromStepV1) for item in cleanup.cleanup_steps)
    assert any(isinstance(item, YieldStepV1) for item in step.body_steps)
    entered = machine.resume()
    faces = list(entered.exits)
    halted = _without_catch_warnings_construction_halt(faces)
    completed = [face for face in faces if isinstance(face, Completed)]
    assert len(halted) == 1
    assert isinstance(halted[0].effect, ContextManagerEnterRuntimeEffect)
    assert "warnings.catch_warnings" in halted[0].effect.reason
    assert len(completed) == 1
    assert isinstance(completed[0].value, YieldEffect)
    assert isinstance(completed[0].value.value, OpaqueManagerProtocolCoordinate)
    assert completed[0].value.value.symbol == "python:cm_enter_result"
    constructed = boundary.desugar()
    assert isinstance(constructed, Complete)
    assert isinstance(constructed.value, BlockValue)
    effects = [
        statement.effect
        for statement in constructed.value.statements
        if isinstance(statement, Incomplete)
    ]
    assert any(
        isinstance(effect, ContextManagerEnterRuntimeEffect)
        and "warnings.catch_warnings" in effect.reason
        for effect in effects
    )
    assert any(
        isinstance(effect, ContextManagerExitRuntimeEffect)
        and "warnings.catch_warnings" in effect.reason
        for effect in effects
    )


def test_installed_cited_opaque_nested_with_structured_finally_import(tmp_path):
    """A finally ``import math`` is ImportStepV1 cleanup.

    The already-written import law advances and continues. Enter still
    keeps both open faces. This does not invent that the module was loaded.
    """
    from sugar_lift_py_tests.effect import (
        ContextManagerEnterRuntimeEffect,
        ContextManagerExitRuntimeEffect,
    )
    from sugar_lift_py_tests.floor.block_value import BlockValue
    from sugar_lift_py_tests.floor.opaque_manager_protocol_coordinate import (
        OpaqueManagerProtocolCoordinate,
    )
    from sugar_lift_py_tests.generator_construction import (
        FinallyStepV1,
        ImportStepV1,
        NestedCitedOpaqueManagerStepV1,
        YieldEffect,
        YieldStepV1,
    )
    from sugar_lift_py_tests.outcome import Complete, Completed, Halted, Incomplete
    from sugar_lift_py_tests.sugar.exit_set_routing import sugar_outcome_to_exitset
    from sugar_lift_py_tests.sugar.generator_with_sugar import GeneratorWithSugar

    boundary = _installed_generator_with(
        tmp_path,
        (
            "import warnings\n"
            "def make_guard():\n"
            "    with warnings.catch_warnings(record=True) as w:\n"
            "        try:\n"
            "            yield w\n"
            "        finally:\n"
            "            import math\n"
        ),
        "import arbitrary\ndef use():\n    with arbitrary.make_guard():\n        pass\n",
    )
    assert isinstance(boundary, GeneratorWithSugar)
    machine = sugar_outcome_to_exitset(boundary.manager.desugar()).exits[0].value
    step = next(
        item
        for item in machine.steps
        if isinstance(item, NestedCitedOpaqueManagerStepV1)
    )
    cleanup = next(item for item in step.body_steps if isinstance(item, FinallyStepV1))
    assert any(isinstance(item, ImportStepV1) for item in cleanup.cleanup_steps)
    assert any(isinstance(item, YieldStepV1) for item in step.body_steps)
    entered = machine.resume()
    faces = list(entered.exits)
    halted = _without_catch_warnings_construction_halt(faces)
    completed = [face for face in faces if isinstance(face, Completed)]
    assert len(halted) == 1
    assert isinstance(halted[0].effect, ContextManagerEnterRuntimeEffect)
    assert "warnings.catch_warnings" in halted[0].effect.reason
    assert len(completed) == 1
    assert isinstance(completed[0].value, YieldEffect)
    assert isinstance(completed[0].value.value, OpaqueManagerProtocolCoordinate)
    assert completed[0].value.value.symbol == "python:cm_enter_result"
    constructed = boundary.desugar()
    assert isinstance(constructed, Complete)
    assert isinstance(constructed.value, BlockValue)
    effects = [
        statement.effect
        for statement in constructed.value.statements
        if isinstance(statement, Incomplete)
    ]
    assert any(
        isinstance(effect, ContextManagerEnterRuntimeEffect)
        and "warnings.catch_warnings" in effect.reason
        for effect in effects
    )
    assert any(
        isinstance(effect, ContextManagerExitRuntimeEffect)
        and "warnings.catch_warnings" in effect.reason
        for effect in effects
    )


def test_installed_cited_opaque_nested_with_structured_finally_assert(tmp_path):
    """A finally ``assert True`` is AssertStepV1 cleanup.

    The already-written true-assert law advances and continues. Enter
    still keeps both open faces.
    """
    from sugar_lift_py_tests.effect import (
        ContextManagerEnterRuntimeEffect,
        ContextManagerExitRuntimeEffect,
    )
    from sugar_lift_py_tests.floor.block_value import BlockValue
    from sugar_lift_py_tests.floor.opaque_manager_protocol_coordinate import (
        OpaqueManagerProtocolCoordinate,
    )
    from sugar_lift_py_tests.generator_construction import (
        AssertStepV1,
        FinallyStepV1,
        NestedCitedOpaqueManagerStepV1,
        YieldEffect,
        YieldStepV1,
    )
    from sugar_lift_py_tests.outcome import Complete, Completed, Halted, Incomplete
    from sugar_lift_py_tests.sugar.exit_set_routing import sugar_outcome_to_exitset
    from sugar_lift_py_tests.sugar.generator_with_sugar import GeneratorWithSugar

    boundary = _installed_generator_with(
        tmp_path,
        (
            "import warnings\n"
            "def make_guard():\n"
            "    with warnings.catch_warnings(record=True) as w:\n"
            "        try:\n"
            "            yield w\n"
            "        finally:\n"
            "            assert True\n"
        ),
        "import arbitrary\ndef use():\n    with arbitrary.make_guard():\n        pass\n",
    )
    assert isinstance(boundary, GeneratorWithSugar)
    machine = sugar_outcome_to_exitset(boundary.manager.desugar()).exits[0].value
    step = next(
        item
        for item in machine.steps
        if isinstance(item, NestedCitedOpaqueManagerStepV1)
    )
    cleanup = next(item for item in step.body_steps if isinstance(item, FinallyStepV1))
    assert any(isinstance(item, AssertStepV1) for item in cleanup.cleanup_steps)
    assert any(isinstance(item, YieldStepV1) for item in step.body_steps)
    entered = machine.resume()
    faces = list(entered.exits)
    halted = _without_catch_warnings_construction_halt(faces)
    completed = [face for face in faces if isinstance(face, Completed)]
    assert len(halted) == 1
    assert isinstance(halted[0].effect, ContextManagerEnterRuntimeEffect)
    assert "warnings.catch_warnings" in halted[0].effect.reason
    assert len(completed) == 1
    assert isinstance(completed[0].value, YieldEffect)
    assert isinstance(completed[0].value.value, OpaqueManagerProtocolCoordinate)
    assert completed[0].value.value.symbol == "python:cm_enter_result"
    constructed = boundary.desugar()
    assert isinstance(constructed, Complete)
    assert isinstance(constructed.value, BlockValue)
    effects = [
        statement.effect
        for statement in constructed.value.statements
        if isinstance(statement, Incomplete)
    ]
    assert any(
        isinstance(effect, ContextManagerEnterRuntimeEffect)
        and "warnings.catch_warnings" in effect.reason
        for effect in effects
    )
    assert any(
        isinstance(effect, ContextManagerExitRuntimeEffect)
        and "warnings.catch_warnings" in effect.reason
        for effect in effects
    )


def test_installed_cited_opaque_nested_with_structured_finally_assert_false(tmp_path):
    """A finally ``assert False`` is an AssertionError halt, not a fall-through.

    First resume still yields the open enter result. Desugar cites the
    already-written ground AssertionError and the still-open enter face.
    This does not invent that the assertion succeeded or that exit ran.
    """
    from sugar_lift_py_tests.effect import (
        ContextManagerEnterRuntimeEffect,
        RaiseEffect,
    )
    from sugar_lift_py_tests.floor.block_value import BlockValue
    from sugar_lift_py_tests.floor.opaque_manager_protocol_coordinate import (
        OpaqueManagerProtocolCoordinate,
    )
    from sugar_lift_py_tests.generator_construction import (
        AssertStepV1,
        FinallyStepV1,
        NestedCitedOpaqueManagerStepV1,
        YieldEffect,
        YieldStepV1,
    )
    from sugar_lift_py_tests.outcome import Complete, Completed, Halted, Incomplete
    from sugar_lift_py_tests.sugar.exit_set_routing import sugar_outcome_to_exitset
    from sugar_lift_py_tests.sugar.generator_with_sugar import GeneratorWithSugar

    boundary = _installed_generator_with(
        tmp_path,
        (
            "import warnings\n"
            "def make_guard():\n"
            "    with warnings.catch_warnings(record=True) as w:\n"
            "        try:\n"
            "            yield w\n"
            "        finally:\n"
            "            assert False\n"
        ),
        "import arbitrary\ndef use():\n    with arbitrary.make_guard():\n        pass\n",
    )
    assert isinstance(boundary, GeneratorWithSugar)
    machine = sugar_outcome_to_exitset(boundary.manager.desugar()).exits[0].value
    step = next(
        item
        for item in machine.steps
        if isinstance(item, NestedCitedOpaqueManagerStepV1)
    )
    cleanup = next(item for item in step.body_steps if isinstance(item, FinallyStepV1))
    assert any(isinstance(item, AssertStepV1) for item in cleanup.cleanup_steps)
    assert any(isinstance(item, YieldStepV1) for item in step.body_steps)
    entered = machine.resume()
    faces = list(entered.exits)
    halted = _without_catch_warnings_construction_halt(faces)
    completed = [face for face in faces if isinstance(face, Completed)]
    assert len(halted) == 1
    assert isinstance(halted[0].effect, ContextManagerEnterRuntimeEffect)
    assert "warnings.catch_warnings" in halted[0].effect.reason
    assert len(completed) == 1
    assert isinstance(completed[0].value, YieldEffect)
    assert isinstance(completed[0].value.value, OpaqueManagerProtocolCoordinate)
    assert completed[0].value.value.symbol == "python:cm_enter_result"
    constructed = boundary.desugar()
    assert isinstance(constructed, Complete)
    assert isinstance(constructed.value, BlockValue)
    assert constructed.value.can_fall_through is False
    effects = [
        statement.effect
        for statement in constructed.value.statements
        if isinstance(statement, Incomplete)
    ]
    raised = next(effect for effect in effects if isinstance(effect, RaiseEffect))
    assert raised.exception_name == "AssertionError"
    assert raised.producer_node_owner == "ground_assertion_error"
    assert any(
        isinstance(effect, ContextManagerEnterRuntimeEffect)
        and "warnings.catch_warnings" in effect.reason
        for effect in effects
    )
    from sugar_lift_py_tests.effect import ContextManagerExitRuntimeEffect

    assert not any(
        isinstance(effect, ContextManagerExitRuntimeEffect) for effect in effects
    )


def test_installed_cited_opaque_nested_with_structured_finally_divzero(tmp_path):
    """A finally ``1 / 0`` term is a ZeroDivisionError halt, not a fall-through.

    First resume still yields the open enter result. Desugar cites the
    already-written ZeroDivisionError and the still-open enter face.
    This does not invent that the division succeeded or that exit ran.
    """
    from sugar_lift_py_tests.effect import (
        ContextManagerEnterRuntimeEffect,
        ContextManagerExitRuntimeEffect,
        RaiseEffect,
    )
    from sugar_lift_py_tests.floor.block_value import BlockValue
    from sugar_lift_py_tests.floor.opaque_manager_protocol_coordinate import (
        OpaqueManagerProtocolCoordinate,
    )
    from sugar_lift_py_tests.generator_construction import (
        FinallyStepV1,
        NestedCitedOpaqueManagerStepV1,
        TermStepV1,
        YieldEffect,
        YieldStepV1,
    )
    from sugar_lift_py_tests.outcome import Complete, Completed, Halted, Incomplete
    from sugar_lift_py_tests.sugar.exit_set_routing import sugar_outcome_to_exitset
    from sugar_lift_py_tests.sugar.generator_with_sugar import GeneratorWithSugar

    boundary = _installed_generator_with(
        tmp_path,
        (
            "import warnings\n"
            "def make_guard():\n"
            "    with warnings.catch_warnings(record=True) as w:\n"
            "        try:\n"
            "            yield w\n"
            "        finally:\n"
            "            1 / 0\n"
        ),
        "import arbitrary\ndef use():\n    with arbitrary.make_guard():\n        pass\n",
    )
    assert isinstance(boundary, GeneratorWithSugar)
    machine = sugar_outcome_to_exitset(boundary.manager.desugar()).exits[0].value
    step = next(
        item
        for item in machine.steps
        if isinstance(item, NestedCitedOpaqueManagerStepV1)
    )
    cleanup = next(item for item in step.body_steps if isinstance(item, FinallyStepV1))
    assert any(isinstance(item, TermStepV1) for item in cleanup.cleanup_steps)
    assert any(isinstance(item, YieldStepV1) for item in step.body_steps)
    entered = machine.resume()
    faces = list(entered.exits)
    halted = _without_catch_warnings_construction_halt(faces)
    completed = [face for face in faces if isinstance(face, Completed)]
    assert len(halted) == 1
    assert isinstance(halted[0].effect, ContextManagerEnterRuntimeEffect)
    assert "warnings.catch_warnings" in halted[0].effect.reason
    assert len(completed) == 1
    assert isinstance(completed[0].value, YieldEffect)
    assert isinstance(completed[0].value.value, OpaqueManagerProtocolCoordinate)
    assert completed[0].value.value.symbol == "python:cm_enter_result"
    constructed = boundary.desugar()
    assert isinstance(constructed, Complete)
    assert isinstance(constructed.value, BlockValue)
    assert constructed.value.can_fall_through is False
    effects = [
        statement.effect
        for statement in constructed.value.statements
        if isinstance(statement, Incomplete)
    ]
    raised = next(effect for effect in effects if isinstance(effect, RaiseEffect))
    assert raised.exception_name == "ZeroDivisionError"
    assert raised.producer_node_owner == "ground_exception_exit"
    assert any(
        isinstance(effect, ContextManagerEnterRuntimeEffect)
        and "warnings.catch_warnings" in effect.reason
        for effect in effects
    )
    assert not any(
        isinstance(effect, ContextManagerExitRuntimeEffect) for effect in effects
    )


def test_installed_cited_opaque_nested_with_structured_finally_assign_divzero(tmp_path):
    """A finally ``holder = 1 / 0`` is a ZeroDivisionError halt, not a bind.

    First resume still yields the open enter result. Desugar cites the
    already-written ZeroDivisionError and the still-open enter face.
    This does not invent that the name was bound or that exit ran.
    """
    from sugar_lift_py_tests.effect import (
        ContextManagerEnterRuntimeEffect,
        ContextManagerExitRuntimeEffect,
        RaiseEffect,
    )
    from sugar_lift_py_tests.floor.block_value import BlockValue
    from sugar_lift_py_tests.floor.opaque_manager_protocol_coordinate import (
        OpaqueManagerProtocolCoordinate,
    )
    from sugar_lift_py_tests.generator_construction import (
        AssignStepV1,
        FinallyStepV1,
        NestedCitedOpaqueManagerStepV1,
        YieldEffect,
        YieldStepV1,
    )
    from sugar_lift_py_tests.outcome import Complete, Completed, Halted, Incomplete
    from sugar_lift_py_tests.sugar.exit_set_routing import sugar_outcome_to_exitset
    from sugar_lift_py_tests.sugar.generator_with_sugar import GeneratorWithSugar

    boundary = _installed_generator_with(
        tmp_path,
        (
            "import warnings\n"
            "def make_guard():\n"
            "    with warnings.catch_warnings(record=True) as w:\n"
            "        try:\n"
            "            yield w\n"
            "        finally:\n"
            "            holder = 1 / 0\n"
        ),
        "import arbitrary\ndef use():\n    with arbitrary.make_guard():\n        pass\n",
    )
    assert isinstance(boundary, GeneratorWithSugar)
    machine = sugar_outcome_to_exitset(boundary.manager.desugar()).exits[0].value
    step = next(
        item
        for item in machine.steps
        if isinstance(item, NestedCitedOpaqueManagerStepV1)
    )
    cleanup = next(item for item in step.body_steps if isinstance(item, FinallyStepV1))
    assert any(
        isinstance(item, AssignStepV1) and item.name == "holder"
        for item in cleanup.cleanup_steps
    )
    assert any(isinstance(item, YieldStepV1) for item in step.body_steps)
    entered = machine.resume()
    faces = list(entered.exits)
    halted = _without_catch_warnings_construction_halt(faces)
    completed = [face for face in faces if isinstance(face, Completed)]
    assert len(halted) == 1
    assert isinstance(halted[0].effect, ContextManagerEnterRuntimeEffect)
    assert "warnings.catch_warnings" in halted[0].effect.reason
    assert len(completed) == 1
    assert isinstance(completed[0].value, YieldEffect)
    assert isinstance(completed[0].value.value, OpaqueManagerProtocolCoordinate)
    assert completed[0].value.value.symbol == "python:cm_enter_result"
    constructed = boundary.desugar()
    assert isinstance(constructed, Complete)
    assert isinstance(constructed.value, BlockValue)
    assert constructed.value.can_fall_through is False
    effects = [
        statement.effect
        for statement in constructed.value.statements
        if isinstance(statement, Incomplete)
    ]
    raised = next(effect for effect in effects if isinstance(effect, RaiseEffect))
    assert raised.exception_name == "ZeroDivisionError"
    assert raised.producer_node_owner == "ground_exception_exit"
    assert any(
        isinstance(effect, ContextManagerEnterRuntimeEffect)
        and "warnings.catch_warnings" in effect.reason
        for effect in effects
    )
    assert not any(
        isinstance(effect, ContextManagerExitRuntimeEffect) for effect in effects
    )


def test_installed_cited_opaque_nested_with_structured_finally_if_divzero(tmp_path):
    """A finally ``if 1 / 0`` guard halt keeps the enter face open.

    First resume still yields the open enter result. Desugar cites the
    already-written ZeroDivisionError and the still-open enter face.
    This does not invent that a branch ran or that exit ran.
    """
    from sugar_lift_py_tests.effect import (
        ContextManagerEnterRuntimeEffect,
        ContextManagerExitRuntimeEffect,
        RaiseEffect,
    )
    from sugar_lift_py_tests.floor.block_value import BlockValue
    from sugar_lift_py_tests.floor.opaque_manager_protocol_coordinate import (
        OpaqueManagerProtocolCoordinate,
    )
    from sugar_lift_py_tests.generator_construction import (
        FinallyStepV1,
        IfStepV1,
        NestedCitedOpaqueManagerStepV1,
        YieldEffect,
        YieldStepV1,
    )
    from sugar_lift_py_tests.outcome import Complete, Completed, Halted, Incomplete
    from sugar_lift_py_tests.sugar.exit_set_routing import sugar_outcome_to_exitset
    from sugar_lift_py_tests.sugar.generator_with_sugar import GeneratorWithSugar

    boundary = _installed_generator_with(
        tmp_path,
        (
            "import warnings\n"
            "def make_guard():\n"
            "    with warnings.catch_warnings(record=True) as w:\n"
            "        try:\n"
            "            yield w\n"
            "        finally:\n"
            "            if 1 / 0:\n"
            "                leftover = 1\n"
        ),
        "import arbitrary\ndef use():\n    with arbitrary.make_guard():\n        pass\n",
    )
    assert isinstance(boundary, GeneratorWithSugar)
    machine = sugar_outcome_to_exitset(boundary.manager.desugar()).exits[0].value
    step = next(
        item
        for item in machine.steps
        if isinstance(item, NestedCitedOpaqueManagerStepV1)
    )
    cleanup = next(item for item in step.body_steps if isinstance(item, FinallyStepV1))
    assert any(isinstance(item, IfStepV1) for item in cleanup.cleanup_steps)
    assert any(isinstance(item, YieldStepV1) for item in step.body_steps)
    entered = machine.resume()
    faces = list(entered.exits)
    halted = _without_catch_warnings_construction_halt(faces)
    completed = [face for face in faces if isinstance(face, Completed)]
    assert len(halted) == 1
    assert isinstance(halted[0].effect, ContextManagerEnterRuntimeEffect)
    assert "warnings.catch_warnings" in halted[0].effect.reason
    assert len(completed) == 1
    assert isinstance(completed[0].value, YieldEffect)
    assert isinstance(completed[0].value.value, OpaqueManagerProtocolCoordinate)
    assert completed[0].value.value.symbol == "python:cm_enter_result"
    constructed = boundary.desugar()
    assert isinstance(constructed, Complete)
    assert isinstance(constructed.value, BlockValue)
    assert constructed.value.can_fall_through is False
    effects = [
        statement.effect
        for statement in constructed.value.statements
        if isinstance(statement, Incomplete)
    ]
    raised = next(effect for effect in effects if isinstance(effect, RaiseEffect))
    assert raised.exception_name == "ZeroDivisionError"
    assert raised.producer_node_owner == "ground_exception_exit"
    assert any(
        isinstance(effect, ContextManagerEnterRuntimeEffect)
        and "warnings.catch_warnings" in effect.reason
        for effect in effects
    )
    assert not any(
        isinstance(effect, ContextManagerExitRuntimeEffect) for effect in effects
    )


def test_installed_cited_opaque_nested_with_structured_finally_for_divzero(tmp_path):
    """A finally ``for x in 1 / 0`` is a ZeroDivisionError halt, not iter_with.

    First resume still yields the open enter result. Desugar cites the
    already-written ZeroDivisionError and the still-open enter face.
    This does not invent iter_with on the raise, that a loop body ran,
    or that exit ran.
    """
    from sugar_lift_py_tests.effect import (
        ContextManagerEnterRuntimeEffect,
        ContextManagerExitRuntimeEffect,
        RaiseEffect,
    )
    from sugar_lift_py_tests.floor.block_value import BlockValue
    from sugar_lift_py_tests.floor.opaque_manager_protocol_coordinate import (
        OpaqueManagerProtocolCoordinate,
    )
    from sugar_lift_py_tests.generator_construction import (
        FinallyStepV1,
        ForStepV1,
        NestedCitedOpaqueManagerStepV1,
        YieldEffect,
        YieldStepV1,
    )
    from sugar_lift_py_tests.outcome import Complete, Completed, Halted, Incomplete
    from sugar_lift_py_tests.sugar.exit_set_routing import sugar_outcome_to_exitset
    from sugar_lift_py_tests.sugar.generator_with_sugar import GeneratorWithSugar

    boundary = _installed_generator_with(
        tmp_path,
        (
            "import warnings\n"
            "def make_guard():\n"
            "    with warnings.catch_warnings(record=True) as w:\n"
            "        try:\n"
            "            yield w\n"
            "        finally:\n"
            "            for x in 1 / 0:\n"
            "                leftover = 1\n"
        ),
        "import arbitrary\ndef use():\n    with arbitrary.make_guard():\n        pass\n",
    )
    assert isinstance(boundary, GeneratorWithSugar)
    machine = sugar_outcome_to_exitset(boundary.manager.desugar()).exits[0].value
    step = next(
        item
        for item in machine.steps
        if isinstance(item, NestedCitedOpaqueManagerStepV1)
    )
    cleanup = next(item for item in step.body_steps if isinstance(item, FinallyStepV1))
    assert any(isinstance(item, ForStepV1) for item in cleanup.cleanup_steps)
    assert any(isinstance(item, YieldStepV1) for item in step.body_steps)
    entered = machine.resume()
    faces = list(entered.exits)
    halted = _without_catch_warnings_construction_halt(faces)
    completed = [face for face in faces if isinstance(face, Completed)]
    assert len(halted) == 1
    assert isinstance(halted[0].effect, ContextManagerEnterRuntimeEffect)
    assert "warnings.catch_warnings" in halted[0].effect.reason
    assert len(completed) == 1
    assert isinstance(completed[0].value, YieldEffect)
    assert isinstance(completed[0].value.value, OpaqueManagerProtocolCoordinate)
    assert completed[0].value.value.symbol == "python:cm_enter_result"
    constructed = boundary.desugar()
    assert isinstance(constructed, Complete)
    assert isinstance(constructed.value, BlockValue)
    assert constructed.value.can_fall_through is False
    effects = [
        statement.effect
        for statement in constructed.value.statements
        if isinstance(statement, Incomplete)
    ]
    raised = next(effect for effect in effects if isinstance(effect, RaiseEffect))
    assert raised.exception_name == "ZeroDivisionError"
    assert raised.producer_node_owner == "ground_exception_exit"
    assert any(
        isinstance(effect, ContextManagerEnterRuntimeEffect)
        and "warnings.catch_warnings" in effect.reason
        for effect in effects
    )
    assert not any(
        isinstance(effect, ContextManagerExitRuntimeEffect) for effect in effects
    )


def test_installed_cited_opaque_nested_with_structured_finally_attribute_assign_divzero(tmp_path):
    """A finally ``holder.hidden = 1 / 0`` halts on the RHS, not a store.

    First resume still yields the open enter result. Desugar cites the
    already-written ZeroDivisionError and the still-open enter face.
    This does not invent that the store ran, an AttributeError from
    ``None.setattr``, or that exit ran.
    """
    from sugar_lift_py_tests.effect import (
        ContextManagerEnterRuntimeEffect,
        ContextManagerExitRuntimeEffect,
        RaiseEffect,
    )
    from sugar_lift_py_tests.floor.block_value import BlockValue
    from sugar_lift_py_tests.floor.opaque_manager_protocol_coordinate import (
        OpaqueManagerProtocolCoordinate,
    )
    from sugar_lift_py_tests.generator_construction import (
        AssignStepV1,
        AttributeAssignStepV1,
        FinallyStepV1,
        NestedCitedOpaqueManagerStepV1,
        YieldEffect,
        YieldStepV1,
    )
    from sugar_lift_py_tests.outcome import Complete, Completed, Halted, Incomplete
    from sugar_lift_py_tests.sugar.exit_set_routing import sugar_outcome_to_exitset
    from sugar_lift_py_tests.sugar.generator_with_sugar import GeneratorWithSugar

    boundary = _installed_generator_with(
        tmp_path,
        (
            "import warnings\n"
            "def make_guard():\n"
            "    with warnings.catch_warnings(record=True) as w:\n"
            "        try:\n"
            "            yield w\n"
            "        finally:\n"
            "            holder = None\n"
            "            holder.hidden = 1 / 0\n"
        ),
        "import arbitrary\ndef use():\n    with arbitrary.make_guard():\n        pass\n",
    )
    assert isinstance(boundary, GeneratorWithSugar)
    machine = sugar_outcome_to_exitset(boundary.manager.desugar()).exits[0].value
    step = next(
        item
        for item in machine.steps
        if isinstance(item, NestedCitedOpaqueManagerStepV1)
    )
    cleanup = next(item for item in step.body_steps if isinstance(item, FinallyStepV1))
    assert any(
        isinstance(item, AssignStepV1) and item.name == "holder"
        for item in cleanup.cleanup_steps
    )
    store = next(
        item
        for item in cleanup.cleanup_steps
        if isinstance(item, AttributeAssignStepV1)
    )
    assert store.attr == "hidden"
    assert any(isinstance(item, YieldStepV1) for item in step.body_steps)
    entered = machine.resume()
    faces = list(entered.exits)
    halted = _without_catch_warnings_construction_halt(faces)
    completed = [face for face in faces if isinstance(face, Completed)]
    assert len(halted) == 1
    assert isinstance(halted[0].effect, ContextManagerEnterRuntimeEffect)
    assert "warnings.catch_warnings" in halted[0].effect.reason
    assert len(completed) == 1
    assert isinstance(completed[0].value, YieldEffect)
    assert isinstance(completed[0].value.value, OpaqueManagerProtocolCoordinate)
    assert completed[0].value.value.symbol == "python:cm_enter_result"
    constructed = boundary.desugar()
    assert isinstance(constructed, Complete)
    assert isinstance(constructed.value, BlockValue)
    assert constructed.value.can_fall_through is False
    effects = [
        statement.effect
        for statement in constructed.value.statements
        if isinstance(statement, Incomplete)
    ]
    raised = next(effect for effect in effects if isinstance(effect, RaiseEffect))
    assert raised.exception_name == "ZeroDivisionError"
    assert raised.producer_node_owner == "ground_exception_exit"
    assert any(
        isinstance(effect, ContextManagerEnterRuntimeEffect)
        and "warnings.catch_warnings" in effect.reason
        for effect in effects
    )
    assert not any(
        isinstance(effect, ContextManagerExitRuntimeEffect) for effect in effects
    )


def test_installed_cited_opaque_nested_with_structured_finally_return_divzero(tmp_path):
    """A finally ``return 1 / 0`` halts on the value, not as a return.

    First resume still yields the open enter result. Desugar cites the
    already-written ZeroDivisionError and the still-open enter face.
    This does not invent that the raise was a return value, or that exit
    ran.
    """
    from sugar_lift_py_tests.effect import (
        ContextManagerEnterRuntimeEffect,
        ContextManagerExitRuntimeEffect,
        RaiseEffect,
    )
    from sugar_lift_py_tests.floor.block_value import BlockValue
    from sugar_lift_py_tests.floor.opaque_manager_protocol_coordinate import (
        OpaqueManagerProtocolCoordinate,
    )
    from sugar_lift_py_tests.generator_construction import (
        FinallyStepV1,
        NestedCitedOpaqueManagerStepV1,
        ReturnStepV1,
        YieldEffect,
        YieldStepV1,
    )
    from sugar_lift_py_tests.outcome import Complete, Completed, Halted, Incomplete
    from sugar_lift_py_tests.sugar.exit_set_routing import sugar_outcome_to_exitset
    from sugar_lift_py_tests.sugar.generator_with_sugar import GeneratorWithSugar

    boundary = _installed_generator_with(
        tmp_path,
        (
            "import warnings\n"
            "def make_guard():\n"
            "    with warnings.catch_warnings(record=True) as w:\n"
            "        try:\n"
            "            yield w\n"
            "        finally:\n"
            "            return 1 / 0\n"
        ),
        "import arbitrary\ndef use():\n    with arbitrary.make_guard():\n        pass\n",
    )
    assert isinstance(boundary, GeneratorWithSugar)
    machine = sugar_outcome_to_exitset(boundary.manager.desugar()).exits[0].value
    step = next(
        item
        for item in machine.steps
        if isinstance(item, NestedCitedOpaqueManagerStepV1)
    )
    cleanup = next(item for item in step.body_steps if isinstance(item, FinallyStepV1))
    assert any(isinstance(item, ReturnStepV1) for item in cleanup.cleanup_steps)
    assert any(isinstance(item, YieldStepV1) for item in step.body_steps)
    entered = machine.resume()
    faces = list(entered.exits)
    halted = _without_catch_warnings_construction_halt(faces)
    completed = [face for face in faces if isinstance(face, Completed)]
    assert len(halted) == 1
    assert isinstance(halted[0].effect, ContextManagerEnterRuntimeEffect)
    assert "warnings.catch_warnings" in halted[0].effect.reason
    assert len(completed) == 1
    assert isinstance(completed[0].value, YieldEffect)
    assert isinstance(completed[0].value.value, OpaqueManagerProtocolCoordinate)
    assert completed[0].value.value.symbol == "python:cm_enter_result"
    constructed = boundary.desugar()
    assert isinstance(constructed, Complete)
    assert isinstance(constructed.value, BlockValue)
    assert constructed.value.can_fall_through is False
    effects = [
        statement.effect
        for statement in constructed.value.statements
        if isinstance(statement, Incomplete)
    ]
    raised = next(effect for effect in effects if isinstance(effect, RaiseEffect))
    assert raised.exception_name == "ZeroDivisionError"
    assert raised.producer_node_owner == "ground_exception_exit"
    assert any(
        isinstance(effect, ContextManagerEnterRuntimeEffect)
        and "warnings.catch_warnings" in effect.reason
        for effect in effects
    )
    assert not any(
        isinstance(effect, ContextManagerExitRuntimeEffect) for effect in effects
    )


def test_installed_cited_opaque_nested_with_structured_finally_yield_divzero(tmp_path):
    """A finally ``yield 1 / 0`` halts on the value, not as a yield.

    First resume still yields the open enter result. Desugar cites the
    already-written ZeroDivisionError and the still-open enter face.
    This does not invent that the raise was yielded, or that exit ran.
    """
    from sugar_lift_py_tests.effect import (
        ContextManagerEnterRuntimeEffect,
        ContextManagerExitRuntimeEffect,
        RaiseEffect,
    )
    from sugar_lift_py_tests.floor.block_value import BlockValue
    from sugar_lift_py_tests.floor.opaque_manager_protocol_coordinate import (
        OpaqueManagerProtocolCoordinate,
    )
    from sugar_lift_py_tests.generator_construction import (
        FinallyStepV1,
        NestedCitedOpaqueManagerStepV1,
        YieldEffect,
        YieldStepV1,
    )
    from sugar_lift_py_tests.outcome import Complete, Completed, Halted, Incomplete
    from sugar_lift_py_tests.sugar.exit_set_routing import sugar_outcome_to_exitset
    from sugar_lift_py_tests.sugar.generator_with_sugar import GeneratorWithSugar

    boundary = _installed_generator_with(
        tmp_path,
        (
            "import warnings\n"
            "def make_guard():\n"
            "    with warnings.catch_warnings(record=True) as w:\n"
            "        try:\n"
            "            yield w\n"
            "        finally:\n"
            "            yield 1 / 0\n"
        ),
        "import arbitrary\ndef use():\n    with arbitrary.make_guard():\n        pass\n",
    )
    assert isinstance(boundary, GeneratorWithSugar)
    machine = sugar_outcome_to_exitset(boundary.manager.desugar()).exits[0].value
    step = next(
        item
        for item in machine.steps
        if isinstance(item, NestedCitedOpaqueManagerStepV1)
    )
    cleanup = next(item for item in step.body_steps if isinstance(item, FinallyStepV1))
    assert any(isinstance(item, YieldStepV1) for item in cleanup.cleanup_steps)
    assert any(isinstance(item, YieldStepV1) for item in step.body_steps)
    entered = machine.resume()
    faces = list(entered.exits)
    halted = _without_catch_warnings_construction_halt(faces)
    completed = [face for face in faces if isinstance(face, Completed)]
    assert len(halted) == 1
    assert isinstance(halted[0].effect, ContextManagerEnterRuntimeEffect)
    assert "warnings.catch_warnings" in halted[0].effect.reason
    assert len(completed) == 1
    assert isinstance(completed[0].value, YieldEffect)
    assert isinstance(completed[0].value.value, OpaqueManagerProtocolCoordinate)
    assert completed[0].value.value.symbol == "python:cm_enter_result"
    constructed = boundary.desugar()
    assert isinstance(constructed, Complete)
    assert isinstance(constructed.value, BlockValue)
    assert constructed.value.can_fall_through is False
    effects = [
        statement.effect
        for statement in constructed.value.statements
        if isinstance(statement, Incomplete)
    ]
    raised = next(effect for effect in effects if isinstance(effect, RaiseEffect))
    assert raised.exception_name == "ZeroDivisionError"
    assert raised.producer_node_owner == "ground_exception_exit"
    assert any(
        isinstance(effect, ContextManagerEnterRuntimeEffect)
        and "warnings.catch_warnings" in effect.reason
        for effect in effects
    )
    assert not any(
        isinstance(effect, ContextManagerExitRuntimeEffect) for effect in effects
    )


def test_installed_cited_opaque_nested_with_structured_finally_helper_for_divzero(tmp_path):
    """A finally helper ``for x in 1 / 0`` halts on the already-written raise.

    The source-visible helper already reduces to a Halted ZeroDivisionError
    ExitSet. TermStep now folds that already-written raise instead of
    gapping on the ExitSet. First resume still yields the open enter
    result. Desugar cites the raise and the still-open enter face. This
    does not invent that the helper returned, or that exit ran.
    """
    from sugar_lift_py_tests.effect import (
        ContextManagerEnterRuntimeEffect,
        ContextManagerExitRuntimeEffect,
        RaiseEffect,
    )
    from sugar_lift_py_tests.floor.block_value import BlockValue
    from sugar_lift_py_tests.floor.opaque_manager_protocol_coordinate import (
        OpaqueManagerProtocolCoordinate,
    )
    from sugar_lift_py_tests.generator_construction import (
        FinallyStepV1,
        NestedCitedOpaqueManagerStepV1,
        TermStepV1,
        YieldEffect,
        YieldStepV1,
    )
    from sugar_lift_py_tests.outcome import Complete, Completed, Halted, Incomplete
    from sugar_lift_py_tests.sugar.exit_set_routing import sugar_outcome_to_exitset
    from sugar_lift_py_tests.sugar.generator_with_sugar import GeneratorWithSugar

    boundary = _installed_generator_with(
        tmp_path,
        (
            "import warnings\n"
            "def consume():\n"
            "    for x in 1 / 0:\n"
            "        leftover = 1\n"
            "def make_guard():\n"
            "    with warnings.catch_warnings(record=True) as w:\n"
            "        try:\n"
            "            yield w\n"
            "        finally:\n"
            "            consume()\n"
        ),
        "import arbitrary\ndef use():\n    with arbitrary.make_guard():\n        pass\n",
    )
    assert isinstance(boundary, GeneratorWithSugar)
    machine = sugar_outcome_to_exitset(boundary.manager.desugar()).exits[0].value
    step = next(
        item
        for item in machine.steps
        if isinstance(item, NestedCitedOpaqueManagerStepV1)
    )
    cleanup = next(item for item in step.body_steps if isinstance(item, FinallyStepV1))
    assert any(isinstance(item, TermStepV1) for item in cleanup.cleanup_steps)
    assert any(isinstance(item, YieldStepV1) for item in step.body_steps)
    entered = machine.resume()
    faces = list(entered.exits)
    halted = _without_catch_warnings_construction_halt(faces)
    completed = [face for face in faces if isinstance(face, Completed)]
    assert len(halted) == 1
    assert isinstance(halted[0].effect, ContextManagerEnterRuntimeEffect)
    assert "warnings.catch_warnings" in halted[0].effect.reason
    assert len(completed) == 1
    assert isinstance(completed[0].value, YieldEffect)
    assert isinstance(completed[0].value.value, OpaqueManagerProtocolCoordinate)
    assert completed[0].value.value.symbol == "python:cm_enter_result"
    constructed = boundary.desugar()
    assert isinstance(constructed, Complete)
    assert isinstance(constructed.value, BlockValue)
    assert constructed.value.can_fall_through is False
    effects = [
        statement.effect
        for statement in constructed.value.statements
        if isinstance(statement, Incomplete)
    ]
    raised = next(effect for effect in effects if isinstance(effect, RaiseEffect))
    assert raised.exception_name == "ZeroDivisionError"
    assert any(
        isinstance(effect, ContextManagerEnterRuntimeEffect)
        and "warnings.catch_warnings" in effect.reason
        for effect in effects
    )
    assert not any(
        isinstance(effect, ContextManagerExitRuntimeEffect) for effect in effects
    )


def test_installed_cited_opaque_nested_with_structured_finally_helper_for_raising_tuple(tmp_path):
    """A finally helper ``for x in (1 / 0,)`` halts on the already-written raise.

    A tuple display is not concrete when an element is a ground
    ZeroDivisionError -- the same refusal range already makes for a bound.
    The loop stays a real fold, and the already-written raise surfaces.
    First resume still yields the open enter result. Desugar cites the
    raise and the still-open enter face. This does not invent that the
    loop unrolled, or that exit ran.
    """
    from sugar_lift_py_tests.effect import (
        ContextManagerEnterRuntimeEffect,
        ContextManagerExitRuntimeEffect,
        RaiseEffect,
    )
    from sugar_lift_py_tests.floor.block_value import BlockValue
    from sugar_lift_py_tests.floor.opaque_manager_protocol_coordinate import (
        OpaqueManagerProtocolCoordinate,
    )
    from sugar_lift_py_tests.generator_construction import (
        FinallyStepV1,
        NestedCitedOpaqueManagerStepV1,
        TermStepV1,
        YieldEffect,
        YieldStepV1,
    )
    from sugar_lift_py_tests.outcome import Complete, Completed, Halted, Incomplete
    from sugar_lift_py_tests.sugar.exit_set_routing import sugar_outcome_to_exitset
    from sugar_lift_py_tests.sugar.generator_with_sugar import GeneratorWithSugar

    boundary = _installed_generator_with(
        tmp_path,
        (
            "import warnings\n"
            "def consume():\n"
            "    for x in (1 / 0,):\n"
            "        leftover = 1\n"
            "def make_guard():\n"
            "    with warnings.catch_warnings(record=True) as w:\n"
            "        try:\n"
            "            yield w\n"
            "        finally:\n"
            "            consume()\n"
        ),
        "import arbitrary\ndef use():\n    with arbitrary.make_guard():\n        pass\n",
    )
    assert isinstance(boundary, GeneratorWithSugar)
    machine = sugar_outcome_to_exitset(boundary.manager.desugar()).exits[0].value
    step = next(
        item
        for item in machine.steps
        if isinstance(item, NestedCitedOpaqueManagerStepV1)
    )
    cleanup = next(item for item in step.body_steps if isinstance(item, FinallyStepV1))
    assert any(isinstance(item, TermStepV1) for item in cleanup.cleanup_steps)
    assert any(isinstance(item, YieldStepV1) for item in step.body_steps)
    entered = machine.resume()
    faces = list(entered.exits)
    halted = _without_catch_warnings_construction_halt(faces)
    completed = [face for face in faces if isinstance(face, Completed)]
    assert len(halted) == 1
    assert isinstance(halted[0].effect, ContextManagerEnterRuntimeEffect)
    assert "warnings.catch_warnings" in halted[0].effect.reason
    assert len(completed) == 1
    assert isinstance(completed[0].value, YieldEffect)
    assert isinstance(completed[0].value.value, OpaqueManagerProtocolCoordinate)
    assert completed[0].value.value.symbol == "python:cm_enter_result"
    constructed = boundary.desugar()
    assert isinstance(constructed, Complete)
    assert isinstance(constructed.value, BlockValue)
    assert constructed.value.can_fall_through is False
    effects = [
        statement.effect
        for statement in constructed.value.statements
        if isinstance(statement, Incomplete)
    ]
    raised = next(effect for effect in effects if isinstance(effect, RaiseEffect))
    assert raised.exception_name == "ZeroDivisionError"
    assert any(
        isinstance(effect, ContextManagerEnterRuntimeEffect)
        and "warnings.catch_warnings" in effect.reason
        for effect in effects
    )
    assert not any(
        isinstance(effect, ContextManagerExitRuntimeEffect) for effect in effects
    )


def test_installed_cited_opaque_nested_with_structured_finally_raise(tmp_path):
    """A finally ``raise ValueError("boom")`` is RaiseStepV1 cleanup.

    First resume still yields the open enter result. Desugar cites the
    authenticated ValueError raise and the still-open enter face. This
    does not invent that exit swallowed the raise.
    """
    from sugar_lift_py_tests.effect import (
        ContextManagerEnterRuntimeEffect,
        RaiseEffect,
    )
    from sugar_lift_py_tests.floor.block_value import BlockValue
    from sugar_lift_py_tests.floor.opaque_manager_protocol_coordinate import (
        OpaqueManagerProtocolCoordinate,
    )
    from sugar_lift_py_tests.floor.string_value import StringValue
    from sugar_lift_py_tests.generator_construction import (
        FinallyStepV1,
        NestedCitedOpaqueManagerStepV1,
        RaiseStepV1,
        YieldEffect,
        YieldStepV1,
    )
    from sugar_lift_py_tests.outcome import Complete, Completed, Halted, Incomplete
    from sugar_lift_py_tests.sugar.exit_set_routing import sugar_outcome_to_exitset
    from sugar_lift_py_tests.sugar.generator_with_sugar import GeneratorWithSugar

    boundary = _installed_generator_with(
        tmp_path,
        (
            "import warnings\n"
            "def make_guard():\n"
            "    with warnings.catch_warnings(record=True) as w:\n"
            "        try:\n"
            "            yield w\n"
            "        finally:\n"
            '            raise ValueError("boom")\n'
        ),
        "import arbitrary\ndef use():\n    with arbitrary.make_guard():\n        pass\n",
    )
    assert isinstance(boundary, GeneratorWithSugar)
    machine = sugar_outcome_to_exitset(boundary.manager.desugar()).exits[0].value
    step = next(
        item
        for item in machine.steps
        if isinstance(item, NestedCitedOpaqueManagerStepV1)
    )
    cleanup = next(item for item in step.body_steps if isinstance(item, FinallyStepV1))
    assert any(isinstance(item, RaiseStepV1) for item in cleanup.cleanup_steps)
    assert any(isinstance(item, YieldStepV1) for item in step.body_steps)
    entered = machine.resume()
    faces = list(entered.exits)
    halted = _without_catch_warnings_construction_halt(faces)
    completed = [face for face in faces if isinstance(face, Completed)]
    assert len(halted) == 1
    assert isinstance(halted[0].effect, ContextManagerEnterRuntimeEffect)
    assert "warnings.catch_warnings" in halted[0].effect.reason
    assert len(completed) == 1
    assert isinstance(completed[0].value, YieldEffect)
    assert isinstance(completed[0].value.value, OpaqueManagerProtocolCoordinate)
    assert completed[0].value.value.symbol == "python:cm_enter_result"
    constructed = boundary.desugar()
    assert isinstance(constructed, Complete)
    assert isinstance(constructed.value, BlockValue)
    assert constructed.value.can_fall_through is False
    effects = [
        statement.effect
        for statement in constructed.value.statements
        if isinstance(statement, Incomplete)
    ]
    raised = next(effect for effect in effects if isinstance(effect, RaiseEffect))
    assert raised.exception_name == "ValueError"
    assert raised.raised_value.arg_values == (StringValue(value="boom"),)
    assert any(
        isinstance(effect, ContextManagerEnterRuntimeEffect)
        and "warnings.catch_warnings" in effect.reason
        for effect in effects
    )


def test_installed_cited_opaque_nested_with_body_return_still_exits(tmp_path):
    """A try-body ``return`` still runs the already-written cited-opaque exit.

    First resume still yields the open enter result. Desugar cites both
    open enter and exit faces, the same completion as a fall-through
    finally. This does not invent a return value for the with or that
    exit swallowed the return.
    """
    from sugar_lift_py_tests.effect import (
        ContextManagerEnterRuntimeEffect,
        ContextManagerExitRuntimeEffect,
    )
    from sugar_lift_py_tests.floor.block_value import BlockValue
    from sugar_lift_py_tests.floor.opaque_manager_protocol_coordinate import (
        OpaqueManagerProtocolCoordinate,
    )
    from sugar_lift_py_tests.generator_construction import (
        AssignStepV1,
        FinallyStepV1,
        NestedCitedOpaqueManagerStepV1,
        ReturnStepV1,
        YieldEffect,
        YieldStepV1,
    )
    from sugar_lift_py_tests.outcome import Complete, Completed, Halted, Incomplete
    from sugar_lift_py_tests.sugar.exit_set_routing import sugar_outcome_to_exitset
    from sugar_lift_py_tests.sugar.generator_with_sugar import GeneratorWithSugar

    boundary = _installed_generator_with(
        tmp_path,
        (
            "import warnings\n"
            "def make_guard():\n"
            "    with warnings.catch_warnings(record=True) as w:\n"
            "        try:\n"
            "            yield w\n"
            "            return 1\n"
            "        finally:\n"
            "            leftover = 1\n"
        ),
        "import arbitrary\ndef use():\n    with arbitrary.make_guard():\n        pass\n",
    )
    assert isinstance(boundary, GeneratorWithSugar)
    machine = sugar_outcome_to_exitset(boundary.manager.desugar()).exits[0].value
    step = next(
        item
        for item in machine.steps
        if isinstance(item, NestedCitedOpaqueManagerStepV1)
    )
    assert any(isinstance(item, YieldStepV1) for item in step.body_steps)
    assert any(isinstance(item, ReturnStepV1) for item in step.body_steps)
    cleanup = next(item for item in step.body_steps if isinstance(item, FinallyStepV1))
    assert any(
        isinstance(item, AssignStepV1) and item.name == "leftover"
        for item in cleanup.cleanup_steps
    )
    entered = machine.resume()
    faces = list(entered.exits)
    halted = _without_catch_warnings_construction_halt(faces)
    completed = [face for face in faces if isinstance(face, Completed)]
    assert len(halted) == 1
    assert isinstance(halted[0].effect, ContextManagerEnterRuntimeEffect)
    assert "warnings.catch_warnings" in halted[0].effect.reason
    assert len(completed) == 1
    assert isinstance(completed[0].value, YieldEffect)
    assert isinstance(completed[0].value.value, OpaqueManagerProtocolCoordinate)
    assert completed[0].value.value.symbol == "python:cm_enter_result"
    constructed = boundary.desugar()
    assert isinstance(constructed, Complete)
    assert isinstance(constructed.value, BlockValue)
    assert constructed.value.can_fall_through is True
    effects = [
        statement.effect
        for statement in constructed.value.statements
        if isinstance(statement, Incomplete)
    ]
    assert any(
        isinstance(effect, ContextManagerEnterRuntimeEffect)
        and "warnings.catch_warnings" in effect.reason
        for effect in effects
    )
    assert any(
        isinstance(effect, ContextManagerExitRuntimeEffect)
        and "warnings.catch_warnings" in effect.reason
        for effect in effects
    )


def test_installed_cited_opaque_nested_with_body_raise_still_exits(tmp_path):
    """A try-body ``raise`` still runs the already-written cited-opaque exit.

    First resume still yields the open enter result. Desugar cites the
    authenticated ValueError raise and both open enter and exit faces.
    This does not invent that exit swallowed the raise.
    """
    from sugar_lift_py_tests.effect import (
        ContextManagerEnterRuntimeEffect,
        ContextManagerExitRuntimeEffect,
        RaiseEffect,
    )
    from sugar_lift_py_tests.floor.block_value import BlockValue
    from sugar_lift_py_tests.floor.opaque_manager_protocol_coordinate import (
        OpaqueManagerProtocolCoordinate,
    )
    from sugar_lift_py_tests.floor.string_value import StringValue
    from sugar_lift_py_tests.generator_construction import (
        AssignStepV1,
        FinallyStepV1,
        NestedCitedOpaqueManagerStepV1,
        RaiseStepV1,
        YieldEffect,
        YieldStepV1,
    )
    from sugar_lift_py_tests.outcome import Complete, Completed, Halted, Incomplete
    from sugar_lift_py_tests.sugar.exit_set_routing import sugar_outcome_to_exitset
    from sugar_lift_py_tests.sugar.generator_with_sugar import GeneratorWithSugar

    boundary = _installed_generator_with(
        tmp_path,
        (
            "import warnings\n"
            "def make_guard():\n"
            "    with warnings.catch_warnings(record=True) as w:\n"
            "        try:\n"
            "            yield w\n"
            "            raise ValueError(\"boom\")\n"
            "        finally:\n"
            "            leftover = 1\n"
        ),
        "import arbitrary\ndef use():\n    with arbitrary.make_guard():\n        pass\n",
    )
    assert isinstance(boundary, GeneratorWithSugar)
    machine = sugar_outcome_to_exitset(boundary.manager.desugar()).exits[0].value
    step = next(
        item
        for item in machine.steps
        if isinstance(item, NestedCitedOpaqueManagerStepV1)
    )
    assert any(isinstance(item, YieldStepV1) for item in step.body_steps)
    assert any(isinstance(item, RaiseStepV1) for item in step.body_steps)
    cleanup = next(item for item in step.body_steps if isinstance(item, FinallyStepV1))
    assert any(
        isinstance(item, AssignStepV1) and item.name == "leftover"
        for item in cleanup.cleanup_steps
    )
    entered = machine.resume()
    faces = list(entered.exits)
    halted = _without_catch_warnings_construction_halt(faces)
    completed = [face for face in faces if isinstance(face, Completed)]
    assert len(halted) == 1
    assert isinstance(halted[0].effect, ContextManagerEnterRuntimeEffect)
    assert "warnings.catch_warnings" in halted[0].effect.reason
    assert len(completed) == 1
    assert isinstance(completed[0].value, YieldEffect)
    assert isinstance(completed[0].value.value, OpaqueManagerProtocolCoordinate)
    assert completed[0].value.value.symbol == "python:cm_enter_result"
    constructed = boundary.desugar()
    assert isinstance(constructed, Complete)
    assert isinstance(constructed.value, BlockValue)
    assert constructed.value.can_fall_through is True
    effects = [
        statement.effect
        for statement in constructed.value.statements
        if isinstance(statement, Incomplete)
    ]
    raised = next(effect for effect in effects if isinstance(effect, RaiseEffect))
    assert raised.exception_name == "ValueError"
    assert raised.raised_value.arg_values == (StringValue(value="boom"),)
    assert any(
        isinstance(effect, ContextManagerEnterRuntimeEffect)
        and "warnings.catch_warnings" in effect.reason
        for effect in effects
    )
    assert any(
        isinstance(effect, ContextManagerExitRuntimeEffect)
        and "warnings.catch_warnings" in effect.reason
        for effect in effects
    )


def test_installed_cited_opaque_nested_with_body_attribute_assign_still_exits(tmp_path):
    """A try-body attribute store halt still runs the already-written exit.

    First resume still yields the open enter result. Desugar cites the
    already-written ``None.setattr`` AttributeError and both open enter
    and exit faces. This does not invent that the attribute was stored
    or that exit swallowed the raise.
    """
    from sugar_lift_py_tests.effect import (
        ContextManagerEnterRuntimeEffect,
        ContextManagerExitRuntimeEffect,
        RaiseEffect,
    )
    from sugar_lift_py_tests.floor.block_value import BlockValue
    from sugar_lift_py_tests.floor.opaque_manager_protocol_coordinate import (
        OpaqueManagerProtocolCoordinate,
    )
    from sugar_lift_py_tests.generator_construction import (
        AssignStepV1,
        AttributeAssignStepV1,
        FinallyStepV1,
        NestedCitedOpaqueManagerStepV1,
        YieldEffect,
        YieldStepV1,
    )
    from sugar_lift_py_tests.outcome import Complete, Completed, Halted, Incomplete
    from sugar_lift_py_tests.sugar.exit_set_routing import sugar_outcome_to_exitset
    from sugar_lift_py_tests.sugar.generator_with_sugar import GeneratorWithSugar

    boundary = _installed_generator_with(
        tmp_path,
        (
            "import warnings\n"
            "def make_guard():\n"
            "    with warnings.catch_warnings(record=True) as w:\n"
            "        try:\n"
            "            yield w\n"
            "            holder = None\n"
            "            holder.hidden = True\n"
            "        finally:\n"
            "            leftover = 1\n"
        ),
        "import arbitrary\ndef use():\n    with arbitrary.make_guard():\n        pass\n",
    )
    assert isinstance(boundary, GeneratorWithSugar)
    machine = sugar_outcome_to_exitset(boundary.manager.desugar()).exits[0].value
    step = next(
        item
        for item in machine.steps
        if isinstance(item, NestedCitedOpaqueManagerStepV1)
    )
    assert any(isinstance(item, YieldStepV1) for item in step.body_steps)
    assert any(isinstance(item, AssignStepV1) and item.name == "holder" for item in step.body_steps)
    store = next(
        item for item in step.body_steps if isinstance(item, AttributeAssignStepV1)
    )
    assert store.attr == "hidden"
    cleanup = next(item for item in step.body_steps if isinstance(item, FinallyStepV1))
    assert any(
        isinstance(item, AssignStepV1) and item.name == "leftover"
        for item in cleanup.cleanup_steps
    )
    entered = machine.resume()
    faces = list(entered.exits)
    halted = _without_catch_warnings_construction_halt(faces)
    completed = [face for face in faces if isinstance(face, Completed)]
    assert len(halted) == 1
    assert isinstance(halted[0].effect, ContextManagerEnterRuntimeEffect)
    assert "warnings.catch_warnings" in halted[0].effect.reason
    assert len(completed) == 1
    assert isinstance(completed[0].value, YieldEffect)
    assert isinstance(completed[0].value.value, OpaqueManagerProtocolCoordinate)
    assert completed[0].value.value.symbol == "python:cm_enter_result"
    constructed = boundary.desugar()
    assert isinstance(constructed, Complete)
    assert isinstance(constructed.value, BlockValue)
    assert constructed.value.can_fall_through is True
    effects = [
        statement.effect
        for statement in constructed.value.statements
        if isinstance(statement, Incomplete)
    ]
    raised = next(effect for effect in effects if isinstance(effect, RaiseEffect))
    assert raised.exception_name == "AttributeError"
    assert raised.producer_node_owner == "NoneValue.setattr"
    assert any(
        isinstance(effect, ContextManagerEnterRuntimeEffect)
        and "warnings.catch_warnings" in effect.reason
        for effect in effects
    )
    assert any(
        isinstance(effect, ContextManagerExitRuntimeEffect)
        and "warnings.catch_warnings" in effect.reason
        for effect in effects
    )


def test_installed_cited_opaque_nested_with_body_assert_false_still_exits(tmp_path):
    """A try-body ``assert False`` halts and still runs the already-written exit.

    First resume still yields the open enter result. Desugar cites the
    already-written ground AssertionError and both open enter and exit
    faces. This does not invent that the assertion succeeded or that
    exit swallowed the raise.
    """
    from sugar_lift_py_tests.effect import (
        ContextManagerEnterRuntimeEffect,
        ContextManagerExitRuntimeEffect,
        RaiseEffect,
    )
    from sugar_lift_py_tests.floor.block_value import BlockValue
    from sugar_lift_py_tests.floor.opaque_manager_protocol_coordinate import (
        OpaqueManagerProtocolCoordinate,
    )
    from sugar_lift_py_tests.generator_construction import (
        AssignStepV1,
        AssertStepV1,
        FinallyStepV1,
        NestedCitedOpaqueManagerStepV1,
        YieldEffect,
        YieldStepV1,
    )
    from sugar_lift_py_tests.outcome import Complete, Completed, Halted, Incomplete
    from sugar_lift_py_tests.sugar.exit_set_routing import sugar_outcome_to_exitset
    from sugar_lift_py_tests.sugar.generator_with_sugar import GeneratorWithSugar

    boundary = _installed_generator_with(
        tmp_path,
        (
            "import warnings\n"
            "def make_guard():\n"
            "    with warnings.catch_warnings(record=True) as w:\n"
            "        try:\n"
            "            yield w\n"
            "            assert False\n"
            "        finally:\n"
            "            leftover = 1\n"
        ),
        "import arbitrary\ndef use():\n    with arbitrary.make_guard():\n        pass\n",
    )
    assert isinstance(boundary, GeneratorWithSugar)
    machine = sugar_outcome_to_exitset(boundary.manager.desugar()).exits[0].value
    step = next(
        item
        for item in machine.steps
        if isinstance(item, NestedCitedOpaqueManagerStepV1)
    )
    assert any(isinstance(item, YieldStepV1) for item in step.body_steps)
    assert any(isinstance(item, AssertStepV1) for item in step.body_steps)
    cleanup = next(item for item in step.body_steps if isinstance(item, FinallyStepV1))
    assert any(
        isinstance(item, AssignStepV1) and item.name == "leftover"
        for item in cleanup.cleanup_steps
    )
    entered = machine.resume()
    faces = list(entered.exits)
    halted = _without_catch_warnings_construction_halt(faces)
    completed = [face for face in faces if isinstance(face, Completed)]
    assert len(halted) == 1
    assert isinstance(halted[0].effect, ContextManagerEnterRuntimeEffect)
    assert "warnings.catch_warnings" in halted[0].effect.reason
    assert len(completed) == 1
    assert isinstance(completed[0].value, YieldEffect)
    assert isinstance(completed[0].value.value, OpaqueManagerProtocolCoordinate)
    assert completed[0].value.value.symbol == "python:cm_enter_result"
    constructed = boundary.desugar()
    assert isinstance(constructed, Complete)
    assert isinstance(constructed.value, BlockValue)
    assert constructed.value.can_fall_through is True
    effects = [
        statement.effect
        for statement in constructed.value.statements
        if isinstance(statement, Incomplete)
    ]
    raised = next(effect for effect in effects if isinstance(effect, RaiseEffect))
    assert raised.exception_name == "AssertionError"
    assert raised.producer_node_owner == "ground_assertion_error"
    assert any(
        isinstance(effect, ContextManagerEnterRuntimeEffect)
        and "warnings.catch_warnings" in effect.reason
        for effect in effects
    )
    assert any(
        isinstance(effect, ContextManagerExitRuntimeEffect)
        and "warnings.catch_warnings" in effect.reason
        for effect in effects
    )


def test_installed_cited_opaque_nested_with_body_divzero_still_exits(tmp_path):
    """A try-body ``1 / 0`` term halts and still runs the already-written exit.

    First resume still yields the open enter result. Desugar cites the
    already-written ZeroDivisionError and both open enter and exit faces.
    This does not invent that the division succeeded or that exit
    swallowed the raise.
    """
    from sugar_lift_py_tests.effect import (
        ContextManagerEnterRuntimeEffect,
        ContextManagerExitRuntimeEffect,
        RaiseEffect,
    )
    from sugar_lift_py_tests.floor.block_value import BlockValue
    from sugar_lift_py_tests.floor.opaque_manager_protocol_coordinate import (
        OpaqueManagerProtocolCoordinate,
    )
    from sugar_lift_py_tests.generator_construction import (
        AssignStepV1,
        FinallyStepV1,
        NestedCitedOpaqueManagerStepV1,
        TermStepV1,
        YieldEffect,
        YieldStepV1,
    )
    from sugar_lift_py_tests.outcome import Complete, Completed, Halted, Incomplete
    from sugar_lift_py_tests.sugar.exit_set_routing import sugar_outcome_to_exitset
    from sugar_lift_py_tests.sugar.generator_with_sugar import GeneratorWithSugar

    boundary = _installed_generator_with(
        tmp_path,
        (
            "import warnings\n"
            "def make_guard():\n"
            "    with warnings.catch_warnings(record=True) as w:\n"
            "        try:\n"
            "            yield w\n"
            "            1 / 0\n"
            "        finally:\n"
            "            leftover = 1\n"
        ),
        "import arbitrary\ndef use():\n    with arbitrary.make_guard():\n        pass\n",
    )
    assert isinstance(boundary, GeneratorWithSugar)
    machine = sugar_outcome_to_exitset(boundary.manager.desugar()).exits[0].value
    step = next(
        item
        for item in machine.steps
        if isinstance(item, NestedCitedOpaqueManagerStepV1)
    )
    assert any(isinstance(item, YieldStepV1) for item in step.body_steps)
    assert any(isinstance(item, TermStepV1) for item in step.body_steps)
    cleanup = next(item for item in step.body_steps if isinstance(item, FinallyStepV1))
    assert any(
        isinstance(item, AssignStepV1) and item.name == "leftover"
        for item in cleanup.cleanup_steps
    )
    entered = machine.resume()
    faces = list(entered.exits)
    halted = _without_catch_warnings_construction_halt(faces)
    completed = [face for face in faces if isinstance(face, Completed)]
    assert len(halted) == 1
    assert isinstance(halted[0].effect, ContextManagerEnterRuntimeEffect)
    assert "warnings.catch_warnings" in halted[0].effect.reason
    assert len(completed) == 1
    assert isinstance(completed[0].value, YieldEffect)
    assert isinstance(completed[0].value.value, OpaqueManagerProtocolCoordinate)
    assert completed[0].value.value.symbol == "python:cm_enter_result"
    constructed = boundary.desugar()
    assert isinstance(constructed, Complete)
    assert isinstance(constructed.value, BlockValue)
    assert constructed.value.can_fall_through is True
    effects = [
        statement.effect
        for statement in constructed.value.statements
        if isinstance(statement, Incomplete)
    ]
    raised = next(effect for effect in effects if isinstance(effect, RaiseEffect))
    assert raised.exception_name == "ZeroDivisionError"
    assert raised.producer_node_owner == "ground_exception_exit"
    assert any(
        isinstance(effect, ContextManagerEnterRuntimeEffect)
        and "warnings.catch_warnings" in effect.reason
        for effect in effects
    )
    assert any(
        isinstance(effect, ContextManagerExitRuntimeEffect)
        and "warnings.catch_warnings" in effect.reason
        for effect in effects
    )


def test_installed_cited_opaque_nested_with_body_assign_divzero_still_exits(tmp_path):
    """A try-body ``holder = 1 / 0`` halts and still runs the already-written exit.

    First resume still yields the open enter result. Desugar cites the
    already-written ZeroDivisionError and both open enter and exit faces.
    This does not invent that the name was bound or that exit swallowed
    the raise.
    """
    from sugar_lift_py_tests.effect import (
        ContextManagerEnterRuntimeEffect,
        ContextManagerExitRuntimeEffect,
        RaiseEffect,
    )
    from sugar_lift_py_tests.floor.block_value import BlockValue
    from sugar_lift_py_tests.floor.opaque_manager_protocol_coordinate import (
        OpaqueManagerProtocolCoordinate,
    )
    from sugar_lift_py_tests.generator_construction import (
        AssignStepV1,
        FinallyStepV1,
        NestedCitedOpaqueManagerStepV1,
        YieldEffect,
        YieldStepV1,
    )
    from sugar_lift_py_tests.outcome import Complete, Completed, Halted, Incomplete
    from sugar_lift_py_tests.sugar.exit_set_routing import sugar_outcome_to_exitset
    from sugar_lift_py_tests.sugar.generator_with_sugar import GeneratorWithSugar

    boundary = _installed_generator_with(
        tmp_path,
        (
            "import warnings\n"
            "def make_guard():\n"
            "    with warnings.catch_warnings(record=True) as w:\n"
            "        try:\n"
            "            yield w\n"
            "            holder = 1 / 0\n"
            "        finally:\n"
            "            leftover = 1\n"
        ),
        "import arbitrary\ndef use():\n    with arbitrary.make_guard():\n        pass\n",
    )
    assert isinstance(boundary, GeneratorWithSugar)
    machine = sugar_outcome_to_exitset(boundary.manager.desugar()).exits[0].value
    step = next(
        item
        for item in machine.steps
        if isinstance(item, NestedCitedOpaqueManagerStepV1)
    )
    assert any(isinstance(item, YieldStepV1) for item in step.body_steps)
    assert any(
        isinstance(item, AssignStepV1) and item.name == "holder"
        for item in step.body_steps
    )
    cleanup = next(item for item in step.body_steps if isinstance(item, FinallyStepV1))
    assert any(
        isinstance(item, AssignStepV1) and item.name == "leftover"
        for item in cleanup.cleanup_steps
    )
    entered = machine.resume()
    faces = list(entered.exits)
    halted = _without_catch_warnings_construction_halt(faces)
    completed = [face for face in faces if isinstance(face, Completed)]
    assert len(halted) == 1
    assert isinstance(halted[0].effect, ContextManagerEnterRuntimeEffect)
    assert "warnings.catch_warnings" in halted[0].effect.reason
    assert len(completed) == 1
    assert isinstance(completed[0].value, YieldEffect)
    assert isinstance(completed[0].value.value, OpaqueManagerProtocolCoordinate)
    assert completed[0].value.value.symbol == "python:cm_enter_result"
    constructed = boundary.desugar()
    assert isinstance(constructed, Complete)
    assert isinstance(constructed.value, BlockValue)
    assert constructed.value.can_fall_through is True
    effects = [
        statement.effect
        for statement in constructed.value.statements
        if isinstance(statement, Incomplete)
    ]
    raised = next(effect for effect in effects if isinstance(effect, RaiseEffect))
    assert raised.exception_name == "ZeroDivisionError"
    assert raised.producer_node_owner == "ground_exception_exit"
    assert any(
        isinstance(effect, ContextManagerEnterRuntimeEffect)
        and "warnings.catch_warnings" in effect.reason
        for effect in effects
    )
    assert any(
        isinstance(effect, ContextManagerExitRuntimeEffect)
        and "warnings.catch_warnings" in effect.reason
        for effect in effects
    )


def test_installed_cited_opaque_nested_with_body_if_divzero_still_exits(tmp_path):
    """A try-body ``if 1 / 0`` guard halt still runs the already-written exit.

    First resume still yields the open enter result. Desugar cites the
    already-written ZeroDivisionError and both open enter and exit faces.
    This does not invent that a branch ran or that exit swallowed the raise.
    """
    from sugar_lift_py_tests.effect import (
        ContextManagerEnterRuntimeEffect,
        ContextManagerExitRuntimeEffect,
        RaiseEffect,
    )
    from sugar_lift_py_tests.floor.block_value import BlockValue
    from sugar_lift_py_tests.floor.opaque_manager_protocol_coordinate import (
        OpaqueManagerProtocolCoordinate,
    )
    from sugar_lift_py_tests.generator_construction import (
        AssignStepV1,
        FinallyStepV1,
        IfStepV1,
        NestedCitedOpaqueManagerStepV1,
        YieldEffect,
        YieldStepV1,
    )
    from sugar_lift_py_tests.outcome import Complete, Completed, Halted, Incomplete
    from sugar_lift_py_tests.sugar.exit_set_routing import sugar_outcome_to_exitset
    from sugar_lift_py_tests.sugar.generator_with_sugar import GeneratorWithSugar

    boundary = _installed_generator_with(
        tmp_path,
        (
            "import warnings\n"
            "def make_guard():\n"
            "    with warnings.catch_warnings(record=True) as w:\n"
            "        try:\n"
            "            yield w\n"
            "            if 1 / 0:\n"
            "                leftover = 1\n"
            "        finally:\n"
            "            leftover = 1\n"
        ),
        "import arbitrary\ndef use():\n    with arbitrary.make_guard():\n        pass\n",
    )
    assert isinstance(boundary, GeneratorWithSugar)
    machine = sugar_outcome_to_exitset(boundary.manager.desugar()).exits[0].value
    step = next(
        item
        for item in machine.steps
        if isinstance(item, NestedCitedOpaqueManagerStepV1)
    )
    assert any(isinstance(item, YieldStepV1) for item in step.body_steps)
    assert any(isinstance(item, IfStepV1) for item in step.body_steps)
    cleanup = next(item for item in step.body_steps if isinstance(item, FinallyStepV1))
    assert any(
        isinstance(item, AssignStepV1) and item.name == "leftover"
        for item in cleanup.cleanup_steps
    )
    entered = machine.resume()
    faces = list(entered.exits)
    halted = _without_catch_warnings_construction_halt(faces)
    completed = [face for face in faces if isinstance(face, Completed)]
    assert len(halted) == 1
    assert isinstance(halted[0].effect, ContextManagerEnterRuntimeEffect)
    assert "warnings.catch_warnings" in halted[0].effect.reason
    assert len(completed) == 1
    assert isinstance(completed[0].value, YieldEffect)
    assert isinstance(completed[0].value.value, OpaqueManagerProtocolCoordinate)
    assert completed[0].value.value.symbol == "python:cm_enter_result"
    constructed = boundary.desugar()
    assert isinstance(constructed, Complete)
    assert isinstance(constructed.value, BlockValue)
    assert constructed.value.can_fall_through is True
    effects = [
        statement.effect
        for statement in constructed.value.statements
        if isinstance(statement, Incomplete)
    ]
    raised = next(effect for effect in effects if isinstance(effect, RaiseEffect))
    assert raised.exception_name == "ZeroDivisionError"
    assert raised.producer_node_owner == "ground_exception_exit"
    assert any(
        isinstance(effect, ContextManagerEnterRuntimeEffect)
        and "warnings.catch_warnings" in effect.reason
        for effect in effects
    )
    assert any(
        isinstance(effect, ContextManagerExitRuntimeEffect)
        and "warnings.catch_warnings" in effect.reason
        for effect in effects
    )


def test_installed_cited_opaque_nested_with_body_for_divzero_still_exits(tmp_path):
    """A try-body ``for x in 1 / 0`` halts and still runs the already-written exit.

    First resume still yields the open enter result. Desugar cites the
    already-written ZeroDivisionError and both open enter and exit faces.
    This does not invent iter_with on the raise, that a loop body ran,
    or that exit swallowed the raise.
    """
    from sugar_lift_py_tests.effect import (
        ContextManagerEnterRuntimeEffect,
        ContextManagerExitRuntimeEffect,
        RaiseEffect,
    )
    from sugar_lift_py_tests.floor.block_value import BlockValue
    from sugar_lift_py_tests.floor.opaque_manager_protocol_coordinate import (
        OpaqueManagerProtocolCoordinate,
    )
    from sugar_lift_py_tests.generator_construction import (
        AssignStepV1,
        FinallyStepV1,
        ForStepV1,
        NestedCitedOpaqueManagerStepV1,
        YieldEffect,
        YieldStepV1,
    )
    from sugar_lift_py_tests.outcome import Complete, Completed, Halted, Incomplete
    from sugar_lift_py_tests.sugar.exit_set_routing import sugar_outcome_to_exitset
    from sugar_lift_py_tests.sugar.generator_with_sugar import GeneratorWithSugar

    boundary = _installed_generator_with(
        tmp_path,
        (
            "import warnings\n"
            "def make_guard():\n"
            "    with warnings.catch_warnings(record=True) as w:\n"
            "        try:\n"
            "            yield w\n"
            "            for x in 1 / 0:\n"
            "                leftover = 1\n"
            "        finally:\n"
            "            leftover = 1\n"
        ),
        "import arbitrary\ndef use():\n    with arbitrary.make_guard():\n        pass\n",
    )
    assert isinstance(boundary, GeneratorWithSugar)
    machine = sugar_outcome_to_exitset(boundary.manager.desugar()).exits[0].value
    step = next(
        item
        for item in machine.steps
        if isinstance(item, NestedCitedOpaqueManagerStepV1)
    )
    assert any(isinstance(item, YieldStepV1) for item in step.body_steps)
    assert any(isinstance(item, ForStepV1) for item in step.body_steps)
    cleanup = next(item for item in step.body_steps if isinstance(item, FinallyStepV1))
    assert any(
        isinstance(item, AssignStepV1) and item.name == "leftover"
        for item in cleanup.cleanup_steps
    )
    entered = machine.resume()
    faces = list(entered.exits)
    halted = _without_catch_warnings_construction_halt(faces)
    completed = [face for face in faces if isinstance(face, Completed)]
    assert len(halted) == 1
    assert isinstance(halted[0].effect, ContextManagerEnterRuntimeEffect)
    assert "warnings.catch_warnings" in halted[0].effect.reason
    assert len(completed) == 1
    assert isinstance(completed[0].value, YieldEffect)
    assert isinstance(completed[0].value.value, OpaqueManagerProtocolCoordinate)
    assert completed[0].value.value.symbol == "python:cm_enter_result"
    constructed = boundary.desugar()
    assert isinstance(constructed, Complete)
    assert isinstance(constructed.value, BlockValue)
    assert constructed.value.can_fall_through is True
    effects = [
        statement.effect
        for statement in constructed.value.statements
        if isinstance(statement, Incomplete)
    ]
    raised = next(effect for effect in effects if isinstance(effect, RaiseEffect))
    assert raised.exception_name == "ZeroDivisionError"
    assert raised.producer_node_owner == "ground_exception_exit"
    assert any(
        isinstance(effect, ContextManagerEnterRuntimeEffect)
        and "warnings.catch_warnings" in effect.reason
        for effect in effects
    )
    assert any(
        isinstance(effect, ContextManagerExitRuntimeEffect)
        and "warnings.catch_warnings" in effect.reason
        for effect in effects
    )


def test_installed_cited_opaque_nested_with_body_attribute_assign_divzero_still_exits(tmp_path):
    """A try-body ``holder.hidden = 1 / 0`` halts on the RHS, then still exits.

    First resume still yields the open enter result. Desugar cites the
    already-written ZeroDivisionError and both open enter and exit faces.
    This does not invent that the store ran, an AttributeError from
    ``None.setattr``, or that exit swallowed the raise.
    """
    from sugar_lift_py_tests.effect import (
        ContextManagerEnterRuntimeEffect,
        ContextManagerExitRuntimeEffect,
        RaiseEffect,
    )
    from sugar_lift_py_tests.floor.block_value import BlockValue
    from sugar_lift_py_tests.floor.opaque_manager_protocol_coordinate import (
        OpaqueManagerProtocolCoordinate,
    )
    from sugar_lift_py_tests.generator_construction import (
        AssignStepV1,
        AttributeAssignStepV1,
        FinallyStepV1,
        NestedCitedOpaqueManagerStepV1,
        YieldEffect,
        YieldStepV1,
    )
    from sugar_lift_py_tests.outcome import Complete, Completed, Halted, Incomplete
    from sugar_lift_py_tests.sugar.exit_set_routing import sugar_outcome_to_exitset
    from sugar_lift_py_tests.sugar.generator_with_sugar import GeneratorWithSugar

    boundary = _installed_generator_with(
        tmp_path,
        (
            "import warnings\n"
            "def make_guard():\n"
            "    with warnings.catch_warnings(record=True) as w:\n"
            "        try:\n"
            "            yield w\n"
            "            holder = None\n"
            "            holder.hidden = 1 / 0\n"
            "        finally:\n"
            "            leftover = 1\n"
        ),
        "import arbitrary\ndef use():\n    with arbitrary.make_guard():\n        pass\n",
    )
    assert isinstance(boundary, GeneratorWithSugar)
    machine = sugar_outcome_to_exitset(boundary.manager.desugar()).exits[0].value
    step = next(
        item
        for item in machine.steps
        if isinstance(item, NestedCitedOpaqueManagerStepV1)
    )
    assert any(isinstance(item, YieldStepV1) for item in step.body_steps)
    assert any(
        isinstance(item, AssignStepV1) and item.name == "holder"
        for item in step.body_steps
    )
    store = next(
        item for item in step.body_steps if isinstance(item, AttributeAssignStepV1)
    )
    assert store.attr == "hidden"
    cleanup = next(item for item in step.body_steps if isinstance(item, FinallyStepV1))
    assert any(
        isinstance(item, AssignStepV1) and item.name == "leftover"
        for item in cleanup.cleanup_steps
    )
    entered = machine.resume()
    faces = list(entered.exits)
    halted = _without_catch_warnings_construction_halt(faces)
    completed = [face for face in faces if isinstance(face, Completed)]
    assert len(halted) == 1
    assert isinstance(halted[0].effect, ContextManagerEnterRuntimeEffect)
    assert "warnings.catch_warnings" in halted[0].effect.reason
    assert len(completed) == 1
    assert isinstance(completed[0].value, YieldEffect)
    assert isinstance(completed[0].value.value, OpaqueManagerProtocolCoordinate)
    assert completed[0].value.value.symbol == "python:cm_enter_result"
    constructed = boundary.desugar()
    assert isinstance(constructed, Complete)
    assert isinstance(constructed.value, BlockValue)
    assert constructed.value.can_fall_through is True
    effects = [
        statement.effect
        for statement in constructed.value.statements
        if isinstance(statement, Incomplete)
    ]
    raised = next(effect for effect in effects if isinstance(effect, RaiseEffect))
    assert raised.exception_name == "ZeroDivisionError"
    assert raised.producer_node_owner == "ground_exception_exit"
    assert any(
        isinstance(effect, ContextManagerEnterRuntimeEffect)
        and "warnings.catch_warnings" in effect.reason
        for effect in effects
    )
    assert any(
        isinstance(effect, ContextManagerExitRuntimeEffect)
        and "warnings.catch_warnings" in effect.reason
        for effect in effects
    )


def test_installed_cited_opaque_nested_with_body_return_divzero_still_exits(tmp_path):
    """A try-body ``return 1 / 0`` halts on the value, then still exits.

    First resume still yields the open enter result. Desugar cites the
    already-written ZeroDivisionError and both open enter and exit faces.
    This does not invent that the raise was a return value, or that exit
    swallowed the raise.
    """
    from sugar_lift_py_tests.effect import (
        ContextManagerEnterRuntimeEffect,
        ContextManagerExitRuntimeEffect,
        RaiseEffect,
    )
    from sugar_lift_py_tests.floor.block_value import BlockValue
    from sugar_lift_py_tests.floor.opaque_manager_protocol_coordinate import (
        OpaqueManagerProtocolCoordinate,
    )
    from sugar_lift_py_tests.generator_construction import (
        AssignStepV1,
        FinallyStepV1,
        NestedCitedOpaqueManagerStepV1,
        ReturnStepV1,
        YieldEffect,
        YieldStepV1,
    )
    from sugar_lift_py_tests.outcome import Complete, Completed, Halted, Incomplete
    from sugar_lift_py_tests.sugar.exit_set_routing import sugar_outcome_to_exitset
    from sugar_lift_py_tests.sugar.generator_with_sugar import GeneratorWithSugar

    boundary = _installed_generator_with(
        tmp_path,
        (
            "import warnings\n"
            "def make_guard():\n"
            "    with warnings.catch_warnings(record=True) as w:\n"
            "        try:\n"
            "            yield w\n"
            "            return 1 / 0\n"
            "        finally:\n"
            "            leftover = 1\n"
        ),
        "import arbitrary\ndef use():\n    with arbitrary.make_guard():\n        pass\n",
    )
    assert isinstance(boundary, GeneratorWithSugar)
    machine = sugar_outcome_to_exitset(boundary.manager.desugar()).exits[0].value
    step = next(
        item
        for item in machine.steps
        if isinstance(item, NestedCitedOpaqueManagerStepV1)
    )
    assert any(isinstance(item, YieldStepV1) for item in step.body_steps)
    assert any(isinstance(item, ReturnStepV1) for item in step.body_steps)
    cleanup = next(item for item in step.body_steps if isinstance(item, FinallyStepV1))
    assert any(
        isinstance(item, AssignStepV1) and item.name == "leftover"
        for item in cleanup.cleanup_steps
    )
    entered = machine.resume()
    faces = list(entered.exits)
    halted = _without_catch_warnings_construction_halt(faces)
    completed = [face for face in faces if isinstance(face, Completed)]
    assert len(halted) == 1
    assert isinstance(halted[0].effect, ContextManagerEnterRuntimeEffect)
    assert "warnings.catch_warnings" in halted[0].effect.reason
    assert len(completed) == 1
    assert isinstance(completed[0].value, YieldEffect)
    assert isinstance(completed[0].value.value, OpaqueManagerProtocolCoordinate)
    assert completed[0].value.value.symbol == "python:cm_enter_result"
    constructed = boundary.desugar()
    assert isinstance(constructed, Complete)
    assert isinstance(constructed.value, BlockValue)
    assert constructed.value.can_fall_through is True
    effects = [
        statement.effect
        for statement in constructed.value.statements
        if isinstance(statement, Incomplete)
    ]
    raised = next(effect for effect in effects if isinstance(effect, RaiseEffect))
    assert raised.exception_name == "ZeroDivisionError"
    assert raised.producer_node_owner == "ground_exception_exit"
    assert any(
        isinstance(effect, ContextManagerEnterRuntimeEffect)
        and "warnings.catch_warnings" in effect.reason
        for effect in effects
    )
    assert any(
        isinstance(effect, ContextManagerExitRuntimeEffect)
        and "warnings.catch_warnings" in effect.reason
        for effect in effects
    )


def test_installed_cited_opaque_nested_with_body_yield_divzero_still_exits(tmp_path):
    """A try-body ``yield 1 / 0`` after ``yield w`` halts, then still exits.

    First resume still yields the open enter result. Desugar cites the
    already-written ZeroDivisionError and both open enter and exit faces.
    This does not invent that the raise was yielded, or that exit swallowed
    the raise.
    """
    from sugar_lift_py_tests.effect import (
        ContextManagerEnterRuntimeEffect,
        ContextManagerExitRuntimeEffect,
        RaiseEffect,
    )
    from sugar_lift_py_tests.floor.block_value import BlockValue
    from sugar_lift_py_tests.floor.opaque_manager_protocol_coordinate import (
        OpaqueManagerProtocolCoordinate,
    )
    from sugar_lift_py_tests.generator_construction import (
        AssignStepV1,
        FinallyStepV1,
        NestedCitedOpaqueManagerStepV1,
        YieldEffect,
        YieldStepV1,
    )
    from sugar_lift_py_tests.outcome import Complete, Completed, Halted, Incomplete
    from sugar_lift_py_tests.sugar.exit_set_routing import sugar_outcome_to_exitset
    from sugar_lift_py_tests.sugar.generator_with_sugar import GeneratorWithSugar

    boundary = _installed_generator_with(
        tmp_path,
        (
            "import warnings\n"
            "def make_guard():\n"
            "    with warnings.catch_warnings(record=True) as w:\n"
            "        try:\n"
            "            yield w\n"
            "            yield 1 / 0\n"
            "        finally:\n"
            "            leftover = 1\n"
        ),
        "import arbitrary\ndef use():\n    with arbitrary.make_guard():\n        pass\n",
    )
    assert isinstance(boundary, GeneratorWithSugar)
    machine = sugar_outcome_to_exitset(boundary.manager.desugar()).exits[0].value
    step = next(
        item
        for item in machine.steps
        if isinstance(item, NestedCitedOpaqueManagerStepV1)
    )
    yields = [item for item in step.body_steps if isinstance(item, YieldStepV1)]
    assert len(yields) == 2
    cleanup = next(item for item in step.body_steps if isinstance(item, FinallyStepV1))
    assert any(
        isinstance(item, AssignStepV1) and item.name == "leftover"
        for item in cleanup.cleanup_steps
    )
    entered = machine.resume()
    faces = list(entered.exits)
    halted = _without_catch_warnings_construction_halt(faces)
    completed = [face for face in faces if isinstance(face, Completed)]
    assert len(halted) == 1
    assert isinstance(halted[0].effect, ContextManagerEnterRuntimeEffect)
    assert "warnings.catch_warnings" in halted[0].effect.reason
    assert len(completed) == 1
    assert isinstance(completed[0].value, YieldEffect)
    assert isinstance(completed[0].value.value, OpaqueManagerProtocolCoordinate)
    assert completed[0].value.value.symbol == "python:cm_enter_result"
    constructed = boundary.desugar()
    assert isinstance(constructed, Complete)
    assert isinstance(constructed.value, BlockValue)
    assert constructed.value.can_fall_through is True
    effects = [
        statement.effect
        for statement in constructed.value.statements
        if isinstance(statement, Incomplete)
    ]
    raised = next(effect for effect in effects if isinstance(effect, RaiseEffect))
    assert raised.exception_name == "ZeroDivisionError"
    assert raised.producer_node_owner == "ground_exception_exit"
    assert any(
        isinstance(effect, ContextManagerEnterRuntimeEffect)
        and "warnings.catch_warnings" in effect.reason
        for effect in effects
    )
    assert any(
        isinstance(effect, ContextManagerExitRuntimeEffect)
        and "warnings.catch_warnings" in effect.reason
        for effect in effects
    )


def test_installed_cited_opaque_nested_with_body_helper_for_divzero_still_exits(tmp_path):
    """A body helper ``for x in 1 / 0`` halts, then the with still exits.

    The source-visible helper already reduces to a Halted ZeroDivisionError
    ExitSet. TermStep now folds that already-written raise instead of
    gapping on the ExitSet. First resume still yields the open enter
    result. Desugar cites the raise and both open enter and exit faces.
    This does not invent that the helper returned, or that exit swallowed
    the raise.
    """
    from sugar_lift_py_tests.effect import (
        ContextManagerEnterRuntimeEffect,
        ContextManagerExitRuntimeEffect,
        RaiseEffect,
    )
    from sugar_lift_py_tests.floor.block_value import BlockValue
    from sugar_lift_py_tests.floor.opaque_manager_protocol_coordinate import (
        OpaqueManagerProtocolCoordinate,
    )
    from sugar_lift_py_tests.generator_construction import (
        AssignStepV1,
        FinallyStepV1,
        NestedCitedOpaqueManagerStepV1,
        TermStepV1,
        YieldEffect,
        YieldStepV1,
    )
    from sugar_lift_py_tests.outcome import Complete, Completed, Halted, Incomplete
    from sugar_lift_py_tests.sugar.exit_set_routing import sugar_outcome_to_exitset
    from sugar_lift_py_tests.sugar.generator_with_sugar import GeneratorWithSugar

    boundary = _installed_generator_with(
        tmp_path,
        (
            "import warnings\n"
            "def consume():\n"
            "    for x in 1 / 0:\n"
            "        leftover = 1\n"
            "def make_guard():\n"
            "    with warnings.catch_warnings(record=True) as w:\n"
            "        try:\n"
            "            yield w\n"
            "            consume()\n"
            "        finally:\n"
            "            leftover = 1\n"
        ),
        "import arbitrary\ndef use():\n    with arbitrary.make_guard():\n        pass\n",
    )
    assert isinstance(boundary, GeneratorWithSugar)
    machine = sugar_outcome_to_exitset(boundary.manager.desugar()).exits[0].value
    step = next(
        item
        for item in machine.steps
        if isinstance(item, NestedCitedOpaqueManagerStepV1)
    )
    assert any(isinstance(item, YieldStepV1) for item in step.body_steps)
    assert any(isinstance(item, TermStepV1) for item in step.body_steps)
    cleanup = next(item for item in step.body_steps if isinstance(item, FinallyStepV1))
    assert any(
        isinstance(item, AssignStepV1) and item.name == "leftover"
        for item in cleanup.cleanup_steps
    )
    entered = machine.resume()
    faces = list(entered.exits)
    halted = _without_catch_warnings_construction_halt(faces)
    completed = [face for face in faces if isinstance(face, Completed)]
    assert len(halted) == 1
    assert isinstance(halted[0].effect, ContextManagerEnterRuntimeEffect)
    assert "warnings.catch_warnings" in halted[0].effect.reason
    assert len(completed) == 1
    assert isinstance(completed[0].value, YieldEffect)
    assert isinstance(completed[0].value.value, OpaqueManagerProtocolCoordinate)
    assert completed[0].value.value.symbol == "python:cm_enter_result"
    constructed = boundary.desugar()
    assert isinstance(constructed, Complete)
    assert isinstance(constructed.value, BlockValue)
    # The opaque exit may suppress the helper's raise: under the truth of its
    # open result the inner With completes and the generator runs on, so the
    # block falls through on that arm (the raise is re-raised under falsity).
    assert constructed.value.can_fall_through is True
    effects = [
        statement.effect
        for statement in constructed.value.statements
        if isinstance(statement, Incomplete)
    ]
    raised = next(effect for effect in effects if isinstance(effect, RaiseEffect))
    assert raised.exception_name == "ZeroDivisionError"
    assert any(
        isinstance(effect, ContextManagerEnterRuntimeEffect)
        and "warnings.catch_warnings" in effect.reason
        for effect in effects
    )
    assert any(
        isinstance(effect, ContextManagerExitRuntimeEffect)
        and "warnings.catch_warnings" in effect.reason
        for effect in effects
    )


def test_installed_cited_opaque_nested_with_body_helper_for_raising_tuple_still_exits(tmp_path):
    """A body helper ``for x in (1 / 0,)`` halts, then the with still exits.

    A tuple display is not concrete when an element is a ground
    ZeroDivisionError -- the same refusal range already makes for a bound.
    The loop stays a real fold, and the already-written raise surfaces.
    First resume still yields the open enter result. Desugar cites the
    raise and both open enter and exit faces. This does not invent that
    the loop unrolled, or that exit swallowed the raise.
    """
    from sugar_lift_py_tests.effect import (
        ContextManagerEnterRuntimeEffect,
        ContextManagerExitRuntimeEffect,
        RaiseEffect,
    )
    from sugar_lift_py_tests.floor.block_value import BlockValue
    from sugar_lift_py_tests.floor.opaque_manager_protocol_coordinate import (
        OpaqueManagerProtocolCoordinate,
    )
    from sugar_lift_py_tests.generator_construction import (
        AssignStepV1,
        FinallyStepV1,
        NestedCitedOpaqueManagerStepV1,
        TermStepV1,
        YieldEffect,
        YieldStepV1,
    )
    from sugar_lift_py_tests.outcome import Complete, Completed, Halted, Incomplete
    from sugar_lift_py_tests.sugar.exit_set_routing import sugar_outcome_to_exitset
    from sugar_lift_py_tests.sugar.generator_with_sugar import GeneratorWithSugar

    boundary = _installed_generator_with(
        tmp_path,
        (
            "import warnings\n"
            "def consume():\n"
            "    for x in (1 / 0,):\n"
            "        leftover = 1\n"
            "def make_guard():\n"
            "    with warnings.catch_warnings(record=True) as w:\n"
            "        try:\n"
            "            yield w\n"
            "            consume()\n"
            "        finally:\n"
            "            leftover = 1\n"
        ),
        "import arbitrary\ndef use():\n    with arbitrary.make_guard():\n        pass\n",
    )
    assert isinstance(boundary, GeneratorWithSugar)
    machine = sugar_outcome_to_exitset(boundary.manager.desugar()).exits[0].value
    step = next(
        item
        for item in machine.steps
        if isinstance(item, NestedCitedOpaqueManagerStepV1)
    )
    assert any(isinstance(item, YieldStepV1) for item in step.body_steps)
    assert any(isinstance(item, TermStepV1) for item in step.body_steps)
    cleanup = next(item for item in step.body_steps if isinstance(item, FinallyStepV1))
    assert any(
        isinstance(item, AssignStepV1) and item.name == "leftover"
        for item in cleanup.cleanup_steps
    )
    entered = machine.resume()
    faces = list(entered.exits)
    halted = _without_catch_warnings_construction_halt(faces)
    completed = [face for face in faces if isinstance(face, Completed)]
    assert len(halted) == 1
    assert isinstance(halted[0].effect, ContextManagerEnterRuntimeEffect)
    assert "warnings.catch_warnings" in halted[0].effect.reason
    assert len(completed) == 1
    assert isinstance(completed[0].value, YieldEffect)
    assert isinstance(completed[0].value.value, OpaqueManagerProtocolCoordinate)
    assert completed[0].value.value.symbol == "python:cm_enter_result"
    constructed = boundary.desugar()
    assert isinstance(constructed, Complete)
    assert isinstance(constructed.value, BlockValue)
    # The opaque exit may suppress the helper's raise: under the truth of its
    # open result the inner With completes and the generator runs on, so the
    # block falls through on that arm (the raise is re-raised under falsity).
    assert constructed.value.can_fall_through is True
    effects = [
        statement.effect
        for statement in constructed.value.statements
        if isinstance(statement, Incomplete)
    ]
    raised = next(effect for effect in effects if isinstance(effect, RaiseEffect))
    assert raised.exception_name == "ZeroDivisionError"
    assert any(
        isinstance(effect, ContextManagerEnterRuntimeEffect)
        and "warnings.catch_warnings" in effect.reason
        for effect in effects
    )
    assert any(
        isinstance(effect, ContextManagerExitRuntimeEffect)
        and "warnings.catch_warnings" in effect.reason
        for effect in effects
    )


def test_installed_cited_opaque_nested_with_structured_finally_while(tmp_path):
    """A finally ``while False`` is WhileStepV1 cleanup.

    The already-written false-while law skips the body and continues. Enter
    still keeps both open faces. Does not invent a bound on ``while True``.
    """
    from sugar_lift_py_tests.effect import (
        ContextManagerEnterRuntimeEffect,
        ContextManagerExitRuntimeEffect,
    )
    from sugar_lift_py_tests.floor.block_value import BlockValue
    from sugar_lift_py_tests.floor.opaque_manager_protocol_coordinate import (
        OpaqueManagerProtocolCoordinate,
    )
    from sugar_lift_py_tests.generator_construction import (
        AssignStepV1,
        FinallyStepV1,
        NestedCitedOpaqueManagerStepV1,
        WhileStepV1,
        YieldEffect,
        YieldStepV1,
    )
    from sugar_lift_py_tests.outcome import Complete, Completed, Halted, Incomplete
    from sugar_lift_py_tests.sugar.exit_set_routing import sugar_outcome_to_exitset
    from sugar_lift_py_tests.sugar.generator_with_sugar import GeneratorWithSugar

    boundary = _installed_generator_with(
        tmp_path,
        (
            "import warnings\n"
            "def make_guard():\n"
            "    with warnings.catch_warnings(record=True) as w:\n"
            "        try:\n"
            "            yield w\n"
            "        finally:\n"
            "            while False:\n"
            "                leftover = 1\n"
        ),
        "import arbitrary\ndef use():\n    with arbitrary.make_guard():\n        pass\n",
    )
    assert isinstance(boundary, GeneratorWithSugar)
    machine = sugar_outcome_to_exitset(boundary.manager.desugar()).exits[0].value
    step = next(
        item
        for item in machine.steps
        if isinstance(item, NestedCitedOpaqueManagerStepV1)
    )
    cleanup = next(item for item in step.body_steps if isinstance(item, FinallyStepV1))
    loop = next(item for item in cleanup.cleanup_steps if isinstance(item, WhileStepV1))
    assert any(
        isinstance(item, AssignStepV1) and item.name == "leftover"
        for item in loop.body_steps
    )
    assert any(isinstance(item, YieldStepV1) for item in step.body_steps)
    entered = machine.resume()
    faces = list(entered.exits)
    halted = _without_catch_warnings_construction_halt(faces)
    completed = [face for face in faces if isinstance(face, Completed)]
    assert len(halted) == 1
    assert isinstance(halted[0].effect, ContextManagerEnterRuntimeEffect)
    assert "warnings.catch_warnings" in halted[0].effect.reason
    assert len(completed) == 1
    assert isinstance(completed[0].value, YieldEffect)
    assert isinstance(completed[0].value.value, OpaqueManagerProtocolCoordinate)
    assert completed[0].value.value.symbol == "python:cm_enter_result"
    constructed = boundary.desugar()
    assert isinstance(constructed, Complete)
    assert isinstance(constructed.value, BlockValue)
    effects = [
        statement.effect
        for statement in constructed.value.statements
        if isinstance(statement, Incomplete)
    ]
    assert any(
        isinstance(effect, ContextManagerEnterRuntimeEffect)
        and "warnings.catch_warnings" in effect.reason
        for effect in effects
    )
    assert any(
        isinstance(effect, ContextManagerExitRuntimeEffect)
        and "warnings.catch_warnings" in effect.reason
        for effect in effects
    )


def test_installed_cited_opaque_nested_with_for_orelse_stays_opaque(tmp_path):
    """A for-else is outside ForStepV1, so the cited-opaque With stays loud."""
    from sugar_lift_py_tests.sugar.generator_with_sugar import GeneratorWithSugar
    from sugar_source_tree.panic import SugarNotWritten

    boundary = _installed_generator_with(
        tmp_path,
        (
            "import warnings\n"
            "def make_guard():\n"
            "    with warnings.catch_warnings(record=True) as w:\n"
            "        try:\n"
            "            yield w\n"
            "        finally:\n"
            "            for leftover in (1,):\n"
            "                seen = leftover\n"
            "            else:\n"
            "                seen = 0\n"
        ),
        "import arbitrary\ndef use():\n    with arbitrary.make_guard():\n        pass\n",
    )
    assert isinstance(boundary, GeneratorWithSugar)
    with pytest.raises(SugarNotWritten) as caught:
        boundary.desugar()
    assert caught.value.owner == "GeneratorWithSugar.desugar"
    assert caught.value.observed == "opaque generator transition: With carrying a suspension"



def test_installed_cited_opaque_nested_with_while_orelse_stays_opaque(tmp_path):
    """A while-else is outside WhileStepV1, so the cited-opaque With stays loud."""
    from sugar_lift_py_tests.sugar.generator_with_sugar import GeneratorWithSugar
    from sugar_source_tree.panic import SugarNotWritten

    boundary = _installed_generator_with(
        tmp_path,
        (
            "import warnings\n"
            "def make_guard():\n"
            "    with warnings.catch_warnings(record=True) as w:\n"
            "        try:\n"
            "            yield w\n"
            "        finally:\n"
            "            while False:\n"
            "                leftover = 1\n"
            "            else:\n"
            "                leftover = 0\n"
        ),
        "import arbitrary\ndef use():\n    with arbitrary.make_guard():\n        pass\n",
    )
    assert isinstance(boundary, GeneratorWithSugar)
    with pytest.raises(SugarNotWritten) as caught:
        boundary.desugar()
    assert caught.value.owner == "GeneratorWithSugar.desugar"
    assert caught.value.observed == "opaque generator transition: With carrying a suspension"


def test_installed_cited_opaque_nested_with_formal_if_in_finally(tmp_path):
    """A finally ``if flag:`` cites the bound formal's truth, not a free name.

    ``make_guard(True)`` and ``make_guard(False)`` both keep the open enter
    faces. The True arm names the assign; the False arm does not invent that
    it ran. Does not invent a default when the formal is bound.
    """
    from sugar_lift_py_tests.effect import (
        ContextManagerEnterRuntimeEffect,
        ContextManagerExitRuntimeEffect,
    )
    from sugar_lift_py_tests.floor.block_value import BlockValue
    from sugar_lift_py_tests.floor.opaque_manager_protocol_coordinate import (
        OpaqueManagerProtocolCoordinate,
    )
    from sugar_lift_py_tests.generator_construction import (
        AssignStepV1,
        FinallyStepV1,
        IfStepV1,
        NestedCitedOpaqueManagerStepV1,
        YieldEffect,
    )
    from sugar_lift_py_tests.outcome import Complete, Completed, Halted, Incomplete
    from sugar_lift_py_tests.sugar.exit_set_routing import sugar_outcome_to_exitset
    from sugar_lift_py_tests.sugar.generator_with_sugar import GeneratorWithSugar

    source = (
        "import warnings\n"
        "def make_guard(flag):\n"
        "    with warnings.catch_warnings(record=True) as w:\n"
        "        try:\n"
        "            yield w\n"
        "        finally:\n"
        "            if flag:\n"
        "                leftover = 1\n"
    )

    def check(root, consumer):
        root.mkdir()
        boundary = _installed_generator_with(root, source, consumer)
        assert isinstance(boundary, GeneratorWithSugar)
        machine = sugar_outcome_to_exitset(boundary.manager.desugar()).exits[0].value
        step = next(
            item
            for item in machine.steps
            if isinstance(item, NestedCitedOpaqueManagerStepV1)
        )
        cleanup = next(
            item for item in step.body_steps if isinstance(item, FinallyStepV1)
        )
        branch = next(item for item in cleanup.cleanup_steps if isinstance(item, IfStepV1))
        has_assign = any(
            isinstance(item, AssignStepV1) and item.name == "leftover"
            for item in branch.then_steps
        )
        assert has_assign is True
        entered = machine.resume()
        faces = list(entered.exits)
        halted = _without_catch_warnings_construction_halt(faces)
        completed = [face for face in faces if isinstance(face, Completed)]
        assert len(halted) == 1
        assert isinstance(halted[0].effect, ContextManagerEnterRuntimeEffect)
        assert "warnings.catch_warnings" in halted[0].effect.reason
        assert len(completed) == 1
        assert isinstance(completed[0].value, YieldEffect)
        assert isinstance(completed[0].value.value, OpaqueManagerProtocolCoordinate)
        assert completed[0].value.value.symbol == "python:cm_enter_result"
        constructed = boundary.desugar()
        assert isinstance(constructed, Complete)
        assert isinstance(constructed.value, BlockValue)
        effects = [
            statement.effect
            for statement in constructed.value.statements
            if isinstance(statement, Incomplete)
        ]
        assert any(
            isinstance(effect, ContextManagerEnterRuntimeEffect)
            and "warnings.catch_warnings" in effect.reason
            for effect in effects
        )
        assert any(
            isinstance(effect, ContextManagerExitRuntimeEffect)
            and "warnings.catch_warnings" in effect.reason
            for effect in effects
        )

    check(
        tmp_path / "truthy",
        "import arbitrary\ndef use():\n    with arbitrary.make_guard(True):\n        pass\n",
    )
    check(
        tmp_path / "falsy",
        "import arbitrary\ndef use():\n    with arbitrary.make_guard(False):\n        pass\n",
    )



def test_installed_cited_opaque_nested_with_builtin_class_if_in_finally(tmp_path):
    """A finally ``if expected:`` cites the language-owned class's truth.

    ``make_guard(FutureWarning)`` binds the builtin class, whose truth is
    already True, so the then arm is named and enter stays open. Does not
    invent a class floor or a default when the name is not a builtin.
    """
    from sugar_lift_py_tests.effect import (
        ContextManagerEnterRuntimeEffect,
        ContextManagerExitRuntimeEffect,
    )
    from sugar_lift_py_tests.floor.block_value import BlockValue
    from sugar_lift_py_tests.floor.opaque_manager_protocol_coordinate import (
        OpaqueManagerProtocolCoordinate,
    )
    from sugar_lift_py_tests.generator_construction import (
        AssignStepV1,
        FinallyStepV1,
        IfStepV1,
        NestedCitedOpaqueManagerStepV1,
        YieldEffect,
    )
    from sugar_lift_py_tests.outcome import Complete, Completed, Halted, Incomplete
    from sugar_lift_py_tests.sugar.exit_set_routing import sugar_outcome_to_exitset
    from sugar_lift_py_tests.sugar.generator_with_sugar import GeneratorWithSugar
    from sugar_lift_py_tests.temporal.builtin_name_bindings import builtin_name_temporal

    boundary = _installed_generator_with(
        tmp_path,
        (
            "import warnings\n"
            "def make_guard(expected):\n"
            "    with warnings.catch_warnings(record=True) as w:\n"
            "        try:\n"
            "            yield w\n"
            "        finally:\n"
            "            if expected:\n"
            "                leftover = 1\n"
        ),
        (
            "import arbitrary\n"
            "def use():\n"
            "    with arbitrary.make_guard(FutureWarning):\n"
            "        pass\n"
        ),
    )
    assert isinstance(boundary, GeneratorWithSugar)
    machine = sugar_outcome_to_exitset(boundary.manager.desugar()).exits[0].value
    expected = builtin_name_temporal().value_if_bound("FutureWarning")
    assert any(binding.floor_value is expected for binding in machine.formal_floor_bindings)
    step = next(
        item
        for item in machine.steps
        if isinstance(item, NestedCitedOpaqueManagerStepV1)
    )
    cleanup = next(item for item in step.body_steps if isinstance(item, FinallyStepV1))
    branch = next(item for item in cleanup.cleanup_steps if isinstance(item, IfStepV1))
    assert any(
        isinstance(item, AssignStepV1) and item.name == "leftover"
        for item in branch.then_steps
    )
    entered = machine.resume()
    faces = list(entered.exits)
    halted = _without_catch_warnings_construction_halt(faces)
    completed = [face for face in faces if isinstance(face, Completed)]
    assert len(halted) == 1
    assert isinstance(halted[0].effect, ContextManagerEnterRuntimeEffect)
    assert "warnings.catch_warnings" in halted[0].effect.reason
    assert len(completed) == 1
    assert isinstance(completed[0].value, YieldEffect)
    assert isinstance(completed[0].value.value, OpaqueManagerProtocolCoordinate)
    assert completed[0].value.value.symbol == "python:cm_enter_result"
    constructed = boundary.desugar()
    assert isinstance(constructed, Complete)
    assert isinstance(constructed.value, BlockValue)
    effects = [
        statement.effect
        for statement in constructed.value.statements
        if isinstance(statement, Incomplete)
    ]
    assert any(
        isinstance(effect, ContextManagerEnterRuntimeEffect)
        and "warnings.catch_warnings" in effect.reason
        for effect in effects
    )
    assert any(
        isinstance(effect, ContextManagerExitRuntimeEffect)
        and "warnings.catch_warnings" in effect.reason
        for effect in effects
    )


def test_installed_cited_opaque_nested_with_isinstance_tuple_if_in_finally(tmp_path):
    """A finally ``if isinstance(expected, tuple):`` cites the class law.

    ``make_guard(FutureWarning)`` binds the language-owned class.
    ``isinstance`` of that class and ``tuple`` is already False, so the else
    arm is named and enter stays open. Does not invent a class floor or a
    tuple decision when the classinfo is not the language-owned tuple.
    """
    from sugar_lift_py_tests.effect import (
        ContextManagerEnterRuntimeEffect,
        ContextManagerExitRuntimeEffect,
    )
    from sugar_lift_py_tests.floor.block_value import BlockValue
    from sugar_lift_py_tests.floor.opaque_manager_protocol_coordinate import (
        OpaqueManagerProtocolCoordinate,
    )
    from sugar_lift_py_tests.generator_construction import (
        AssignStepV1,
        FinallyStepV1,
        IfStepV1,
        NestedCitedOpaqueManagerStepV1,
        YieldEffect,
    )
    from sugar_lift_py_tests.outcome import Complete, Completed, Halted, Incomplete
    from sugar_lift_py_tests.sugar.exit_set_routing import sugar_outcome_to_exitset
    from sugar_lift_py_tests.sugar.generator_with_sugar import GeneratorWithSugar
    from sugar_lift_py_tests.temporal.builtin_name_bindings import builtin_name_temporal

    boundary = _installed_generator_with(
        tmp_path,
        (
            "import warnings\n"
            "def make_guard(expected):\n"
            "    with warnings.catch_warnings(record=True) as w:\n"
            "        try:\n"
            "            yield w\n"
            "        finally:\n"
            "            if isinstance(expected, tuple):\n"
            "                leftover = 1\n"
            "            else:\n"
            "                named = 1\n"
        ),
        (
            "import arbitrary\n"
            "def use():\n"
            "    with arbitrary.make_guard(FutureWarning):\n"
            "        pass\n"
        ),
    )
    assert isinstance(boundary, GeneratorWithSugar)
    machine = sugar_outcome_to_exitset(boundary.manager.desugar()).exits[0].value
    expected = builtin_name_temporal().value_if_bound("FutureWarning")
    assert any(binding.floor_value is expected for binding in machine.formal_floor_bindings)
    step = next(
        item
        for item in machine.steps
        if isinstance(item, NestedCitedOpaqueManagerStepV1)
    )
    cleanup = next(item for item in step.body_steps if isinstance(item, FinallyStepV1))
    branch = next(item for item in cleanup.cleanup_steps if isinstance(item, IfStepV1))
    assert any(
        isinstance(item, AssignStepV1) and item.name == "leftover"
        for item in branch.then_steps
    )
    assert any(
        isinstance(item, AssignStepV1) and item.name == "named"
        for item in branch.else_steps
    )
    from sugar_lift_py_tests.outcome import Complete as _Complete
    from sugar_lift_py_tests.sugar.false_bool_literal_sugar import FalseBoolLiteralSugar
    truth = machine._guard_truth(branch.guard)
    assert isinstance(truth, _Complete)
    assert isinstance(truth.value, FalseBoolLiteralSugar)
    assert machine._decide_guard(truth.value) is False
    entered = machine.resume()
    faces = list(entered.exits)
    halted = _without_catch_warnings_construction_halt(faces)
    completed = [face for face in faces if isinstance(face, Completed)]
    assert len(halted) == 1
    assert isinstance(halted[0].effect, ContextManagerEnterRuntimeEffect)
    assert "warnings.catch_warnings" in halted[0].effect.reason
    assert len(completed) == 1
    assert isinstance(completed[0].value, YieldEffect)
    assert isinstance(completed[0].value.value, OpaqueManagerProtocolCoordinate)
    assert completed[0].value.value.symbol == "python:cm_enter_result"
    constructed = boundary.desugar()
    assert isinstance(constructed, Complete)
    assert isinstance(constructed.value, BlockValue)
    effects = [
        statement.effect
        for statement in constructed.value.statements
        if isinstance(statement, Incomplete)
    ]
    assert any(
        isinstance(effect, ContextManagerEnterRuntimeEffect)
        and "warnings.catch_warnings" in effect.reason
        for effect in effects
    )
    assert any(
        isinstance(effect, ContextManagerExitRuntimeEffect)
        and "warnings.catch_warnings" in effect.reason
        for effect in effects
    )


def test_installed_cited_opaque_nested_with_term_only_helper_iterates_enter_result(tmp_path):
    """A term-only finally ``consume(w)`` stays loud on the enter result.

    The call is a TermStepV1 in finally cleanup and reduces already-written
    prefix, but ``for item in xs`` over ``python:cm_enter_result`` has no
    iter_with. Enter stays open. Does not invent a warning list or iter_with.
    """
    from sugar_lift_py_tests.effect import ContextManagerEnterRuntimeEffect
    from sugar_lift_py_tests.floor.opaque_manager_protocol_coordinate import (
        OpaqueManagerProtocolCoordinate,
    )
    from sugar_lift_py_tests.generator_construction import (
        FinallyStepV1,
        NestedCitedOpaqueManagerStepV1,
        TermStepV1,
        YieldEffect,
    )
    from sugar_lift_py_tests.outcome import Completed, Halted
    from sugar_lift_py_tests.sugar.exit_set_routing import sugar_outcome_to_exitset
    from sugar_lift_py_tests.sugar.generator_with_sugar import GeneratorWithSugar
    from sugar_source_tree.panic import SugarNotWritten

    boundary = _installed_generator_with(
        tmp_path,
        (
            "import warnings\n"
            "def consume(xs):\n"
            "    for item in xs:\n"
            "        leftover = 1\n"
            "def make_guard():\n"
            "    with warnings.catch_warnings(record=True) as w:\n"
            "        try:\n"
            "            yield w\n"
            "        finally:\n"
            "            consume(w)\n"
        ),
        (
            "import arbitrary\n"
            "def use():\n"
            "    with arbitrary.make_guard():\n"
            "        pass\n"
        ),
    )
    assert isinstance(boundary, GeneratorWithSugar)
    machine = sugar_outcome_to_exitset(boundary.manager.desugar()).exits[0].value
    step = next(
        item
        for item in machine.steps
        if isinstance(item, NestedCitedOpaqueManagerStepV1)
    )
    cleanup = next(item for item in step.body_steps if isinstance(item, FinallyStepV1))
    assert any(isinstance(item, TermStepV1) for item in cleanup.cleanup_steps)
    entered = machine.resume()
    faces = list(entered.exits)
    halted = _without_catch_warnings_construction_halt(faces)
    completed = [face for face in faces if isinstance(face, Completed)]
    assert len(halted) == 1
    assert isinstance(halted[0].effect, ContextManagerEnterRuntimeEffect)
    assert "warnings.catch_warnings" in halted[0].effect.reason
    assert len(completed) == 1
    assert isinstance(completed[0].value, YieldEffect)
    assert isinstance(completed[0].value.value, OpaqueManagerProtocolCoordinate)
    assert completed[0].value.value.symbol == "python:cm_enter_result"
    # The loop's ConstructionPanic propagates under its own name. The
    # generator transition must not rewrite it into a transition gap.
    from sugar_lift_py_tests.gap.panic import ConstructionPanic

    with pytest.raises(ConstructionPanic) as caught:
        boundary.desugar()
    assert caught.value.info.owner == "LoopRecurrenceSugar"
    assert caught.value.info.requested == "iter_with"
    assert caught.value.info.observed == "OpaqueManagerProtocolCoordinate"


def test_installed_pandas_warning_manager_names_opaque_generator_transition(tmp_path):
    """The cited-opaque catch_warnings With is now named, including its for.

    ``if expected_warning:`` cites the language-owned FutureWarning class and
    decides True. The nested
    ``if isinstance(expected_warning, tuple) and must_find_all_warnings:``
    cites the already-written class law and decides False. The leftover is
    the else-arm ``_assert_caught_expected_warnings`` body iterating ``w``:
    ``w`` is the open enter result, not a warning list, so the loop stays
    ``LoopRecurrenceSugar requested iter_with on OpaqueManagerProtocolCoordinate``.
    Construction must keep that loud, not invent iter_with, a warning list,
    or zip items.
    """
    consumer = (
        "import pandas._testing as tm\n"
        "def use_boundary(f):\n"
        "    with tm.assert_produces_warning(FutureWarning):\n"
        "        f()\n"
    )
    path = tmp_path / "consumer.py"
    path.write_text(consumer, encoding="utf-8")
    from sugar_lift_py_tests.context_manager_resolution import (
        TreeConstructionContextV1,
    )
    from sugar_lift_py_tests.sugar.generator_with_sugar import (
        GeneratorWithSugar,
    )
    from sugar_source_tree.panic import SugarNotWritten

    context = TreeConstructionContextV1.for_source_call_construction()
    tree = SourceFile(
        (consumer, str(path), blake3_512_of(consumer.encode("utf-8"))),
        construction_context=context,
    )
    pandas_distribution = importlib.metadata.distribution("pandas")
    populate_source_derived_resource_refs(
        tree,
        root=tmp_path,
        path=path,
        session=SourceResolutionSession(
            enrolled_distributions=frozenset({pandas_distribution.metadata["Name"]})
        ),
    )

    boundary = next(node for node in tree.nodes() if node.kind == "With").sugar()
    assert isinstance(boundary, GeneratorWithSugar)
    # The loop's ConstructionPanic propagates under its own name. The
    # generator transition must not rewrite it into a transition gap.
    from sugar_lift_py_tests.gap.panic import ConstructionPanic

    with pytest.raises(ConstructionPanic) as caught:
        boundary.desugar()
    assert caught.value.info.owner == "LoopRecurrenceSugar"
    assert caught.value.info.requested == "iter_with"
    assert caught.value.info.observed == "OpaqueManagerProtocolCoordinate"


def test_imported_renamed_generator_manager_installs_native_frame(tmp_path):
    """Truthful twin: suspension testimony, not a manager-name table, opens it."""
    distribution = _distribution(
        tmp_path,
        _contextmanager_decorated("def make_guard(expected):\n    yield expected\n"),
    )
    consumer = "import arbitrary\nwith arbitrary.make_guard(23):\n    pass\n"
    path = tmp_path / "consumer.py"
    path.write_text(consumer, encoding="utf-8")
    from sugar_lift_py_tests.context_manager_resolution import TreeConstructionContextV1
    from sugar_lift_py_tests.sugar.generator_with_sugar import GeneratorWithSugar

    context = TreeConstructionContextV1.for_source_call_construction()
    tree = SourceFile(
        (consumer, str(path), blake3_512_of(consumer.encode("utf-8"))),
        construction_context=context,
    )
    populate_source_derived_resource_refs(
        tree,
        root=tmp_path,
        path=path,
        distribution_index={"arbitrary": distribution},
        session=SourceResolutionSession(
            enrolled_distributions=frozenset({distribution.metadata["Name"]})
        ),
    )

    assert isinstance(
        next(node for node in tree.nodes() if node.kind == "With").sugar(),
        GeneratorWithSugar,
    )


def test_imported_ordinary_factory_cannot_lie_as_generator_manager(tmp_path):
    """Lying twin: same import/call shape without a suspension gets no frame."""
    distribution = _distribution(
        tmp_path,
        "def make_guard(expected):\n    return expected\n",
    )
    consumer = "import arbitrary\nwith arbitrary.make_guard(23):\n    pass\n"
    path = tmp_path / "consumer.py"
    path.write_text(consumer, encoding="utf-8")
    from sugar_lift_py_tests.context_manager_resolution import (
        ContextManagerResolutionGapV1,
        TreeConstructionContextV1,
    )

    context = TreeConstructionContextV1.for_source_call_construction()
    tree = SourceFile(
        (consumer, str(path), blake3_512_of(consumer.encode("utf-8"))),
        construction_context=context,
    )
    populate_source_derived_resource_refs(
        tree,
        root=tmp_path,
        path=path,
        distribution_index={"arbitrary": distribution},
        session=SourceResolutionSession(
            enrolled_distributions=frozenset({distribution.metadata["Name"]})
        ),
    )

    assert context.source_call_frames == {}
    gap = next(iter(context.source_derived_contract_refs.values()))
    assert isinstance(gap, ContextManagerResolutionGapV1)
    assert (gap.kind, gap.detail) == ("non-manager-result", "TermValue")


def _installed_plain_expected_halt_reference(tmp_path, function_body: str):
    """Populate the installed pytest.raises dual-mode residual for plain expected."""
    consumer = (
        "import pytest\n"
        "def use_boundary():\n"
        "    with pytest.raises(ValueError):\n"
        f"        {function_body}\n"
    )
    path = tmp_path / "plain_expected_halt.py"
    path.write_text(consumer, encoding="utf-8")
    from sugar_lift_py_tests.context_manager_resolution import (
        ContextManagerResolutionGapV1,
        SourceDerivedContextManagerRefV1,
        TreeConstructionContextV1,
    )
    from sugar_lift_py_tests.sugar.with_effect_boundary_sugar import (
        WithEffectBoundarySugar,
    )

    context = TreeConstructionContextV1.for_source_call_construction()
    tree = SourceFile(
        (consumer, str(path), blake3_512_of(consumer.encode("utf-8"))),
        construction_context=context,
    )
    pytest_distribution = importlib.metadata.distribution("pytest")
    populate_source_derived_resource_refs(
        tree,
        root=tmp_path,
        path=path,
        session=SourceResolutionSession(
            enrolled_distributions=frozenset({pytest_distribution.metadata["Name"]})
        ),
    )
    reference = next(iter(context.source_derived_contract_refs.values()))
    with_node = next(node for node in tree.nodes() if node.kind == "With")
    if isinstance(reference, SourceDerivedContextManagerRefV1):
        boundary = with_node.sugar()
        assert isinstance(boundary, WithEffectBoundarySugar), boundary
        return reference, boundary.desugar()
    assert isinstance(reference, ContextManagerResolutionGapV1), reference
    return reference, None


def test_installed_plain_expected_halt_completes(tmp_path):
    """TRUTHFUL: plain pytest.raises constructs through the dual-mode return.

    When EffectBoundary seals, the expected native halt is the passing face.
    Until the exit residual drains, the seated residual is stage-keyed
    ``exit-may-halt`` (unary ``not`` over CallSiteValue) — never helper spelling.
    """
    from sugar_lift_py_tests.context_manager_resolution import (
        ContextManagerResolutionGapV1,
        SourceDerivedContextManagerRefV1,
    )
    from sugar_lift_py_tests.outcome import Completed, outcome_to_exitset

    reference, outcome = _installed_plain_expected_halt_reference(
        tmp_path, "raise ValueError('expected')"
    )
    if isinstance(reference, SourceDerivedContextManagerRefV1):
        exits = _without_pytest_raises_construction_halts(
            outcome_to_exitset(outcome).exits
        )
        assert len(exits) == 1
        assert isinstance(exits[0], Completed), exits
        return
    assert isinstance(reference, ContextManagerResolutionGapV1)
    assert reference.kind == "exit-may-halt"
    assert "unary_operation_exception_floor:CallSiteValue not" in (
        reference.detail or ""
    )


def test_installed_plain_expected_halt_lie_fails(tmp_path):
    """LYING: returning normally cannot satisfy an expected-halt assertion.

    Same construction residual as the truthful twin while EffectBoundary is
    unsealed; when sealed, the lie must Halt with ExpectationNotMetEffect.
    """
    from sugar_lift_py_tests.context_manager_resolution import (
        ContextManagerResolutionGapV1,
        SourceDerivedContextManagerRefV1,
    )
    from sugar_lift_py_tests.effect import ExpectationNotMetEffect
    from sugar_lift_py_tests.outcome import Halted, outcome_to_exitset

    reference, outcome = _installed_plain_expected_halt_reference(tmp_path, "pass")
    if isinstance(reference, SourceDerivedContextManagerRefV1):
        exits = _without_pytest_raises_construction_halts(
            outcome_to_exitset(outcome).exits
        )
        assert len(exits) == 1
        assert isinstance(exits[0], Halted), exits
        assert isinstance(exits[0].effect, ExpectationNotMetEffect), exits[0]
        return
    assert isinstance(reference, ContextManagerResolutionGapV1)
    assert reference.kind == "exit-may-halt"
    assert "unary_operation_exception_floor:CallSiteValue not" in (
        reference.detail or ""
    )


def test_protocol_resource_never_selects_effect_boundary_assertion_door(tmp_path):
    """Assertion membrane must not admit ProtocolResource managers.

    A NeverSuppresses resource constructs as WithSourceResourceSugar. It must
    never install as EffectBoundary / WithEffectBoundarySugar merely because
    it appears under ``with``.
    """
    implementation = (
        "class RenamedResource:\n"
        "    def __enter__(self):\n"
        "        return 9\n"
        "    def __exit__(self, effect_type, effect, traceback):\n"
        "        return False\n\n"
        "def make_resource():\n"
        "    return RenamedResource()\n"
    )
    distribution = _distribution(tmp_path, implementation, exported="make_resource")
    consumer = (
        "import arbitrary\n"
        "def use_resource():\n"
        "    with arbitrary.make_resource():\n"
        "        pass\n"
    )
    path = tmp_path / "consumer.py"
    path.write_text(consumer, encoding="utf-8")
    from sugar_lift_py_tests.context_manager_contract import (
        EffectBoundarySemanticsV1,
        ProtocolResourceSemanticsV1,
    )
    from sugar_lift_py_tests.context_manager_resolution import (
        SourceDerivedContextManagerRefV1,
        TreeConstructionContextV1,
    )
    from sugar_lift_py_tests.sugar.with_effect_boundary_sugar import (
        WithEffectBoundarySugar,
    )
    from sugar_lift_py_tests.sugar.with_source_resource_sugar import (
        WithSourceResourceSugar,
    )

    context = TreeConstructionContextV1.for_source_call_construction()
    tree = SourceFile(
        (consumer, str(path), blake3_512_of(consumer.encode("utf-8"))),
        construction_context=context,
    )
    populate_source_derived_resource_refs(
        tree,
        root=tmp_path,
        path=path,
        distribution_index={"arbitrary": distribution},
        session=SourceResolutionSession(
            enrolled_distributions=frozenset({distribution.metadata["Name"]})
        ),
    )
    reference = next(iter(context.source_derived_contract_refs.values()))
    assert isinstance(reference, SourceDerivedContextManagerRefV1)
    assert isinstance(reference.semantics, ProtocolResourceSemanticsV1)
    assert not isinstance(reference.semantics, EffectBoundarySemanticsV1)
    with_node = next(node for node in tree.nodes() if node.kind == "With")
    sugar = with_node.sugar()
    assert isinstance(sugar, WithSourceResourceSugar)
    assert not isinstance(sugar, WithEffectBoundarySugar)


def test_expects_effect_boundary_never_installs_as_protocol_resource(tmp_path):
    """Expects/Raise boundary is the assertion membrane, not a resource."""
    implementation = (
        "class RenamedBoundary:\n"
        "    def __init__(self, expected):\n"
        "        self.expected = expected\n"
        "    def __enter__(self):\n"
        "        return self\n"
        "    def __exit__(self, effect_type, effect, traceback):\n"
        "        if effect_type is None:\n"
        "            raise RuntimeError()\n"
        "        return effect_type is self.expected\n\n"
        "def make_boundary(expected):\n"
        "    return RenamedBoundary(expected)\n"
    )
    distribution = _distribution(tmp_path, implementation, exported="make_boundary")
    consumer = (
        "import arbitrary\n"
        "def use_boundary():\n"
        "    with arbitrary.make_boundary(ValueError):\n"
        "        pass\n"
    )
    path = tmp_path / "consumer.py"
    path.write_text(consumer, encoding="utf-8")
    from sugar_lift_py_tests.context_manager_contract import (
        EffectBoundarySemanticsV1,
        ExpectsModeV1,
        ProtocolResourceSemanticsV1,
    )
    from sugar_lift_py_tests.context_manager_resolution import (
        SourceDerivedContextManagerRefV1,
        TreeConstructionContextV1,
    )
    from sugar_lift_py_tests.sugar.with_effect_boundary_sugar import (
        WithEffectBoundarySugar,
    )
    from sugar_lift_py_tests.sugar.with_source_resource_sugar import (
        WithSourceResourceSugar,
    )

    context = TreeConstructionContextV1.for_source_call_construction()
    tree = SourceFile(
        (consumer, str(path), blake3_512_of(consumer.encode("utf-8"))),
        construction_context=context,
    )
    populate_source_derived_resource_refs(
        tree,
        root=tmp_path,
        path=path,
        distribution_index={"arbitrary": distribution},
        session=SourceResolutionSession(
            enrolled_distributions=frozenset({distribution.metadata["Name"]})
        ),
    )
    reference = next(iter(context.source_derived_contract_refs.values()))
    assert isinstance(reference, SourceDerivedContextManagerRefV1)
    assert isinstance(reference.semantics, EffectBoundarySemanticsV1)
    assert isinstance(reference.semantics.mode, ExpectsModeV1)
    assert not isinstance(reference.semantics, ProtocolResourceSemanticsV1)
    with_node = next(node for node in tree.nodes() if node.kind == "With")
    sugar = with_node.sugar()
    assert isinstance(sugar, WithEffectBoundarySugar)
    assert not isinstance(sugar, WithSourceResourceSugar)


def test_installed_stdlib_suppress_reaches_grouped_unpack_after_graph_authentication(
    tmp_path,
):
    consumer = (
        "import contextlib as renamed_stdlib\n"
        "def use_boundary():\n"
        "    with renamed_stdlib.suppress(ValueError):\n"
        "        raise ValueError('boom')\n"
    )
    path = tmp_path / "consumer.py"
    path.write_text(consumer, encoding="utf-8")
    from sugar_lift_py_tests.context_manager_resolution import (
        ContextManagerResolutionGapV1,
        TreeConstructionContextV1,
    )

    context = TreeConstructionContextV1.for_source_call_construction()
    tree = SourceFile(
        (consumer, str(path), blake3_512_of(consumer.encode("utf-8"))),
        construction_context=context,
    )
    graphs = {}
    # Graph authentication of stdlib contextlib succeeds. Later-stage residual
    # (exit method ExitSet / unpack) stays a typed gap — not a bare SugarNotWritten.
    populate_source_derived_resource_refs(
        tree,
        root=tmp_path,
        path=path,
        artifact_graph_cache=graphs,
        session=SourceResolutionSession(enrolled_distributions=frozenset()),
    )

    graph = graphs["contextlib"]
    assert graph.artifact_kind == "stdlib"
    assert "contextlib" in graph.modules
    resolution = next(iter(context.source_derived_contract_refs.values()))
    assert isinstance(resolution, ContextManagerResolutionGapV1)
    assert resolution.kind in {
        "exit-may-halt",
        "enter-may-halt",
        "force-floor",
        "non-manager-result",
        "method-construction",
        "opaque-exit-truthiness",
    }, resolution.kind


@pytest.mark.parametrize(
    ("body", "expected_face", "expected_effect"),
    [
        ('raise ValueError("needle")', "completed", None),
        ('raise TypeError("needle")', "halted", "RaiseEffect"),
        ('raise ValueError("different")', "halted", "RaiseEffect"),
        ("pass", "halted", "ExpectationNotMetEffect"),
    ],
)
def test_renamed_source_boundary_routes_type_and_message_by_derived_formals(
    tmp_path, body, expected_face, expected_effect
):
    implementation = (
        "class Boundary:\n"
        "    def __init__(self, expected, pattern):\n"
        "        self.expected = expected\n"
        "        self.pattern = pattern\n"
        "    def __enter__(self):\n"
        "        return self\n"
        "    def __exit__(self, effect_type, effect, traceback):\n"
        "        if effect_type is None:\n"
        "            raise RuntimeError()\n"
        "        return (effect_type is self.expected) and (effect.message == self.pattern)\n\n"
        "def boundary(expected, pattern):\n"
        "    return Boundary(expected, pattern)\n"
    )
    distribution = _distribution(tmp_path, implementation, exported="boundary")
    consumer = (
        "import arbitrary\n"
        "def use_boundary():\n"
        '    with arbitrary.boundary(ValueError, "needle"):\n'
        f"        {body}\n"
    )
    path = tmp_path / "consumer.py"
    path.write_text(consumer, encoding="utf-8")
    from sugar_lift_py_tests.context_manager_resolution import TreeConstructionContextV1

    context = TreeConstructionContextV1.for_source_call_construction()
    tree = SourceFile(
        (consumer, str(path), blake3_512_of(consumer.encode("utf-8"))),
        construction_context=context,
    )
    populate_source_derived_resource_refs(
        tree,
        root=tmp_path,
        path=path,
        distribution_index={"arbitrary": distribution},
        session=SourceResolutionSession(
            enrolled_distributions=frozenset({distribution.metadata["Name"]})
        ),
    )
    boundary = next(node for node in tree.nodes() if node.kind == "With").sugar()
    from sugar_lift_py_tests.outcome import Completed, Halted, outcome_to_exitset

    face = outcome_to_exitset(boundary.desugar()).exits[0]
    assert type(face).__name__.lower() == expected_face
    if isinstance(face, Halted):
        assert type(face.effect).__name__ == expected_effect
    else:
        assert isinstance(face, Completed)


# --- Guarded-literal exit predicate (#6298 assertion-With drain) --------------
#
# The community shape for an effect boundary does NOT return one predicate
# expression. It routes to `return True` / `return False` under guards:
#
#     if effect_type is None:
#         raise ...
#     if not <matched>:
#         return False
#     return True
#
# That is the SAME theorem as `return effect_type is self.expected`, with the
# partition moved from the value level to the guard level. Deriving it means
# reading the disjunction of the guards of the exact-True completed faces —
# never a manager name, never a spelling.


def _guarded_literal_boundary(tmp_path, *, exit_body: str):
    graph, resolved, actual, call_site = _resolved(
        tmp_path,
        "class ArbitraryBoundary:\n"
        "    def __init__(self, expected):\n"
        "        self.expected = expected\n"
        "    def __enter__(self):\n"
        "        return self\n"
        "    def __exit__(self, effect_type, effect, traceback):\n"
        + exit_body
        + "def make_guard(expected):\n"
        "    return ArbitraryBoundary(expected)\n",
    )
    behavior = construct_manager_behavior(
        resolved, graph=graph, actuals=(actual,), call_site=call_site
    )
    assert isinstance(behavior, ConstructedManagerBehaviorV1)
    protocol = construct_manager_protocol(behavior, exit_face_id="guarded-literal-face")
    assert isinstance(protocol, ConstructedManagerProtocolV1)
    return derive_manager_summary(protocol, behavior=behavior)


def _assert_source_exit_faces_resource_not_boundary(summary, disposition):
    """A guarded exit halt is carried as the exit's own face, never a boundary.

    The exit may halt, so the resource is not total; it seals only as
    ``source-exit-faces``, which With honours by re-running the exit frame per
    body face. No Expects/Suppresses theorem is minted from the True face.
    """
    from sugar_lift_py_tests.context_manager_contract import (
        EffectBoundarySemanticsV1,
        NeverSuppressesDispositionV1,
        ProtocolResourceSemanticsV1,
        ReturnTruthinessDispositionV1,
        SourceExitFacesCompletionV1,
    )
    from sugar_lift_python_source.manager_summary_derivation import (
        DerivedManagerSummaryV1,
    )

    disposition = {
        "never": NeverSuppressesDispositionV1,
        "truth": ReturnTruthinessDispositionV1,
    }[disposition]
    assert isinstance(summary, DerivedManagerSummaryV1)
    assert not isinstance(summary.semantics, EffectBoundarySemanticsV1)
    assert isinstance(summary.semantics, ProtocolResourceSemanticsV1)
    assert isinstance(summary.semantics.exit.completion, SourceExitFacesCompletionV1)
    assert isinstance(summary.semantics.exit.disposition, disposition)


def test_guarded_literal_exit_derives_expects_raise_boundary(tmp_path):
    summary = _guarded_literal_boundary(
        tmp_path,
        exit_body=(
            "        if effect_type is None:\n"
            "            raise RuntimeError()\n"
            "        if effect_type is self.expected:\n"
            "            return True\n"
            "        return False\n"
        ),
    )
    from sugar_lift_py_tests.context_manager_contract import (
        EffectBoundarySemanticsV1,
        ExpectsModeV1,
        FormalArgumentProjectionV1,
        RaiseEffectKindV1,
    )

    assert isinstance(summary, DerivedManagerSummaryV1)
    assert isinstance(summary.semantics, EffectBoundarySemanticsV1)
    assert isinstance(summary.semantics.mode, ExpectsModeV1)
    assert isinstance(summary.semantics.effect_kind, RaiseEffectKindV1)
    assert summary.semantics.expected_type_operand == FormalArgumentProjectionV1(0)


def test_guarded_literal_exit_without_absent_effect_halt_derives_suppresses(tmp_path):
    summary = _guarded_literal_boundary(
        tmp_path,
        exit_body=(
            "        if effect_type is self.expected:\n"
            "            return True\n"
            "        return False\n"
        ),
    )
    from sugar_lift_py_tests.context_manager_contract import (
        EffectBoundarySemanticsV1,
        FormalArgumentProjectionV1,
        SuppressesModeV1,
    )

    assert isinstance(summary, DerivedManagerSummaryV1)
    assert isinstance(summary.semantics, EffectBoundarySemanticsV1)
    assert isinstance(summary.semantics.mode, SuppressesModeV1)
    assert summary.semantics.expected_type_operand == FormalArgumentProjectionV1(0)


def test_guarded_literal_exit_with_opaque_completed_face_is_not_a_boundary(tmp_path):
    """Discrimination: one non-literal completed face admits NOTHING.

    `return self.expected` is neither exact True nor exact False, so the
    guard disjunction would silently speak for a face it does not cover.
    The whole derivation must stay a typed gap.
    """
    summary = _guarded_literal_boundary(
        tmp_path,
        exit_body=(
            "        if effect_type is None:\n"
            "            raise RuntimeError()\n"
            "        if effect_type is self.expected:\n"
            "            return True\n"
            "        return self.expected\n"
        ),
    )
    _assert_source_exit_faces_resource_not_boundary(
        summary, "truth"
    )


def test_guarded_literal_exit_with_no_true_face_is_not_a_boundary(tmp_path):
    """An all-False exit names no suppression predicate, so nothing is derived.

    Teeth note: perturbing the explicit empty-disjunction refusal in
    `_guarded_literal_suppression_formula` does NOT turn this red — an empty
    disjunction is `false_guard()`, which carries no exit-type coordinate, so
    the operand-resolution arm refuses it anyway. The explicit refusal is
    defence in depth, not the arm this case exercises. This test pins the
    CLASS (all-False exit is never a boundary), and its independent teeth are
    the operand arm's.
    """
    summary = _guarded_literal_boundary(
        tmp_path,
        exit_body=(
            "        if effect_type is None:\n"
            "            raise RuntimeError()\n"
            "        return False\n"
        ),
    )
    _assert_source_exit_faces_resource_not_boundary(
        summary, "never"
    )


def test_guarded_literal_exit_without_type_coordinate_is_not_a_boundary(tmp_path):
    """Discrimination: a guard that never tests the exit-type coordinate.

    No formal index is resolvable, so no expected-type operand exists and
    the boundary must not be constructed from the True face alone.
    """
    summary = _guarded_literal_boundary(
        tmp_path,
        exit_body=(
            "        if effect_type is None:\n"
            "            raise RuntimeError()\n"
            "        if effect is self.expected:\n"
            "            return True\n"
            "        return False\n"
        ),
    )
    _assert_source_exit_faces_resource_not_boundary(
        summary, "truth"
    )


# --- Effect boundary consumes an ANCESTOR match, not only exact identity -----
#
# `matches_raise_effect` is the one matcher for With and Try, and it walks the
# raised effect's ancestry. Builtin ancestry is Python's own testimony, so a
# boundary written against `Exception` consumes a `ValueError` halt and does
# NOT consume a `KeyboardInterrupt` one. Both faces, because an ancestry table
# that says yes to everything is as wrong as one that says no to everything.


@pytest.mark.parametrize(
    ("expected_type", "body", "expected_face"),
    [
        ("Exception", 'raise ValueError("needle")', "completed"),
        ("ArithmeticError", 'raise ZeroDivisionError("needle")', "completed"),
        ("BaseException", 'raise KeyboardInterrupt("needle")', "completed"),
        ("Exception", 'raise KeyboardInterrupt("needle")', "halted"),
        ("ValueError", 'raise Exception("needle")', "halted"),
        ("ArithmeticError", 'raise OSError("needle")', "halted"),
    ],
)
def test_boundary_consumes_authenticated_builtin_ancestry_only_in_one_direction(
    tmp_path, expected_type, body, expected_face
):
    implementation = (
        "class Boundary:\n"
        "    def __init__(self, expected):\n"
        "        self.expected = expected\n"
        "    def __enter__(self):\n"
        "        return self\n"
        "    def __exit__(self, effect_type, effect, traceback):\n"
        "        if effect_type is None:\n"
        "            raise RuntimeError()\n"
        "        return effect_type is self.expected\n\n"
        "def boundary(expected):\n"
        "    return Boundary(expected)\n"
    )
    distribution = _distribution(tmp_path, implementation, exported="boundary")
    consumer = (
        "import arbitrary\n"
        "def use_boundary():\n"
        f"    with arbitrary.boundary({expected_type}):\n"
        f"        {body}\n"
    )
    path = tmp_path / "consumer.py"
    path.write_text(consumer, encoding="utf-8")
    from sugar_lift_py_tests.context_manager_resolution import TreeConstructionContextV1

    context = TreeConstructionContextV1.for_source_call_construction()
    tree = SourceFile(
        (consumer, str(path), blake3_512_of(consumer.encode("utf-8"))),
        construction_context=context,
    )
    populate_source_derived_resource_refs(
        tree,
        root=tmp_path,
        path=path,
        distribution_index={"arbitrary": distribution},
        session=SourceResolutionSession(
            enrolled_distributions=frozenset({distribution.metadata["Name"]})
        ),
    )
    boundary = next(node for node in tree.nodes() if node.kind == "With").sugar()
    from sugar_lift_py_tests.outcome import outcome_to_exitset

    face = outcome_to_exitset(boundary.desugar()).exits[0]
    assert type(face).__name__.lower() == expected_face


# --- bind-observed-effect: `with <boundary> as info:` -------------------------
#
# The binding projects the ROUTED OCCURRENCE COORDINATE and never fabricates
# `E()`. So the slot is authenticated on exactly one arm -- the one whose halt
# this boundary actually consumed. On a restored halt there is an occurrence
# but it is not this boundary's, and on a completed body there is no occurrence
# at all; both must carry zero binding facts.


_BOUNDARY_IMPLEMENTATION = (
    "class Boundary:\n"
    "    def __init__(self, expected):\n"
    "        self.expected = expected\n"
    "    def __enter__(self):\n"
    "        return self\n"
    "    def __exit__(self, effect_type, effect, traceback):\n"
    "        if effect_type is None:\n"
    "            raise RuntimeError()\n"
    "        return effect_type is self.expected\n\n"
    "def boundary(expected):\n"
    "    return Boundary(expected)\n"
)


def _route_boundary_with_binding(
    tmp_path,
    *,
    body: str,
    as_clause: str = " as info",
    following: str = "",
    implementation: str = _BOUNDARY_IMPLEMENTATION,
    prefix: str = "",
    manager: str = "arbitrary.boundary(ValueError)",
):
    distribution = _distribution(tmp_path, implementation, exported="boundary")
    consumer = "import arbitrary\ndef use_boundary():\n"
    if prefix:
        consumer += textwrap.indent(textwrap.dedent(prefix), "    ")
    consumer += f"    with {manager}{as_clause}:\n"
    consumer += textwrap.indent(textwrap.dedent(body), "        ") + "\n"
    if following:
        consumer += textwrap.indent(textwrap.dedent(following), "    ") + "\n"
    path = tmp_path / "consumer.py"
    path.write_text(consumer, encoding="utf-8")
    from sugar_lift_py_tests.context_manager_resolution import TreeConstructionContextV1

    context = TreeConstructionContextV1.for_source_call_construction()
    tree = SourceFile(
        (consumer, str(path), blake3_512_of(consumer.encode("utf-8"))),
        construction_context=context,
    )
    populate_source_derived_resource_refs(
        tree,
        root=tmp_path,
        path=path,
        distribution_index={"arbitrary": distribution},
        session=SourceResolutionSession(
            enrolled_distributions=frozenset({distribution.metadata["Name"]})
        ),
    )
    from sugar_lift_py_tests.outcome import outcome_to_exitset

    if following:
        from sugar_lift_py_tests.sugar.function_universe_sugar import (
            reduce_block_to_exitset,
        )

        function = next(tree.functions()).sugar()
        return reduce_block_to_exitset(function.statements)
    return outcome_to_exitset(
        next(node for node in tree.nodes() if node.kind == "With").sugar().desugar()
    )


def test_boundary_as_binding_outlives_block_and_projects_consumed_effect(tmp_path):
    """Concrete assertion-With: post-block `.value` reads the consumed halt."""
    from sugar_lift_py_tests.outcome import Completed

    exits = _route_boundary_with_binding(
        tmp_path,
        body='raise ValueError("cannot convert")',
        following='assert "cannot convert" in str(info.value)',
    )
    assert len(exits.exits) == 1
    face = exits.exits[0]
    assert isinstance(face, Completed)
    assert len(_effect_binding_facts(face)) == 3


def test_boundary_as_binding_never_reifies_a_nonmatching_halt(tmp_path):
    """Lying twin: post-block `.value` is unreachable without testimony."""
    from sugar_lift_py_tests.outcome import Halted

    exits = _route_boundary_with_binding(
        tmp_path,
        body='raise TypeError("cannot convert")',
        following='assert "cannot convert" in str(info.value)',
    )
    assert len(exits.exits) == 1
    face = exits.exits[0]
    assert isinstance(face, Halted)
    assert _effect_slot_facts(face) == ()


_CHAINED_BODY = (
    "try:\n"
    "    raise ImportError('inner')\n"
    "except ImportError:\n"
    "    raise ValueError('cannot convert')"
)


def test_boundary_as_binding_projects_authenticated_exception_context(tmp_path):
    """Truthful chained twin: the consumed raise carries its handled context.

    The boundary consumes the handler's raise, so the statement after the With
    runs (it was once dropped because the halted prefix claimed it never fell
    through). The context testimony rides the completed face.
    """
    from sugar_lift_py_tests.floor import ReturnValue, TermValue
    from sugar_lift_py_tests.outcome import Completed

    exits = _route_boundary_with_binding(
        tmp_path, body=_CHAINED_BODY, following="return 7"
    )
    completed = [face for face in exits.exits if isinstance(face, Completed)]
    assert len(completed) == 1
    assert ReturnValue(TermValue(7)) in completed[0].value.entries
    face = completed[0]
    assert len(_effect_binding_facts(face)) == 3
    context_facts = tuple(
        entry
        for entry in _effect_slot_facts(face)
        if "effect_slot_context" in str(entry.formula)
    )
    assert len(context_facts) == 1


def test_boundary_context_binding_composes_with_variable_message_predicate(tmp_path):
    """The binding survives a same-manager predicate supplied through Assign."""
    implementation = (
        "class Boundary:\n"
        "    def __init__(self, expected, match):\n"
        "        self.expected = expected\n"
        "        self.match = match\n"
        "    def __enter__(self):\n"
        "        return self\n"
        "    def __exit__(self, effect_type, effect, traceback):\n"
        "        if effect_type is None:\n"
        "            raise RuntimeError()\n"
        "        return (effect_type is self.expected) and (effect.message == self.match)\n\n"
        "def boundary(expected, match):\n"
        "    return Boundary(expected, match)\n"
    )
    from sugar_lift_py_tests.outcome import Completed

    exits = _route_boundary_with_binding(
        tmp_path,
        implementation=implementation,
        prefix="pattern = 'cannot convert'\n",
        manager="arbitrary.boundary(ValueError, match=pattern)",
        body=_CHAINED_BODY,
        following="return 7",
    )
    completed = [face for face in exits.exits if isinstance(face, Completed)]
    assert len(completed) == 1
    assert any(
        "effect_slot_context" in str(entry.formula)
        for entry in _effect_slot_facts(completed[0])
    )


def test_boundary_as_binding_context_read_after_the_with_stays_loud(tmp_path):
    """Reading `.value.__context__` after the With reaches the raised value.

    That value is the handler's ``ValueError(...)`` call, whose chaining is not
    projected yet, so the read refuses instead of inventing ``ImportError``.
    """
    from sugar_source_tree.panic import SugarNotWritten

    with pytest.raises(SugarNotWritten) as caught:
        _route_boundary_with_binding(
            tmp_path,
            body=_CHAINED_BODY,
            following="assert isinstance(info.value.__context__, ImportError)",
        )
    assert "__context__" in str(caught.value)


def test_boundary_as_binding_refuses_missing_exception_context(tmp_path):
    """Lying chained twin: no context preimage means no usable value."""
    from sugar_lift_py_tests.gap.panic import ConstructionPanic

    with pytest.raises(ConstructionPanic) as caught:
        _route_boundary_with_binding(
            tmp_path,
            body="raise ValueError('cannot convert')",
            following="assert isinstance(info.value.__context__, ImportError)",
        )
    assert caught.value.info.owner == "EffectCoordinate.attribute.__context__"
    assert "no authenticated context preimage" in caught.value.info.observed


def _effect_slot_facts(face) -> tuple:
    """Every `effect_slot_*` row this arm carries. Exact, not `>= 1`."""
    from sugar_lift_py_tests.floor.inv_value import InvValue
    from sugar_lift_py_tests.outcome import Completed

    state = face.value if isinstance(face, Completed) else face.state
    return tuple(
        entry
        for entry in (getattr(state, "entries", ()) or ())
        if isinstance(entry, InvValue) and "effect_slot" in str(entry.formula)
    )


def _effect_binding_facts(face) -> tuple:
    return tuple(
        entry
        for entry in _effect_slot_facts(face)
        if any(
            name in str(entry.formula)
            for name in ("effect_slot_kind", "effect_slot_type", "effect_slot_origin")
        )
    )


def test_boundary_as_binding_authenticates_the_slot_it_consumed(tmp_path):
    """Truthful twin: the consumed halt authenticates the observation slot."""
    from sugar_lift_py_tests.outcome import Completed

    exits = _route_boundary_with_binding(tmp_path, body='raise ValueError("boom")')
    assert len(exits.exits) == 1
    face = exits.exits[0]
    assert isinstance(face, Completed)
    # kind, type, origin -- exactly the three rows EffectBinding.to_facts owes.
    assert len(_effect_binding_facts(face)) == 3


def test_boundary_as_binding_is_absent_when_the_halt_was_restored(tmp_path):
    """Lying twin: a nonmatching halt stays halted AND authenticates nothing."""
    from sugar_lift_py_tests.outcome import Halted

    exits = _route_boundary_with_binding(tmp_path, body='raise TypeError("boom")')
    assert len(exits.exits) == 1
    face = exits.exits[0]
    assert isinstance(face, Halted)
    assert _effect_slot_facts(face) == ()


def test_boundary_as_binding_is_absent_when_the_body_completed(tmp_path):
    """Lying twin: no occurrence exists, so no `E()` may be invented for it."""
    from sugar_lift_py_tests.outcome import Halted

    exits = _route_boundary_with_binding(tmp_path, body="pass")
    assert len(exits.exits) == 1
    face = exits.exits[0]
    assert isinstance(face, Halted)
    assert type(face.effect).__name__ == "ExpectationNotMetEffect"
    assert _effect_slot_facts(face) == ()


def test_boundary_without_as_clause_authenticates_no_slot(tmp_path):
    """No `as` name, no slot: the consumed arm carries no binding testimony."""
    from sugar_lift_py_tests.outcome import Completed

    exits = _route_boundary_with_binding(
        tmp_path, body='raise ValueError("boom")', as_clause=""
    )
    face = exits.exits[0]
    assert isinstance(face, Completed)
    assert _effect_slot_facts(face) == ()


def test_as_binding_requires_a_contract_that_declares_one(tmp_path):
    """A slot is granted by the CONTRACT, never by the `as` spelling.

    The same source with the same name stays loud when the authenticated
    semantics carry `NoBindingV1` -- otherwise syntax would be handing the
    body a projection the manager never agreed to provide.
    """
    from dataclasses import replace

    from sugar_lift_py_tests.context_manager_contract import NoBindingV1
    from sugar_source_tree.panic import UnsupportedWithBindingTarget

    distribution = _distribution(
        tmp_path, _BOUNDARY_IMPLEMENTATION, exported="boundary"
    )
    consumer = (
        "import arbitrary\n"
        "def use_boundary():\n"
        "    with arbitrary.boundary(ValueError) as info:\n"
        '        raise ValueError("boom")\n'
    )
    path = tmp_path / "consumer.py"
    path.write_text(consumer, encoding="utf-8")
    from sugar_lift_py_tests.context_manager_resolution import TreeConstructionContextV1

    context = TreeConstructionContextV1.for_source_call_construction()
    tree = SourceFile(
        (consumer, str(path), blake3_512_of(consumer.encode("utf-8"))),
        construction_context=context,
    )
    populate_source_derived_resource_refs(
        tree,
        root=tmp_path,
        path=path,
        distribution_index={"arbitrary": distribution},
        session=SourceResolutionSession(
            enrolled_distributions=frozenset({distribution.metadata["Name"]})
        ),
    )
    refs = context.source_derived_contract_refs
    coordinate, reference = next(iter(refs.items()))
    refs[coordinate] = replace(
        reference, semantics=replace(reference.semantics, binding=NoBindingV1())
    )

    with pytest.raises(UnsupportedWithBindingTarget):
        next(node for node in tree.nodes() if node.kind == "With").sugar()


# --- computed exception class paths (Attribute / import identity) ------------
#
# ``raises(pkg.Error)`` is an Attribute path, not a bare Name. Construction
# projects the import identity without re-entering AttributeSugar on a
# SymbolicValue module receiver. A factory() call stays typed opaque.


_ATTRIBUTE_EXCEPTION_BOUNDARY = (
    "class Boundary:\n"
    "    def __init__(self, expected, match=None):\n"
    "        self.expected = expected\n"
    "        self.match = match\n"
    "    def __enter__(self):\n"
    "        return self\n"
    "    def __exit__(self, effect_type, effect, traceback):\n"
    "        if effect_type is None:\n"
    "            raise RuntimeError()\n"
    "        return effect_type is self.expected\n\n"
    "def boundary(expected, match=None):\n"
    "    return Boundary(expected, match)\n\n"
    "class MyError(Exception):\n"
    "    pass\n"
)

# Exit must mention the message formal for match= to derive; keep it separate
# so the type-only Attribute path stays a single-predicate derivation.
_ATTRIBUTE_EXCEPTION_BOUNDARY_WITH_MATCH = (
    "class Boundary:\n"
    "    def __init__(self, expected, match=None):\n"
    "        self.expected = expected\n"
    "        self.match = match\n"
    "    def __enter__(self):\n"
    "        return self\n"
    "    def __exit__(self, effect_type, effect, traceback):\n"
    "        if effect_type is None:\n"
    "            raise RuntimeError()\n"
    "        return (effect_type is self.expected) and (\n"
    "            effect.message == self.match\n"
    "        )\n\n"
    "def boundary(expected, match=None):\n"
    "    return Boundary(expected, match)\n\n"
    "class MyError(Exception):\n"
    "    pass\n"
)


def _attribute_exception_tree(
    tmp_path,
    *,
    manager: str,
    body: str,
    as_clause: str = "",
    implementation: str = _ATTRIBUTE_EXCEPTION_BOUNDARY,
):
    tmp_path = Path(tmp_path)
    tmp_path.mkdir(parents=True, exist_ok=True)
    distribution = _distribution(tmp_path, implementation, exported="boundary")
    (tmp_path / "arbitrary" / "__init__.py").write_text(
        "from arbitrary.manager import boundary, MyError\n",
        encoding="utf-8",
    )
    consumer = (
        "import arbitrary\n"
        "def use_boundary():\n"
        f"    with {manager}{as_clause}:\n"
        f"{textwrap.indent(textwrap.dedent(body), '        ')}\n"
    )
    path = tmp_path / "consumer.py"
    path.write_text(consumer, encoding="utf-8")
    from sugar_lift_py_tests.context_manager_resolution import TreeConstructionContextV1

    context = TreeConstructionContextV1.for_source_call_construction()
    tree = SourceFile(
        (consumer, str(path), blake3_512_of(consumer.encode("utf-8"))),
        construction_context=context,
    )
    populate_source_derived_resource_refs(
        tree,
        root=tmp_path,
        path=path,
        distribution_index={"arbitrary": distribution},
        session=SourceResolutionSession(
            enrolled_distributions=frozenset({distribution.metadata["Name"]})
        ),
    )
    return tree, context


def test_attribute_exception_class_path_constructs_effect_boundary(tmp_path):
    """Truthful twin: ``boundary(arbitrary.MyError)`` is EffectBoundary, not gap."""
    from sugar_lift_py_tests.sugar.with_effect_boundary_sugar import (
        WithEffectBoundarySugar,
    )

    tree, context = _attribute_exception_tree(
        tmp_path,
        manager="arbitrary.boundary(arbitrary.MyError)",
        body='raise arbitrary.MyError("boom")',
    )
    assert len(context.source_derived_contract_refs) == 1
    sugar = next(node for node in tree.nodes() if node.kind == "With").sugar()
    assert isinstance(sugar, WithEffectBoundarySugar)


def _construction_halts(exits):
    """Split off ``arbitrary.MyError(...)``'s own may-raise construction arm.

    Constructing a source-defined class runs its unprojected ``__init__``, so
    ``raise arbitrary.MyError("boom")`` first halts with an
    ``UndeterminedRaiseEffect`` under the complement of
    ``python:source_construction.completes``; the boundary sees the raise only
    on the completing arm. Returns (construction halts, the remaining faces).
    """
    from sugar_lift_py_tests.effect.raise_effect import UndeterminedRaiseEffect
    from sugar_lift_py_tests.outcome import Halted

    construction = [
        face
        for face in exits.exits
        if isinstance(face, Halted)
        and isinstance(face.effect, UndeterminedRaiseEffect)
        and (face.effect.producer_node_owner or "").startswith(
            "UnprojectedSourceConstruction:"
        )
    ]
    rest = [face for face in exits.exits if face not in construction]
    assert len(construction) == 1
    assert "python:source_construction.completes" in repr(construction[0].guard)
    for face in rest:
        assert "python:source_construction.completes" in repr(face.guard)
    return construction, rest


def test_attribute_exception_class_path_consumes_matching_raise(tmp_path):
    """Attribute expected type and Attribute raise share one import identity."""
    from sugar_lift_py_tests.outcome import Completed, outcome_to_exitset

    tree, _context = _attribute_exception_tree(
        tmp_path,
        manager="arbitrary.boundary(arbitrary.MyError)",
        body='raise arbitrary.MyError("boom")',
    )
    exits = outcome_to_exitset(
        next(node for node in tree.nodes() if node.kind == "With").sugar().desugar()
    )
    _construction, rest = _construction_halts(exits)
    assert len(rest) == 1
    assert isinstance(rest[0], Completed)


def test_attribute_exception_class_path_restores_wrong_raise(tmp_path):
    """Lying twin: the wrong type is never consumed by a borrowed identity.

    ``arbitrary.MyError`` reaches the boundary as an ``import`` coordinate: a
    PATH, not a class. Nothing testified which class it names, and an import
    path can alias a builtin (``socket.error is OSError``), so ``raise
    ValueError`` against it is not a decided miss. The ValueError halt is
    restored, still red, under the complement of the retained type test; it is
    consumed only under that test.
    """
    from sugar_lift_py_tests.effect.raise_effect import RaiseEffect
    from sugar_lift_py_tests.outcome import Completed, Halted, outcome_to_exitset

    tree, _context = _attribute_exception_tree(
        tmp_path,
        manager="arbitrary.boundary(arbitrary.MyError)",
        body='raise ValueError("boom")',
    )
    exits = outcome_to_exitset(
        next(node for node in tree.nodes() if node.kind == "With").sugar().desugar()
    )
    halted = [face for face in exits.exits if isinstance(face, Halted)]
    consumed = [face for face in exits.exits if isinstance(face, Completed)]
    assert len(halted) == 1 and len(consumed) == 1
    face = halted[0]
    assert isinstance(face.effect, RaiseEffect)
    assert face.effect.exception_name == "ValueError"
    assert "adt.is_python_type" in repr(consumed[0].guard)
    assert getattr(face.guard, "kind", None) == "not"


def test_attribute_exception_class_with_match_consumes_and_misses(tmp_path):
    """Attribute class path + match= predicate: hit completes, miss restores.

    Regex empty-pattern / alternation semantics are pinned at the ExitSet
    consumer. Here the manager derives an exact message formal so the
    Attribute class path is exercised end-to-end with a message obligation.
    """
    from sugar_lift_py_tests.outcome import Completed, Halted, outcome_to_exitset

    tree, _context = _attribute_exception_tree(
        tmp_path / "match-hit",
        manager='arbitrary.boundary(arbitrary.MyError, match="boom")',
        body='raise arbitrary.MyError("boom")',
        implementation=_ATTRIBUTE_EXCEPTION_BOUNDARY_WITH_MATCH,
    )
    exits = outcome_to_exitset(
        next(node for node in tree.nodes() if node.kind == "With").sugar().desugar()
    )
    _construction, rest = _construction_halts(exits)
    assert len(rest) == 1
    assert isinstance(rest[0], Completed)

    tree, _context = _attribute_exception_tree(
        tmp_path / "match-miss",
        manager='arbitrary.boundary(arbitrary.MyError, match="boom")',
        body='raise arbitrary.MyError("other")',
        implementation=_ATTRIBUTE_EXCEPTION_BOUNDARY_WITH_MATCH,
    )
    exits = outcome_to_exitset(
        next(node for node in tree.nodes() if node.kind == "With").sugar().desugar()
    )
    _construction, rest = _construction_halts(exits)
    assert len(rest) == 1
    assert isinstance(rest[0], Halted)


def test_attribute_exception_class_as_binding_projects_consumed_effect(tmp_path):
    """``as info`` on an Attribute class path authenticates the observation slot."""
    from sugar_lift_py_tests.outcome import Completed, outcome_to_exitset

    tree, _context = _attribute_exception_tree(
        tmp_path,
        manager="arbitrary.boundary(arbitrary.MyError)",
        body='raise arbitrary.MyError("boom")',
        as_clause=" as info",
    )
    exits = outcome_to_exitset(
        next(node for node in tree.nodes() if node.kind == "With").sugar().desugar()
    )
    _construction, rest = _construction_halts(exits)
    assert len(rest) == 1
    face = rest[0]
    assert isinstance(face, Completed)
    assert len(_effect_binding_facts(face)) == 3


def test_computed_exception_class_factory_stays_typed_opaque(tmp_path):
    """Lying twin: ``boundary(factory())`` cannot borrow Attribute-path proof."""
    from sugar_source_tree.panic import SugarNotWritten

    distribution = _distribution(
        tmp_path,
        _ATTRIBUTE_EXCEPTION_BOUNDARY + "def factory():\n    return MyError\n",
        exported="boundary",
    )
    (tmp_path / "arbitrary" / "__init__.py").write_text(
        "from arbitrary.manager import boundary, MyError, factory\n",
        encoding="utf-8",
    )
    consumer = (
        "import arbitrary\n"
        "def use_boundary():\n"
        "    with arbitrary.boundary(arbitrary.factory()):\n"
        "        raise arbitrary.MyError('boom')\n"
    )
    path = tmp_path / "consumer.py"
    path.write_text(consumer, encoding="utf-8")
    from sugar_lift_py_tests.context_manager_resolution import TreeConstructionContextV1

    context = TreeConstructionContextV1.for_source_call_construction()
    tree = SourceFile(
        (consumer, str(path), blake3_512_of(consumer.encode("utf-8"))),
        construction_context=context,
    )
    populate_source_derived_resource_refs(
        tree,
        root=tmp_path,
        path=path,
        distribution_index={"arbitrary": distribution},
        session=SourceResolutionSession(
            enrolled_distributions=frozenset({distribution.metadata["Name"]})
        ),
    )
    with_node = next(node for node in tree.nodes() if node.kind == "With")
    # Either preconstruction refuses the call actual, or With stays force-floor /
    # resolution-gap. Never silently constructs EffectBoundary without identity.
    try:
        sugar = with_node.sugar()
    except Exception as caught:
        assert type(caught).__name__ in {
            "SugarNotWritten",
            "ContextManagerResolutionConstructionGap",
            "SugarNotWritten",
        }, type(caught).__name__
        return
    from sugar_lift_py_tests.sugar.with_effect_boundary_sugar import (
        WithEffectBoundarySugar,
    )

    # If sugar constructs, desugar must not consume via a fabricated identity.
    if isinstance(sugar, WithEffectBoundarySugar):
        from sugar_lift_py_tests.outcome import Halted, outcome_to_exitset

        exits = outcome_to_exitset(sugar.desugar())
        # Without authenticated expected type, match is retained or restored —
        # never a sole Completed face claiming a decided identity match.
        assert not (
            len(exits.exits) == 1 and type(exits.exits[0]).__name__ == "Completed"
        )


@pytest.mark.parametrize(
    "class_name, selector", [("First", "payload"), ("Other", "renamed")]
)
def test_constructor_snapshot_partition_keeps_each_branch_value(
    tmp_path, class_name, selector
):
    graph, resolved, actual, call_site = _resolved(
        tmp_path,
        f"class {class_name}:\n"
        "    def __init__(self, marker):\n"
        "        self.prefix = marker\n"
        "        if marker:\n"
        f"            self.{selector} = 11\n"
        "        else:\n"
        f"            self.{selector} = 19\n\n"
        "    def __enter__(self):\n"
        f"        return self.{selector}\n\n"
        "    def __exit__(self, effect_type, effect, traceback):\n"
        "        return False\n\n"
        "def make_guard(marker):\n"
        f"    return {class_name}(marker)\n",
    )
    from sugar_lift_py_tests.floor import (
        ReceiverStatePartitionValue,
        ReturnValue,
        SymbolicValue,
        TermValue,
    )
    from sugar_lift_py_tests.ir import _term_content_cid, make_var
    from sugar_lift_py_tests.outcome import Completed, outcome_to_exitset

    symbolic = SymbolicValue(make_var("constructor-selector"))
    actual = ConstructedCallActualV1(
        actual.node,
        symbolic,
        ConstructedValueTestimonyV1.mint(
            actual.node.fragment, _term_content_cid(symbolic.to_term(owner="test"))
        ),
    )
    behavior = construct_manager_behavior(
        resolved, graph=graph, actuals=(actual,), call_site=call_site
    )
    assert isinstance(behavior, ConstructedManagerBehaviorV1)
    assert isinstance(behavior.receiver_state, ReceiverStatePartitionValue)
    completed = tuple(
        face
        for face in behavior.receiver_state.exits.exits
        if isinstance(face, Completed)
    )
    assert len(completed) == 2
    assert {face.value.attribute(selector, "test").value for face in completed} == {
        TermValue(11),
        TermValue(19),
    }
    assert all(
        face.value.attribute("prefix", "test").value == symbolic for face in completed
    )
    from sugar_lift_py_tests.outcome.exit_set import complement_guard

    by_value = {
        face.value.attribute(selector, "test").value.value: face for face in completed
    }
    assert by_value[19].guard.kind == "not"
    assert by_value[11].guard == complement_guard(by_value[19].guard)
    protocol = construct_manager_protocol(behavior, exit_face_id="constructor-values")
    assert isinstance(protocol, ConstructedManagerProtocolV1)
    entered = outcome_to_exitset(protocol.enter_resource_outcome()).exits
    assert len(entered) == 2 and all(isinstance(face, Completed) for face in entered)
    assert {face.value.enter_value.statements[-1] for face in entered} == {
        ReturnValue(TermValue(11)),
        ReturnValue(TermValue(19)),
    }


# Concrete counterexample for argument-only Expects-Raise sealing. The native
# entry call is valid Python but has no enrolled Python body for construction.
_NONSUPPRESSING_NATIVE_ENTRY = (
    "from _thread import get_ident\n"
    "class Boundary:\n"
    "    def __init__(self, expected):\n"
    "        self.expected = expected\n"
    "    def __enter__(self):\n"
    "        return get_ident()\n"
    "    def __exit__(self, effect_type, effect, traceback):\n"
    "        return False\n"
    "def boundary(expected):\n"
    "    return Boundary(expected)\n"
    "class MyError(Exception):\n"
    "    pass\n"
)


_DOTTED_TUPLE_RESOURCE = (
    "class Boundary:\n"
    "    def __init__(self, payload):\n"
    "        self.payload = payload\n"
    "    def __enter__(self):\n"
    "        return self\n"
    "    def __exit__(self, effect_type, effect, traceback):\n"
    "        return False\n\n"
    "def boundary(payload):\n"
    "    return Boundary(payload)\n\n"
    "class MyError(Exception):\n"
    "    pass\n"
)


@pytest.mark.parametrize("body", ["pass", "raise ValueError('must escape')"])
def test_exception_argument_cannot_turn_nonsuppressing_manager_into_assertion(
    tmp_path, body
):
    from sugar_lift_py_tests.context_manager_contract import ProtocolResourceSemanticsV1
    from sugar_lift_py_tests.context_manager_resolution import (
        ContextManagerResolutionGapV1,
        SourceDerivedContextManagerRefV1,
    )
    from sugar_lift_py_tests.effect import RaiseEffect
    from sugar_lift_py_tests.outcome import Completed, Halted, outcome_to_exitset

    # Truthful native twin: returning normally does not require an exception.
    # Lying seal twin: supplying ValueError does not license suppressing one.
    namespace = {}
    exec(_NONSUPPRESSING_NATIVE_ENTRY, namespace)
    if body == "pass":
        with namespace["boundary"](ValueError):
            pass
    else:
        with pytest.raises(ValueError, match="must escape"):
            with namespace["boundary"](ValueError):
                raise ValueError("must escape")

    tree, context = _attribute_exception_tree(
        tmp_path,
        manager="arbitrary.boundary(ValueError)",
        body=body,
        implementation=_NONSUPPRESSING_NATIVE_ENTRY,
    )
    reference = next(iter(context.source_derived_contract_refs.values()))
    if isinstance(reference, ContextManagerResolutionGapV1):
        # An unconstructed native entry remains an honest typed construction
        # gap, never a fabricated suppression/expected-raise theorem.
        from sugar_source_tree.panic import ContextManagerResolutionConstructionGap

        with pytest.raises(ContextManagerResolutionConstructionGap):
            next(node for node in tree.nodes() if node.kind == "With").sugar()
        return
    assert isinstance(reference, SourceDerivedContextManagerRefV1)
    boundary = next(node for node in tree.nodes() if node.kind == "With").sugar()
    exits = outcome_to_exitset(boundary.desugar()).exits
    if body == "pass":
        assert any(
            isinstance(face, Completed) and face.value.can_fall_through
            for face in exits
        ), exits
        # The only halts are the enter's call to get_ident, which is not
        # bridged and may raise anything; the ValueError actual never becomes
        # an expected raise.
        from sugar_lift_py_tests.effect import UndeterminedRaiseEffect

        for face in exits:
            if isinstance(face, Halted):
                assert isinstance(face.effect, UndeterminedRaiseEffect), face
                assert not face.effect.producer_node_owner.startswith(
                    "LanguageOwned"
                ), face
    else:
        assert any(
            isinstance(face, Halted)
            and isinstance(face.effect, RaiseEffect)
            and face.effect.exception_name == "ValueError"
            for face in exits
        ), exits
        assert not any(
            isinstance(face, Completed) and face.value.can_fall_through
            for face in exits
        ), exits
    assert isinstance(reference.semantics, ProtocolResourceSemanticsV1)



def _deferred_exit_message_comparison(expression='effect.message == "needle"'):
    from sugar_lift_py_tests.context.reduce_context import ReduceContext
    from sugar_lift_py_tests.context_manager_resolution import TreeConstructionContextV1
    from sugar_lift_py_tests.floor.manager_coordinate import ExitValueCoordinate
    from sugar_lift_py_tests.temporal import builtin_name_temporal

    source = expression + "\n"
    tree = SourceFile(
        (source, "deferred-exit.py", blake3_512_of(source.encode())),
        construction_context=TreeConstructionContextV1.for_test_without_workspace(),
    )
    comparison = next(node for node in tree.nodes() if node.kind == "Compare")
    coordinate = ExitValueCoordinate("actual-exit-face")
    ctx = ReduceContext(
        temporal=builtin_name_temporal().bind_value("effect", coordinate)
    )
    return coordinate, comparison.sugar().desugar(ctx), comparison.fragment


@pytest.mark.parametrize("message", ["needle", "haystack"])
def test_exit_attribute_comparison_waits_for_actual_receiver_fields(message):
    from sugar_lift_py_tests.caller_parameter_contract import (
        NativeOperationExitCarrierV1,
    )
    from sugar_lift_py_tests.floor import ObjectField, ObjectValue, StringValue
    from sugar_lift_py_tests.outcome import Completed

    coordinate, deferred, site = _deferred_exit_message_comparison()
    assert isinstance(deferred, NativeOperationExitCarrierV1)
    assert deferred.demand.operator == "attribute_named"
    receiver = ObjectValue(
        "Error",
        (ObjectField("message", StringValue(message)),),
        identity="raised-error",
    )
    result = deferred.discharge({coordinate.coordinate_cid: receiver})
    expected = StringValue(message).equals(StringValue("needle"), site).value
    assert result.exits
    assert all(
        isinstance(face, Completed) and face.value.formula == expected.formula
        for face in result.exits
    )


@pytest.mark.parametrize(
    "getter", ['return "needle"', 'return "haystack"', 'raise LookupError("getter")']
)
def test_deferred_exit_attribute_runs_authenticated_property_before_comparison(
    tmp_path, getter
):
    from sugar_lift_py_tests.caller_parameter_contract import (
        NativeOperationExitCarrierV1,
    )
    from sugar_lift_py_tests.outcome import Completed, Halted
    from sugar_lift_py_tests.effect import RaiseEffect

    source = (
        "class Payload:\n"
        "    def __init__(self, marker):\n"
        "        self.marker = marker\n"
        "    def __enter__(self):\n"
        "        return self\n"
        "    def __exit__(self, *args):\n"
        "        return False\n"
        "    @property\n"
        "    def message(self):\n"
        f"        {getter}\n"
        "def make_guard(marker):\n"
        "    return Payload(marker)\n"
    )
    native = {}
    exec(source, native)
    if getter.startswith("raise"):
        with pytest.raises(LookupError, match="getter"):
            native["Payload"](23).message == "needle"
    else:
        assert (native["Payload"](23).message == "needle") is (
            getter == 'return "needle"'
        )
    graph, resolved, actual, call_site = _resolved(tmp_path, source)
    behavior = construct_manager_behavior(
        resolved, graph=graph, actuals=(actual,), call_site=call_site
    )
    assert isinstance(behavior, ConstructedManagerBehaviorV1)
    coordinate, deferred, site = _deferred_exit_message_comparison()
    assert isinstance(deferred, NativeOperationExitCarrierV1)
    result = deferred.discharge({coordinate.coordinate_cid: behavior.receiver_state})
    assert result.exits
    if getter.startswith("raise"):
        assert all(
            isinstance(face, Halted)
            and isinstance(face.effect, RaiseEffect)
            and face.effect.exception_name == "LookupError"
            for face in result.exits
        )
        assert all(
            face.effect.exception_type_coordinate is not None
            and face.effect.occurrence is not None
            for face in result.exits
        )
    else:
        from sugar_lift_py_tests.floor import StringValue

        message = "needle" if getter == 'return "needle"' else "haystack"
        expected = StringValue(message).equals(StringValue("needle"), site).value
        assert all(
            isinstance(face, Completed) and face.value.formula == expected.formula
            for face in result.exits
        )


def test_deferred_exit_projection_cannot_be_consumed_as_a_completed_outcome():
    from sugar_lift_py_tests.gap import ConstructionPanic, GapKind, GapLocus
    from sugar_lift_py_tests.outcome import outcome_to_exitset

    _, deferred, _ = _deferred_exit_message_comparison()
    with pytest.raises(ConstructionPanic) as caught:
        outcome_to_exitset(deferred)
    assert caught.value.info.owner == "outcome_to_exitset"
    assert caught.value.info.gap_kind is GapKind.FLOOR
    assert caught.value.info.gap_locus is GapLocus.CONSTRUCTION


def test_deferred_exit_projection_requires_its_own_actual_face():
    from sugar_lift_py_tests.floor import ObjectField, ObjectValue, StringValue
    from sugar_lift_py_tests.floor.manager_coordinate import ExitValueCoordinate
    from sugar_source_tree.panic import SugarNotWritten

    coordinate, deferred, _ = _deferred_exit_message_comparison()
    wrong = ExitValueCoordinate("a-different-exit-face")
    assert coordinate.coordinate_cid != wrong.coordinate_cid
    receiver = ObjectValue(
        "Error",
        (ObjectField("message", StringValue("needle")),),
        identity="another-error",
    )
    with pytest.raises(SugarNotWritten) as caught:
        deferred.discharge({wrong.coordinate_cid: receiver})
    assert caught.value.owner == "NativeOperationResolutionV1.project"


def test_deferred_exit_projection_does_not_authenticate_unknown_message_equality():
    from sugar_lift_py_tests.floor import ObjectField, ObjectValue, SymbolicValue
    from sugar_lift_py_tests.ir import make_var

    coordinate, deferred, _ = _deferred_exit_message_comparison()
    receiver = ObjectValue(
        "Error",
        (ObjectField("message", SymbolicValue(make_var("unknown-payload"))),),
        identity="raised-error",
    )
    # An unknown payload's ``__eq__`` is undecided dispatch: the predicate is
    # never authenticated as a total completion.  It completes only under the
    # opaque ``python:compare.completes`` atom and halts undetermined (no
    # invented exception type) under the complement -- the #7585 two faces.
    from sugar_lift_py_tests.effect.raise_effect import UndeterminedRaiseEffect
    from sugar_lift_py_tests.outcome import Completed, Halted, outcome_to_exitset

    exits = outcome_to_exitset(
        deferred.discharge({coordinate.coordinate_cid: receiver})
    ).exits
    (completed,) = [face for face in exits if isinstance(face, Completed)]
    (halted,) = [face for face in exits if isinstance(face, Halted)]
    assert completed.guard.name == "python:compare.completes"
    assert completed.value.formula.name == "py.eq"
    assert completed.value.formula.args[0] == make_var("unknown-payload")
    assert isinstance(halted.effect, UndeterminedRaiseEffect)
    assert halted.effect.exception_name is None
    assert halted.effect.producer_node_owner == "UndecidedCompare:Eq"


@pytest.mark.parametrize(
    "eq_body", ["return True", "return False", 'raise LookupError("equality")']
)
@pytest.mark.parametrize("operator", ["==", "!="])
def test_deferred_exit_payload_uses_authenticated_rich_equality(
    tmp_path, eq_body, operator
):
    from sugar_lift_py_tests.floor import ObjectField, ObjectValue
    from sugar_lift_py_tests.outcome import Completed, Halted
    from sugar_lift_py_tests.effect import RaiseEffect

    import operator as native_operator

    compare = native_operator.eq if operator == "==" else native_operator.ne
    payload_class, payload = _source_equality_payload(tmp_path, eq_body)
    if eq_body.startswith("raise"):
        with pytest.raises(LookupError, match="equality"):
            compare(payload_class(23), "needle")
    else:
        assert compare(payload_class(23), "needle") is (
            (eq_body == "return True") == (operator == "==")
        )
    coordinate, deferred, _ = _deferred_exit_message_comparison(
        f'effect.message {operator} "needle"'
    )
    error = ObjectValue(
        "Error", (ObjectField("message", payload),), identity="raised-error"
    )
    result = deferred.discharge({coordinate.coordinate_cid: error})
    assert result.exits
    if eq_body.startswith("raise"):
        assert all(
            isinstance(face, Halted)
            and isinstance(face.effect, RaiseEffect)
            and face.effect.exception_name == "LookupError"
            for face in result.exits
        )
    else:
        from sugar_lift_py_tests.sugar.true_bool_literal_sugar import (
            TrueBoolLiteralSugar,
        )
        from sugar_lift_py_tests.sugar.false_bool_literal_sugar import (
            FalseBoolLiteralSugar,
        )

        expected = (
            TrueBoolLiteralSugar
            if ((eq_body == "return True") == (operator == "=="))
            else FalseBoolLiteralSugar
        )
        assert all(
            isinstance(face, Completed) and isinstance(face.value, expected)
            for face in result.exits
        )


def _source_equality_payload(tmp_path, eq_body, ne_body=None):
    source = (
        "class Payload:\n"
        "    def __init__(self, marker):\n"
        "        self.marker = marker\n"
        "    def __enter__(self):\n"
        "        return self\n"
        "    def __exit__(self, *args):\n"
        "        return False\n"
        "    def __eq__(self, other):\n"
        f"        {eq_body}\n"
        "def make_guard(marker):\n"
        "    return Payload(marker)\n"
    )
    if ne_body is not None:
        source = source.replace(
            "def make_guard",
            "    def __ne__(self, other):\n        " + ne_body + "\ndef make_guard",
        )
    native = {}
    exec(source, native)
    graph, resolved, actual, call_site = _resolved(tmp_path, source)
    behavior = construct_manager_behavior(
        resolved, graph=graph, actuals=(actual,), call_site=call_site
    )
    assert isinstance(behavior, ConstructedManagerBehaviorV1)
    return native["Payload"], behavior.receiver_state


@pytest.mark.parametrize(
    "expression,eq_body,ne_body",
    [
        ('"needle" == effect.message', "return True", None),
        ('effect.message == "needle"', 'return "not a boolean"', None),
        ('effect.message == "needle"', "self.marker = 99\n        return True", None),
        ('effect.message != "needle"', "return True", "return True"),
    ],
)
def test_deferred_rich_equality_refuses_unconstructed_dispatch_faces(
    tmp_path, expression, eq_body, ne_body
):
    from sugar_lift_py_tests.floor import ObjectField, ObjectValue
    from sugar_lift_py_tests.gap import ConstructionPanic

    _, payload = _source_equality_payload(tmp_path, eq_body, ne_body)
    coordinate, deferred, _ = _deferred_exit_message_comparison(expression)
    error = ObjectValue(
        "Error", (ObjectField("message", payload),), identity="raised-error"
    )
    with pytest.raises(ConstructionPanic):
        deferred.discharge({coordinate.coordinate_cid: error})


@pytest.mark.parametrize("case", ["needle", "haystack", "raising-payload"])
def test_source_manager_protocol_defers_exit_lookup_until_actual_value(tmp_path, case):
    from sugar_lift_py_tests.caller_parameter_contract import (
        NativeOperationExitCarrierV1,
    )
    from sugar_lift_py_tests.floor import (
        BlockValue,
        ObjectField,
        ObjectValue,
        ReturnValue,
        StringValue,
    )
    from sugar_lift_py_tests.floor.manager_coordinate import ExitValueCoordinate
    from sugar_lift_py_tests.outcome import Completed, Halted
    from sugar_lift_py_tests.effect import RaiseEffect

    (tmp_path / "manager").mkdir()
    (tmp_path / "payload").mkdir()
    graph, resolved, actual, call_site = _resolved(
        tmp_path / "manager",
        "class Resource:\n"
        "    def __init__(self, marker):\n"
        "        self.marker = marker\n"
        "    def __enter__(self):\n"
        "        return self\n"
        "    def __exit__(self, effect_type, effect, traceback):\n"
        '        return effect.message == "needle"\n'
        "def make_guard(marker):\n"
        "    return Resource(marker)\n",
    )
    behavior = construct_manager_behavior(
        resolved, graph=graph, actuals=(actual,), call_site=call_site
    )
    protocol = construct_manager_protocol(
        behavior, exit_face_id="deferred-protocol-face"
    )
    assert isinstance(protocol, ConstructedManagerProtocolV1)
    deferred = protocol.exit_outcome()
    assert isinstance(deferred, NativeOperationExitCarrierV1)
    if case == "raising-payload":
        _, payload = _source_equality_payload(
            tmp_path / "payload", 'raise LookupError("equality")'
        )
    else:
        payload = StringValue(case)
    receiver = ObjectValue(
        "Error", (ObjectField("message", payload),), identity="raised-error"
    )
    coordinate = ExitValueCoordinate(protocol.exit_face_id)
    result = deferred.discharge({coordinate.coordinate_cid: receiver})
    assert result.exits
    if case == "raising-payload":
        assert all(
            isinstance(face, Halted)
            and isinstance(face.effect, RaiseEffect)
            and face.effect.exception_name == "LookupError"
            for face in result.exits
        )
    else:
        expected = StringValue(case).equals(StringValue("needle"), call_site).value
        for face in result.exits:
            assert isinstance(face, Completed)
            assert isinstance(face.value, BlockValue)
            assert isinstance(face.value.statements[-1], ReturnValue)
            assert face.value.statements[-1].value.formula == expected.formula


@pytest.mark.parametrize("parameter", ["payload", "expected"])
@pytest.mark.parametrize("keyword", [False, True])
def test_dotted_tuple_preconstruction_preserves_member_testimony_and_resource_contract(
    tmp_path, parameter, keyword
):
    """Tuple members take the scalar construction door before frame binding."""
    from sugar_lift_py_tests.context_manager_contract import (
        NeverSuppressesDispositionV1,
        ProtocolResourceSemanticsV1,
    )
    from sugar_lift_py_tests.context_manager_resolution import (
        SourceDerivedContextManagerRefV1,
    )
    from sugar_lift_py_tests.floor.authenticated_exception_type_value import (
        AuthenticatedExceptionTypeValue,
    )
    from sugar_lift_py_tests.floor.tuple_value import TupleValue
    from sugar_lift_py_tests.ir import ctor, str_const
    from sugar_lift_py_tests.outcome import Complete
    from sugar_lift_py_tests.sugar.with_source_resource_sugar import (
        WithSourceResourceSugar,
    )

    argument = "(ValueError, arbitrary.MyError)"
    if keyword:
        argument = f"{parameter}={argument}"
    tree, context = _attribute_exception_tree(
        tmp_path,
        manager=f"arbitrary.boundary({argument})",
        body="pass",
        implementation=_DOTTED_TUPLE_RESOURCE.replace("payload", parameter),
    )
    reference = next(iter(context.source_derived_contract_refs.values()))
    assert isinstance(reference, SourceDerivedContextManagerRefV1)
    assert isinstance(reference.semantics, ProtocolResourceSemanticsV1)
    assert isinstance(
        reference.semantics.exit.disposition, NeverSuppressesDispositionV1
    )
    # A type operand does not turn a nonsuppressing resource into Expects-Raise.
    assert isinstance(
        next(n for n in tree.nodes() if n.kind == "With").sugar(),
        WithSourceResourceSugar,
    )
    projected = reference.protocol.receiver_state.attribute(
        parameter, "tuple-preconstruction"
    )
    assert isinstance(projected, Complete)
    assert isinstance(projected.value, TupleValue)
    assert len(projected.value.elements) == 2
    member = projected.value.elements[1]
    assert isinstance(member, AuthenticatedExceptionTypeValue)
    assert member.exception_type_identity() == ctor(
        "python:exception_type_identity",
        [str_const("import"), str_const("arbitrary.manager.MyError")],
    )
    assert member.class_value is not None
    assert member.exception_type_mro() is not None


def test_dotted_tuple_preconstruction_keeps_missing_provider_member_loud(tmp_path):
    from sugar_source_tree.panic import UnattributableRefusal

    with pytest.raises(UnattributableRefusal) as caught:
        _attribute_exception_tree(
            tmp_path,
            manager="arbitrary.boundary((ValueError, arbitrary.MissingError))",
            body="pass",
            implementation=_DOTTED_TUPLE_RESOURCE,
        )
    assert caught.value.owner == "provider_exception_type_construction"


@pytest.mark.parametrize("keyword", [False, True])
@pytest.mark.parametrize("tuple_operand", [False, True])
@pytest.mark.parametrize("body", ["pass", 'raise ValueError("boom")'])
def test_authenticated_resource_actuals_reduce_without_raw_module_attributes(
    tmp_path, keyword, tuple_operand, body
):
    from sugar_lift_py_tests.effect import RaiseEffect
    from sugar_lift_py_tests.outcome import Completed, Halted, outcome_to_exitset

    argument = (
        "(ValueError, arbitrary.MyError)" if tuple_operand else "arbitrary.MyError"
    )
    if keyword:
        argument = f"payload={argument}"
    tree, _ = _attribute_exception_tree(
        tmp_path,
        manager=f"arbitrary.boundary({argument})",
        body=body,
        implementation=_DOTTED_TUPLE_RESOURCE,
    )
    boundary = next(n for n in tree.nodes() if n.kind == "With").sugar()
    exits = outcome_to_exitset(boundary.desugar()).exits
    if body == "pass":
        assert len(exits) == 1
        assert isinstance(exits[0], Completed)
        assert exits[0].value.can_fall_through
    else:
        halts = [face for face in exits if isinstance(face, Halted)]
        assert len(halts) == 1
        assert isinstance(halts[0].effect, RaiseEffect)
        assert halts[0].effect.exception_name == "ValueError"
        # Resource binding facts may ride a companion terminal residue. It
        # must never become an executable completion that swallows the raise.
        assert all(
            isinstance(face, Halted) or not face.value.can_fall_through
            for face in exits
        )


@pytest.mark.parametrize("runtime_value", [7, 19])
def test_resource_actual_construction_reads_current_context_not_preconstruction_values(
    tmp_path, runtime_value
):
    from sugar_lift_py_tests.context.reduce_context import ReduceContext
    from sugar_lift_py_tests.floor import ObjectValue, TermValue
    from sugar_lift_py_tests.outcome import Completed, outcome_to_exitset
    from sugar_lift_py_tests.sugar.with_source_resource_sugar import (
        _project_manager_receiver,
    )
    from sugar_lift_py_tests.temporal import builtin_name_temporal

    tree, context = _attribute_exception_tree(
        tmp_path,
        manager="arbitrary.boundary((arbitrary.MyError, runtime))",
        body="pass",
        implementation=_DOTTED_TUPLE_RESOURCE,
    )
    reference = next(iter(context.source_derived_contract_refs.values()))
    previous = reference.protocol.receiver_state.attribute("payload", "test").value
    assert previous.elements[1].to_term(owner="test") != TermValue(
        runtime_value
    ).to_term(owner="test")
    boundary = next(n for n in tree.nodes() if n.kind == "With").sugar()
    ctx = ReduceContext(
        temporal=builtin_name_temporal().bind_value("runtime", TermValue(runtime_value))
    )
    managers = (
        outcome_to_exitset(boundary.manager.desugar(ctx))
        .sequence(lambda value: _project_manager_receiver(value, ctx))
        .exits
    )
    assert len(managers) == 1
    assert isinstance(managers[0], Completed)
    assert isinstance(managers[0].value, ObjectValue)
    current = managers[0].value.attribute("payload", "test").value
    assert current.elements[1].to_term(owner="test") == TermValue(
        runtime_value
    ).to_term(owner="test")
    exits = outcome_to_exitset(boundary.desugar(ctx)).exits
    assert len(exits) == 1 and isinstance(exits[0], Completed)


def test_resource_actual_construction_refuses_foreign_occurrence_or_call_shape(
    tmp_path,
):
    from dataclasses import replace
    from sugar_lift_py_tests.context_manager_resolution import ContractRefProtocolError

    tree, context = _attribute_exception_tree(
        tmp_path,
        manager="arbitrary.boundary((ValueError, arbitrary.MyError))",
        body="pass",
        implementation=_DOTTED_TUPLE_RESOURCE,
    )
    reference = next(iter(context.source_derived_contract_refs.values()))
    construction = reference.call_actual_sugars
    manager = next(n for n in tree.nodes() if n.kind == "With").sugar().manager
    foreign = replace(
        construction.use_site, start_col=construction.use_site.start_col + 1
    )
    with pytest.raises(ContractRefProtocolError, match="different source occurrence"):
        construction.bind(manager, use_site=foreign)
    with pytest.raises(ContractRefProtocolError, match="original call shape"):
        construction.bind(replace(manager, args=()), use_site=construction.use_site)
    with pytest.raises(ContractRefProtocolError, match="defining source frame"):
        replace(construction, source_call_frame=None)


@pytest.mark.parametrize("message", ["needle", "haystack"])
def test_with_body_value_discharges_deferred_exit_message(tmp_path, message):
    """Same source protocol, actual body payload decides suppression (or not)."""
    from sugar_lift_py_tests.context_manager_contract import ProtocolResourceSemanticsV1
    from sugar_lift_py_tests.sugar.with_source_resource_sugar import (
        WithSourceResourceSugar,
    )
    from sugar_lift_py_tests.outcome import Completed, Halted, outcome_to_exitset
    from sugar_lift_py_tests.effect import RaiseEffect
    from sugar_lift_py_tests.floor import StringValue

    source = _DEFERRED_BODY_MESSAGE_RESOURCE
    native = {}
    exec(source, native)
    observed = []
    try:
        with native["boundary"]("needle"):
            raise native["MyError"](message)
        observed.append("completed")
    except native["MyError"]:
        observed.append("raised")
    assert observed == (["completed"] if message == "needle" else ["raised"])

    tree, _ = _attribute_exception_tree(
        tmp_path,
        manager='arbitrary.boundary("needle")',
        body="raise actual_error",
        implementation=source,
    )
    sugar = next(node for node in tree.nodes() if node.kind == "With").sugar()
    assert isinstance(sugar, WithSourceResourceSugar)
    assert isinstance(sugar.summary.semantics, ProtocolResourceSemanticsV1)
    actual_error = _constructed_message_error(
        tmp_path / "actual-error", StringValue(message)
    )
    identity = actual_error.identity
    ctx = _actual_error_context(actual_error)
    result = outcome_to_exitset(sugar.desugar(ctx))
    live = [
        face
        for face in result.exits
        if not (
            isinstance(face, Completed)
            and getattr(face.value, "can_fall_through", True) is False
        )
    ]
    assert live
    if message == "needle":
        assert all(isinstance(face, Completed) for face in live)
    else:
        assert all(
            isinstance(face, Halted)
            and isinstance(face.effect, RaiseEffect)
            and face.effect.exception_type_coordinate == identity
            for face in live
        )


def _constructed_message_error(root, message, eq_body=None):
    """Construct the actual exception through a cited native initializer frame."""
    root.mkdir()
    source = (
        "class MyError(Exception):\n"
        "    def __init__(self, message):\n"
        "        self.message = message\n"
        "    def __enter__(self):\n"
        "        return self\n"
        "    def __exit__(self, *args):\n"
        "        return False\n"
        "def make_guard(message):\n"
        "    return MyError(message)\n"
    )
    if eq_body is not None:
        source = source.replace(
            "def make_guard",
            "    def __eq__(self, other):\n        " + eq_body + "\ndef make_guard",
        )
    graph, resolved, _, site = _resolved(root, source)
    # An actual supplied at a value boundary, not a forged literal constructor.
    source = "actual_message\n"
    actual_tree = SourceFile(
        (source, "actual_message.py", blake3_512_of(source.encode()))
    )
    node = next(n for n in actual_tree.nodes() if isinstance(n, Name))
    from sugar_lift_py_tests.ir import _term_content_cid

    actual = ConstructedCallActualV1(
        node,
        message,
        ConstructedValueTestimonyV1.mint(
            node.fragment, _term_content_cid(message.to_term(owner="actual message"))
        ),
    )
    behavior = construct_manager_behavior(
        resolved, graph=graph, actuals=(actual,), call_site=site
    )
    assert isinstance(behavior, ConstructedManagerBehaviorV1)
    value = behavior.receiver_state
    unit = value.defining_class.initializer.source_call_frame.owner.unit
    name = next(
        n for n in unit.typed_module.walk() if isinstance(n, Name) and n.id == "MyError"
    )
    identity = unit.exception_type_identity(name)
    assert identity is not None
    from sugar_lift_py_tests.floor.authenticated_exception_type_value import (
        AuthenticatedExceptionTypeValue,
    )

    return AuthenticatedExceptionTypeValue(value, identity)


def _actual_error_context(error):
    from sugar_lift_py_tests.context.reduce_context import ReduceContext
    from sugar_lift_py_tests.temporal import builtin_name_temporal

    return ReduceContext(
        temporal=builtin_name_temporal().bind_value("actual_error", error)
    )


_DEFERRED_BODY_MESSAGE_RESOURCE = (
    "class MyError(Exception):\n"
    "    def __init__(self, message):\n"
    "        self.message = message\n"
    "class Resource:\n"
    "    def __init__(self, pattern):\n"
    "        self.pattern = pattern\n"
    "    def __enter__(self):\n"
    "        return self\n"
    "    def __exit__(self, effect_type, effect, traceback):\n"
    "        if effect_type is None:\n"
    "            return False\n"
    "        return effect.message == self.pattern\n"
    "def boundary(pattern):\n"
    "    return Resource(pattern)\n"
)


def test_with_body_value_keeps_native_comparison_raise(tmp_path):
    from sugar_lift_py_tests.effect import RaiseEffect
    from sugar_lift_py_tests.outcome import Completed, Halted, outcome_to_exitset

    payload_root = tmp_path / "payload"
    payload_root.mkdir()
    NativePayload, payload = _source_equality_payload(
        payload_root, 'raise LookupError("equality")'
    )
    native = {}
    exec(_DEFERRED_BODY_MESSAGE_RESOURCE, native)
    native_error = native["MyError"](NativePayload(23))
    with pytest.raises(LookupError, match="equality"):
        with native["boundary"]("needle"):
            raise native_error

    error = _constructed_message_error(tmp_path / "error", payload)
    tree, _ = _attribute_exception_tree(
        tmp_path / "consumer",
        manager='arbitrary.boundary("needle")',
        body="raise actual_error",
        implementation=_DEFERRED_BODY_MESSAGE_RESOURCE,
    )
    sugar = next(n for n in tree.nodes() if n.kind == "With").sugar()
    result = outcome_to_exitset(sugar.desugar(_actual_error_context(error)))
    live = [
        f
        for f in result.exits
        if not (
            isinstance(f, Completed)
            and getattr(f.value, "can_fall_through", True) is False
        )
    ]
    assert live
    assert all(
        isinstance(f, Halted)
        and isinstance(f.effect, RaiseEffect)
        and f.effect.exception_name == "LookupError"
        for f in live
    )


def test_with_normal_body_binds_none_before_exit_lookup(tmp_path):
    from sugar_lift_py_tests.outcome import Completed, outcome_to_exitset

    source = _DEFERRED_BODY_MESSAGE_RESOURCE.replace(
        "            return False",
        "            return effect is None and traceback is None",
    )
    native = {}
    exec(source, native)
    with native["boundary"]("needle"):
        pass
    tree, _ = _attribute_exception_tree(
        tmp_path,
        manager='arbitrary.boundary("needle")',
        body="pass",
        implementation=source,
    )
    result = outcome_to_exitset(
        next(n for n in tree.nodes() if n.kind == "With").sugar().desugar()
    )
    assert result.exits and all(isinstance(f, Completed) for f in result.exits)


@pytest.mark.parametrize("reads_value", [False, True])
@pytest.mark.parametrize("value_kind", ["absent", "class"])
def test_body_exit_missing_actual_value_is_not_a_guessed_instance(
    tmp_path, reads_value, value_kind
):
    from sugar_lift_py_tests.caller_parameter_contract import (
        NativeOperationExitCarrierV1,
    )
    from sugar_lift_py_tests.effect import RaiseEffect
    from sugar_lift_py_tests.gap import ConstructionPanic
    from sugar_lift_py_tests.outcome import Completed, Halted, outcome_to_exitset
    from sugar_lift_py_tests.outcome.exit_set import true_guard

    result_expression = "effect.message" if reads_value else "False"
    graph, resolved, actual, site = _resolved(
        tmp_path,
        "class Resource:\n"
        "    def __init__(self, marker):\n"
        "        self.marker = marker\n"
        "    def __enter__(self):\n"
        "        return self\n"
        "    def __exit__(self, kind, effect, stack):\n"
        f"        return {result_expression}\n"
        "def make_guard(marker):\n"
        "    return Resource(marker)\n",
    )
    behavior = construct_manager_behavior(
        resolved, graph=graph, actuals=(actual,), call_site=site
    )
    protocol = construct_manager_protocol(behavior, exit_face_id="missing-actual-face")
    entered = outcome_to_exitset(protocol.enter_resource_outcome()).exits[0].value
    from sugar_lift_py_tests.floor.exception_class_value import ExceptionClassValue

    value = None if value_kind == "absent" else ExceptionClassValue("ValueError")
    body = Halted(
        true_guard(),
        RaiseEffect.for_builtin("ValueError", occurrence=site, raised_value=value),
    )
    outcome = protocol.exit_outcome_for_body(entered, body)
    if reads_value:
        assert isinstance(outcome, NativeOperationExitCarrierV1)
        with pytest.raises(
            ConstructionPanic, match="undischarged native operation demand"
        ):
            outcome_to_exitset(outcome)
    else:
        assert all(isinstance(f, Completed) for f in outcome_to_exitset(outcome).exits)


def test_native_exit_guarded_returns_keep_authentication_and_obligations():
    from sugar_lift_py_tests.floor import BranchResultAuthentication, GuardedReturn
    from sugar_lift_py_tests.floor.branch_result_coordinate import branch_result_guard
    from sugar_lift_py_tests.ir import atomic
    from sugar_lift_py_tests.outcome import Completed, ExitSet
    from sugar_lift_py_tests.outcome.exit_set import (
        complement_guard,
        partition,
        true_guard,
    )
    from sugar_lift_py_tests.sugar.with_source_resource_sugar import _exit_return_values
    from sugar_source_tree.binding_state import BranchResultSlot

    slot = BranchResultSlot("native-return-slot")
    observed = atomic("native.condition", [])
    guard = branch_result_guard(slot, None)
    block = BlockValue(
        (
            BranchResultAuthentication(slot, observed),
            GuardedReturn((guard,), TermValue(True)),
            ReturnValue(TermValue(False)),
        ),
        can_fall_through=False,
    )
    faces = frozenset({partition("native-return-owner")[0]})
    result = _exit_return_values(ExitSet((Completed(true_guard(), block, faces),)))
    assert {f.value.value: f.guard for f in result.exits} == {
        True: observed,
        False: complement_guard(observed),
    }
    assert all(f.faces == faces for f in result.exits)


@pytest.mark.parametrize("refusal", ["unproved-guard", "prefix-store", "empty-green"])
def test_native_exit_return_projection_cannot_drop_unproved_work(refusal):
    from sugar_lift_py_tests.floor import GuardedReturn, ObjectValue
    from sugar_lift_py_tests.floor.branch_result_coordinate import branch_result_guard
    from sugar_lift_py_tests.floor.receiver_field_store_value import (
        ReceiverFieldStoreValue,
    )
    from sugar_lift_py_tests.gap import ConstructionPanic
    from sugar_lift_py_tests.outcome import ExitSet
    from sugar_lift_py_tests.sugar.with_source_resource_sugar import _exit_return_values
    from sugar_source_tree.binding_state import BranchResultSlot

    if refusal == "unproved-guard":
        statements = (
            GuardedReturn(
                (branch_result_guard(BranchResultSlot("unknown"), None),),
                TermValue(True),
            ),
        )
    elif refusal == "prefix-store":
        statements = (
            ReceiverFieldStoreValue(
                ObjectValue("Resource", ()), "marker", TermValue(3)
            ),
            ReturnValue(TermValue(True)),
        )
    else:
        statements = ()
    with pytest.raises(ConstructionPanic):
        _exit_return_values(
            ExitSet.completed(BlockValue(statements, can_fall_through=False))
        )


def test_deferred_protocol_admission_rejects_a_foreign_exit_slot(tmp_path, monkeypatch):
    graph, resolved, actual, site = _resolved(
        tmp_path,
        _DEFERRED_BODY_MESSAGE_RESOURCE.replace(
            "def boundary(pattern):", "def make_guard(pattern):"
        ),
    )
    behavior = construct_manager_behavior(
        resolved, graph=graph, actuals=(actual,), call_site=site
    )
    protocol = construct_manager_protocol(behavior, exit_face_id="owned-exit-face")
    _, foreign, _ = _deferred_exit_message_comparison()
    monkeypatch.setattr(
        ConstructedManagerProtocolV1, "exit_outcome", lambda self, ctx=None: foreign
    )
    summary = derive_manager_summary(protocol, behavior=behavior)
    assert isinstance(summary, DerivedManagerSummaryGapV1)
    assert summary.kind == "exit-may-halt"


def test_source_call_binding_gap_during_exit_is_exit_may_halt(tmp_path, monkeypatch):
    """A foreign native coordinate during exit is a leftover, not an uncaught raise."""
    from sugar_lift_py_tests.source_call_frame import SourceCallBindingGap

    graph, resolved, actual, site = _resolved(
        tmp_path,
        _DEFERRED_BODY_MESSAGE_RESOURCE.replace(
            "def boundary(pattern):", "def make_guard(pattern):"
        ),
    )
    behavior = construct_manager_behavior(
        resolved, graph=graph, actuals=(actual,), call_site=site
    )
    protocol = construct_manager_protocol(behavior, exit_face_id="owned-exit-face")

    def boom(self, ctx=None):
        raise SourceCallBindingGap(
            "native formal coordinate roster contains a foreign coordinate type"
        )

    monkeypatch.setattr(ConstructedManagerProtocolV1, "exit_outcome", boom)
    summary = derive_manager_summary(protocol, behavior=behavior)
    assert isinstance(summary, DerivedManagerSummaryGapV1)
    assert summary.kind == "exit-may-halt"
    assert "foreign coordinate type" in summary.detail


@pytest.mark.parametrize(
    "eq_body", ["return True", 'raise LookupError("exception equality")']
)
def test_with_exit_compares_native_instance_not_its_type_witness(tmp_path, eq_body):
    from sugar_lift_py_tests.effect import RaiseEffect
    from sugar_lift_py_tests.floor import StringValue
    from sugar_lift_py_tests.outcome import Completed, Halted, outcome_to_exitset

    source = _DEFERRED_BODY_MESSAGE_RESOURCE.replace(
        "return effect.message == self.pattern", "return effect == self.pattern"
    )
    source = source.replace(
        "class Resource:",
        "    def __eq__(self, other):\n        " + eq_body + "\nclass Resource:",
    )
    native = {}
    exec(source, native)

    def run_native():
        with native["boundary"]("needle"):
            raise native["MyError"]("message")

    if eq_body == "return True":
        run_native()
    else:
        with pytest.raises(LookupError, match="exception equality"):
            run_native()

    actual_error = _constructed_message_error(
        tmp_path / "actual-error", StringValue("message"), eq_body
    )
    tree, _ = _attribute_exception_tree(
        tmp_path / "consumer",
        manager='arbitrary.boundary("needle")',
        body="raise actual_error",
        implementation=source,
    )
    result = outcome_to_exitset(
        next(n for n in tree.nodes() if n.kind == "With")
        .sugar()
        .desugar(_actual_error_context(actual_error))
    )
    live = [
        f
        for f in result.exits
        if not (
            isinstance(f, Completed)
            and getattr(f.value, "can_fall_through", True) is False
        )
    ]
    assert live
    if eq_body == "return True":
        assert all(isinstance(f, Completed) for f in live)
    else:
        assert all(
            isinstance(f, Halted)
            and isinstance(f.effect, RaiseEffect)
            and f.effect.exception_name == "LookupError"
            for f in live
        )


def test_raised_type_coordinate_is_not_rich_comparison_outcome_testimony():
    from sugar_lift_py_tests.effect import RaiseEffect
    from sugar_lift_py_tests.floor import NoneValue
    from sugar_lift_py_tests.floor.exception_class_value import ExceptionClassValue
    from sugar_lift_py_tests.floor.manager_coordinate import RaisedExitTypeValue
    from sugar_lift_py_tests.gap import ConstructionPanic

    effect = RaiseEffect.for_builtin("ValueError", occurrence="raised type coordinate")
    value = RaisedExitTypeValue(effect.exception_type_coordinate)
    for other in (NoneValue(), ExceptionClassValue("ValueError")):
        with pytest.raises(ConstructionPanic):
            value.equals(other, "native class equality")
    with pytest.raises(ConstructionPanic):
        value.is_identical(ExceptionClassValue("ValueError"), "native class identity")


@pytest.mark.parametrize("expression", ["kind == ValueError", "ValueError == kind"])
def test_body_type_coordinate_defers_rich_compare_until_class_binding(
    tmp_path, expression
):
    from sugar_lift_py_tests.caller_parameter_contract import (
        NativeOperationExitCarrierV1,
    )
    from sugar_lift_py_tests.effect import RaiseEffect
    from sugar_lift_py_tests.gap import ConstructionPanic
    from sugar_lift_py_tests.outcome import Halted, outcome_to_exitset
    from sugar_lift_py_tests.outcome.exit_set import true_guard

    graph, resolved, actual, site = _resolved(
        tmp_path,
        "class Resource:\n"
        "    def __init__(self, marker):\n"
        "        self.marker = marker\n"
        "    def __enter__(self):\n"
        "        return self\n"
        "    def __exit__(self, kind, value, stack):\n"
        f"        return {expression}\n"
        "def make_guard(marker):\n"
        "    return Resource(marker)\n",
    )
    behavior = construct_manager_behavior(
        resolved, graph=graph, actuals=(actual,), call_site=site
    )
    protocol = construct_manager_protocol(behavior, exit_face_id="class-binding-face")
    entered = outcome_to_exitset(protocol.enter_resource_outcome()).exits[0].value
    body = Halted(true_guard(), RaiseEffect.for_builtin("ValueError", occurrence=site))
    outcome = protocol.exit_outcome_for_body(entered, body)
    assert isinstance(outcome, NativeOperationExitCarrierV1)
    with pytest.raises(ConstructionPanic, match="undischarged native operation demand"):
        outcome_to_exitset(outcome)


def _identity_and_message_protocol(tmp_path, expression, *, exit_face_id="message-face"):
    from sugar_lift_py_tests.floor import StringValue
    from sugar_lift_py_tests.ir import _term_content_cid

    graph, resolved, expected, call_site = _resolved(
        tmp_path,
        "class ArbitraryBoundary:\n"
        "    def __init__(self, expected, pattern):\n"
        "        self.expected = expected\n"
        "        self.pattern = pattern\n"
        "    def __enter__(self):\n"
        "        return self\n"
        "    def __exit__(self, effect_type, effect, traceback):\n"
        "        if effect_type is None:\n"
        "            raise RuntimeError()\n"
        f"        return {expression}\n"
        "def make_guard(expected, pattern):\n"
        "    return ArbitraryBoundary(expected, pattern)\n",
    )
    pattern_source = SourceFile(
        ('"needle"\n', str(tmp_path / "pattern.py"), "blake3-512:" + ("91" * 64))
    )
    pattern_node = next(
        node for node in pattern_source.nodes() if isinstance(node, Constant)
    )
    pattern_value = StringValue("needle")
    pattern = ConstructedCallActualV1(
        pattern_node,
        pattern_value,
        ConstructedValueTestimonyV1.mint(
            pattern_node.fragment,
            _term_content_cid(pattern_value.to_term(owner=resolved.cid)),
        ),
    )
    behavior = construct_manager_behavior(
        resolved,
        graph=graph,
        actuals=(expected, pattern),
        call_site=call_site,
    )
    protocol = construct_manager_protocol(behavior, exit_face_id=exit_face_id)
    return behavior, protocol


@pytest.mark.parametrize(
    "expression",
    [
        "(effect_type is self.expected) and (effect.message == self.pattern)",
        "(effect_type is self.expected) or (effect.message == self.pattern)",
    ],
)
def test_boolop_deferred_rhs_is_not_forced_through_outcome_to_exitset(
    tmp_path, expression
):
    from sugar_lift_py_tests.caller_parameter_contract import (
        NativeOperationExitCarrierV1,
    )
    from sugar_lift_py_tests.floor.predicate_value import PredicateValue
    from sugar_lift_py_tests.gap import ConstructionPanic
    from sugar_lift_py_tests.outcome import Completed, Halted, outcome_to_exitset

    _behavior, protocol = _identity_and_message_protocol(tmp_path, expression)
    outcome = protocol.exit_outcome()
    assert isinstance(outcome, NativeOperationExitCarrierV1)
    assert outcome.demand.operator == "attribute_named"
    assert outcome.short_circuits
    continuing_guard, stopped, _continuing_face, _stopped_face = (
        outcome.short_circuits[0]
    )

    def mentions_identity(formula):
        if getattr(formula, "name", None) == "identity":
            return True
        return any(
            mentions_identity(operand)
            for operand in getattr(formula, "operands", ())
        )

    assert mentions_identity(continuing_guard)
    assert len(stopped.exits) == 1
    assert isinstance(stopped.exits[0], Completed)
    assert isinstance(stopped.exits[0].value, PredicateValue)
    assert outcome.prefix_composition is not None
    resolved_exits = outcome.prefix_composition[0]
    assert any(isinstance(face, Halted) for face in resolved_exits)
    with pytest.raises(ConstructionPanic, match="undischarged native operation demand"):
        outcome_to_exitset(outcome)


def test_ifexp_deferred_message_lookup_is_not_forced_through_outcome_to_exitset():
    """``effect.message if cond else str(effect)`` keeps the deferred lookup."""
    from sugar_lift_py_tests.caller_parameter_contract import (
        NativeOperationExitCarrierV1,
    )
    from sugar_lift_py_tests.context.reduce_context import ReduceContext
    from sugar_lift_py_tests.context_manager_resolution import TreeConstructionContextV1
    from sugar_lift_py_tests.floor import StringValue
    from sugar_lift_py_tests.floor.manager_coordinate import ExitValueCoordinate
    from sugar_lift_py_tests.floor.predicate_value import PredicateValue
    from sugar_lift_py_tests.gap import ConstructionPanic
    from sugar_lift_py_tests.ir import atomic
    from sugar_lift_py_tests.outcome import outcome_to_exitset
    from sugar_lift_py_tests.temporal import builtin_name_temporal

    source = "effect.message if cond else str(effect)\n"
    tree = SourceFile(
        (source, "ifexp-deferred-exit.py", blake3_512_of(source.encode())),
        construction_context=TreeConstructionContextV1.for_test_without_workspace(),
    )
    ifexp = next(node for node in tree.nodes() if node.kind == "IfExp")
    coordinate = ExitValueCoordinate("ifexp-message-face")
    ctx = ReduceContext(
        temporal=builtin_name_temporal()
        .bind_value("effect", coordinate)
        .bind_value("cond", PredicateValue(atomic("python:group_test", [])))
    )
    outcome = ifexp.sugar().desugar(ctx)
    assert isinstance(outcome, NativeOperationExitCarrierV1)
    assert outcome.demand.operator == "attribute_named"
    assert outcome.operands[1] == StringValue("message")
    assert outcome.short_circuits
    with pytest.raises(ConstructionPanic, match="undischarged native operation demand"):
        outcome_to_exitset(outcome)


def test_spread_deferred_message_lookup_is_not_forced_through_outcome_to_exitset():
    """``[effect.message, *rest]`` keeps the deferred lookup."""
    from sugar_lift_py_tests.caller_parameter_contract import (
        NativeOperationExitCarrierV1,
    )
    from sugar_lift_py_tests.context.reduce_context import ReduceContext
    from sugar_lift_py_tests.context_manager_resolution import TreeConstructionContextV1
    from sugar_lift_py_tests.floor import StringValue, TupleValue
    from sugar_lift_py_tests.floor.manager_coordinate import ExitValueCoordinate
    from sugar_lift_py_tests.gap import ConstructionPanic
    from sugar_lift_py_tests.outcome import outcome_to_exitset
    from sugar_lift_py_tests.temporal import builtin_name_temporal

    source = "[effect.message, *rest]\n"
    tree = SourceFile(
        (source, "spread-deferred-exit.py", blake3_512_of(source.encode())),
        construction_context=TreeConstructionContextV1.for_test_without_workspace(),
    )
    display = next(node for node in tree.nodes() if node.kind == "List")
    coordinate = ExitValueCoordinate("spread-message-face")
    ctx = ReduceContext(
        temporal=builtin_name_temporal()
        .bind_value("effect", coordinate)
        .bind_value("rest", TupleValue(()))
    )
    outcome = display.sugar().desugar(ctx)
    assert isinstance(outcome, NativeOperationExitCarrierV1)
    assert outcome.demand.operator == "attribute_named"
    assert outcome.operands[1] == StringValue("message")
    with pytest.raises(ConstructionPanic, match="undischarged native operation demand"):
        outcome_to_exitset(outcome)


def test_helper_lookup_of_bound_exit_value_is_not_a_foreign_formal(tmp_path):
    """A helper that looks up ``exc.message`` after binding the exit value
    must not treat that ``ExitValueCoordinate`` as one of its formals."""
    from sugar_lift_py_tests.caller_parameter_contract import (
        NativeOperationExitCarrierV1,
    )
    from sugar_lift_py_tests.floor import StringValue
    from sugar_lift_py_tests.floor.manager_coordinate import ExitValueCoordinate
    from sugar_lift_py_tests.source_call_frame import SourceCallBindingGap

    source = (
        "class Resource:\n"
        "    def __enter__(self):\n"
        "        return self\n"
        "    def __exit__(self, kind, effect, stack):\n"
        "        return stringify(effect)\n"
        "def stringify(exc):\n"
        "    return exc.message\n"
        "def make_guard(pattern):\n"
        "    return Resource()\n"
    )
    graph, resolved, actual, site = _resolved(tmp_path, source)
    behavior = construct_manager_behavior(
        resolved, graph=graph, actuals=(actual,), call_site=site
    )
    protocol = construct_manager_protocol(behavior, exit_face_id="owned-exit-face")
    try:
        outcome = protocol.exit_outcome()
    except SourceCallBindingGap as exc:
        raise AssertionError(
            "already-substituted exit value was treated as a callee formal"
        ) from exc
    assert isinstance(outcome, NativeOperationExitCarrierV1), outcome
    assert outcome.demand.operator == "attribute_named"
    assert outcome.operands[1] == StringValue("message")
    assert any(
        isinstance(coordinate, ExitValueCoordinate)
        for coordinate in outcome.coordinates
    )


def test_caller_reduce_block_omits_a_second_pre_effect_state(tmp_path):
    """A caller statement that sees a callee's already-enrolled lookup
    must not overwrite that inner reducer state."""
    from sugar_lift_py_tests.caller_parameter_contract import (
        NativeOperationExitCarrierV1,
    )
    from sugar_lift_py_tests.floor import StringValue
    from sugar_lift_py_tests.gap import ConstructionPanic

    source = (
        "class Resource:\n"
        "    def __enter__(self):\n"
        "        return self\n"
        "    def __exit__(self, kind, effect, stack):\n"
        "        if stringify(effect):\n"
        "            return True\n"
        "        return False\n"
        "def stringify(exc):\n"
        "    return exc.message\n"
        "def make_guard(pattern):\n"
        "    return Resource()\n"
    )
    graph, resolved, actual, site = _resolved(tmp_path, source)
    behavior = construct_manager_behavior(
        resolved, graph=graph, actuals=(actual,), call_site=site
    )
    protocol = construct_manager_protocol(behavior, exit_face_id="owned-exit-face")
    try:
        outcome = protocol.exit_outcome()
    except ConstructionPanic as exc:
        raise AssertionError(
            "caller overwrite of an already-enrolled lookup state"
        ) from exc
    assert isinstance(outcome, NativeOperationExitCarrierV1), outcome
    assert outcome.demand.operator == "attribute_named"
    assert outcome.operands[1] == StringValue("message")
    assert outcome.pre_effect_state is not None


def test_boolop_or_message_comparison_is_not_effect_boundary(tmp_path):
    """Disjunction is not EffectBoundary's type-and-message conjunction."""
    from sugar_lift_py_tests.context_manager_contract import EffectBoundarySemanticsV1

    behavior, protocol = _identity_and_message_protocol(
        tmp_path,
        "(effect_type is self.expected) or (effect.message == self.pattern)",
    )
    summary = derive_manager_summary(protocol, behavior=behavior)
    assert not (
        isinstance(summary, DerivedManagerSummaryV1)
        and isinstance(summary.semantics, EffectBoundarySemanticsV1)
    ), summary



def test_optional_match_or_still_derives_effect_boundary(tmp_path):
    """``pattern is None or message == pattern`` stays an EffectBoundary."""
    from sugar_lift_py_tests.context_manager_contract import (
        EffectBoundarySemanticsV1,
        OptionalFormalArgumentProjectionV1,
    )

    behavior, protocol = _identity_and_message_protocol(
        tmp_path,
        "(effect_type is self.expected) and "
        "(self.pattern is None or effect.message == self.pattern)",
    )
    summary = derive_manager_summary(protocol, behavior=behavior)
    assert isinstance(summary, DerivedManagerSummaryV1), summary
    assert isinstance(summary.semantics, EffectBoundarySemanticsV1)
    assert summary.semantics.message_pattern_operand == (
        OptionalFormalArgumentProjectionV1(1)
    )


def test_partitioned_match_faces_emit_factored_effect_boundary(tmp_path):
    """Constructor-partitioned match=None vs match=pattern stays factored."""
    from sugar_lift_py_tests.context_manager_contract import (
        NoMessagePatternV1,
        OptionalFormalArgumentProjectionV1,
    )
    from sugar_lift_py_tests.floor import (
        ReceiverStatePartitionValue,
        StringValue,
        SymbolicValue,
    )
    from sugar_lift_py_tests.ir import _term_content_cid, make_var
    from sugar_lift_py_tests.outcome import Completed
    from sugar_lift_python_source.manager_summary_derivation import (
        FactoredEffectBoundarySummaryV1,
    )

    graph, resolved, expected, call_site = _resolved(
        tmp_path,
        "class Boundary:\n"
        "    def __init__(self, expected, match=None, flag=None):\n"
        "        self.expected = expected\n"
        "        if flag:\n"
        "            self.match = match\n"
        "        else:\n"
        "            self.match = None\n"
        "    def __enter__(self):\n"
        "        return self\n"
        "    def __exit__(self, effect_type, effect, traceback):\n"
        "        if effect_type is None:\n"
        "            raise RuntimeError('unmet')\n"
        "        return (effect_type is self.expected) and (\n"
        "            self.match is None or effect.message == self.match\n"
        "        )\n"
        "def make_guard(expected, match=None, flag=None):\n"
        "    return Boundary(expected, match, flag)\n",
    )
    pattern_source = SourceFile(
        ('"needle"\n', str(tmp_path / "pattern.py"), "blake3-512:" + ("92" * 64))
    )
    pattern_node = next(
        node for node in pattern_source.nodes() if isinstance(node, Constant)
    )
    pattern_value = StringValue("needle")
    pattern = ConstructedCallActualV1(
        pattern_node,
        pattern_value,
        ConstructedValueTestimonyV1.mint(
            pattern_node.fragment,
            _term_content_cid(pattern_value.to_term(owner=resolved.cid)),
        ),
    )
    flag_source = SourceFile(
        ("0\n", str(tmp_path / "flag.py"), "blake3-512:" + ("93" * 64))
    )
    flag_node = next(
        node for node in flag_source.nodes() if isinstance(node, Constant)
    )
    flag_value = SymbolicValue(make_var("constructor-flag"))
    flag = ConstructedCallActualV1(
        flag_node,
        flag_value,
        ConstructedValueTestimonyV1.mint(
            flag_node.fragment,
            _term_content_cid(flag_value.to_term(owner=resolved.cid)),
        ),
    )
    behavior = construct_manager_behavior(
        resolved,
        graph=graph,
        actuals=(expected, pattern, flag),
        call_site=call_site,
    )
    assert isinstance(behavior.receiver_state, ReceiverStatePartitionValue)
    protocol = construct_manager_protocol(behavior, exit_face_id="partition-face")
    summary = derive_manager_summary(protocol, behavior=behavior)
    assert isinstance(summary, FactoredEffectBoundarySummaryV1), summary
    completed = [
        face
        for face in summary.boundary_faces.exits
        if isinstance(face, Completed)
    ]
    operands = {face.value.message_pattern_operand for face in completed}
    assert NoMessagePatternV1() in operands
    assert any(
        isinstance(operand, OptionalFormalArgumentProjectionV1)
        for operand in operands
    )
    assert len(completed) == 2
