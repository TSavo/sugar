from __future__ import annotations

from types import MappingProxyType, SimpleNamespace
from dataclasses import replace
import inspect

import pytest

from sugar_lift_py_tests.context_manager_contract import (
    CallParameterV1,
    EffectBoundarySemanticsV1,
    ExceptionInfoBindingV1,
    ExpectsModeV1,
    FormalArgumentProjectionV1,
    KeywordOnlyV1,
    LiteralDefaultV1,
    NoDefaultV1,
    OptionalFormalArgumentProjectionV1,
    PositionalOrKeywordV1,
    RaiseEffectKindV1,
    ProtocolResourceSemanticsV1,
    EnterResultContractV1,
    ExitContractV1,
    NeverSuppressesDispositionV1,
    ReturnTruthinessDispositionV1,
)
from sugar_lift_py_tests.context_manager_resolution import (
    ContextManagerContractRefV1,
    ContextManagerResolutionGapV1,
    NativeDefinitionCoordinateGapV1,
    ImportSignatureV2,
    NativeProtocolSlot,
    ResolvedContractRefsV1,
    SourceDerivedContextManagerRefV1,
    SourceFragmentCoordinateV1,
    TreeConstructionContextV1,
    _hash_json,
)
from sugar_lift_py_tests.ir import PrimitiveSort
from sugar_lift_py_tests.floor import TermValue
from sugar_lift_py_tests.outcome import Complete, ExitSet, Incomplete
from sugar_lift_py_tests.outcome.exit_set import Completed, Halted
from sugar_lift_py_tests.effect import ExpectationNotMetEffect, RaiseEffect
from sugar_lift_py_tests.sugar.with_effect_boundary_sugar import WithEffectBoundarySugar
from sugar_lift_py_tests.sugar.with_resource_sugar import WithResourceSugar
from sugar_lift_py_tests.sugar.with_source_resource_sugar import WithSourceResourceSugar
from sugar_source_tree.panic import SugarNotWritten
from sugar_source_tree.tree import SourceFile


def _cid(char: str) -> str:
    return "blake3-512:" + char * 128


def _coordinate(node) -> SourceFragmentCoordinateV1:
    span = node.line_col_span()
    return SourceFragmentCoordinateV1(
        node.unit.source_cid,
        span.start_line,
        span.start_col,
        span.end_line,
        span.end_col,
    )


def _source_with_resolution(source_identity, resolution, *, native_definitions=None):
    first = SourceFile(source_identity)
    with_node = next(
        node for node in first.nodes() if node.kind in {"With", "AsyncWith"}
    )
    use_site = _coordinate(with_node.items[0].context_expr)
    if callable(resolution):
        resolution = resolution(use_site)
    if native_definitions is None:
        native_definitions = _native_protocol_definitions
    table = ResolvedContractRefsV1(
        catalog_cid=_cid("c"),
        table_cid=_cid("t"),
        by_use_site=MappingProxyType({use_site: resolution}),
        native_definitions=MappingProxyType(
            {} if native_definitions is None else native_definitions(use_site)
        ),
    )
    return SourceFile(
        source_identity,
        construction_context=TreeConstructionContextV1(table),
    )


class _RecordingRefs:
    """Construction-table wrapper proving the one producer door is traversed."""

    def __init__(self, table, definitions):
        self.table = table
        self.definitions = definitions
        self.calls = []

    def require(self, use_site):
        return self.table.require(use_site)

    def require_native_definition(self, receiver, slot):
        self.calls.append((receiver, slot))
        return self.definitions[(receiver, slot)]


def _source_with_recording_refs(source_identity, resolution, definitions):
    first = SourceFile(source_identity)
    with_node = next(
        node for node in first.nodes() if node.kind in {"With", "AsyncWith"}
    )
    use_site = _coordinate(with_node.items[0].context_expr)
    table = ResolvedContractRefsV1(
        catalog_cid=_cid("c"),
        table_cid=_cid("t"),
        by_use_site=MappingProxyType({use_site: resolution(use_site)}),
    )
    recording = _RecordingRefs(table, definitions)
    source = SourceFile(
        source_identity,
        construction_context=TreeConstructionContextV1(recording),
    )
    return source, recording, use_site


