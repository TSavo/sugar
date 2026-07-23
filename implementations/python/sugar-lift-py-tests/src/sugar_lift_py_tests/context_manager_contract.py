"""Typed context-manager dispositions and sealed CM-contract publications."""

from __future__ import annotations

from dataclasses import dataclass
import json
import re
from typing import Any, Optional, Sequence, TYPE_CHECKING

if TYPE_CHECKING:
    from sugar_lift_py_tests.context_manager_resolution import (
        SourceFragmentCoordinateV1,
    )
    from sugar_lift_py_tests.sugar.sugar_base import Sugar

from .canonicalizer import blake3_512_of, encode_jcs, varr, vobj, vstr
from .claim_envelope import ClaimEnvelope, _assemble_layered
from .ir import FunctionSort, PrimitiveSort, RegionSort, Sort, sort_to_value
from .signing import Signer, ed25519_verify_string


@dataclass(frozen=True)
class MessagePattern:
    pattern: str


@dataclass(frozen=True)
class EffectMatcher:
    kind: str
    name: str
    payload_obligations: tuple = ()


EXCEPTION_INFO = "exception_info"
WARNING_OBSERVATION = "warning_observation"
EFFECT = "effect"
ENTER_RESULT = "enter-result"


@dataclass(frozen=True)
class NeverSuppresses:
    pass


@dataclass(frozen=True)
class Suppresses:
    matcher: EffectMatcher


@dataclass(frozen=True)
class Expects:
    matcher: EffectMatcher
    binding: Optional[str] = None


@dataclass(frozen=True)
class RuntimeSelected:
    pass


Contract = NeverSuppresses | Suppresses | Expects | RuntimeSelected


@dataclass(frozen=True)
class NeverSuppressesDispositionV1:
    kind: str = "never-suppresses"


@dataclass(frozen=True)
class ReturnTruthinessDispositionV1:
    kind: str = "return-truthiness"


@dataclass(frozen=True)
class TotalCompletionV1:
    kind: str = "total"


@dataclass(frozen=True)
class EnterResultContractV1:
    sort: Sort
    completion: TotalCompletionV1 = TotalCompletionV1()
    projection: str = ENTER_RESULT


@dataclass(frozen=True)
class ExitContractV1:
    disposition: NeverSuppressesDispositionV1 | ReturnTruthinessDispositionV1
    completion: TotalCompletionV1 = TotalCompletionV1()


@dataclass(frozen=True)
class ProtocolResourceSemanticsV1:
    enter: EnterResultContractV1
    exit: ExitContractV1
    kind: str = "protocol-resource"
    schema_version: str = "1"


@dataclass(frozen=True)
class ExpectsModeV1:
    kind: str = "expects"


@dataclass(frozen=True)
class SuppressesModeV1:
    kind: str = "suppresses"


@dataclass(frozen=True)
class RaiseEffectKindV1:
    kind: str = "raise"


@dataclass(frozen=True)
class WarningEffectKindV1:
    kind: str = "warning"


@dataclass(frozen=True)
class FormalArgumentProjectionV1:
    parameter_index: int
    kind: str = "formal-argument"


@dataclass(frozen=True)
class NoMessagePatternV1:
    kind: str = "none"


@dataclass(frozen=True)
class OptionalFormalArgumentProjectionV1:
    parameter_index: int
    kind: str = "optional-formal-argument"


@dataclass(frozen=True)
class VariadicPositionalElementProjectionV1:
    parameter_index: int
    element_index: int
    kind: str = "variadic-positional-element"


@dataclass(frozen=True)
class VariadicKeywordEntryProjectionV1:
    parameter_index: int
    keyword: str
    kind: str = "variadic-keyword-entry"


@dataclass(frozen=True)
class NoBindingV1:
    kind: str = "none"


@dataclass(frozen=True)
class ExceptionInfoBindingV1:
    kind: str = "exception-info"


@dataclass(frozen=True)
class WarningObservationBindingV1:
    kind: str = "warning-observation"


@dataclass(frozen=True)
class PositionalOnlyV1:
    kind: str = "positional-only"


@dataclass(frozen=True)
class PositionalOrKeywordV1:
    kind: str = "positional-or-keyword"


@dataclass(frozen=True)
class KeywordOnlyV1:
    kind: str = "keyword-only"


@dataclass(frozen=True)
class VariadicPositionalV1:
    kind: str = "variadic-positional"


@dataclass(frozen=True)
class VariadicKeywordV1:
    kind: str = "variadic-keyword"


def _validate_literal_default(value: Any) -> None:
    if not isinstance(value, dict):
        raise ContextManagerContractError("literal default must be an exact typed term")
    if set(value) == {"kind", "name", "args"} and value == {
        "kind": "ctor",
        "name": "None",
        "args": [],
    }:
        return
    if set(value) != {"kind", "value", "sort"} or value.get("kind") != "const":
        raise ContextManagerContractError(
            "literal default must be None or an exact typed constant"
        )
    sort = value["sort"]
    if (
        not isinstance(sort, dict)
        or set(sort) != {"kind", "name"}
        or sort.get("kind") != "primitive"
    ):
        raise ContextManagerContractError(
            "literal default has malformed sort testimony"
        )
    name = sort.get("name")
    literal = value["value"]
    valid = (
        (name == "Bool" and type(literal) is bool)
        or (name == "Int" and type(literal) is int)
        or (name == "String" and isinstance(literal, str))
    )
    if not valid:
        raise ContextManagerContractError("literal default sort/value mismatch")


