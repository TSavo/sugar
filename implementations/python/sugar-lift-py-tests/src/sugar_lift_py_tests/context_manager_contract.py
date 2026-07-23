"""Typed context-manager dispositions and sealed CM-contract publications."""

from __future__ import annotations

from dataclasses import dataclass
import json
import re
from typing import Any, Mapping, Optional, Sequence, TYPE_CHECKING

if TYPE_CHECKING:
    from sugar_lift_py_tests.context_manager_resolution import SourceFragmentCoordinateV1
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
    if set(value) == {"kind", "name", "args"} and value == {"kind": "ctor", "name": "None", "args": []}:
        return
    if set(value) != {"kind", "value", "sort"} or value.get("kind") != "const":
        raise ContextManagerContractError("literal default must be None or an exact typed constant")
    sort = value["sort"]
    if not isinstance(sort, dict) or set(sort) != {"kind", "name"} or sort.get("kind") != "primitive":
        raise ContextManagerContractError("literal default has malformed sort testimony")
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
class ProviderValueRefV1:
    value_ref_cid: str
    sort: Sort
    kind: str = "provider-value-ref"

    def __post_init__(self) -> None:
        if not isinstance(self.value_ref_cid, str) or re.fullmatch(r"blake3-512:[0-9a-f]{128}", self.value_ref_cid) is None:
            raise ContextManagerContractError("provider default valueRefCid must be a CID")


@dataclass(frozen=True)
class ProviderKitKeyBindingV1:
    provider_kit_cid: str
    signer_key_id: str
    signer_public_key: str

    def __post_init__(self) -> None:
        if re.fullmatch(r"blake3-512:[0-9a-f]{128}", self.provider_kit_cid) is None:
            raise ContextManagerContractError("provider key binding requires a provider kit CID")
        if not self.signer_key_id or not self.signer_public_key.startswith("ed25519:"):
            raise ContextManagerContractError("provider key binding requires an authorized signer")


@dataclass(frozen=True)
class ProviderValueCatalogMemberV1:
    member_cid: str
    canonical_bytes: bytes

    def __post_init__(self) -> None:
        if re.fullmatch(r"blake3-512:[0-9a-f]{128}", self.member_cid) is None \
                or not isinstance(self.canonical_bytes, bytes):
            raise ContextManagerContractError("provider value catalog member is malformed")


@dataclass(frozen=True)
class AuthenticatedProviderValueCatalogV1:
    key_binding: ProviderKitKeyBindingV1
    members_by_value_cid: Mapping[str, ProviderValueCatalogMemberV1]

    def __post_init__(self) -> None:
        if not isinstance(self.key_binding, ProviderKitKeyBindingV1):
            raise ContextManagerContractError("provider value catalog requires a key binding")
        if not isinstance(self.members_by_value_cid, Mapping):
            raise ContextManagerContractError("provider value catalog requires canonical members")
        for cid, member in self.members_by_value_cid.items():
            if re.fullmatch(r"blake3-512:[0-9a-f]{128}", cid) is None \
                    or not isinstance(member, ProviderValueCatalogMemberV1):
                raise ContextManagerContractError("provider value catalog member is malformed")


@dataclass(frozen=True)
class ResolvedProviderValueV1:
    """Opaque projection verified from one provider-signed canonical member."""

    member_cid: str
    payload_cid: str
    provider_kit_cid: str
    sort: Sort
    value_jcs: str


@dataclass(frozen=True)
class CallParameterV1:
    name: str
    sort: Sort
    passing: PositionalOnlyV1 | PositionalOrKeywordV1 | KeywordOnlyV1 | VariadicPositionalV1 | VariadicKeywordV1
    required: bool
    default: NoDefaultV1 | LiteralDefaultV1 | ProviderValueRefV1

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
        if self.required or not isinstance(self.default, NoDefaultV1) or self.sort != PrimitiveSort("Value"):
            raise ContextManagerContractError("variadic parameter requires Value, required=false, default=no-default")
    elif self.required:
        if not isinstance(self.default, NoDefaultV1):
            raise ContextManagerContractError("required parameter must have no-default")
    elif isinstance(self.default, NoDefaultV1):
        raise ContextManagerContractError("optional fixed parameter requires authenticated default")
    if isinstance(self.default, LiteralDefaultV1) and self.default.value.get("kind") == "const":
        literal_sort = _decode_sort(self.default.value["sort"])
        if literal_sort != self.sort:
            raise ContextManagerContractError("literal default sort must equal parameter sort")
    if isinstance(self.default, ProviderValueRefV1) and self.default.sort != self.sort:
        raise ContextManagerContractError("provider default sort must equal parameter sort")


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
            raise ContextManagerContractError("call parameter passing modes are illegally ordered")
        if sum(isinstance(p.passing, VariadicPositionalV1) for p in self.parameters) > 1 or sum(isinstance(p.passing, VariadicKeywordV1) for p in self.parameters) > 1:
            raise ContextManagerContractError("at most one variadic positional and keyword parameter")