def _resolved(use_site) -> ContextManagerContractRefV1:
    semantics = ProtocolResourceSemanticsV1(
        enter=EnterResultContractV1(sort=PrimitiveSort("Value")),
        exit=ExitContractV1(disposition=NeverSuppressesDispositionV1()),
    )
    return ContextManagerContractRefV1(
        resolution_cid=_cid("r"),
        demand_cid=_cid("d"),
        use_site=use_site,
        use_site_cid=_hash_json(use_site.wire()),
        authenticated_import_use_cid=_cid("u"),
        import_binding_cid=_cid("i"),
        construction_context_generation_cid=_cid("g"),
        contract_cid=_cid("m"),
        payload_cid=_cid("p"),
        provenance_cid=_cid("v"),
        distribution_artifact_cid=_cid("a"),
        dependency_artifact_graph_cid=_cid("b"),
        module_source_cid=_cid("s"),
        resolved_definition_cid=_cid("f"),
        manager_construction_cid=_cid("n"),
        enter_testimony_cid=_cid("1"),
        exit_testimony_cid=_cid("2"),
        import_signature=ImportSignatureV2(()),
        semantics=semantics,
    )


def _truthiness_resolved(use_site) -> ContextManagerContractRefV1:
    resolved = _resolved(use_site)
    return ContextManagerContractRefV1(
        **{
            **resolved.__dict__,
            "semantics": ProtocolResourceSemanticsV1(
                enter=EnterResultContractV1(sort=PrimitiveSort("Value")),
                exit=ExitContractV1(disposition=ReturnTruthinessDispositionV1()),
            ),
        }
    )


def _native_protocol_definitions(use_site):
    return {
        (use_site, NativeProtocolSlot.CONTEXT_ENTER): SourceFragmentCoordinateV1(
            _cid("e"), 10, 4, 11, 20
        ),
        (use_site, NativeProtocolSlot.CONTEXT_EXIT): SourceFragmentCoordinateV1(
            _cid("x"), 20, 4, 22, 20
        ),
    }


class _InjectedSourceProtocol:
    """Task-2 stand-in: lifecycle testimony only, never coordinate authority."""

    def enter_resource_outcome(self, ctx=None):
        del ctx
        return Complete(SimpleNamespace(enter_value=TermValue(7)))

    def exit_outcome_for(self, entered, ctx=None):
        del entered, ctx
        return Complete(TermValue(False))


def _source_derived(use_site):
    return SourceDerivedContextManagerRefV1(
        use_site=use_site,
        summary_cid=_cid("s"),
        semantics=ProtocolResourceSemanticsV1(
            enter=EnterResultContractV1(sort=PrimitiveSort("Value")),
            exit=ExitContractV1(disposition=ReturnTruthinessDispositionV1()),
        ),
        import_signature=ImportSignatureV2(()),
        protocol=_InjectedSourceProtocol(),
    )


