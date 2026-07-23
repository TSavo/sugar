"""Typed context-manager dispositions and sealed CM-contract publications."""

from __future__ import annotations

from dataclasses import dataclass
import json
from typing import Any, Optional, Sequence

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
    index: int
    kind: str = "formal-argument"


@dataclass(frozen=True)
class NoMessagePatternV1:
    kind: str = "none"


@dataclass(frozen=True)
class OptionalFormalArgumentProjectionV1:
    index: int
    kind: str = "optional-formal-argument"


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
class CallParameterV1:
    name: str
    sort: Sort
    passing: PositionalOnlyV1 | PositionalOrKeywordV1 | KeywordOnlyV1
    required: bool

    def __post_init__(self) -> None:
        if not self.name:
            raise ContextManagerContractError("call parameter name must be nonempty")


@dataclass(frozen=True)
class ImportSignatureV2:
    parameters: tuple[CallParameterV1, ...]

    def __post_init__(self) -> None:
        names = tuple(parameter.name for parameter in self.parameters)
        if len(set(names)) != len(names):
            raise ContextManagerContractError("call parameter names must be unique")


@dataclass(frozen=True)
class EffectBoundarySemanticsV1:
    mode: ExpectsModeV1 | SuppressesModeV1
    effect_kind: RaiseEffectKindV1 | WarningEffectKindV1
    expected_type_operand: FormalArgumentProjectionV1
    message_pattern_operand: NoMessagePatternV1 | OptionalFormalArgumentProjectionV1
    binding: NoBindingV1 | ExceptionInfoBindingV1 | WarningObservationBindingV1
    kind: str = "effect-boundary"
    schema_version: str = "1"


ContextManagerSemanticsV1 = ProtocolResourceSemanticsV1 | EffectBoundarySemanticsV1


@dataclass(frozen=True)
class PublishedContextManagerContractV1:
    bridge_source_symbol: str
    import_signature: ImportSignatureV2
    semantics: ContextManagerSemanticsV1
    source_warrants: tuple[str, ...]
    payload_cid: str