@dataclass(frozen=True)
class NoDefaultV1:
    kind: str = "no-default"


@dataclass(frozen=True)
class LiteralDefaultV1:
    value: Any
    kind: str = "literal-default"

    def __post_init__(self) -> None:
        _validate_literal_default(self.value)


@dataclass(frozen=True)
class CallParameterV1:
    name: str
    sort: Sort
    passing: (
        PositionalOnlyV1
        | PositionalOrKeywordV1
        | KeywordOnlyV1
        | VariadicPositionalV1
        | VariadicKeywordV1
    )
    required: bool
    default: NoDefaultV1 | LiteralDefaultV1

    def __post_init__(self) -> None:
        _validate_call_parameter_v1(self)


def _validate_call_parameter_v1(parameter: CallParameterV1) -> None:
    self = parameter
    if not self.name:
        raise ContextManagerContractError("call parameter name must be nonempty")
    if type(self.required) is not bool:
        raise ContextManagerContractError("call parameter required must be bool")
    variadic = isinstance(self.passing, (VariadicPositionalV1, VariadicKeywordV1))
    if variadic:
        if (
            self.required
            or not isinstance(self.default, NoDefaultV1)
            or self.sort != PrimitiveSort("Value")
        ):
            raise ContextManagerContractError(
                "variadic parameter requires Value, required=false, default=no-default"
            )
    elif self.required:
        if not isinstance(self.default, NoDefaultV1):
            raise ContextManagerContractError("required parameter must have no-default")
    elif isinstance(self.default, NoDefaultV1):
        raise ContextManagerContractError(
            "optional fixed parameter requires authenticated default"
        )
    if (
        isinstance(self.default, LiteralDefaultV1)
        and self.default.value.get("kind") == "const"
    ):
        literal_sort = _decode_sort(self.default.value["sort"])
        if literal_sort != self.sort:
            raise ContextManagerContractError(
                "literal default sort must equal parameter sort"
            )


@dataclass(frozen=True)
class ImportSignatureV2:
    parameters: tuple[CallParameterV1, ...]

    def __post_init__(self) -> None:
        names = tuple(parameter.name for parameter in self.parameters)
        if len(set(names)) != len(names):
            raise ContextManagerContractError("call parameter names must be unique")
        passing_rank = {
            PositionalOnlyV1: 0,
            PositionalOrKeywordV1: 1,
            VariadicPositionalV1: 2,
            KeywordOnlyV1: 3,
            VariadicKeywordV1: 4,
        }
        ranks = []
        for parameter in self.parameters:
            rank = passing_rank.get(type(parameter.passing))
            if rank is None:
                raise ContextManagerContractError("unknown parameter passing mode")
            ranks.append(rank)
        if ranks != sorted(ranks):
            raise ContextManagerContractError(
                "call parameter passing modes are illegally ordered"
            )
        if (
            sum(isinstance(p.passing, VariadicPositionalV1) for p in self.parameters)
            > 1
            or sum(isinstance(p.passing, VariadicKeywordV1) for p in self.parameters)
            > 1
        ):
            raise ContextManagerContractError(
                "at most one variadic positional and keyword parameter"
            )


@dataclass(frozen=True)
class EffectBoundarySemanticsV1:
    mode: ExpectsModeV1 | SuppressesModeV1
    effect_kind: RaiseEffectKindV1 | WarningEffectKindV1
    expected_type_operand: (
        FormalArgumentProjectionV1
        | VariadicPositionalElementProjectionV1
        | VariadicKeywordEntryProjectionV1
    )
    message_pattern_operand: (
        NoMessagePatternV1
        | OptionalFormalArgumentProjectionV1
        | VariadicPositionalElementProjectionV1
        | VariadicKeywordEntryProjectionV1
    )
    binding: NoBindingV1 | ExceptionInfoBindingV1 | WarningObservationBindingV1
    kind: str = "effect-boundary"
    schema_version: str = "1"


ContextManagerSemanticsV1 = ProtocolResourceSemanticsV1 | EffectBoundarySemanticsV1


@dataclass(frozen=True)
class ConstructedOperandOccurrenceV1:
    occurrence: SourceFragmentCoordinateV1
    keyword: str | None
    value: Sugar

    def __post_init__(self) -> None:
        from sugar_lift_py_tests.context_manager_resolution import (
            SourceFragmentCoordinateV1,
        )
        from sugar_lift_py_tests.sugar.sugar_base import Sugar

        if not isinstance(
            self.occurrence, SourceFragmentCoordinateV1
        ) or not isinstance(self.value, Sugar):
            raise ContextManagerContractError(
                "constructed operand occurrence requires a source coordinate and Sugar child"
            )
        if self.keyword is not None and (
            not isinstance(self.keyword, str) or not self.keyword
        ):
            raise ContextManagerContractError(
                "constructed operand occurrence keyword must be nonempty"
            )