def test_source_derived_resource_consumes_exactly_two_injected_definition_coordinates():
    source = (
        "from dependency import option_context\n"
        "def f(value):\n"
        "    with option_context('mode.key', value) as entered:\n"
        "        return entered\n"
    )
    first = SourceFile((source, "injected-source-resource.py", _cid("q")))
    use_site = _coordinate(
        next(node for node in first.nodes() if node.kind == "With")
        .items[0]
        .context_expr
    )
    enter = SourceFragmentCoordinateV1(_cid("e"), 10, 4, 11, 20)
    exit_ = SourceFragmentCoordinateV1(_cid("x"), 20, 4, 22, 20)
    tree, recording, _ = _source_with_recording_refs(
        (source, "injected-source-resource.py", _cid("q")),
        _source_derived,
        {
            (use_site, NativeProtocolSlot.CONTEXT_ENTER): enter,
            (use_site, NativeProtocolSlot.CONTEXT_EXIT): exit_,
        },
    )

    function = next(tree.functions()).sugar()
    resource = next(
        statement
        for statement in function.statements
        if isinstance(statement, WithSourceResourceSugar)
    )

    assert recording.calls == [
        (use_site, NativeProtocolSlot.CONTEXT_ENTER),
        (use_site, NativeProtocolSlot.CONTEXT_EXIT),
    ]
    assert resource.enter.native_definition_coordinate == enter
    assert resource.exit.native_definition_coordinate == exit_
    assert resource.body[0].value.slot_id == resource.enter_slot_id
    assert resource.body[0].value.projection == "enter-result"

    def authority_lookup_after_construction(*args, **kwargs):
        raise AssertionError(f"desugar authority lookup: {args!r} {kwargs!r}")

    recording.require_native_definition = authority_lookup_after_construction
    assert resource.desugar() is not None


def test_native_resource_requires_both_authenticated_definition_coordinates():
    source = (
        "from pandas import option_context\n"
        "def f():\n"
        "    with option_context('display.max_rows', 10) as resource:\n"
        "        return resource\n"
    )
    tree = _source_with_resolution(
        (source, "native-resource.py", _cid("q")),
        _truthiness_resolved,
        native_definitions=_native_protocol_definitions,
    )
    boundary = next(node for node in tree.nodes() if node.kind == "With").sugar()
    assert isinstance(boundary, WithResourceSugar)
    enter_definition = SourceFragmentCoordinateV1(_cid("e"), 10, 4, 11, 20)
    exit_definition = SourceFragmentCoordinateV1(_cid("x"), 20, 4, 22, 20)
    assert boundary.enter_definition == enter_definition
    assert boundary.exit_definition == exit_definition
    assert boundary.enter.native_definition_coordinate == enter_definition
    assert boundary.exit.native_definition_coordinate == exit_definition
    assert boundary.enter_slot_id is not None
    assert boundary.enter_slot_id.startswith(boundary.manager_slot_id)


def test_open_name_without_native_definition_stays_typed_loud():
    """A builtin spelling grants no authority when the shared door has a gap."""
    source = "def f(path):\n    with open(path):\n        pass\n"
    tree = _source_with_resolution(
        (source, "native-resource-gap.py", _cid("q")),
        _truthiness_resolved,
        native_definitions=lambda use_site: {},
    )
    with pytest.raises(SugarNotWritten, match="authenticated source definition"):
        next(node for node in tree.nodes() if node.kind == "With").sugar()


def test_open_gap_is_the_builtin_authority_discrimination_arm():
    """The real C builtin asks the door; it is not admitted by spelling."""
    source = "def f(path):\n    with open(path) as resource:\n        return resource\n"
    tree = _source_with_resolution(
        (source, "builtin-open-gap.py", _cid("q")),
        _truthiness_resolved,
        native_definitions=lambda use_site: {},
    )
    with_node = next(node for node in tree.nodes() if node.kind == "With")
    receiver = _coordinate(with_node.items[0].context_expr)
    refs = with_node.unit.construction_context.contract_refs
    enter_gap = refs.require_native_definition(
        receiver, NativeProtocolSlot.CONTEXT_ENTER
    )
    exit_gap = refs.require_native_definition(receiver, NativeProtocolSlot.CONTEXT_EXIT)
    assert enter_gap.slot is NativeProtocolSlot.CONTEXT_ENTER
    assert exit_gap.slot is NativeProtocolSlot.CONTEXT_EXIT
    assert enter_gap.reason.startswith("authenticated source definition")
    assert exit_gap.reason.startswith("authenticated source definition")


