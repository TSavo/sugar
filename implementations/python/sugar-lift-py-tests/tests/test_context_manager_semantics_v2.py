import json
import pytest

from sugar_lift_py_tests.context_manager_contract import (
    ContextManagerContractError,
    EffectBoundarySemanticsV1,
    ExceptionInfoBindingV1,
    ExpectsModeV1,
    FormalArgumentProjectionV1,
    ImportSignatureV2,
    CallParameterV1,
    KeywordOnlyV1,
    PositionalOrKeywordV1,
    NoMessagePatternV1,
    OptionalFormalArgumentProjectionV1,
    ProtocolResourceSemanticsV1,
    ReturnTruthinessDispositionV1,
    TotalCompletionV1,
    EnterResultContractV1,
    ExitContractV1,
    RaiseEffectKindV1,
    decode_context_manager_semantics_v1,
    semantics_to_value,
    publish_context_manager_contract,
    publish_effect_boundary_context_manager_contract,
    decode_context_manager_contract,
)
from sugar_lift_py_tests.canonicalizer import encode_jcs
from sugar_lift_py_tests.ir import PrimitiveSort
from sugar_lift_py_tests.signing import Signer
from sugar_lift_py_tests.kit_rpc import ContextManagerContractIrV1


def _resource(disposition=ReturnTruthinessDispositionV1()):
    return ProtocolResourceSemanticsV1(
        enter=EnterResultContractV1(
            sort=PrimitiveSort("Value"), completion=TotalCompletionV1()
        ),
        exit=ExitContractV1(
            disposition=disposition, completion=TotalCompletionV1()
        ),
    )


def _effect_boundary():
    return EffectBoundarySemanticsV1(
        mode=ExpectsModeV1(),
        effect_kind=RaiseEffectKindV1(),
        expected_type_operand=FormalArgumentProjectionV1(0),
        message_pattern_operand=OptionalFormalArgumentProjectionV1(1),
        binding=ExceptionInfoBindingV1(),
    )


def _wire(value):
    return json.loads(encode_jcs(semantics_to_value(value)))


def test_protocol_resource_return_truthiness_round_trips_closed_decoder():
    value = _resource()
    assert decode_context_manager_semantics_v1(_wire(value)) == value


def _signature():
    return ImportSignatureV2((
        CallParameterV1("expected_exception", PrimitiveSort("Value"), PositionalOrKeywordV1(), True),
        CallParameterV1("match", PrimitiveSort("String"), KeywordOnlyV1(), False),
    ))


def test_effect_boundary_round_trips_by_formal_position_without_baked_values():
    wire = _wire(_effect_boundary())
    assert wire["kind"] == "effect-boundary"
    assert "ValueError" not in str(wire)
    assert decode_context_manager_semantics_v1(wire, _signature()) == _effect_boundary()


@pytest.mark.parametrize(
    "mutation",
    [
        lambda wire: wire.update(kind="future-boundary"),
        lambda wire: wire.update(extra=True),
        lambda wire: wire["enter"].update(completion={"kind": "sometimes"}),
        lambda wire: wire["exit"]["disposition"].update(kind="future-disposition"),
    ],
)
def test_unknown_or_cross_schema_resource_fields_are_loud(mutation):
    wire = _wire(_resource())
    mutation(wire)
    with pytest.raises(ContextManagerContractError):
        decode_context_manager_semantics_v1(wire)


def test_effect_boundary_negative_formal_index_is_loud_before_pending_holes():
    wire = _wire(_effect_boundary())
    wire["matcher"]["expectedTypeOperand"]["index"] = -1
    with pytest.raises(ContextManagerContractError, match="nonnegative"):
        decode_context_manager_semantics_v1(wire, _signature())


def test_effect_boundary_selector_role_and_sort_mismatch_is_loud():
    wire = _wire(_effect_boundary())
    wire["matcher"]["expectedTypeOperand"]["index"] = 1
    with pytest.raises(ContextManagerContractError, match="required Value"):
        decode_context_manager_semantics_v1(wire, _signature())


def test_effect_boundary_unknown_field_is_loud():
    wire = _wire(_effect_boundary())
    wire["matcher"]["extra"] = True
    with pytest.raises(ContextManagerContractError, match="malformed effect-boundary matcher"):
        decode_context_manager_semantics_v1(wire, _signature())