@dataclass(frozen=True)
class EffectBoundarySemanticsV1:
    mode: ExpectsModeV1 | SuppressesModeV1
    effect_kind: RaiseEffectKindV1 | WarningEffectKindV1
    expected_type_operand: FormalArgumentProjectionV1 | VariadicPositionalElementProjectionV1 | VariadicKeywordEntryProjectionV1
    message_pattern_operand: NoMessagePatternV1 | OptionalFormalArgumentProjectionV1 | VariadicPositionalElementProjectionV1 | VariadicKeywordEntryProjectionV1
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

        if not isinstance(self.occurrence, SourceFragmentCoordinateV1) \
                or not isinstance(self.value, Sugar):
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
        if isinstance(self.formal_index, bool) or not isinstance(self.formal_index, int) or self.formal_index < 0:
            raise ContextManagerContractError("variadic positional actual requires a nonnegative formal index")
        if any(element.keyword is not None for element in self.elements):
            raise ContextManagerContractError("variadic positional actual cannot carry keyword entries")


@dataclass(frozen=True)
class VariadicKeywordActualV1:
    formal_index: int
    entries: tuple[ConstructedOperandOccurrenceV1, ...]

    def __post_init__(self) -> None:
        if isinstance(self.formal_index, bool) or not isinstance(self.formal_index, int) or self.formal_index < 0:
            raise ContextManagerContractError("variadic keyword actual requires a nonnegative formal index")
        keys = tuple(entry.keyword for entry in self.entries)
        if any(not isinstance(key, str) or not key for key in keys) or len(set(keys)) != len(keys):
            raise ContextManagerContractError("variadic keyword actuals require unique real keywords")


def project_formal_selector_v1(
    selector,
    *,
    fixed_actuals: Mapping[int, Any],
    variadic_positional_actuals: Mapping[int, VariadicPositionalActualV1],
    variadic_keyword_actuals: Mapping[int, VariadicKeywordActualV1],
):
    """Project an already-constructed actual; never create a replacement value."""
    if isinstance(selector, (FormalArgumentProjectionV1, OptionalFormalArgumentProjectionV1)):
        try:
            return fixed_actuals[selector.parameter_index]
        except KeyError as exc:
            if isinstance(selector, OptionalFormalArgumentProjectionV1):
                return None
            raise ContextManagerContractError("required formal actual is absent") from exc
    if isinstance(selector, VariadicPositionalElementProjectionV1):
        pack = variadic_positional_actuals.get(selector.parameter_index)
        if pack is None or pack.formal_index != selector.parameter_index:
            raise ContextManagerContractError("variadic positional actual is absent")
        try:
            return pack.elements[selector.element_index].value
        except IndexError as exc:
            raise ContextManagerContractError("variadic positional element is out of range") from exc
    if isinstance(selector, VariadicKeywordEntryProjectionV1):
        pack = variadic_keyword_actuals.get(selector.parameter_index)
        if pack is None or pack.formal_index != selector.parameter_index:
            raise ContextManagerContractError("variadic keyword actual is absent")
        matches = tuple(entry for entry in pack.entries if entry.keyword == selector.keyword)
        if len(matches) != 1:
            raise ContextManagerContractError("variadic keyword entry is absent or ambiguous")
        return matches[0].value
    raise ContextManagerContractError("unknown formal selector")


def resolve_parameter_default_v1(
    parameter: CallParameterV1,
    provider_catalog: AuthenticatedProviderValueCatalogV1,
):
    default = parameter.default
    if isinstance(default, NoDefaultV1):
        raise ContextManagerContractError("parameter has no authenticated default")
    if isinstance(default, LiteralDefaultV1):
        return default.value
    if isinstance(default, ProviderValueRefV1):
        if not isinstance(provider_catalog, AuthenticatedProviderValueCatalogV1):
            raise ContextManagerContractError(
                "provider default requires an authenticated provider catalog"
            )
        resolved = _resolve_provider_value_member_v1(
            default.value_ref_cid, provider_catalog
        )
        if resolved.sort != default.sort or resolved.sort != parameter.sort:
            raise ContextManagerContractError("provider default sort mismatch")
        return resolved
    raise ContextManagerContractError("unknown authenticated default")