def test_recording_door_source_defined_calls_enter_then_exit_and_desugars():
    source = (
        "from pandas import option_context\n"
        "def f():\n"
        "    with option_context('display.max_rows', 10) as resource:\n"
        "        return resource\n"
    )
    source_file = SourceFile((source, "recording-source-defined.py", _cid("q")))
    use_site = _coordinate(
        next(node for node in source_file.nodes() if node.kind == "With")
        .items[0]
        .context_expr
    )
    enter = SourceFragmentCoordinateV1(_cid("e"), 10, 4, 11, 20)
    exit_ = SourceFragmentCoordinateV1(_cid("x"), 20, 4, 22, 20)
    definitions = {
        (use_site, NativeProtocolSlot.CONTEXT_ENTER): enter,
        (use_site, NativeProtocolSlot.CONTEXT_EXIT): exit_,
    }
    source, recording, _ = _source_with_recording_refs(
        (source, "recording-source-defined.py", _cid("q")),
        _truthiness_resolved,
        definitions,
    )
    sugar = next(node for node in source.nodes() if node.kind == "With").sugar()
    assert recording.calls == [
        (use_site, NativeProtocolSlot.CONTEXT_ENTER),
        (use_site, NativeProtocolSlot.CONTEXT_EXIT),
    ]
    assert sugar.enter_definition == enter
    assert sugar.exit_definition == exit_
    assert sugar.enter.native_definition_coordinate == enter
    assert sugar.exit.native_definition_coordinate == exit_
    assert sugar.desugar() is not None


def test_recording_door_builtin_open_calls_both_slots_then_stays_loud():
    source = "def f(path):\n    with open(path) as resource:\n        return resource\n"
    source_file = SourceFile((source, "recording-open.py", _cid("q")))
    use_site = _coordinate(
        next(node for node in source_file.nodes() if node.kind == "With")
        .items[0]
        .context_expr
    )
    definitions = {
        (use_site, NativeProtocolSlot.CONTEXT_ENTER): NativeDefinitionCoordinateGapV1(
            use_site,
            NativeProtocolSlot.CONTEXT_ENTER,
            "authenticated source definition coordinate is not enrolled",
        ),
        (use_site, NativeProtocolSlot.CONTEXT_EXIT): NativeDefinitionCoordinateGapV1(
            use_site,
            NativeProtocolSlot.CONTEXT_EXIT,
            "authenticated source definition coordinate is not enrolled",
        ),
    }
    source, recording, _ = _source_with_recording_refs(
        (source, "recording-open.py", _cid("q")),
        _truthiness_resolved,
        definitions,
    )
    with pytest.raises(SugarNotWritten, match="authenticated source definition"):
        next(node for node in source.nodes() if node.kind == "With").sugar()
    assert len(recording.calls) == 2
    assert recording.calls[0][1] is NativeProtocolSlot.CONTEXT_ENTER
    assert recording.calls[1][1] is NativeProtocolSlot.CONTEXT_EXIT


def test_source_defined_coordinate_and_builtin_gap_are_distinct_door_outcomes():
    """Both authorities use With.sugar; only source testimony constructs."""
    source = (
        "from pandas import option_context\n"
        "def f():\n"
        "    with option_context('display.max_rows', 10) as resource:\n"
        "        return resource\n"
    )
    tree = _source_with_resolution(
        (source, "source-defined-resource.py", _cid("q")),
        _truthiness_resolved,
        native_definitions=_native_protocol_definitions,
    )
    boundary = next(node for node in tree.nodes() if node.kind == "With").sugar()
    expected_enter = SourceFragmentCoordinateV1(_cid("e"), 10, 4, 11, 20)
    expected_exit = SourceFragmentCoordinateV1(_cid("x"), 20, 4, 22, 20)
    assert boundary.enter_definition == expected_enter
    assert boundary.exit_definition == expected_exit
    assert boundary.enter.native_definition_coordinate == expected_enter
    assert boundary.exit.native_definition_coordinate == expected_exit
    assert boundary.desugar() is not None


