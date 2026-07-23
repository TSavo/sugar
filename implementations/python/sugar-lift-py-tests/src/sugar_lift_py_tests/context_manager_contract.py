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
ENTER_RESULT = "enter_result"


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
class EnterResultContractV1:
    sort: Sort
    completion: str = "total"
    projection: str = ENTER_RESULT


@dataclass(frozen=True)
class ExitContractV1:
    disposition: NeverSuppressesDispositionV1
    completion: str = "total"


@dataclass(frozen=True)
class ContextManagerSemanticsV1:
    enter: EnterResultContractV1
    exit: ExitContractV1
    kind: str = "context-manager-semantics"
    schema_version: str = "1"


@dataclass(frozen=True)
class PublishedContextManagerContractV1:
    bridge_source_symbol: str
    import_formals: tuple[str, ...]
    import_sorts: tuple[Sort, ...]
    semantics: ContextManagerSemanticsV1
    source_warrants: tuple[str, ...]
    payload_cid: str


class ContextManagerContractError(ValueError):
    """A sealed CM-contract member is malformed, stale, or unauthenticated."""


def semantics_to_value(semantics: ContextManagerSemanticsV1):
    if semantics.kind != "context-manager-semantics" or semantics.schema_version != "1":
        raise ContextManagerContractError("unsupported context-manager semantics schema")
    if semantics.enter.completion != "total" or semantics.enter.projection != ENTER_RESULT:
        raise ContextManagerContractError("unsupported enter testimony")
    if semantics.exit.completion != "total" or not isinstance(
        semantics.exit.disposition, NeverSuppressesDispositionV1
    ):
        raise ContextManagerContractError("unsupported exit disposition")
    return vobj([
        ("kind", vstr("context-manager-semantics")),
        ("schemaVersion", vstr("1")),
        ("enter", vobj([
            ("completion", vstr("total")),
            ("result", vobj([
                ("kind", vstr("projection")),
                ("projection", vstr(ENTER_RESULT)),
                ("sort", sort_to_value(semantics.enter.sort)),
            ])),
        ])),
        ("exit", vobj([
            ("completion", vstr("total")),
            ("disposition", vobj([("kind", vstr("never-suppresses"))])),
        ])),
    ])


def publish_never_suppresses_context_manager_contract(
    *, bridge_source_symbol: str, import_signature: Any,
    enter_result_sort: Sort, source_warrants: Sequence[str],
    signer: Signer, declared_at: str,
) -> ClaimEnvelope:
    if not bridge_source_symbol:
        raise ContextManagerContractError("bridgeSourceSymbol must be non-empty")
    formals = tuple(import_signature.formals)
    sorts = tuple(import_signature.sorts)
    if len(formals) != len(sorts):
        raise ContextManagerContractError("import signature formals/sorts length mismatch")
    if not all(isinstance(w, str) and w.startswith("blake3-512:") for w in source_warrants):
        raise ContextManagerContractError("sourceWarrants must be CID references")
    semantics = ContextManagerSemanticsV1(
        enter=EnterResultContractV1(sort=enter_result_sort),
        exit=ExitContractV1(disposition=NeverSuppressesDispositionV1()),
    )
    payload = semantics_to_value(semantics)
    payload_cid = blake3_512_of(encode_jcs(payload).encode())
    sorted_inputs = sorted(source_warrants)
    header = vobj([
        ("schemaVersion", vstr("1.2")),
        ("kind", vstr("context-manager-contract")),
        ("cid", vstr(payload_cid)),
        ("payloadCid", vstr(payload_cid)),
        ("bridgeSourceSymbol", vstr(bridge_source_symbol)),
        ("importSignature", vobj([
            ("formals", varr([vstr(v) for v in formals])),
            ("sorts", varr([sort_to_value(v) for v in sorts])),
        ])),
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


def _decode_semantics(raw: Any) -> ContextManagerSemanticsV1:
    if not isinstance(raw, dict) or set(raw) != {"kind", "schemaVersion", "enter", "exit"}:
        raise ContextManagerContractError("malformed context-manager semantics")
    if raw["kind"] != "context-manager-semantics" or raw["schemaVersion"] != "1":
        raise ContextManagerContractError("unknown context-manager semantics schema")
    enter = raw["enter"]
    exit_ = raw["exit"]
    if not isinstance(enter, dict) or set(enter) != {"completion", "result"}:
        raise ContextManagerContractError("malformed context-manager semantics enter")
    result = enter["result"]
    if enter["completion"] != "total" or not isinstance(result, dict) or set(result) != {"kind", "projection", "sort"} or result["kind"] != "projection" or result["projection"] != ENTER_RESULT:
        raise ContextManagerContractError("unsupported enter testimony")
    if not isinstance(exit_, dict) or set(exit_) != {"completion", "disposition"}:
        raise ContextManagerContractError("malformed context-manager semantics exit")
    disposition = exit_["disposition"]
    if exit_["completion"] != "total" or not isinstance(disposition, dict) or set(disposition) != {"kind"}:
        raise ContextManagerContractError("malformed exit disposition")
    if disposition["kind"] != "never-suppresses":
        raise ContextManagerContractError("unknown exit disposition")
    return ContextManagerSemanticsV1(
        enter=EnterResultContractV1(sort=_decode_sort(result["sort"])),
        exit=ExitContractV1(disposition=NeverSuppressesDispositionV1()),
    )


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
    semantics = _decode_semantics(header["payload"])
    payload_cid = blake3_512_of(encode_jcs(semantics_to_value(semantics)).encode())
    if header["cid"] != payload_cid or header["payloadCid"] != payload_cid:
        raise ContextManagerContractError("context-manager payload CID does not match semantics")
    signature = header["importSignature"]
    if not isinstance(signature, dict) or set(signature) != {"formals", "sorts"} or not isinstance(signature["formals"], list) or not isinstance(signature["sorts"], list) or len(signature["formals"]) != len(signature["sorts"]):
        raise ContextManagerContractError("malformed importSignature")
    if not all(isinstance(v, str) for v in signature["formals"]):
        raise ContextManagerContractError("import formals must be strings")
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
        import_formals=tuple(signature["formals"]),
        import_sorts=tuple(_decode_sort(v) for v in signature["sorts"]),
        semantics=semantics,
        source_warrants=tuple(warrants),
        payload_cid=payload_cid,
    )