@dataclass(frozen=True)
class PublishedContextManagerContractV1:
    bridge_source_symbol: str
    import_signature: ImportSignatureV2
    semantics: ContextManagerSemanticsV1
    source_warrants: tuple[str, ...]
    payload_cid: str
    provider_kit_cid: str | None = None
    provider_export_cid: str | None = None
    signer_key_id: str | None = None


class ContextManagerContractError(ValueError):
    """A sealed CM-contract member is malformed, stale, or unauthenticated."""


def _selector_to_value(selector):
    index = getattr(selector, "parameter_index", None)
    if isinstance(index, bool) or not isinstance(index, int) or index < 0:
        raise ContextManagerContractError("selector requires a nonnegative parameter index")
    if isinstance(selector, FormalArgumentProjectionV1):
        return vobj([("kind", vstr("formal-argument")), ("parameterIndex", _json_value(index))])
    if isinstance(selector, OptionalFormalArgumentProjectionV1):
        return vobj([("kind", vstr("optional-formal-argument")), ("parameterIndex", _json_value(index))])
    if isinstance(selector, VariadicPositionalElementProjectionV1):
        if isinstance(selector.element_index, bool) or not isinstance(selector.element_index, int) or selector.element_index < 0:
            raise ContextManagerContractError("variadic element selector requires a nonnegative element index")
        return vobj([
            ("kind", vstr("variadic-positional-element")),
            ("parameterIndex", _json_value(index)),
            ("elementIndex", _json_value(selector.element_index)),
        ])
    if isinstance(selector, VariadicKeywordEntryProjectionV1):
        if not isinstance(selector.keyword, str) or not selector.keyword:
            raise ContextManagerContractError("variadic keyword selector requires a keyword")
        return vobj([
            ("kind", vstr("variadic-keyword-entry")),
            ("parameterIndex", _json_value(index)),
            ("keyword", vstr(selector.keyword)),
        ])
    raise ContextManagerContractError("unknown formal selector")


def semantics_to_value(semantics: ContextManagerSemanticsV1):
    if isinstance(semantics, ProtocolResourceSemanticsV1):
        if semantics.schema_version != "1" or not isinstance(semantics.enter.completion, TotalCompletionV1) or semantics.enter.projection != ENTER_RESULT:
            raise ContextManagerContractError("unsupported protocol-resource enter testimony")
        if not isinstance(semantics.exit.completion, TotalCompletionV1):
            raise ContextManagerContractError("unsupported protocol-resource exit testimony")
        if isinstance(semantics.exit.disposition, NeverSuppressesDispositionV1):
            disposition = "never-suppresses"
        elif isinstance(semantics.exit.disposition, ReturnTruthinessDispositionV1):
            disposition = "return-truthiness"
        else:
            raise ContextManagerContractError("unknown protocol-resource exit disposition")
        return vobj([
        ("kind", vstr("protocol-resource")),
        ("schemaVersion", vstr("1")),
        ("enter", vobj([
            ("completion", vobj([("kind", vstr("total"))])),
            ("result", vobj([
                ("kind", vstr("projection")),
                ("projection", vstr(ENTER_RESULT)),
                ("sort", sort_to_value(semantics.enter.sort)),
            ])),
        ])),
        ("exit", vobj([
            ("completion", vobj([("kind", vstr("total"))])),
            ("disposition", vobj([("kind", vstr(disposition))])),
        ])),
        ])
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
        return vobj([
            ("kind", vstr("effect-boundary")),
            ("schemaVersion", vstr("1")),
            ("mode", vobj([("kind", vstr(mode))])),
            ("matcher", vobj([
                ("effectKind", vobj([("kind", vstr(effect_kind))])),
                ("expectedTypeOperand", expected_value),
                ("messagePatternOperand", message_value),
            ])),
            ("binding", vobj([("kind", vstr(binding))])),
        ])
    raise ContextManagerContractError("unknown context-manager semantics variant")


def publish_never_suppresses_context_manager_contract(
    *, bridge_source_symbol: str, import_signature: Any,
    enter_result_sort: Sort, source_warrants: Sequence[str],
    signer: Signer, declared_at: str,
) -> ClaimEnvelope:
    semantics = ProtocolResourceSemanticsV1(
        enter=EnterResultContractV1(sort=enter_result_sort),
        exit=ExitContractV1(disposition=NeverSuppressesDispositionV1()),
    )
    return publish_context_manager_contract(
        bridge_source_symbol=bridge_source_symbol,
        import_signature=import_signature,
        semantics=semantics,
        source_warrants=source_warrants,
        signer=signer,
        declared_at=declared_at,
    )