@pytest.mark.parametrize(
    "missing_slot", [NativeProtocolSlot.CONTEXT_ENTER, NativeProtocolSlot.CONTEXT_EXIT]
)
def test_missing_one_native_definition_is_typed_loud(missing_slot):
    source = (
        "def f(path):\n    with acquire(path) as resource:\n        return resource\n"
    )

    def definitions(use_site):
        values = _native_protocol_definitions(use_site)
        values.pop((use_site, missing_slot))
        return values

    tree = _source_with_resolution(
        (source, "missing-one-native-definition.py", _cid("q")),
        _truthiness_resolved,
        native_definitions=definitions,
    )
    with pytest.raises(SugarNotWritten, match="authenticated source definition"):
        next(node for node in tree.nodes() if node.kind == "With").sugar()


def test_swapped_definition_coordinates_are_rejected_by_authenticated_calls():
    source = (
        "def f(path):\n    with acquire(path) as resource:\n        return resource\n"
    )
    tree = _source_with_resolution(
        (source, "swapped-native-definition.py", _cid("q")),
        _truthiness_resolved,
        native_definitions=_native_protocol_definitions,
    )
    boundary = next(node for node in tree.nodes() if node.kind == "With").sugar()
    with pytest.raises(ValueError, match="not authenticated"):
        replace(
            boundary,
            enter_definition=boundary.exit_definition,
            exit_definition=boundary.enter_definition,
        )


def test_resource_desugar_has_no_second_native_definition_lookup():
    source = inspect.getsource(WithResourceSugar.desugar)
    assert "require_native_definition" not in source


def _function_sugar(source_identity, resolution):
    source = _source_with_resolution(source_identity, resolution)
    return next(source.functions()).sugar()


def _effect_resolved(use_site) -> ContextManagerContractRefV1:
    signature = ImportSignatureV2(
        (
            CallParameterV1(
                "expected_exception",
                PrimitiveSort("Value"),
                PositionalOrKeywordV1(),
                True,
                NoDefaultV1(),
            ),
            CallParameterV1(
                "match",
                PrimitiveSort("String"),
                KeywordOnlyV1(),
                False,
                LiteralDefaultV1({"kind": "ctor", "name": "None", "args": []}),
            ),
        )
    )
    return ContextManagerContractRefV1(
        resolution_cid=_cid("r"),
        demand_cid=_cid("d"),
        use_site=use_site,
        use_site_cid=_hash_json(use_site.wire()),
        authenticated_import_use_cid=_cid("u"),
        import_binding_cid=_cid("i"),
        construction_context_generation_cid=_cid("g"),
        contract_cid=_cid("m"),
        payload_cid=_cid("p"),
        provenance_cid=_cid("v"),
        distribution_artifact_cid=_cid("a"),
        dependency_artifact_graph_cid=_cid("b"),
        module_source_cid=_cid("s"),
        resolved_definition_cid=_cid("f"),
        manager_construction_cid=_cid("n"),
        enter_testimony_cid=_cid("1"),
        exit_testimony_cid=_cid("2"),
        import_signature=signature,
        semantics=EffectBoundarySemanticsV1(
            ExpectsModeV1(),
            RaiseEffectKindV1(),
            FormalArgumentProjectionV1(0),
            OptionalFormalArgumentProjectionV1(1),
            ExceptionInfoBindingV1(),
        ),
    )


@pytest.mark.parametrize(
    ("body", "result_type", "effect_type"),
    [
        ('raise ValueError("boom")', Completed, None),
        ('raise TypeError("boom")', Halted, RaiseEffect),
        ("pass", Halted, ExpectationNotMetEffect),
    ],
)
def test_effect_boundary_projects_real_call_actuals_and_routes_exitset(
    tmp_path, body, result_type, effect_type
):
    path = tmp_path / "pytest_boundary.py"
    path.write_text(
        "from pytest import raises as expect_raises\n"
        "def f():\n"
        '    with expect_raises(ValueError, match="boom"):\n'
        f"        {body}\n"
    )
    from sugar_lift_python_source.source_oracle import path_source

    sugar = _function_sugar(path_source(str(path)), _effect_resolved)
    boundary = next(
        statement
        for statement in sugar.statements
        if isinstance(statement, WithEffectBoundarySugar)
    )
    outcome = boundary.desugar()
    assert isinstance(outcome, ExitSet)
    assert len(outcome.exits) == 1
    face = outcome.exits[0]
    if result_type is Completed:
        assert isinstance(face, Completed)
    else:
        assert isinstance(face, Halted)
        assert isinstance(face.effect, effect_type)