@dataclass(frozen=True)
class VariadicPositionalActualV1:
    formal_index: int
    elements: tuple[ConstructedOperandOccurrenceV1, ...]

    def __post_init__(self) -> None:
        if (
            isinstance(self.formal_index, bool)
            or not isinstance(self.formal_index, int)
            or self.formal_index < 0
        ):
            raise ContextManagerContractError(
                "variadic positional actual requires a nonnegative formal index"
            )
        if any(element.keyword is not None for element in self.elements):
            raise ContextManagerContractError(
                "variadic positional actual cannot carry keyword entries"
            )


@dataclass(frozen=True)
class VariadicKeywordActualV1:
    formal_index: int
    entries: tuple[ConstructedOperandOccurrenceV1, ...]

    def __post_init__(self) -> None:
        if (
            isinstance(self.formal_index, bool)
            or not isinstance(self.formal_index, int)
            or self.formal_index < 0
        ):
            raise ContextManagerContractError(
                "variadic keyword actual requires a nonnegative formal index"
            )
        keys = tuple(entry.keyword for entry in self.entries)
        if any(not isinstance(key, str) or not key for key in keys) or len(
            set(keys)
        ) != len(keys):
            raise ContextManagerContractError(
                "variadic keyword actuals require unique real keywords"
            )


def project_formal_selector_v1(
    selector,
    *,
    fixed_actuals: Mapping[int, Any],
    variadic_positional_actuals: Mapping[int, VariadicPositionalActualV1],
    variadic_keyword_actuals: Mapping[int, VariadicKeywordActualV1],
):
    """Project an already-constructed actual; never create a replacement value."""
    if isinstance(
        selector, (FormalArgumentProjectionV1, OptionalFormalArgumentProjectionV1)
    ):
        try:
            return fixed_actuals[selector.parameter_index]
        except KeyError as exc:
            if isinstance(selector, OptionalFormalArgumentProjectionV1):
                return None
            raise ContextManagerContractError(
                "required formal actual is absent"
            ) from exc
    if isinstance(selector, VariadicPositionalElementProjectionV1):
        pack = variadic_positional_actuals.get(selector.parameter_index)
        if pack is None or pack.formal_index != selector.parameter_index:
            raise ContextManagerContractError("variadic positional actual is absent")
        try:
            return pack.elements[selector.element_index].value
        except IndexError as exc:
            raise ContextManagerContractError(
                "variadic positional element is out of range"
            ) from exc
    if isinstance(selector, VariadicKeywordEntryProjectionV1):
        pack = variadic_keyword_actuals.get(selector.parameter_index)
        if pack is None or pack.formal_index != selector.parameter_index:
            raise ContextManagerContractError("variadic keyword actual is absent")
        matches = tuple(
            entry for entry in pack.entries if entry.keyword == selector.keyword
        )
        if len(matches) != 1:
            raise ContextManagerContractError(
                "variadic keyword entry is absent or ambiguous"
            )
        return matches[0].value
    raise ContextManagerContractError("unknown formal selector")


@dataclass(frozen=True)
class ContextManagerDerivationProvenanceV1:
    distribution_artifact_cid: str
    dependency_artifact_graph_cid: str
    module_identity_cid: str
    module_source_cid: str
    re_export_warrant_cids: tuple[str, ...]
    resolved_definition: "SourceFragmentCoordinateV1"
    resolved_definition_cid: str
    manager_construction_cid: str
    enter_testimony_cid: str
    exit_testimony_cid: str
    use_site: "SourceFragmentCoordinateV1"
    use_site_cid: str
    derivation_algorithm_cid: str
    derivation_cid: str
    kind: str = "python-context-manager-derivation"
    schema_version: str = "1"


@dataclass(frozen=True)
class DerivedContextManagerContractV1:
    import_signature: ImportSignatureV2
    semantics: ContextManagerSemanticsV1
    payload_cid: str
    provenance: ContextManagerDerivationProvenanceV1
    provenance_cid: str
    contract_cid: str


class ContextManagerContractError(ValueError):
    """A sealed CM-contract member is malformed, stale, or unauthenticated."""


def _selector_to_value(selector):
    index = getattr(selector, "parameter_index", None)
    if isinstance(index, bool) or not isinstance(index, int) or index < 0:
        raise ContextManagerContractError(
            "selector requires a nonnegative parameter index"
        )
    if isinstance(selector, FormalArgumentProjectionV1):
        return vobj(
            [("kind", vstr("formal-argument")), ("parameterIndex", _json_value(index))]
        )
    if isinstance(selector, OptionalFormalArgumentProjectionV1):
        return vobj(
            [
                ("kind", vstr("optional-formal-argument")),
                ("parameterIndex", _json_value(index)),
            ]
        )
    if isinstance(selector, VariadicPositionalElementProjectionV1):
        if (
            isinstance(selector.element_index, bool)
            or not isinstance(selector.element_index, int)
            or selector.element_index < 0
        ):
            raise ContextManagerContractError(
                "variadic element selector requires a nonnegative element index"
            )
        return vobj(
            [
                ("kind", vstr("variadic-positional-element")),
                ("parameterIndex", _json_value(index)),
                ("elementIndex", _json_value(selector.element_index)),
            ]
        )
    if isinstance(selector, VariadicKeywordEntryProjectionV1):
        if not isinstance(selector.keyword, str) or not selector.keyword:
            raise ContextManagerContractError(
                "variadic keyword selector requires a keyword"
            )
        return vobj(
            [
                ("kind", vstr("variadic-keyword-entry")),
                ("parameterIndex", _json_value(index)),
                ("keyword", vstr(selector.keyword)),
            ]
        )
    raise ContextManagerContractError("unknown formal selector")