class ContextManagerContractError(ValueError):
    """A sealed CM-contract member is malformed, stale, or unauthenticated."""


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
        expected = semantics.expected_type_operand
        if not isinstance(expected, FormalArgumentProjectionV1) or isinstance(expected.index, bool) or not isinstance(expected.index, int) or expected.index < 0:
            raise ContextManagerContractError("expected-type selector requires a nonnegative formal position")
        message = semantics.message_pattern_operand
        if isinstance(message, NoMessagePatternV1):
            message_value = vobj([("kind", vstr("none"))])
        elif isinstance(message, OptionalFormalArgumentProjectionV1) and not isinstance(message.index, bool) and isinstance(message.index, int) and message.index >= 0:
            message_value = vobj([("kind", vstr("optional-formal-argument")), ("index", _json_value(message.index))])
        else:
            raise ContextManagerContractError("unknown message-pattern selector")
        return vobj([
            ("kind", vstr("effect-boundary")),
            ("schemaVersion", vstr("1")),
            ("mode", vobj([("kind", vstr(mode))])),
            ("matcher", vobj([
                ("effectKind", vobj([("kind", vstr(effect_kind))])),
                ("expectedTypeOperand", vobj([
                    ("kind", vstr("formal-argument")),
                    ("index", _json_value(expected.index)),
                ])),
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


def publish_context_manager_contract(
    *, bridge_source_symbol: str, import_signature: ImportSignatureV2,
    semantics: ContextManagerSemanticsV1, source_warrants: Sequence[str],
    signer: Signer, declared_at: str,
) -> ClaimEnvelope:
    if not bridge_source_symbol:
        raise ContextManagerContractError("bridgeSourceSymbol must be non-empty")
    if not isinstance(import_signature, ImportSignatureV2):
        raise ContextManagerContractError("ImportSignatureV2 required")
    if not all(isinstance(w, str) and w.startswith("blake3-512:") for w in source_warrants):
        raise ContextManagerContractError("sourceWarrants must be CID references")
    payload = semantics_to_value(semantics)
    payload_cid = blake3_512_of(encode_jcs(payload).encode())
    sorted_inputs = sorted(source_warrants)
    header = vobj([
        ("schemaVersion", vstr("1.2")),
        ("kind", vstr("context-manager-contract")),
        ("cid", vstr(payload_cid)),
        ("payloadCid", vstr(payload_cid)),
        ("bridgeSourceSymbol", vstr(bridge_source_symbol)),
        ("importSignature", import_signature_to_value(import_signature)),
        ("payload", payload),
        ("sourceWarrants", varr([vstr(v) for v in source_warrants])),
        ("inputCids", varr([vstr(v) for v in sorted_inputs])),
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
        if isinstance(parameter.passing, PositionalOnlyV1):
            passing = "positional-only"
        elif isinstance(parameter.passing, PositionalOrKeywordV1):
            passing = "positional-or-keyword"
        elif isinstance(parameter.passing, KeywordOnlyV1):
            passing = "keyword-only"
        else:
            raise ContextManagerContractError("unknown parameter passing mode")
        if type(parameter.required) is not bool:
            raise ContextManagerContractError("call parameter required must be bool")
        rows.append(vobj([
            ("name", vstr(parameter.name)),
            ("sort", sort_to_value(parameter.sort)),
            ("passing", vobj([("kind", vstr(passing))])),
            ("required", _json_value(parameter.required)),
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
    }
    for value in raw["parameters"]:
        if not isinstance(value, dict) or set(value) != {"name", "sort", "passing", "required"}:
            raise ContextManagerContractError("malformed call parameter")
        if not isinstance(value["name"], str) or not value["name"] or type(value["required"]) is not bool:
            raise ContextManagerContractError("malformed call parameter fields")
        passing = _tag(value["passing"], passing_types, "parameter passing mode")
        parameters.append(CallParameterV1(value["name"], _decode_sort(value["sort"]), passing, value["required"]))
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


def _projection(raw: Any, *, optional: bool):
    expected = "optional-formal-argument" if optional else "formal-argument"
    if not isinstance(raw, dict) or set(raw) != {"kind", "index"} or raw["kind"] != expected:
        raise ContextManagerContractError("malformed formal argument projection")
    if isinstance(raw["index"], bool) or not isinstance(raw["index"], int) or raw["index"] < 0:
        raise ContextManagerContractError("formal argument index must be nonnegative")
    cls = OptionalFormalArgumentProjectionV1 if optional else FormalArgumentProjectionV1
    return cls(raw["index"])


def _decode_effect_boundary(raw: Any, signature: ImportSignatureV2) -> EffectBoundarySemanticsV1:
    if set(raw) != {"kind", "schemaVersion", "mode", "matcher", "binding"} or raw["schemaVersion"] != "1":
        raise ContextManagerContractError("malformed effect-boundary semantics")
    matcher = raw["matcher"]
    if not isinstance(matcher, dict) or set(matcher) != {"effectKind", "expectedTypeOperand", "messagePatternOperand"}:
        raise ContextManagerContractError("malformed effect-boundary matcher")
    mode = _tag(raw["mode"], {"expects": ExpectsModeV1, "suppresses": SuppressesModeV1}, "effect-boundary mode")
    effect_kind = _tag(matcher["effectKind"], {"raise": RaiseEffectKindV1, "warning": WarningEffectKindV1}, "effect kind")
    expected = _projection(matcher["expectedTypeOperand"], optional=False)
    message_raw = matcher["messagePatternOperand"]
    if isinstance(message_raw, dict) and set(message_raw) == {"kind"} and message_raw["kind"] == "none":
        message = NoMessagePatternV1()
    else:
        message = _projection(message_raw, optional=True)
    binding = _tag(raw["binding"], {"none": NoBindingV1, "exception-info": ExceptionInfoBindingV1, "warning-observation": WarningObservationBindingV1}, "effect-boundary binding")
    if expected.index >= len(signature.parameters):
        raise ContextManagerContractError("expected-type selector is outside ImportSignatureV2")
    expected_parameter = signature.parameters[expected.index]
    if not expected_parameter.required or expected_parameter.sort != PrimitiveSort("Value"):
        raise ContextManagerContractError("expected-type selector requires a required Value formal")
    if isinstance(message, OptionalFormalArgumentProjectionV1):
        if message.index >= len(signature.parameters):
            raise ContextManagerContractError("message selector is outside ImportSignatureV2")
        parameter = signature.parameters[message.index]
        if message.index == expected.index:
            raise ContextManagerContractError("effect-boundary selectors must be distinct")
        if parameter.required or not isinstance(parameter.passing, (PositionalOrKeywordV1, KeywordOnlyV1)) or parameter.sort != PrimitiveSort("String"):
            raise ContextManagerContractError("message selector requires an optional keyword-bindable String formal")
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
    expected = {"schemaVersion", "kind", "cid", "payloadCid", "bridgeSourceSymbol", "importSignature", "payload", "sourceWarrants", "inputCids"}
    if not isinstance(header, dict) or set(header) != expected or header.get("schemaVersion") != "1.2" or header.get("kind") != "context-manager-contract":
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
    return PublishedContextManagerContractV1(
        bridge_source_symbol=symbol,
        import_signature=signature,
        semantics=semantics,
        source_warrants=tuple(warrants),
        payload_cid=payload_cid,
    )