def test_effect_boundary_as_name_exports_through_assign(tmp_path, monkeypatch):
    """The post-With binding uses Assign's one lexical binding algebra."""
    path = tmp_path / "observed.py"
    path.write_text(
        "from pytest import raises\n"
        "def f():\n"
        "    with raises(ValueError) as info:\n"
        "        raise ValueError('cannot convert')\n"
        "    return info.value\n"
    )
    from sugar_lift_python_source.source_oracle import path_source
    from sugar_source_tree.nodes import Assign

    seen = []
    original = Assign.substitution_binding

    def observe(self, scope):
        if self.value.kind == "ObservationRef":
            seen.append((self.targets[0].kind, self.value.projection))
        return original(self, scope)

    monkeypatch.setattr(Assign, "substitution_binding", observe)
    _function_sugar(path_source(str(path)), _effect_resolved)
    assert seen == [("Name", "exception_info")]


def _effect_boundary_face(tmp_path, source):
    path = tmp_path / "identity_boundary.py"
    path.write_text(source)
    from sugar_lift_python_source.source_oracle import path_source

    sugar = _function_sugar(path_source(str(path)), _effect_resolved)
    boundary = next(
        statement
        for statement in sugar.statements
        if isinstance(statement, WithEffectBoundarySugar)
    )
    outcome = boundary.desugar()
    assert isinstance(outcome, ExitSet)
    assert len(outcome.exits) == 1
    return outcome.exits[0]


def test_effect_boundary_matches_builtin_exception_alias_by_identity(tmp_path):
    face = _effect_boundary_face(
        tmp_path,
        "from builtins import ValueError as VE\n"
        "from pytest import raises\n"
        "def f():\n"
        "    with raises(VE):\n"
        "        raise ValueError('boom')\n",
    )
    assert isinstance(face, Completed)


def test_effect_boundary_does_not_match_distinct_same_spelling_type(tmp_path):
    face = _effect_boundary_face(
        tmp_path,
        "from builtins import ValueError as BuiltinVE\n"
        "from pytest import raises\n"
        "class ValueError(Exception):\n"
        "    pass\n"
        "def f():\n"
        "    with raises(ValueError):\n"
        "        raise BuiltinVE('boom')\n",
    )
    assert isinstance(face, Halted)
    assert isinstance(face.effect, RaiseEffect)


def test_effect_boundary_with_formal_expected_type_stays_symbolic(tmp_path):
    """A formal expected type is not a ground identity — keep both faces.

    ``with raises(expected):`` when ``expected`` is a parameter cannot collapse
    to a single authenticated exception-type identity. Desugar must stay a
    multi-arm ExitSet under the symbolic type predicate, never invent a green
    sole face and never panic as missing identity sugar.
    """
    path = tmp_path / "unknown_identity.py"
    path.write_text(
        "from pytest import raises\n"
        "def f(expected):\n"
        "    with raises(expected):\n"
        "        raise ValueError('boom')\n"
    )
    from sugar_lift_python_source.source_oracle import path_source
    from sugar_lift_py_tests.outcome import Completed, ExitSet, Halted

    sugar = _function_sugar(path_source(str(path)), _effect_resolved)
    boundary = next(
        statement
        for statement in sugar.statements
        if isinstance(statement, WithEffectBoundarySugar)
    )
    outcome = boundary.desugar()
    assert isinstance(outcome, ExitSet)
    assert len(outcome.exits) >= 2
    assert any(isinstance(exit_, Completed) for exit_ in outcome.exits)
    assert any(isinstance(exit_, Halted) for exit_ in outcome.exits)