def semantics_to_value(semantics: ContextManagerSemanticsV1):
    if isinstance(semantics, ProtocolResourceSemanticsV1):
        if (
            semantics.schema_version != "1"
            or not isinstance(semantics.enter.completion, TotalCompletionV1)
            or semantics.enter.projection != ENTER_RESULT
        ):
            raise ContextManagerContractError(
                "unsupported protocol-resource enter testimony"
            )
        if not isinstance(semantics.exit.completion, TotalCompletionV1):
            raise ContextManagerContractError(
                "unsupported protocol-resource exit testimony"
            )
        if isinstance(semantics.exit.disposition, NeverSuppressesDispositionV1):
            disposition = "never-suppresses"
        elif isinstance(semantics.exit.disposition, ReturnTruthinessDispositionV1):
            disposition = "return-truthiness"
        else:
            raise ContextManagerContractError(
                "unknown protocol-resource exit disposition"
            )
        return vobj(
            [
                ("kind", vstr("protocol-resource")),
                ("schemaVersion", vstr("1")),
                (
                    "enter",
                    vobj(
                        [
                            ("completion", vobj([("kind", vstr("total"))])),
                            (
                                "result",
                                vobj(
                                    [
                                        ("kind", vstr("projection")),
                                        ("projection", vstr(ENTER_RESULT)),
                                        ("sort", sort_to_value(semantics.enter.sort)),
                                    ]
                                ),
                            ),
                        ]
                    ),
                ),
                (
                    "exit",
                    vobj(
                        [
                            ("completion", vobj([("kind", vstr("total"))])),
                            ("disposition", vobj([("kind", vstr(disposition))])),
                        ]
                    ),
                ),
            ]
        )
    if isinstance(semantics, EffectBoundarySemanticsV1):
        if semantics.schema_version != "1":
            raise ContextManagerContractError("unsupported effect-boundary schema")
        if isinstance(semantics.mode, ExpectsModeV1):
            mode = "expects"
        elif isinstance(semantics.mode, SuppressesModeV1):
            mode = "suppresses"
        else:
            raise ContextManagerContractError("unknown effect-boundary mode")
        if isinstance(semantics.effect_kind, RaiseEffectKindV1):
            effect_kind = "raise"
        elif isinstance(semantics.effect_kind, WarningEffectKindV1):
            effect_kind = "warning"
        else:
            raise ContextManagerContractError("unknown effect kind")
        if isinstance(semantics.binding, NoBindingV1):
            binding = "none"
        elif isinstance(semantics.binding, ExceptionInfoBindingV1):
            binding = "exception-info"
        elif isinstance(semantics.binding, WarningObservationBindingV1):
            binding = "warning-observation"
        else:
            raise ContextManagerContractError("unknown effect-boundary binding")
        expected_value = _selector_to_value(semantics.expected_type_operand)
        message = semantics.message_pattern_operand
        if isinstance(message, NoMessagePatternV1):
            message_value = vobj([("kind", vstr("none"))])
        else:
            message_value = _selector_to_value(message)
        return vobj(
            [
                ("kind", vstr("effect-boundary")),
                ("schemaVersion", vstr("1")),
                ("mode", vobj([("kind", vstr(mode))])),
                (
                    "matcher",
                    vobj(
                        [
                            ("effectKind", vobj([("kind", vstr(effect_kind))])),
                            ("expectedTypeOperand", expected_value),
                            ("messagePatternOperand", message_value),
                        ]
                    ),
                ),
                ("binding", vobj([("kind", vstr(binding))])),
            ]
        )
    raise ContextManagerContractError("unknown context-manager semantics variant")


def _cid_of_json(value: Any) -> str:
    return blake3_512_of(encode_jcs(_json_value(value)).encode())


def derivation_provenance_to_dict(
    provenance: ContextManagerDerivationProvenanceV1,
) -> dict[str, Any]:
    return {
        "kind": provenance.kind,
        "schemaVersion": provenance.schema_version,
        "distributionArtifactCid": provenance.distribution_artifact_cid,
        "dependencyArtifactGraphCid": provenance.dependency_artifact_graph_cid,
        "moduleIdentityCid": provenance.module_identity_cid,
        "moduleSourceCid": provenance.module_source_cid,
        "reExportWarrantCids": list(provenance.re_export_warrant_cids),
        "resolvedDefinition": provenance.resolved_definition.wire(),
        "resolvedDefinitionCid": provenance.resolved_definition_cid,
        "managerConstructionCid": provenance.manager_construction_cid,
        "enterTestimonyCid": provenance.enter_testimony_cid,
        "exitTestimonyCid": provenance.exit_testimony_cid,
        "useSite": provenance.use_site.wire(),
        "useSiteCid": provenance.use_site_cid,
        "derivationAlgorithmCid": provenance.derivation_algorithm_cid,
        "derivationCid": provenance.derivation_cid,
    }