def publish_effect_boundary_context_manager_contract(
    *, bridge_source_symbol: str, import_signature: ImportSignatureV2,
    mode: ExpectsModeV1 | SuppressesModeV1,
    effect_kind: RaiseEffectKindV1 | WarningEffectKindV1,
    expected_type_operand: FormalArgumentProjectionV1 | VariadicPositionalElementProjectionV1 | VariadicKeywordEntryProjectionV1,
    message_pattern_operand: NoMessagePatternV1 | OptionalFormalArgumentProjectionV1 | VariadicPositionalElementProjectionV1 | VariadicKeywordEntryProjectionV1,
    binding: NoBindingV1 | ExceptionInfoBindingV1 | WarningObservationBindingV1,
    source_warrants: Sequence[str], signer: Signer, declared_at: str,
    provider_kit_cid: str | None = None, signer_key_id: str | None = None,
) -> ClaimEnvelope:
    """Publish a provider-owned EffectBoundary through the sole CM envelope door."""
    return publish_context_manager_contract(
        bridge_source_symbol=bridge_source_symbol,
        import_signature=import_signature,
        semantics=EffectBoundarySemanticsV1(
            mode=mode,
            effect_kind=effect_kind,
            expected_type_operand=expected_type_operand,
            message_pattern_operand=message_pattern_operand,
            binding=binding,
        ),
        source_warrants=source_warrants,
        signer=signer,
        declared_at=declared_at,
        provider_kit_cid=provider_kit_cid,
        signer_key_id=signer_key_id,
    )


def publish_context_manager_contract(
    *, bridge_source_symbol: str, import_signature: ImportSignatureV2,
    semantics: ContextManagerSemanticsV1, source_warrants: Sequence[str],
    signer: Signer, declared_at: str,
    provider_kit_cid: str | None = None,
    signer_key_id: str | None = None,
) -> ClaimEnvelope:
    if not bridge_source_symbol:
        raise ContextManagerContractError("bridgeSourceSymbol must be non-empty")
    if not isinstance(import_signature, ImportSignatureV2):
        raise ContextManagerContractError("ImportSignatureV2 required")
    if not all(isinstance(w, str) and w.startswith("blake3-512:") for w in source_warrants):
        raise ContextManagerContractError("sourceWarrants must be CID references")
    payload = semantics_to_value(semantics)
    decoded_payload = json.loads(encode_jcs(payload))
    if decode_context_manager_semantics_v1(decoded_payload, import_signature) != semantics:
        raise ContextManagerContractError("context-manager semantics failed canonical validation")
    payload_cid = blake3_512_of(encode_jcs(payload).encode())
    sorted_inputs = sorted(source_warrants)
    provider_fields = ()
    schema_version = "1.2"
    if provider_kit_cid is not None or signer_key_id is not None:
        if not isinstance(provider_kit_cid, str) or not provider_kit_cid.startswith("blake3-512:"):
            raise ContextManagerContractError("providerKitCid must be an authenticated CID")
        if not isinstance(signer_key_id, str) or not signer_key_id:
            raise ContextManagerContractError("provider member requires signerKeyId")
        provider_export_cid = blake3_512_of(encode_jcs(vobj([
            ("kind", vstr("provider-export")),
            ("schemaVersion", vstr("1")),
            ("providerKitCid", vstr(provider_kit_cid)),
            ("bridgeSourceSymbol", vstr(bridge_source_symbol)),
            ("importSignature", import_signature_to_value(import_signature)),
        ])).encode())
        schema_version = "1.3"
        provider_fields = (
            ("providerKitCid", vstr(provider_kit_cid)),
            ("providerExportCid", vstr(provider_export_cid)),
            ("signerKeyId", vstr(signer_key_id)),
        )
    header = vobj([
        ("schemaVersion", vstr(schema_version)),
        ("kind", vstr("context-manager-contract")),
        ("cid", vstr(payload_cid)),
        ("payloadCid", vstr(payload_cid)),
        ("bridgeSourceSymbol", vstr(bridge_source_symbol)),
        ("importSignature", import_signature_to_value(import_signature)),
        ("payload", payload),
        ("sourceWarrants", varr([vstr(v) for v in source_warrants])),
        ("inputCids", varr([vstr(v) for v in sorted_inputs])),
        *provider_fields,
    ])
    metadata = vobj([
        ("authoring", vobj([
            ("producerKind", vstr("kit-author")),
            ("author", vstr(signer.producer_id)),
        ])),
        ("producedBy", vstr(signer.producer_id)),
        ("producedAt", vstr(declared_at)),
    ])
    return _assemble_layered(header, metadata, declared_at, signer.seed, payload_cid)


