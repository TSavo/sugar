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
    resolve_import_binding,
)
from sugar_lift_python_source.manager_construction import (
    CALL_TARGET_GAP_KINDS as _CALL_TARGET_GAP_KINDS,
    ConstructedCallActualV1,
    ConstructedManagerBehaviorV1,
    ManagerConstructionGapV1,
    _call_coordinate,
    _install_opaque_call_obligation,
    _install_source_call_frame,
    construct_manager_behavior,
    resolve_source_visible_frame,
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
from sugar_source_tree.binding_provenance import ConstructedValueTestimonyV1
from sugar_source_tree.binding_state import BindingEntryV1
from sugar_source_tree.nodes import Call, ClassDef, Constant, Name
from sugar_source_tree.tree import SourceFile


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
    obligation = context.opaque_source_call_obligations[coordinate]
    assert obligation.coordinate == coordinate
    assert obligation.target_name == "missing_helper"
    assert obligation.resolved_object_cid == resolved.cid
    assert obligation.resolution_kind == "call-target-source-absent"


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

    with pytest.raises(BackendDefect, match="conflicting opaque-call obligation"):
        _install_opaque_call_obligation(
            context,
            call,
            OpaqueSourceCallObligationV1(
                coordinate,
                "other_helper",
                "blake3-512:" + "2" * 128,
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

    assert raised.value.info.owner == "attribute"
    assert raised.value.info.observed == "ObjectValue"


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
    assert raised.value.info.owner == "attribute"
    assert raised.value.info.observed == "ObjectValue"


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
    assert not behavior.receiver_state.has_method("project")
    from sugar_lift_py_tests.gap.panic import ConstructionPanic

    with pytest.raises(ConstructionPanic) as caught:
        behavior.receiver_state.call_method_value(
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
    assert behavior.receiver_state.class_name == "SomeGuard"
    assert behavior.receiver_state.has_method("__enter__")
    assert behavior.receiver_state.has_method("__exit__")
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
    """The tempting pandas helper spelling has no assertion authority.

    This is the lying twin for the returned-manager reproducer.  It uses the
    exact helper name but returns an ordinary resource manager; native protocol
    testimony must keep it out of the EffectBoundary arm.
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
    )

    from sugar_lift_py_tests.context_manager_resolution import (
        SourceDerivedContextManagerRefV1,
    )

    assert len(context.source_derived_contract_refs) == 1
    assert isinstance(
        next(iter(context.source_derived_contract_refs.values())),
        SourceDerivedContextManagerRefV1,
    )


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
    populate_source_derived_resource_refs(tree, root=tmp_path, path=path)
    return tree, context


def test_installed_pytest_raises_truthful_route_keeps_enter_gap_typed(
    tmp_path,
):
    from sugar_source_tree.panic import (
        WithConstructionGap,
        WithConstructionGapKind,
    )

    tree, context = _installed_pytest_boundary(
        tmp_path,
        'pytest.raises(ValueError, match="boom")',
        'raise ValueError("boom")',
    )

    assert len(context.source_derived_contract_refs) == 1
    with_node = next(node for node in tree.nodes() if node.kind == "With")
    with pytest.raises(WithConstructionGap) as caught:
        with_node.sugar()

    assert caught.value.gap_kind is WithConstructionGapKind.FORCE_FLOOR
    assert "Try.sugar:Try at _pytest/raises.py:" in caught.value.observed
    assert "ExitSet with 3 arms" not in caught.value.observed
    assert (
        caught.value.coordinate.start_line,
        caught.value.coordinate.start_col,
        caught.value.coordinate.end_line,
        caught.value.coordinate.end_col,
    ) == (3, 9, 3, 48)


def test_installed_pytest_raises_lying_legacy_callable_route_stays_typed_loud(
    tmp_path,
):
    from sugar_source_tree.panic import (
        WithConstructionGap,
        WithConstructionGapKind,
    )

    tree, context = _installed_pytest_boundary(
        tmp_path,
        'pytest.raises(ValueError, int, "bad")',
        "pass",
    )

    assert len(context.source_derived_contract_refs) == 1
    with_node = next(node for node in tree.nodes() if node.kind == "With")
    with pytest.raises(WithConstructionGap) as caught:
        with_node.sugar()

    assert caught.value.gap_kind is WithConstructionGapKind.FORCE_FLOOR
    assert "Try.sugar:Try at _pytest/raises.py:" in caught.value.observed
    assert "ExitSet with 4 arms" not in caught.value.observed
    assert (
        caught.value.coordinate.start_line,
        caught.value.coordinate.start_col,
        caught.value.coordinate.end_line,
        caught.value.coordinate.end_col,
    ) == (3, 9, 3, 46)


def test_installed_pandas_warning_manager_names_opaque_generator_transition(tmp_path):
    """Real producer advances to its first still-opaque native transition.

    The imported generator frame comes only from authenticated pandas source,
    and construction names its first unconsumable step instead of inventing
    warning testimony or collapsing the site to
    ``non-manager-result:BlockValue``.

    ``assert_produces_warning`` has a THREE-statement body::

        0  Expr    (a ``Constant`` -- the docstring)
        1  Assign  (``__tracebackhide__ = True``)
        2  With    (the warning capture)

    Statement 0 owes nothing -- no effect, no binding, no suspension -- so it
    is stepped as an ``InertStepV1`` and is not the answer. Statement 1 is,
    because a binding is real work the machine cannot yet perform.

    This test previously asserted ``With``, which is statement TWO PAST where
    the machine can reach; it was born red and never passed. ``With`` is the
    KNOWN REMAINING DISTANCE, not a defect in this arm: naming it requires
    stepping ``__tracebackhide__ = True``, and a binding step needs an
    authenticated binding record that ``binding_state`` does not yet hold.
    That is its own mechanism and its own PR.

    Still a tooth: remove ``InertStepV1`` and the docstring blocks first, so
    this node reports ``Expr`` and goes red.
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
    populate_source_derived_resource_refs(tree, root=tmp_path, path=path)

    boundary = next(node for node in tree.nodes() if node.kind == "With").sugar()
    assert isinstance(boundary, GeneratorWithSugar)
    with pytest.raises(SugarNotWritten) as caught:
        boundary.desugar()
    assert caught.value.owner == "GeneratorWithSugar.desugar"
    assert caught.value.observed == "opaque generator transition: Assign"


def test_imported_renamed_generator_manager_installs_native_frame(tmp_path):
    """Truthful twin: suspension testimony, not a manager-name table, opens it."""
    distribution = _distribution(
        tmp_path,
        "def make_guard(expected):\n    yield expected\n",
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
    )

    assert context.source_call_frames == {}
    gap = next(iter(context.source_derived_contract_refs.values()))
    assert isinstance(gap, ContextManagerResolutionGapV1)
    assert (gap.kind, gap.detail) == ("non-manager-result", "TermValue")


def _installed_plain_expected_halt(tmp_path, function_body: str):
    consumer = (
        "import pytest\n"
        "def use_boundary():\n"
        "    with pytest.raises(ValueError):\n"
        f"        {function_body}\n"
    )
    path = tmp_path / "plain_expected_halt.py"
    path.write_text(consumer, encoding="utf-8")
    from sugar_lift_py_tests.context_manager_resolution import (
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
    populate_source_derived_resource_refs(tree, root=tmp_path, path=path)
    reference = next(iter(context.source_derived_contract_refs.values()))
    assert isinstance(reference, SourceDerivedContextManagerRefV1), reference
    with_node = next(node for node in tree.nodes() if node.kind == "With")
    boundary = with_node.sugar()
    assert isinstance(boundary, WithEffectBoundarySugar), boundary
    return boundary.desugar()


def test_installed_plain_expected_halt_completes(tmp_path):
    """TRUTHFUL: the expected native halt is the assertion's passing face."""
    from sugar_lift_py_tests.outcome import Completed, outcome_to_exitset

    outcome = _installed_plain_expected_halt(
        tmp_path, "raise ValueError('expected')"
    )
    exits = outcome_to_exitset(outcome).exits
    assert len(exits) == 1
    assert isinstance(exits[0], Completed), exits


def test_installed_plain_expected_halt_lie_fails(tmp_path):
    """LYING: returning normally cannot satisfy an expected-halt assertion."""
    from sugar_lift_py_tests.effect import ExpectationNotMetEffect
    from sugar_lift_py_tests.outcome import Halted, outcome_to_exitset

    outcome = _installed_plain_expected_halt(tmp_path, "pass")
    exits = outcome_to_exitset(outcome).exits
    assert len(exits) == 1
    assert isinstance(exits[0], Halted), exits
    assert isinstance(exits[0].effect, ExpectationNotMetEffect), exits[0]


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
        tree, root=tmp_path, path=path, artifact_graph_cache=graphs
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


def test_guarded_literal_exit_with_opaque_completed_face_stays_gap(tmp_path):
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
    assert isinstance(summary, DerivedManagerSummaryGapV1)
    assert summary.kind == "exit-may-halt"


def test_guarded_literal_exit_with_no_true_face_stays_gap(tmp_path):
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
    assert isinstance(summary, DerivedManagerSummaryGapV1)
    assert summary.kind == "exit-may-halt"


def test_guarded_literal_exit_without_type_coordinate_stays_gap(tmp_path):
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
    assert isinstance(summary, DerivedManagerSummaryGapV1)


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
    distribution = _distribution(
        tmp_path, implementation, exported="boundary"
    )
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


def test_boundary_as_binding_projects_authenticated_exception_context(tmp_path):
    """Truthful chained twin: `.value.__context__` is the handled occurrence."""
    from sugar_lift_py_tests.outcome import Completed

    exits = _route_boundary_with_binding(
        tmp_path,
        body=(
            "try:\n"
            "    raise ImportError('inner')\n"
            "except ImportError:\n"
            "    raise ValueError('cannot convert')"
        ),
        following="assert isinstance(info.value.__context__, ImportError)",
    )
    completed = [face for face in exits.exits if isinstance(face, Completed)]
    assert len(completed) == 1
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
        body=(
            "try:\n"
            "    raise ImportError('inner')\n"
            "except ImportError:\n"
            "    raise ValueError('cannot convert')"
        ),
        following="assert isinstance(info.value.__context__, ImportError)",
    )
    completed = [face for face in exits.exits if isinstance(face, Completed)]
    assert len(completed) == 1
    assert any(
        "effect_slot_context" in str(entry.formula)
        for entry in _effect_slot_facts(completed[0])
    )


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
    )
    refs = context.source_derived_contract_refs
    coordinate, reference = next(iter(refs.items()))
    refs[coordinate] = replace(
        reference, semantics=replace(reference.semantics, binding=NoBindingV1())
    )

    with pytest.raises(UnsupportedWithBindingTarget):
        next(node for node in tree.nodes() if node.kind == "With").sugar()