def validate_derivation_provenance_v1(
    provenance: ContextManagerDerivationProvenanceV1,
) -> None:
    if not isinstance(provenance, ContextManagerDerivationProvenanceV1):
        raise ContextManagerContractError("derived CM contract requires typed provenance")
    if provenance.kind != "python-context-manager-derivation" or provenance.schema_version != "1":
        raise ContextManagerContractError("unsupported CM derivation provenance")
    wire = derivation_provenance_to_dict(provenance)
    cid_fields = (
        "distributionArtifactCid",
        "dependencyArtifactGraphCid",
        "moduleIdentityCid",
        "moduleSourceCid",
        "resolvedDefinitionCid",
        "managerConstructionCid",
        "enterTestimonyCid",
        "exitTestimonyCid",
        "useSiteCid",
        "derivationAlgorithmCid",
        "derivationCid",
    )
    if any(
        not isinstance(wire[field], str) or not wire[field].startswith("blake3-512:")
        for field in cid_fields
    ):
        raise ContextManagerContractError("CM derivation provenance requires CIDs")
    if any(
        not isinstance(cid, str) or not cid.startswith("blake3-512:")
        for cid in provenance.re_export_warrant_cids
    ):
        raise ContextManagerContractError("re-export warrants must be ordered CIDs")
    if provenance.resolved_definition.source_cid != provenance.module_source_cid:
        raise ContextManagerContractError("resolved definition is outside module source")
    if _cid_of_json(wire["resolvedDefinition"]) != provenance.resolved_definition_cid:
        raise ContextManagerContractError("resolved definition CID mismatch")
    if _cid_of_json(wire["useSite"]) != provenance.use_site_cid:
        raise ContextManagerContractError("use-site CID mismatch")
    derivation_preimage = {key: value for key, value in wire.items() if key != "derivationCid"}
    if _cid_of_json(derivation_preimage) != provenance.derivation_cid:
        raise ContextManagerContractError("derivation CID mismatch")


def seal_derived_context_manager_contract(
    *,
    import_signature: ImportSignatureV2,
    semantics: ContextManagerSemanticsV1,
    provenance: ContextManagerDerivationProvenanceV1,
    signer: Signer,
    declared_at: str,
) -> ClaimEnvelope:
    """Seal a checked construction summary; the signer grants no CM semantics."""
    if not isinstance(import_signature, ImportSignatureV2):
        raise ContextManagerContractError("ImportSignatureV2 required")
    validate_derivation_provenance_v1(provenance)
    payload = semantics_to_value(semantics)
    decoded_payload = json.loads(encode_jcs(payload))
    if decode_context_manager_semantics_v1(decoded_payload, import_signature) != semantics:
        raise ContextManagerContractError("context-manager semantics failed canonical validation")
    payload_cid = blake3_512_of(encode_jcs(payload).encode())
    provenance_wire = derivation_provenance_to_dict(provenance)
    provenance_cid = _cid_of_json(provenance_wire)
    contract_preimage = {
        "kind": "context-manager-contract",
        "schemaVersion": "derived-1",
        "importSignature": json.loads(encode_jcs(import_signature_to_value(import_signature))),
        "semantics": decoded_payload,
        "payloadCid": payload_cid,
        "provenance": provenance_wire,
        "provenanceCid": provenance_cid,
    }
    contract_cid = _cid_of_json(contract_preimage)
    header = _json_value({**contract_preimage, "cid": contract_cid, "contractCid": contract_cid})
    metadata = vobj(
        [
            (
                "authoring",
                vobj(
                    [
                        ("producerKind", vstr("construction-derivation")),
                        ("author", vstr(signer.producer_id)),
                    ]
                ),
            ),
            ("producedBy", vstr(signer.producer_id)),
            ("producedAt", vstr(declared_at)),
        ]
    )
    return _assemble_layered(header, metadata, declared_at, signer.seed, contract_cid)


def _json_value(value: Any):
    from .canonicalizer import vbool, vint, vnull

    if value is None:
        return vnull()
    if isinstance(value, bool):
        return vbool(value)
    if isinstance(value, int):
        return vint(value)
    if isinstance(value, str):
        return vstr(value)
    if isinstance(value, list):
        return varr([_json_value(v) for v in value])
    if isinstance(value, dict):
        return vobj([(k, _json_value(v)) for k, v in value.items()])
    raise ContextManagerContractError(f"unsupported payload value: {type(value)!r}")


def _decode_sort(raw: Any) -> Sort:
    if not isinstance(raw, dict):
        raise ContextManagerContractError("sort must be an object")
    if (
        raw.get("kind") == "primitive"
        and set(raw) == {"kind", "name"}
        and isinstance(raw["name"], str)
    ):
        return PrimitiveSort(raw["name"])
    if (
        raw.get("kind") == "region"
        and set(raw) == {"kind", "name"}
        and isinstance(raw["name"], str)
    ):
        return RegionSort(raw["name"])
    if (
        raw.get("kind") == "function"
        and set(raw) == {"kind", "args", "return"}
        and isinstance(raw["args"], list)
    ):
        return FunctionSort(
            tuple(_decode_sort(v) for v in raw["args"]), _decode_sort(raw["return"])
        )
    raise ContextManagerContractError("unsupported or malformed sort")