def publish_provider_value_v1(
    *, provider_kit_cid: str, signer_key_id: str, sort: Sort,
    value: Mapping[str, object], signer: Signer, declared_at: str,
) -> ClaimEnvelope:
    """Seal one provider-owned opaque value coordinate for signature defaults."""
    if re.fullmatch(r"blake3-512:[0-9a-f]{128}", provider_kit_cid) is None:
        raise ContextManagerContractError("provider value requires a provider kit CID")
    if not signer_key_id or not isinstance(value, Mapping):
        raise ContextManagerContractError("provider value requires a signer key and value preimage")
    payload = vobj([
        ("kind", vstr("provider-value")),
        ("schemaVersion", vstr("1")),
        ("sort", sort_to_value(sort)),
        ("value", _json_value(dict(value))),
    ])
    payload_cid = blake3_512_of(encode_jcs(payload).encode())
    header = vobj([
        ("schemaVersion", vstr("1")),
        ("kind", vstr("provider-value")),
        ("cid", vstr(payload_cid)),
        ("payloadCid", vstr(payload_cid)),
        ("providerKitCid", vstr(provider_kit_cid)),
        ("signerKeyId", vstr(signer_key_id)),
        ("sort", sort_to_value(sort)),
        ("payload", payload),
        ("inputCids", varr([])),
    ])
    metadata = vobj([
        ("authoring", vobj([
            ("producerKind", vstr("kit-author")),
            ("author", vstr(signer.producer_id)),
        ])),
        ("producedBy", vstr(signer.producer_id)),
        ("producedAt", vstr(declared_at)),
    ])
    return _assemble_layered(
        header, metadata, declared_at, signer.seed, payload_cid
    )


def _resolve_provider_value_member_v1(
    requested_cid: str,
    catalog: AuthenticatedProviderValueCatalogV1,
) -> ResolvedProviderValueV1:
    try:
        catalog_member = catalog.members_by_value_cid[requested_cid]
    except KeyError as exc:
        raise ContextManagerContractError("unresolved provider default") from exc
    canonical_bytes = catalog_member.canonical_bytes
    try:
        raw = json.loads(canonical_bytes)
    except (TypeError, ValueError) as exc:
        raise ContextManagerContractError("provider default member is not canonical JSON") from exc
    if not isinstance(raw, dict) or set(raw) != {"envelope", "header", "metadata"}:
        raise ContextManagerContractError("provider default member is malformed")
    envelope, header, metadata = raw["envelope"], raw["header"], raw["metadata"]
    if not isinstance(envelope, dict) or not isinstance(header, dict) or not isinstance(metadata, dict):
        raise ContextManagerContractError("provider default member layers are malformed")
    actual_member_cid = blake3_512_of(encode_jcs(_json_value(envelope)).encode())
    if actual_member_cid != catalog_member.member_cid:
        raise ContextManagerContractError("provider default member CID is stale")
    expected_header = {
        "schemaVersion", "kind", "cid", "payloadCid", "providerKitCid",
        "signerKeyId", "sort", "payload", "inputCids",
    }
    if set(header) != expected_header or header.get("schemaVersion") != "1" \
            or header.get("kind") != "provider-value" or header.get("inputCids") != []:
        raise ContextManagerContractError("provider default member header is malformed")
    payload = header["payload"]
    if not isinstance(payload, dict) or set(payload) != {
        "kind", "schemaVersion", "sort", "value"
    } or payload.get("kind") != "provider-value" or payload.get("schemaVersion") != "1":
        raise ContextManagerContractError("provider default payload is malformed")
    payload_cid = blake3_512_of(encode_jcs(_json_value(payload)).encode())
    if requested_cid != payload_cid or header.get("cid") != payload_cid \
            or header.get("payloadCid") != payload_cid:
        raise ContextManagerContractError("provider default content CID does not match preimage")
    binding = catalog.key_binding
    if header.get("providerKitCid") != binding.provider_kit_cid \
            or header.get("signerKeyId") != binding.signer_key_id \
            or envelope.get("signer") != binding.signer_public_key:
        raise ContextManagerContractError("provider default provider signer is not authorized")
    signing = vobj([
        ("header", _json_value(header)),
        ("metadata", _json_value(metadata)),
    ])
    if not ed25519_verify_string(
        binding.signer_public_key,
        envelope.get("signature", ""),
        encode_jcs(signing).encode(),
    ):
        raise ContextManagerContractError("provider default signature does not verify")
    sort = _decode_sort(payload["sort"])
    if _decode_sort(header["sort"]) != sort:
        raise ContextManagerContractError("provider default sort testimony disagrees")
    return ResolvedProviderValueV1(
        member_cid=catalog_member.member_cid,
        payload_cid=payload_cid,
        provider_kit_cid=binding.provider_kit_cid,
        sort=sort,
        value_jcs=encode_jcs(_json_value(payload["value"])),
    )


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
    if raw.get("kind") == "primitive" and set(raw) == {"kind", "name"} and isinstance(raw["name"], str):
        return PrimitiveSort(raw["name"])
    if raw.get("kind") == "region" and set(raw) == {"kind", "name"} and isinstance(raw["name"], str):
        return RegionSort(raw["name"])
    if raw.get("kind") == "function" and set(raw) == {"kind", "args", "return"} and isinstance(raw["args"], list):
        return FunctionSort(tuple(_decode_sort(v) for v in raw["args"]), _decode_sort(raw["return"]))
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
            default = vobj([("kind", vstr("literal-default")), ("value", _json_value(parameter.default.value))])
        elif isinstance(parameter.default, ProviderValueRefV1):
            default = vobj([
                ("kind", vstr("provider-value-ref")),
                ("valueRefCid", vstr(parameter.default.value_ref_cid)),
                ("sort", sort_to_value(parameter.default.sort)),
            ])
        else:
            raise ContextManagerContractError("unknown authenticated default")
        rows.append(vobj([
            ("name", vstr(parameter.name)),
            ("sort", sort_to_value(parameter.sort)),
            ("passing", vobj([("kind", vstr(passing))])),
            ("required", _json_value(parameter.required)),
            ("default", default),
        ]))
    return vobj([("parameters", varr([
        *rows
    ]))])


