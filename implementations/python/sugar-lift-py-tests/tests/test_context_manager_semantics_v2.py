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
    VariadicPositionalV1,
    VariadicKeywordV1,
    NoDefaultV1,
    LiteralDefaultV1,
    PositionalOrKeywordV1,
    NoMessagePatternV1,
    OptionalFormalArgumentProjectionV1,
    VariadicPositionalElementProjectionV1,
    VariadicKeywordEntryProjectionV1,
    VariadicPositionalActualV1,
    VariadicKeywordActualV1,
    ConstructedOperandOccurrenceV1,
    project_formal_selector_v1,
    ProtocolResourceSemanticsV1,
    ReturnTruthinessDispositionV1,
    TotalCompletionV1,
    EnterResultContractV1,
    ExitContractV1,
    RaiseEffectKindV1,
    decode_context_manager_semantics_v1,
    decode_import_signature_v2,
    import_signature_to_value,
    semantics_to_value,
)
from sugar_lift_py_tests.canonicalizer import encode_jcs
from sugar_lift_py_tests.ir import PrimitiveSort


def _cid(fill: str) -> str:
    return "blake3-512:" + fill * 128


def _resource(disposition=ReturnTruthinessDispositionV1()):
    return ProtocolResourceSemanticsV1(
        enter=EnterResultContractV1(
            sort=PrimitiveSort("Value"), completion=TotalCompletionV1()
        ),
        exit=ExitContractV1(disposition=disposition, completion=TotalCompletionV1()),
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
    return ImportSignatureV2(
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
    wire["matcher"]["expectedTypeOperand"]["parameterIndex"] = -1
    with pytest.raises(ContextManagerContractError, match="nonnegative"):
        decode_context_manager_semantics_v1(wire, _signature())


def test_effect_boundary_selector_role_and_sort_mismatch_is_loud():
    wire = _wire(_effect_boundary())
    wire["matcher"]["expectedTypeOperand"]["parameterIndex"] = 1
    with pytest.raises(ContextManagerContractError, match="Value formal"):
        decode_context_manager_semantics_v1(wire, _signature())


def test_effect_boundary_unknown_field_is_loud():
    wire = _wire(_effect_boundary())
    wire["matcher"]["extra"] = True
    with pytest.raises(
        ContextManagerContractError, match="malformed effect-boundary matcher"
    ):
        decode_context_manager_semantics_v1(wire, _signature())


def test_effect_boundary_selectors_are_positions_not_privileged_formal_names():
    renamed = ImportSignatureV2(
        (
            CallParameterV1(
                "arbitrary_expected",
                PrimitiveSort("Value"),
                PositionalOrKeywordV1(),
                True,
                NoDefaultV1(),
            ),
            CallParameterV1(
                "arbitrary_pattern",
                PrimitiveSort("String"),
                KeywordOnlyV1(),
                False,
                LiteralDefaultV1({"kind": "ctor", "name": "None", "args": []}),
            ),
        )
    )
    assert (
        decode_context_manager_semantics_v1(_wire(_effect_boundary()), renamed)
        == _effect_boundary()
    )


def test_effect_boundary_lying_selector_for_an_unrelated_formal_is_loud():
    signature = ImportSignatureV2(
        (
            CallParameterV1(
                "unrelated",
                PrimitiveSort("String"),
                PositionalOrKeywordV1(),
                True,
                NoDefaultV1(),
            ),
            CallParameterV1(
                "expected",
                PrimitiveSort("Value"),
                PositionalOrKeywordV1(),
                True,
                NoDefaultV1(),
            ),
            CallParameterV1(
                "pattern",
                PrimitiveSort("String"),
                KeywordOnlyV1(),
                False,
                LiteralDefaultV1({"kind": "ctor", "name": "None", "args": []}),
            ),
        )
    )
    with pytest.raises(ContextManagerContractError, match="Value formal"):
        decode_context_manager_semantics_v1(_wire(_effect_boundary()), signature)


def test_variadic_signature_and_selectors_round_trip_exhaustively():
    signature = ImportSignatureV2(
        (
            CallParameterV1(
                "args",
                PrimitiveSort("Value"),
                VariadicPositionalV1(),
                False,
                NoDefaultV1(),
            ),
            CallParameterV1(
                "kwargs",
                PrimitiveSort("Value"),
                VariadicKeywordV1(),
                False,
                NoDefaultV1(),
            ),
        )
    )
    assert (
        decode_import_signature_v2(
            json.loads(encode_jcs(import_signature_to_value(signature)))
        )
        == signature
    )

    positional = VariadicPositionalElementProjectionV1(0, 2)
    keyword = VariadicKeywordEntryProjectionV1(1, "match")
    semantics = EffectBoundarySemanticsV1(
        ExpectsModeV1(),
        RaiseEffectKindV1(),
        positional,
        keyword,
        ExceptionInfoBindingV1(),
    )
    assert _wire(semantics)["matcher"] == {
        "effectKind": {"kind": "raise"},
        "expectedTypeOperand": {
            "kind": "variadic-positional-element",
            "parameterIndex": 0,
            "elementIndex": 2,
        },
        "messagePatternOperand": {
            "kind": "variadic-keyword-entry",
            "parameterIndex": 1,
            "keyword": "match",
        },
    }
    assert decode_context_manager_semantics_v1(_wire(semantics), signature) == semantics


def test_ensure_clean_variadic_keyword_pack_projects_real_constructed_entries():
    signature = ImportSignatureV2(
        (
            CallParameterV1(
                "filename",
                PrimitiveSort("Value"),
                PositionalOrKeywordV1(),
                False,
                LiteralDefaultV1({"kind": "ctor", "name": "None", "args": []}),
            ),
            CallParameterV1(
                "return_filelike",
                PrimitiveSort("Bool"),
                PositionalOrKeywordV1(),
                False,
                LiteralDefaultV1(
                    {
                        "kind": "const",
                        "value": False,
                        "sort": {"kind": "primitive", "name": "Bool"},
                    }
                ),
            ),
            CallParameterV1(
                "kwargs",
                PrimitiveSort("Value"),
                VariadicKeywordV1(),
                False,
                NoDefaultV1(),
            ),
        )
    )
    assert isinstance(signature.parameters[2].passing, VariadicKeywordV1)
    from sugar_lift_py_tests.context_manager_resolution import (
        SourceFragmentCoordinateV1,
    )
    from sugar_lift_py_tests.sugar.name_sugar import NameSugar

    first = NameSugar("first", None)
    second = NameSugar("second", None)
    pack = VariadicKeywordActualV1(
        2,
        (
            ConstructedOperandOccurrenceV1(
                SourceFragmentCoordinateV1(_cid("1"), 1, 0, 1, 5), "foo", first
            ),
            ConstructedOperandOccurrenceV1(
                SourceFragmentCoordinateV1(_cid("2"), 2, 0, 2, 6), "bar", second
            ),
        ),
    )
    assert (
        project_formal_selector_v1(
            VariadicKeywordEntryProjectionV1(2, "bar"),
            fixed_actuals={},
            variadic_positional_actuals={},
            variadic_keyword_actuals={2: pack},
        )
        is second
    )


def test_variadic_parameter_with_non_value_sort_is_loud():
    with pytest.raises(ContextManagerContractError, match="requires Value"):
        CallParameterV1(
            "kwargs",
            PrimitiveSort("String"),
            VariadicKeywordV1(),
            False,
            NoDefaultV1(),
        )


def test_real_positional_and_mapping_pack_projections_preserve_occurrence_identity():
    from sugar_lift_py_tests.context_manager_resolution import (
        SourceFragmentCoordinateV1,
    )
    from sugar_lift_py_tests.sugar.name_sugar import NameSugar

    positional_value = NameSugar("positional", None)
    mapping_value = NameSugar("mapping", None)
    positional = VariadicPositionalActualV1(
        0,
        (
            ConstructedOperandOccurrenceV1(
                SourceFragmentCoordinateV1(_cid("3"), 1, 0, 1, 10),
                None,
                positional_value,
            ),
        ),
    )
    mapping = VariadicKeywordActualV1(
        1,
        (
            ConstructedOperandOccurrenceV1(
                SourceFragmentCoordinateV1(_cid("4"), 2, 0, 2, 12), "key", mapping_value
            ),
        ),
    )
    assert (
        project_formal_selector_v1(
            VariadicPositionalElementProjectionV1(0, 0),
            fixed_actuals={},
            variadic_positional_actuals={0: positional},
            variadic_keyword_actuals={1: mapping},
        )
        is positional_value
    )
    assert (
        project_formal_selector_v1(
            VariadicKeywordEntryProjectionV1(1, "key"),
            fixed_actuals={},
            variadic_positional_actuals={0: positional},
            variadic_keyword_actuals={1: mapping},
        )
        is mapping_value
    )
    with pytest.raises(ContextManagerContractError, match="out of range"):
        project_formal_selector_v1(
            VariadicPositionalElementProjectionV1(0, 1),
            fixed_actuals={},
            variadic_positional_actuals={0: positional},
            variadic_keyword_actuals={},
        )
    with pytest.raises(ContextManagerContractError, match="unique real keywords"):
        VariadicKeywordActualV1(
            1,
            (
                ConstructedOperandOccurrenceV1(
                    SourceFragmentCoordinateV1(_cid("5"), 3, 0, 3, 4),
                    "same",
                    NameSugar("one", None),
                ),
                ConstructedOperandOccurrenceV1(
                    SourceFragmentCoordinateV1(_cid("6"), 4, 0, 4, 4),
                    "same",
                    NameSugar("two", None),
                ),
            ),
        )


def test_source_call_variadic_projection_returns_the_exact_constructed_child(tmp_path):
    from sugar_lift_python_source.source_oracle import path_source
    from sugar_lift_py_tests.context_manager_resolution import (
        SourceFragmentCoordinateV1,
    )
    from sugar_source_tree.nodes import Call
    from sugar_source_tree.tree import SourceFile

    path = tmp_path / "actual.py"
    path.write_text("def f():\n    ensure_clean(foo=side_effect())\n")
    call = next(
        node
        for node in SourceFile(path_source(str(path))).nodes()
        if isinstance(node, Call) and getattr(node.func, "id", None) == "ensure_clean"
    )
    call_sugar = call.sugar()
    constructed_child = call_sugar.keywords[0][1]
    span = call.keywords[0].value.line_col_span()
    occurrence = SourceFragmentCoordinateV1(
        call.unit.source_cid,
        span.start_line,
        span.start_col,
        span.end_line,
        span.end_col,
    )
    pack = VariadicKeywordActualV1(
        2, (ConstructedOperandOccurrenceV1(occurrence, "foo", constructed_child),)
    )

    projected = project_formal_selector_v1(
        VariadicKeywordEntryProjectionV1(2, "foo"),
        fixed_actuals={},
        variadic_positional_actuals={},
        variadic_keyword_actuals={2: pack},
    )

    assert projected is constructed_child


def test_fabricated_variadic_occurrence_wrapper_is_loud():
    from sugar_lift_py_tests.context_manager_resolution import (
        SourceFragmentCoordinateV1,
    )
    from sugar_lift_py_tests.sugar.name_sugar import NameSugar

    with pytest.raises(
        ContextManagerContractError, match="constructed operand occurrence"
    ):
        ConstructedOperandOccurrenceV1(
            "source:invented", "key", NameSugar("real-child", None)
        )
    with pytest.raises(
        ContextManagerContractError, match="constructed operand occurrence"
    ):
        ConstructedOperandOccurrenceV1(
            SourceFragmentCoordinateV1(_cid("7"), 1, 0, 1, 1), "key", object()
        )


def test_cross_kind_variadic_selectors_are_loud():
    signature = ImportSignatureV2(
        (
            CallParameterV1(
                "fixed",
                PrimitiveSort("Value"),
                PositionalOrKeywordV1(),
                True,
                NoDefaultV1(),
            ),
            CallParameterV1(
                "args",
                PrimitiveSort("Value"),
                VariadicPositionalV1(),
                False,
                NoDefaultV1(),
            ),
            CallParameterV1(
                "kwargs",
                PrimitiveSort("Value"),
                VariadicKeywordV1(),
                False,
                NoDefaultV1(),
            ),
        )
    )
    base = _wire(
        EffectBoundarySemanticsV1(
            ExpectsModeV1(),
            RaiseEffectKindV1(),
            FormalArgumentProjectionV1(0),
            VariadicKeywordEntryProjectionV1(2, "match"),
            ExceptionInfoBindingV1(),
        )
    )
    base["matcher"]["messagePatternOperand"] = {
        "kind": "variadic-keyword-entry",
        "parameterIndex": 1,
        "keyword": "match",
    }
    with pytest.raises(ContextManagerContractError, match=r"requires \*\*kwargs"):
        decode_context_manager_semantics_v1(base, signature)


@pytest.mark.parametrize(
    "mutation",
    [
        lambda wire: wire["parameters"][0]["passing"].update(kind="future-pack"),
        lambda wire: wire["parameters"][0].update(required=True),
        lambda wire: wire["parameters"][0].update(
            default={
                "kind": "literal-default",
                "value": {
                    "kind": "const",
                    "value": 1,
                    "sort": {"kind": "primitive", "name": "Int"},
                },
            }
        ),
        lambda wire: wire["parameters"][0].update(extra=True),
    ],
)
def test_malformed_variadic_signature_is_loud(mutation):
    signature = ImportSignatureV2(
        (
            CallParameterV1(
                "kwargs",
                PrimitiveSort("Value"),
                VariadicKeywordV1(),
                False,
                NoDefaultV1(),
            ),
        )
    )
    wire = json.loads(encode_jcs(import_signature_to_value(signature)))
    mutation(wire)
    with pytest.raises(ContextManagerContractError):
        decode_import_signature_v2(wire)


def test_optional_parameter_without_authenticated_default_is_loud():
    with pytest.raises(ContextManagerContractError, match="optional fixed parameter"):
        CallParameterV1(
            "match", PrimitiveSort("String"), KeywordOnlyV1(), False, NoDefaultV1()
        )
    with pytest.raises(ContextManagerContractError, match="literal default sort"):
        CallParameterV1(
            "flag",
            PrimitiveSort("Bool"),
            KeywordOnlyV1(),
            False,
            LiteralDefaultV1(
                {
                    "kind": "const",
                    "value": 1,
                    "sort": {"kind": "primitive", "name": "Int"},
                }
            ),
        )


def test_mutated_literal_default_cannot_be_signed_as_authenticated_testimony():
    value = {
        "kind": "const",
        "value": False,
        "sort": {"kind": "primitive", "name": "Bool"},
    }
    parameter = CallParameterV1(
        "flag",
        PrimitiveSort("Bool"),
        KeywordOnlyV1(),
        False,
        LiteralDefaultV1(value),
    )
    value["sort"] = {"kind": "primitive", "name": "Int"}
    with pytest.raises(ContextManagerContractError, match="literal default sort"):
        import_signature_to_value(ImportSignatureV2((parameter,)))