def import_signature_to_value(signature: ImportSignatureV2):
    if not isinstance(signature, ImportSignatureV2):
        raise ContextManagerContractError("ImportSignatureV2 required")
    rows = []
    for parameter in signature.parameters:
        _validate_call_parameter_v1(parameter)
        if isinstance(parameter.passing, PositionalOnlyV1):
            passing = "positional-only"
        elif isinstance(parameter.passing, PositionalOrKeywordV1):
            passing = "positional-or-keyword"
        elif isinstance(parameter.passing, KeywordOnlyV1):
            passing = "keyword-only"
        elif isinstance(parameter.passing, VariadicPositionalV1):
            passing = "variadic-positional"
        elif isinstance(parameter.passing, VariadicKeywordV1):
            passing = "variadic-keyword"
        else:
            raise ContextManagerContractError("unknown parameter passing mode")
        if type(parameter.required) is not bool:
            raise ContextManagerContractError("call parameter required must be bool")
        if isinstance(parameter.default, NoDefaultV1):
            default = vobj([("kind", vstr("no-default"))])
        elif isinstance(parameter.default, LiteralDefaultV1):
            _validate_literal_default(parameter.default.value)
            default = vobj(
                [
                    ("kind", vstr("literal-default")),
                    ("value", _json_value(parameter.default.value)),
                ]
            )
        else:
            raise ContextManagerContractError("unknown authenticated default")
        rows.append(
            vobj(
                [
                    ("name", vstr(parameter.name)),
                    ("sort", sort_to_value(parameter.sort)),
                    ("passing", vobj([("kind", vstr(passing))])),
                    ("required", _json_value(parameter.required)),
                    ("default", default),
                ]
            )
        )
    return vobj([("parameters", varr([*rows]))])


def decode_import_signature_v2(raw: Any) -> ImportSignatureV2:
    if (
        not isinstance(raw, dict)
        or set(raw) != {"parameters"}
        or not isinstance(raw["parameters"], list)
    ):
        raise ContextManagerContractError("malformed ImportSignatureV2")
    parameters = []
    passing_types = {
        "positional-only": PositionalOnlyV1,
        "positional-or-keyword": PositionalOrKeywordV1,
        "keyword-only": KeywordOnlyV1,
        "variadic-positional": VariadicPositionalV1,
        "variadic-keyword": VariadicKeywordV1,
    }
    for value in raw["parameters"]:
        if not isinstance(value, dict) or set(value) != {
            "name",
            "sort",
            "passing",
            "required",
            "default",
        }:
            raise ContextManagerContractError("malformed call parameter")
        if (
            not isinstance(value["name"], str)
            or not value["name"]
            or type(value["required"]) is not bool
        ):
            raise ContextManagerContractError("malformed call parameter fields")
        passing = _tag(value["passing"], passing_types, "parameter passing mode")
        raw_default = value["default"]
        if not isinstance(raw_default, dict) or "kind" not in raw_default:
            raise ContextManagerContractError("malformed authenticated default")
        if raw_default.get("kind") == "no-default" and set(raw_default) == {"kind"}:
            default = NoDefaultV1()
        elif raw_default.get("kind") == "literal-default" and set(raw_default) == {
            "kind",
            "value",
        }:
            default = LiteralDefaultV1(raw_default["value"])
        else:
            raise ContextManagerContractError(
                "unknown or malformed authenticated default"
            )
        parameters.append(
            CallParameterV1(
                value["name"],
                _decode_sort(value["sort"]),
                passing,
                value["required"],
                default,
            )
        )
    return ImportSignatureV2(tuple(parameters))


def _decode_total(raw: Any) -> TotalCompletionV1:
    if not isinstance(raw, dict) or set(raw) != {"kind"} or raw["kind"] != "total":
        raise ContextManagerContractError("unknown completion testimony")
    return TotalCompletionV1()


def _decode_protocol_resource(raw: Any) -> ProtocolResourceSemanticsV1:
    if (
        set(raw) != {"kind", "schemaVersion", "enter", "exit"}
        or raw["schemaVersion"] != "1"
    ):
        raise ContextManagerContractError("malformed protocol-resource semantics")
    enter = raw["enter"]
    exit_ = raw["exit"]
    if not isinstance(enter, dict) or set(enter) != {"completion", "result"}:
        raise ContextManagerContractError("malformed context-manager semantics enter")
    result = enter["result"]
    completion = _decode_total(enter["completion"])
    if (
        not isinstance(result, dict)
        or set(result) != {"kind", "projection", "sort"}
        or result["kind"] != "projection"
        or result["projection"] != ENTER_RESULT
    ):
        raise ContextManagerContractError("unsupported enter testimony")
    if not isinstance(exit_, dict) or set(exit_) != {"completion", "disposition"}:
        raise ContextManagerContractError("malformed context-manager semantics exit")
    disposition = exit_["disposition"]
    exit_completion = _decode_total(exit_["completion"])
    if not isinstance(disposition, dict) or set(disposition) != {"kind"}:
        raise ContextManagerContractError("malformed exit disposition")
    if disposition["kind"] == "never-suppresses":
        decoded_disposition = NeverSuppressesDispositionV1()
    elif disposition["kind"] == "return-truthiness":
        decoded_disposition = ReturnTruthinessDispositionV1()
    else:
        raise ContextManagerContractError("unknown exit disposition")
    return ProtocolResourceSemanticsV1(
        enter=EnterResultContractV1(
            sort=_decode_sort(result["sort"]), completion=completion
        ),
        exit=ExitContractV1(
            disposition=decoded_disposition, completion=exit_completion
        ),
    )