def decode_import_signature_v2(raw: Any) -> ImportSignatureV2:
    if not isinstance(raw, dict) or set(raw) != {"parameters"} or not isinstance(raw["parameters"], list):
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
        if not isinstance(value, dict) or set(value) != {"name", "sort", "passing", "required", "default"}:
            raise ContextManagerContractError("malformed call parameter")
        if not isinstance(value["name"], str) or not value["name"] or type(value["required"]) is not bool:
            raise ContextManagerContractError("malformed call parameter fields")
        passing = _tag(value["passing"], passing_types, "parameter passing mode")
        raw_default = value["default"]
        if not isinstance(raw_default, dict) or "kind" not in raw_default:
            raise ContextManagerContractError("malformed authenticated default")
        if raw_default.get("kind") == "no-default" and set(raw_default) == {"kind"}:
            default = NoDefaultV1()
        elif raw_default.get("kind") == "literal-default" and set(raw_default) == {"kind", "value"}:
            default = LiteralDefaultV1(raw_default["value"])
        elif raw_default.get("kind") == "provider-value-ref" and set(raw_default) == {"kind", "valueRefCid", "sort"}:
            default = ProviderValueRefV1(raw_default["valueRefCid"], _decode_sort(raw_default["sort"]))
        else:
            raise ContextManagerContractError("unknown or malformed authenticated default")
        parameters.append(CallParameterV1(value["name"], _decode_sort(value["sort"]), passing, value["required"], default))
    return ImportSignatureV2(tuple(parameters))


def _decode_total(raw: Any) -> TotalCompletionV1:
    if not isinstance(raw, dict) or set(raw) != {"kind"} or raw["kind"] != "total":
        raise ContextManagerContractError("unknown completion testimony")
    return TotalCompletionV1()


def _decode_protocol_resource(raw: Any) -> ProtocolResourceSemanticsV1:
    if set(raw) != {"kind", "schemaVersion", "enter", "exit"} or raw["schemaVersion"] != "1":
        raise ContextManagerContractError("malformed protocol-resource semantics")
    enter = raw["enter"]
    exit_ = raw["exit"]
    if not isinstance(enter, dict) or set(enter) != {"completion", "result"}:
        raise ContextManagerContractError("malformed context-manager semantics enter")
    result = enter["result"]
    completion = _decode_total(enter["completion"])
    if not isinstance(result, dict) or set(result) != {"kind", "projection", "sort"} or result["kind"] != "projection" or result["projection"] != ENTER_RESULT:
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
        enter=EnterResultContractV1(sort=_decode_sort(result["sort"]), completion=completion),
        exit=ExitContractV1(disposition=decoded_disposition, completion=exit_completion),
    )


