from __future__ import annotations

import csv
import importlib.metadata
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
    ConstructedCallActualV1,
    ConstructedManagerBehaviorV1,
    ManagerConstructionGapV1,
    construct_manager_behavior,
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
from sugar_source_tree.nodes import Call, ClassDef, Constant
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
    """A free (non-local, non-builtin) name remains opaque-call-target."""
    graph, resolved, actual, call_site = _resolved(
        tmp_path, "def make_guard(expected):\n    return missing_helper(expected)\n"
    )

    result = construct_manager_behavior(
        resolved, graph=graph, actuals=(actual,), call_site=call_site
    )

    assert isinstance(result, ManagerConstructionGapV1)
    assert result.kind == "opaque-call-target"
    assert result.detail == "missing_helper"


def test_builtin_named_call_is_not_false_opaque_call_target(tmp_path):
    """Python builtin names are not free-name opaques at frame resolution.

    ``len`` is in the builtin temporal. Frame scan must not abort as
    ``opaque-call-target:len``; construction may still refuse later when the
    builtin is not yet a reducible force_floor (stage-keyed gap).
    """
    graph, resolved, actual, call_site = _resolved(
        tmp_path, "def make_guard(expected):\n    return len(expected)\n"
    )

    result = construct_manager_behavior(
        resolved, graph=graph, actuals=(actual,), call_site=call_site
    )

    assert isinstance(result, ManagerConstructionGapV1)
    assert result.kind != "opaque-call-target", result
    assert result.kind in {"non-manager-result", "force-floor"}, result


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
    from sugar_lift_py_tests.gap.panic import ConstructionPanic

    behavior = construct_manager_behavior(
        resolved, graph=graph, actuals=(actual,), call_site=call_site
    )
    assert isinstance(behavior, ConstructedManagerBehaviorV1)
    protocol = construct_manager_protocol(behavior, exit_face_id="boundary-face")
    assert isinstance(protocol, ConstructedManagerProtocolV1)

    with pytest.raises(ConstructionPanic, match="Python type operand"):
        derive_manager_summary(protocol)


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


def test_installed_source_boundary_with_opaque_builtin_verdict_stays_loud(tmp_path):
    consumer = (
        "import pytest\n"
        "def use_boundary():\n"
        "    with pytest.raises(ValueError):\n"
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
    populate_source_derived_resource_refs(tree, root=tmp_path, path=path)

    resolution = next(iter(context.source_derived_contract_refs.values()))
    assert isinstance(resolution, ContextManagerResolutionGapV1)
    # Stage-keyed residual — not a silent generic no-derived-contract, and not
    # a resource-membrane admission. pytest.raises stays typed-loud until its
    # free-name / force-floor chain constructs without vendor arms.
    assert resolution.kind != "derived-contract"
    assert resolution.target_symbol and "raises" in resolution.target_symbol
    assert (
        resolution.kind.startswith("opaque-call-target")
        or resolution.kind.startswith("force-floor")
        or resolution.kind.startswith("non-manager-result")
        or resolution.kind.startswith("protocol-construction")
        or resolution.kind.startswith("summary-derivation")
        or resolution.kind == "no-derived-contract"
    ), resolution.kind


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
    from sugar_lift_py_tests.context_manager_resolution import TreeConstructionContextV1

    context = TreeConstructionContextV1.for_source_call_construction()
    tree = SourceFile(
        (consumer, str(path), blake3_512_of(consumer.encode("utf-8"))),
        construction_context=context,
    )
    graphs = {}
    from sugar_source_tree.panic import SugarNotWritten

    with pytest.raises(SugarNotWritten, match="DynamicUnpackAssignSugar"):
        populate_source_derived_resource_refs(
            tree, root=tmp_path, path=path, artifact_graph_cache=graphs
        )

    graph = graphs["contextlib"]
    assert graph.artifact_kind == "stdlib"
    assert "contextlib" in graph.modules


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
        "    def __exit__(self, effect_type, effect, traceback):\n" + exit_body +
        "def make_guard(expected):\n"
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