def test_authenticated_ref_constructs_resource_once_and_binds_enter_result(
    tmp_path, monkeypatch
):
    path = tmp_path / "consumer.py"
    path.write_text(
        "from dependency import manager\n"
        "def f():\n"
        "    with manager() as entered:\n"
        "        return entered\n"
    )
    from sugar_lift_python_source.source_oracle import path_source
    from sugar_source_tree.nodes import Call

    manager_constructions = []
    original_call_sugar = Call.sugar

    def count_original_manager(self):
        if self.func.kind == "Name" and self.func.id == "manager":
            manager_constructions.append(self)
        return original_call_sugar(self)

    monkeypatch.setattr(Call, "sugar", count_original_manager)

    # Authenticated contract-ref path only — raw-AST exit_disposition_proof is gone.
    sugar = _function_sugar(path_source(str(path)), _resolved)
    resource = next(
        statement
        for statement in sugar.statements
        if isinstance(statement, WithResourceSugar)
    )
    assert resource.contract_ref.contract_cid == _cid("m")
    assert resource.contract_ref.payload_cid == _cid("p")
    assert resource.enter_slot_id == f"{resource.manager_slot_id}#enter_result"
    assert len(manager_constructions) == 1
    bound_return = resource.body[0]
    assert bound_return.value.slot_id == resource.enter_slot_id
    assert bound_return.value.projection == "enter-result"


@pytest.mark.parametrize(
    ("body", "incoming_kind"),
    [
        ("pass", Completed),
        ('raise ValueError("boom")', Halted),
    ],
)
def test_real_resource_reproducer_closes_every_exitset_face(
    tmp_path, monkeypatch, body, incoming_kind
):
    """An authenticated provider resource closes after completion and halt."""
    path = tmp_path / f"resource_{incoming_kind.__name__.lower()}.py"
    path.write_text(
        "from arbitrary_provider import acquire\n"
        "def f():\n"
        "    with acquire():\n"
        f"        {body}\n"
    )
    from sugar_lift_python_source.source_oracle import path_source

    resource = next(
        statement
        for statement in _function_sugar(path_source(str(path)), _resolved).statements
        if isinstance(statement, WithResourceSugar)
    )
    # Observed through `and_exit` -- the ONE algebra the resource contract
    # routes through. Pinning `and_finally` here would pin a mechanism; the law
    # is that every body face reaches the contract.
    original = ExitSet.and_exit
    seen = []

    def observe(incoming, exit_es, *, disposition):
        seen.append(type(incoming.exits[0]))
        return original(incoming, exit_es, disposition=disposition)

    monkeypatch.setattr(ExitSet, "and_exit", observe)
    resource.desugar()

    assert seen == [incoming_kind]


def test_unsupported_semantics_gap_does_not_construct_resource(tmp_path):
    path = tmp_path / "unsupported.py"
    path.write_text(
        "from dependency import manager\n"
        "def f():\n"
        "    with manager():\n"
        "        pass\n"
    )
    from sugar_lift_python_source.source_oracle import path_source

    def unsupported(use_site):
        return ContextManagerResolutionGapV1(
            demand_cid=_cid("d"),
            use_site=use_site,
            target_symbol="context-manager:dependency.manager",
            kind="unsupported-cm-schema",
            candidate_member_cids=(_cid("m"),),
        )

    with pytest.raises(SugarNotWritten) as caught:
        _function_sugar(path_source(str(path)), unsupported)
    assert type(caught.value).__name__ == "ContextManagerResolutionConstructionGap"
    assert caught.value.kind == "unsupported-cm-schema"