def _tag(raw: Any, allowed: dict[str, Any], owner: str):
    if not isinstance(raw, dict) or set(raw) != {"kind"} or raw["kind"] not in allowed:
        raise ContextManagerContractError(f"unknown {owner}")
    return allowed[raw["kind"]]()


def _decode_selector(raw: Any, *, allow_optional: bool):
    if not isinstance(raw, dict) or not isinstance(raw.get("kind"), str):
        raise ContextManagerContractError("malformed formal selector")
    kind = raw["kind"]
    fixed_cls = OptionalFormalArgumentProjectionV1 if allow_optional else FormalArgumentProjectionV1
    fixed_kind = "optional-formal-argument" if allow_optional else "formal-argument"
    if kind == fixed_kind and set(raw) == {"kind", "parameterIndex"}:
        selector = fixed_cls(raw["parameterIndex"])
    elif kind == "variadic-positional-element" and set(raw) == {"kind", "parameterIndex", "elementIndex"}:
        selector = VariadicPositionalElementProjectionV1(raw["parameterIndex"], raw["elementIndex"])
    elif kind == "variadic-keyword-entry" and set(raw) == {"kind", "parameterIndex", "keyword"}:
        selector = VariadicKeywordEntryProjectionV1(raw["parameterIndex"], raw["keyword"])
    else:
        raise ContextManagerContractError("unknown or malformed formal selector")
    _selector_to_value(selector)
    return selector


def _selector_parameter(selector, signature: ImportSignatureV2) -> CallParameterV1:
    if selector.parameter_index >= len(signature.parameters):
        raise ContextManagerContractError("selector is outside ImportSignatureV2")
    parameter = signature.parameters[selector.parameter_index]
    if isinstance(selector, (FormalArgumentProjectionV1, OptionalFormalArgumentProjectionV1)):
        if isinstance(parameter.passing, (VariadicPositionalV1, VariadicKeywordV1)):
            raise ContextManagerContractError("fixed selector cannot address a variadic parameter")
    elif isinstance(selector, VariadicPositionalElementProjectionV1):
        if not isinstance(parameter.passing, VariadicPositionalV1):
            raise ContextManagerContractError("variadic element selector requires *args")
    elif isinstance(selector, VariadicKeywordEntryProjectionV1):
        if not isinstance(parameter.passing, VariadicKeywordV1):
            raise ContextManagerContractError("variadic keyword selector requires **kwargs")
    else:
        raise ContextManagerContractError("unknown formal selector")
    return parameter


def _decode_effect_boundary(raw: Any, signature: ImportSignatureV2) -> EffectBoundarySemanticsV1:
    if set(raw) != {"kind", "schemaVersion", "mode", "matcher", "binding"} or raw["schemaVersion"] != "1":
        raise ContextManagerContractError("malformed effect-boundary semantics")
    matcher = raw["matcher"]
    if not isinstance(matcher, dict) or set(matcher) != {"effectKind", "expectedTypeOperand", "messagePatternOperand"}:
        raise ContextManagerContractError("malformed effect-boundary matcher")
    mode = _tag(raw["mode"], {"expects": ExpectsModeV1, "suppresses": SuppressesModeV1}, "effect-boundary mode")
    effect_kind = _tag(matcher["effectKind"], {"raise": RaiseEffectKindV1, "warning": WarningEffectKindV1}, "effect kind")
    expected = _decode_selector(matcher["expectedTypeOperand"], allow_optional=False)
    message_raw = matcher["messagePatternOperand"]
    if isinstance(message_raw, dict) and set(message_raw) == {"kind"} and message_raw["kind"] == "none":
        message = NoMessagePatternV1()
    else:
        message = _decode_selector(message_raw, allow_optional=True)
    binding = _tag(raw["binding"], {"none": NoBindingV1, "exception-info": ExceptionInfoBindingV1, "warning-observation": WarningObservationBindingV1}, "effect-boundary binding")
    expected_parameter = _selector_parameter(expected, signature)
    if expected_parameter.sort != PrimitiveSort("Value"):
        raise ContextManagerContractError("expected-type selector requires a Value formal")
    if not isinstance(message, NoMessagePatternV1):
        parameter = _selector_parameter(message, signature)
        if message == expected:
            raise ContextManagerContractError("effect-boundary selectors must be distinct")
        if isinstance(message, OptionalFormalArgumentProjectionV1):
            if parameter.required or not isinstance(parameter.passing, (PositionalOrKeywordV1, KeywordOnlyV1)) or parameter.sort not in (PrimitiveSort("String"), PrimitiveSort("Value")):
                raise ContextManagerContractError("message selector requires an optional keyword-bindable String-or-Value formal")
        elif parameter.sort != PrimitiveSort("Value"):
            raise ContextManagerContractError("variadic message selector requires a Value pack")
    return EffectBoundarySemanticsV1(mode, effect_kind, expected, message, binding)