def _tag(raw: Any, allowed: dict[str, Any], owner: str):
    if not isinstance(raw, dict) or set(raw) != {"kind"} or raw["kind"] not in allowed:
        raise ContextManagerContractError(f"unknown {owner}")
    return allowed[raw["kind"]]()


def _decode_selector(raw: Any, *, allow_optional: bool):
    if not isinstance(raw, dict) or not isinstance(raw.get("kind"), str):
        raise ContextManagerContractError("malformed formal selector")
    kind = raw["kind"]
    fixed_cls = (
        OptionalFormalArgumentProjectionV1
        if allow_optional
        else FormalArgumentProjectionV1
    )
    fixed_kind = "optional-formal-argument" if allow_optional else "formal-argument"
    if kind == fixed_kind and set(raw) == {"kind", "parameterIndex"}:
        selector = fixed_cls(raw["parameterIndex"])
    elif kind == "variadic-positional-element" and set(raw) == {
        "kind",
        "parameterIndex",
        "elementIndex",
    }:
        selector = VariadicPositionalElementProjectionV1(
            raw["parameterIndex"], raw["elementIndex"]
        )
    elif kind == "variadic-keyword-entry" and set(raw) == {
        "kind",
        "parameterIndex",
        "keyword",
    }:
        selector = VariadicKeywordEntryProjectionV1(
            raw["parameterIndex"], raw["keyword"]
        )
    else:
        raise ContextManagerContractError("unknown or malformed formal selector")
    _selector_to_value(selector)
    return selector


def _selector_parameter(selector, signature: ImportSignatureV2) -> CallParameterV1:
    if selector.parameter_index >= len(signature.parameters):
        raise ContextManagerContractError("selector is outside ImportSignatureV2")
    parameter = signature.parameters[selector.parameter_index]
    if isinstance(
        selector, (FormalArgumentProjectionV1, OptionalFormalArgumentProjectionV1)
    ):
        if isinstance(parameter.passing, (VariadicPositionalV1, VariadicKeywordV1)):
            raise ContextManagerContractError(
                "fixed selector cannot address a variadic parameter"
            )
    elif isinstance(selector, VariadicPositionalElementProjectionV1):
        if not isinstance(parameter.passing, VariadicPositionalV1):
            raise ContextManagerContractError(
                "variadic element selector requires *args"
            )
    elif isinstance(selector, VariadicKeywordEntryProjectionV1):
        if not isinstance(parameter.passing, VariadicKeywordV1):
            raise ContextManagerContractError(
                "variadic keyword selector requires **kwargs"
            )
    else:
        raise ContextManagerContractError("unknown formal selector")
    return parameter


def _decode_effect_boundary(
    raw: Any, signature: ImportSignatureV2
) -> EffectBoundarySemanticsV1:
    if (
        set(raw) != {"kind", "schemaVersion", "mode", "matcher", "binding"}
        or raw["schemaVersion"] != "1"
    ):
        raise ContextManagerContractError("malformed effect-boundary semantics")
    matcher = raw["matcher"]
    if not isinstance(matcher, dict) or set(matcher) != {
        "effectKind",
        "expectedTypeOperand",
        "messagePatternOperand",
    }:
        raise ContextManagerContractError("malformed effect-boundary matcher")
    mode = _tag(
        raw["mode"],
        {"expects": ExpectsModeV1, "suppresses": SuppressesModeV1},
        "effect-boundary mode",
    )
    effect_kind = _tag(
        matcher["effectKind"],
        {"raise": RaiseEffectKindV1, "warning": WarningEffectKindV1},
        "effect kind",
    )
    expected = _decode_selector(matcher["expectedTypeOperand"], allow_optional=False)
    message_raw = matcher["messagePatternOperand"]
    if (
        isinstance(message_raw, dict)
        and set(message_raw) == {"kind"}
        and message_raw["kind"] == "none"
    ):
        message = NoMessagePatternV1()
    else:
        message = _decode_selector(message_raw, allow_optional=True)
    binding = _tag(
        raw["binding"],
        {
            "none": NoBindingV1,
            "exception-info": ExceptionInfoBindingV1,
            "warning-observation": WarningObservationBindingV1,
        },
        "effect-boundary binding",
    )
    expected_parameter = _selector_parameter(expected, signature)
    if expected_parameter.sort != PrimitiveSort("Value"):
        raise ContextManagerContractError(
            "expected-type selector requires a Value formal"
        )
    if not isinstance(message, NoMessagePatternV1):
        parameter = _selector_parameter(message, signature)
        if message == expected:
            raise ContextManagerContractError(
                "effect-boundary selectors must be distinct"
            )
        if isinstance(message, OptionalFormalArgumentProjectionV1):
            if (
                parameter.required
                or not isinstance(
                    parameter.passing, (PositionalOrKeywordV1, KeywordOnlyV1)
                )
                or parameter.sort
                not in (PrimitiveSort("String"), PrimitiveSort("Value"))
            ):
                raise ContextManagerContractError(
                    "message selector requires an optional keyword-bindable String-or-Value formal"
                )
        elif parameter.sort != PrimitiveSort("Value"):
            raise ContextManagerContractError(
                "variadic message selector requires a Value pack"
            )
    return EffectBoundarySemanticsV1(mode, effect_kind, expected, message, binding)