def test_effect_boundary_seals_and_recomputes_payload_cid_through_existing_envelope():
    sealed = publish_context_manager_contract(
        bridge_source_symbol="context-manager:any_provider.renamed",
        import_signature=_signature(),
        semantics=_effect_boundary(),
        source_warrants=(),
        signer=Signer(bytes(range(32)), "fixture-provider"),
        declared_at="2026-07-23T00:00:00.000Z",
    )
    decoded = decode_context_manager_contract(sealed.canonical_bytes, sealed.cid)
    assert decoded.semantics == _effect_boundary()
    assert decoded.payload_cid.startswith("blake3-512:")


def test_provider_publishes_effect_boundary_through_named_production_door():
    sealed = publish_effect_boundary_context_manager_contract(
        bridge_source_symbol="context-manager:fixture_provider.expect",
        import_signature=_signature(),
        mode=ExpectsModeV1(),
        effect_kind=RaiseEffectKindV1(),
        expected_type_operand=FormalArgumentProjectionV1(0),
        message_pattern_operand=OptionalFormalArgumentProjectionV1(1),
        binding=ExceptionInfoBindingV1(),
        source_warrants=(),
        signer=Signer(bytes(range(32)), "fixture-provider"),
        declared_at="2026-07-23T00:00:00.000Z",
    )
    decoded = decode_context_manager_contract(sealed.canonical_bytes, sealed.cid)
    assert decoded.bridge_source_symbol == "context-manager:fixture_provider.expect"
    assert decoded.import_signature == _signature()
    assert decoded.semantics == _effect_boundary()


def test_provider_kit_effect_boundary_member_uses_the_closed_union_payload():
    member = ContextManagerContractIrV1.effect_boundary(
        bridge_source_symbol="context-manager:fixture_provider.expect",
        import_signature=_signature(),
        mode=ExpectsModeV1(),
        effect_kind=RaiseEffectKindV1(),
        expected_type_operand=FormalArgumentProjectionV1(0),
        message_pattern_operand=OptionalFormalArgumentProjectionV1(1),
        binding=ExceptionInfoBindingV1(),
        source_warrants=(),
    )
    wire = member.to_rpc_with_term_table(None)
    assert wire["payload"] == _wire(_effect_boundary())
    assert wire["importSignature"]["parameters"][0]["sort"] == {
        "kind": "primitive", "name": "Value",
    }
    assert wire["importSignature"]["parameters"][1]["sort"] == {
        "kind": "primitive", "name": "String",
    }


def test_effect_boundary_selectors_are_positions_not_privileged_formal_names():
    renamed = ImportSignatureV2((
        CallParameterV1("arbitrary_expected", PrimitiveSort("Value"), PositionalOrKeywordV1(), True),
        CallParameterV1("arbitrary_pattern", PrimitiveSort("String"), KeywordOnlyV1(), False),
    ))
    assert decode_context_manager_semantics_v1(_wire(_effect_boundary()), renamed) == _effect_boundary()


def test_effect_boundary_lying_selector_for_an_unrelated_formal_is_loud():
    signature = ImportSignatureV2((
        CallParameterV1("unrelated", PrimitiveSort("String"), PositionalOrKeywordV1(), True),
        CallParameterV1("expected", PrimitiveSort("Value"), PositionalOrKeywordV1(), True),
        CallParameterV1("pattern", PrimitiveSort("String"), KeywordOnlyV1(), False),
    ))
    with pytest.raises(ContextManagerContractError, match="required Value"):
        decode_context_manager_semantics_v1(_wire(_effect_boundary()), signature)


def test_effect_boundary_publisher_does_not_sign_a_lying_selector():
    with pytest.raises(ContextManagerContractError, match="required Value"):
        publish_effect_boundary_context_manager_contract(
            bridge_source_symbol="context-manager:fixture_provider.expect",
            import_signature=ImportSignatureV2((
                CallParameterV1("unrelated", PrimitiveSort("String"), PositionalOrKeywordV1(), True),
            )),
            mode=ExpectsModeV1(),
            effect_kind=RaiseEffectKindV1(),
            expected_type_operand=FormalArgumentProjectionV1(0),
            message_pattern_operand=NoMessagePatternV1(),
            binding=ExceptionInfoBindingV1(),
            source_warrants=(),
            signer=Signer(bytes(range(32)), "fixture-provider"),
            declared_at="2026-07-23T00:00:00.000Z",
        )