def decode_context_manager_semantics_v1(raw: Any, signature: ImportSignatureV2 | None = None) -> ContextManagerSemanticsV1:
    if not isinstance(raw, dict) or "kind" not in raw:
        raise ContextManagerContractError("malformed context-manager semantics")
    if raw["kind"] == "protocol-resource":
        return _decode_protocol_resource(raw)
    if raw["kind"] == "effect-boundary":
        if signature is None:
            raise ContextManagerContractError("EffectBoundary decoding requires ImportSignatureV2")
        return _decode_effect_boundary(raw, signature)
    raise ContextManagerContractError("unknown context-manager semantics variant")


def decode_context_manager_contract(
    canonical_bytes: bytes, member_cid: str
) -> PublishedContextManagerContractV1:
    try:
        raw = json.loads(canonical_bytes)
    except (TypeError, ValueError) as exc:
        raise ContextManagerContractError("member is not JSON") from exc
    if not isinstance(raw, dict) or set(raw) != {"envelope", "header", "metadata"}:
        raise ContextManagerContractError("CM contract must be a layered member")
    envelope, header = raw["envelope"], raw["header"]
    if not isinstance(raw["metadata"], dict):
        raise ContextManagerContractError("layered metadata must be an object")
    if blake3_512_of(encode_jcs(_json_value(envelope)).encode()) != member_cid:
        raise ContextManagerContractError("member attestation CID does not match envelope")
    signing = vobj([("header", _json_value(header)), ("metadata", _json_value(raw["metadata"]))])
    if not ed25519_verify_string(envelope.get("signer", ""), envelope.get("signature", ""), encode_jcs(signing).encode()):
        raise ContextManagerContractError("member signature does not verify")
    common = {"schemaVersion", "kind", "cid", "payloadCid", "bridgeSourceSymbol", "importSignature", "payload", "sourceWarrants", "inputCids"}
    provider = {"providerKitCid", "providerExportCid", "signerKeyId"}
    if not isinstance(header, dict) or header.get("kind") != "context-manager-contract" or (
        header.get("schemaVersion") == "1.2" and set(header) != common
    ) or (
        header.get("schemaVersion") == "1.3" and set(header) != common | provider
    ) or header.get("schemaVersion") not in {"1.2", "1.3"}:
        raise ContextManagerContractError("malformed context-manager-contract header")
    signature = decode_import_signature_v2(header["importSignature"])
    semantics = decode_context_manager_semantics_v1(header["payload"], signature)
    payload_cid = blake3_512_of(encode_jcs(semantics_to_value(semantics)).encode())
    if header["cid"] != payload_cid or header["payloadCid"] != payload_cid:
        raise ContextManagerContractError("context-manager payload CID does not match semantics")
    warrants = header["sourceWarrants"]
    if not isinstance(warrants, list) or not all(isinstance(v, str) and v.startswith("blake3-512:") for v in warrants):
        raise ContextManagerContractError("sourceWarrants must be CID references")
    if header["inputCids"] != sorted(warrants):
        raise ContextManagerContractError("inputCids do not match sourceWarrants")
    symbol = header["bridgeSourceSymbol"]
    if not isinstance(symbol, str) or not symbol:
        raise ContextManagerContractError("bridgeSourceSymbol must be non-empty")
    provider_kit_cid = header.get("providerKitCid")
    provider_export_cid = header.get("providerExportCid")
    signer_key_id = header.get("signerKeyId")
    if header["schemaVersion"] == "1.3":
        expected_export = blake3_512_of(encode_jcs(vobj([
            ("kind", vstr("provider-export")), ("schemaVersion", vstr("1")),
            ("providerKitCid", vstr(provider_kit_cid)),
            ("bridgeSourceSymbol", vstr(symbol)),
            ("importSignature", import_signature_to_value(signature)),
        ])).encode())
        if provider_export_cid != expected_export or not signer_key_id:
            raise ContextManagerContractError("provider export identity mismatch")
    return PublishedContextManagerContractV1(
        bridge_source_symbol=symbol,
        import_signature=signature,
        semantics=semantics,
        source_warrants=tuple(warrants),
        payload_cid=payload_cid,
        provider_kit_cid=provider_kit_cid,
        provider_export_cid=provider_export_cid,
        signer_key_id=signer_key_id,
    )