def decode_context_manager_semantics_v1(
    raw: Any, signature: ImportSignatureV2 | None = None
) -> ContextManagerSemanticsV1:
    if not isinstance(raw, dict) or "kind" not in raw:
        raise ContextManagerContractError("malformed context-manager semantics")
    if raw["kind"] == "protocol-resource":
        return _decode_protocol_resource(raw)
    if raw["kind"] == "effect-boundary":
        if signature is None:
            raise ContextManagerContractError(
                "EffectBoundary decoding requires ImportSignatureV2"
            )
        return _decode_effect_boundary(raw, signature)
    raise ContextManagerContractError("unknown context-manager semantics variant")


def decode_context_manager_contract(
    canonical_bytes: bytes, member_cid: str
) -> DerivedContextManagerContractV1:
    from sugar_lift_py_tests.context_manager_resolution import SourceFragmentCoordinateV1

    try:
        raw = json.loads(canonical_bytes)
    except (TypeError, ValueError) as exc:
        raise ContextManagerContractError("member is not JSON") from exc
    if not isinstance(raw, dict) or set(raw) != {"envelope", "header", "metadata"}:
        raise ContextManagerContractError("CM contract must be a layered member")
    envelope, header, metadata = raw["envelope"], raw["header"], raw["metadata"]
    if not all(isinstance(value, dict) for value in (envelope, header, metadata)):
        raise ContextManagerContractError("CM contract layers must be objects")
    if blake3_512_of(encode_jcs(_json_value(envelope)).encode()) != member_cid:
        raise ContextManagerContractError("member attestation CID does not match envelope")
    signing = vobj([("header", _json_value(header)), ("metadata", _json_value(metadata))])
    if not ed25519_verify_string(
        envelope.get("signer", ""),
        envelope.get("signature", ""),
        encode_jcs(signing).encode(),
    ):
        raise ContextManagerContractError("member signature does not verify")
    expected_header = {
        "kind",
        "schemaVersion",
        "cid",
        "contractCid",
        "importSignature",
        "semantics",
        "payloadCid",
        "provenance",
        "provenanceCid",
    }
    if (
        set(header) != expected_header
        or header.get("kind") != "context-manager-contract"
        or header.get("schemaVersion") != "derived-1"
    ):
        raise ContextManagerContractError("malformed derived context-manager contract")
    signature = decode_import_signature_v2(header["importSignature"])
    semantics = decode_context_manager_semantics_v1(header["semantics"], signature)
    payload_cid = _cid_of_json(header["semantics"])
    if header["payloadCid"] != payload_cid:
        raise ContextManagerContractError("context-manager payload CID mismatch")
    p = header["provenance"]
    expected_provenance = {
        "kind",
        "schemaVersion",
        "distributionArtifactCid",
        "dependencyArtifactGraphCid",
        "moduleIdentityCid",
        "moduleSourceCid",
        "reExportWarrantCids",
        "resolvedDefinition",
        "resolvedDefinitionCid",
        "managerConstructionCid",
        "enterTestimonyCid",
        "exitTestimonyCid",
        "useSite",
        "useSiteCid",
        "derivationAlgorithmCid",
        "derivationCid",
    }
    if not isinstance(p, dict) or set(p) != expected_provenance:
        raise ContextManagerContractError("malformed CM derivation provenance")
    provenance = ContextManagerDerivationProvenanceV1(
        distribution_artifact_cid=p["distributionArtifactCid"],
        dependency_artifact_graph_cid=p["dependencyArtifactGraphCid"],
        module_identity_cid=p["moduleIdentityCid"],
        module_source_cid=p["moduleSourceCid"],
        re_export_warrant_cids=tuple(p["reExportWarrantCids"]),
        resolved_definition=SourceFragmentCoordinateV1.decode(p["resolvedDefinition"]),
        resolved_definition_cid=p["resolvedDefinitionCid"],
        manager_construction_cid=p["managerConstructionCid"],
        enter_testimony_cid=p["enterTestimonyCid"],
        exit_testimony_cid=p["exitTestimonyCid"],
        use_site=SourceFragmentCoordinateV1.decode(p["useSite"]),
        use_site_cid=p["useSiteCid"],
        derivation_algorithm_cid=p["derivationAlgorithmCid"],
        derivation_cid=p["derivationCid"],
    )
    validate_derivation_provenance_v1(provenance)
    provenance_cid = _cid_of_json(p)
    if header["provenanceCid"] != provenance_cid:
        raise ContextManagerContractError("CM provenance CID mismatch")
    preimage = {
        key: header[key]
        for key in (
            "kind",
            "schemaVersion",
            "importSignature",
            "semantics",
            "payloadCid",
            "provenance",
            "provenanceCid",
        )
    }
    contract_cid = _cid_of_json(preimage)
    if header["cid"] != contract_cid or header["contractCid"] != contract_cid:
        raise ContextManagerContractError("CM contract CID mismatch")
    return DerivedContextManagerContractV1(
        import_signature=signature,
        semantics=semantics,
        payload_cid=payload_cid,
        provenance=provenance,
        provenance_cid=provenance_cid,
        contract_cid=contract_cid,
    )