def test_async_with_stays_typed_loud_even_with_sync_ref(tmp_path):
    path = tmp_path / "async_manager.py"
    path.write_text(
        "from dependency import manager\n"
        "async def f():\n"
        "    async with manager():\n"
        "        pass\n"
    )
    from sugar_lift_python_source.source_oracle import path_source

    source = _source_with_resolution(path_source(str(path)), _resolved)
    async_with = next(node for node in source.nodes() if node.kind == "AsyncWith")
    with pytest.raises(SugarNotWritten) as caught:
        async_with.sugar()
    assert type(caught.value).__name__ == "AsyncContextManagerUnsupported"


def test_multiple_items_nest_and_store_binding_target_constructs(tmp_path):
    """Multi-item With is no longer a gap: it nests into single-item Withs.

    ``MultipleContextManagerItems`` was the shell that watched this; it is
    deleted, because the illegal shape (a multi-manager With reaching the
    resource router) is now unconstructable — construction rewrites it into
    Python's own nested spelling first.

    The non-Name binding half of this test used to assert
    ``UnsupportedWithBindingTarget``. That refusal is retired for authenticated
    ProtocolResource sites: the as-clause is Python's own assignment, so
    ``With._bind_store_target`` rewrites a store target into
    ``<target> = ObservationRef(enter_slot)`` as the first body statement and
    inherits ``Assign``'s target totality. The law is now owned in full by
    ``test_with_store_binding_target.py``; this arm keeps the nesting law and
    pins that the two rewrites compose.
    """
    from sugar_lift_python_source.source_oracle import path_source

    multiple = tmp_path / "multiple.py"
    multiple.write_text(
        "from dependency import manager\n"
        "def f():\n"
        "    with manager(), manager():\n"
        "        pass\n"
    )
    first = SourceFile(path_source(str(multiple)))
    with_node = next(node for node in first.nodes() if node.kind == "With")
    rows = {
        _coordinate(item.context_expr): _resolved(_coordinate(item.context_expr))
        for item in with_node.items
    }
    native_definitions = {}
    for use_site in rows:
        native_definitions.update(_native_protocol_definitions(use_site))
    context = TreeConstructionContextV1(
        ResolvedContractRefsV1(
            _cid("c"),
            _cid("t"),
            MappingProxyType(rows),
            MappingProxyType(native_definitions),
        )
    )
    source = SourceFile(path_source(str(multiple)), construction_context=context)
    nested = next(source.functions()).sugar()
    chain = []

    def _walk(node):
        if isinstance(node, WithResourceSugar):
            chain.append(node)
            for child in node.body:
                _walk(child)
            return
        for field in ("body", "statements", "entries"):
            for child in getattr(node, field, ()) or ():
                _walk(child)

    _walk(nested)
    assert len(chain) == 2
    assert chain[1] in chain[0].body

    # Both rewrites compose: two managers nest, and the inner one's store
    # target becomes an ordinary assignment at the head of its body.
    target = tmp_path / "target.py"
    target.write_text(
        "from dependency import manager\n"
        "def f():\n"
        "    with manager(), manager() as (left, right):\n"
        "        pass\n"
    )
    probe = SourceFile(path_source(str(target)))
    node = next(n for n in probe.nodes() if n.kind == "With")
    rows = {
        _coordinate(item.context_expr): _resolved(_coordinate(item.context_expr))
        for item in node.items
    }
    native_definitions = {}
    for use_site in rows:
        native_definitions.update(_native_protocol_definitions(use_site))
    composed = SourceFile(
        path_source(str(target)),
        construction_context=TreeConstructionContextV1(
            ResolvedContractRefsV1(
                _cid("c"),
                _cid("t"),
                MappingProxyType(rows),
                MappingProxyType(native_definitions),
            )
        ),
    )
    chain = []
    _walk(next(composed.functions()).sugar())
    outer, inner = chain[0], chain[1]
    assert inner in outer.body
    assert outer.enter_slot_id is None, "the outer manager names no target"
    assert inner.enter_slot_id == f"{inner.manager_slot_id}#enter_result"
