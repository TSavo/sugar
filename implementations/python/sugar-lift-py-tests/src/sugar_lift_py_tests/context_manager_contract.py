"""The typed context-manager contract, and the recognition membrane that issues it.

T's ruling: three contracts wear the one `with` syntax, and production tree code
sees a TYPED CONTRACT, never a vendor spelling. `pytest` is a vendor: the
membrane authenticates community spellings (`pytest.raises(E)`,
`contextlib.suppress(E)`, `tm.assert_produces_warning(W)`) and issues the
general contract; the language implementation (nodes.py) consults the membrane
and never matches names itself.

The exit contracts (the only licenses for temporal dissolution):
- ``NeverSuppresses`` -- exceptional body effect passes through after __exit__.
- ``Suppresses(matcher)`` -- matching effects are consumed (permission).
- ``Expects(matcher)`` -- matching effect is REQUIRED and consumed (obligation).
- ``RuntimeSelected`` -- suppression undecidable statically; stays loud.

Matching rule (pinned): EXACT exception-name match. Subclass matching needs a
static type hierarchy the lift does not hold; a subclass raise therefore lands
as the mismatch twin (loud, never silently matched) until that rule is widened
deliberately.

Enrollment (issue #5994): community coordinates enter ONLY through an
explicitly loaded, hashed kit manifest that maps authenticated spellings to
these contracts. This module holds the provider-neutral TYPES only; no vendor
spelling may appear in code, tree-side or kit-side.
"""

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
    """A payload obligation: the observed effect's message must match this
    regex. Independently dischargeable -- undischarged (not passed, not failed)
    until the effect witness carries authenticated message content."""

    pattern: str


@dataclass(frozen=True)
class EffectMatcher:
    """A CONJUNCTION of independently dischargeable obligations (T's ruling:
    the unit of honesty is the individual obligation, never the surface
    construct). The type obligation is decidable against the observed halt;
    each payload obligation (e.g. MessagePattern from `match=`) carries its own
    closed verdict -- discharged / disproven / undischarged -- sharing the same
    observed-effect witness identity."""

    kind: str  # "raise" | "warning"
    name: str  # e.g. "ValueError", "FutureWarning"
    payload_obligations: tuple = ()  # e.g. (MessagePattern(pat),)


# Binding projections for `with … as name` — declared by the membrane, never
# by matching vendor spellings in the tree. Syntax rewrites the name to an
# ObservationRef(slot, projection=…); routing authenticates the slot.
EXCEPTION_INFO = "exception_info"
WARNING_OBSERVATION = "warning_observation"
EFFECT = "effect"
# Resource enter-result: tree coordinate for ``with m as x`` under a resource
# disposition (NeverSuppresses / proven exit). Not an exception witness.
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
    # What `as name` denotes when this contract is issued (None → no as-export).
    binding: Optional[str] = None


@dataclass(frozen=True)
class RuntimeSelected:
    pass


Contract = NeverSuppresses | Suppresses | Expects | RuntimeSelected


class ContextManagerContractError(ValueError):
    """A sealed CM-contract member is malformed, stale, or unauthenticated."""


@dataclass(frozen=True)
class PublishedContextManagerContract:
    name: str
    kit: str
    bridge_source_symbol: str
    constructor_formals: tuple[str, ...]
    constructor_sorts: tuple[Sort, ...]
    enter_result_sort: Sort
    exit_disposition: str
    source_warrants: tuple[dict[str, Any], ...]
    contract_cid: str


def _payload_value(
    *, name: str, kit: str, bridge_source_symbol: str,
    constructor_formals: Sequence[str], constructor_sorts: Sequence[Sort],
    enter_result_sort: Sort, source_warrants: Sequence[dict[str, Any]],
):
    if not all(isinstance(warrant, dict) for warrant in source_warrants):
        raise ContextManagerContractError("sourceWarrants entries must be objects")
    return vobj([
        ("schemaVersion", vstr("1")),
        ("kind", vstr("context-manager-contract")),
        ("name", vstr(name)),
        ("kit", vstr(kit)),
        ("bridgeSourceSymbol", vstr(bridge_source_symbol)),
        ("constructorSignature", vobj([
            ("formals", varr([vstr(v) for v in constructor_formals])),
            ("sorts", varr([sort_to_value(v) for v in constructor_sorts])),
        ])),
        ("enter", vobj([
            ("outcome", vstr("total")),
            ("result", vobj([
                ("kind", vstr("projection")),
                ("projection", vstr(ENTER_RESULT)),
                ("sort", sort_to_value(enter_result_sort)),
            ])),
        ])),
        ("exit", vobj([
            ("outcome", vstr("total")),
            ("disposition", vobj([("kind", vstr("never-suppresses"))])),
        ])),
        ("sourceWarrants", varr([_json_value(warrant) for warrant in source_warrants])),
    ])


def publish_never_suppresses_context_manager_contract(
    *, name: str, kit: str, bridge_source_symbol: str,
    constructor_formals: Sequence[str], constructor_sorts: Sequence[Sort],
    enter_result_sort: Sort, source_warrants: Sequence[dict[str, Any]],
    signer: Signer, declared_at: str,
) -> ClaimEnvelope:
    if not name or not kit or not bridge_source_symbol:
        raise ContextManagerContractError("name, kit, and bridgeSourceSymbol must be non-empty")
    if len(constructor_formals) != len(constructor_sorts):
        raise ContextManagerContractError("constructor formals and sorts must have equal length")
    payload = _payload_value(
        name=name, kit=kit, bridge_source_symbol=bridge_source_symbol,
        constructor_formals=constructor_formals, constructor_sorts=constructor_sorts,
        enter_result_sort=enter_result_sort, source_warrants=source_warrants,
    )
    content_cid = blake3_512_of(encode_jcs(payload).encode())
    raw = json.loads(encode_jcs(payload))
    header = vobj([(k, vstr(content_cid) if k == "cid" else _json_value(v)) for k, v in ({**raw, "cid": content_cid}).items()])
    return _assemble_layered(header, vobj([]), declared_at, signer.seed, content_cid)


def _json_value(value: Any):
    from .canonicalizer import vbool, vint, vnull
    if value is None: return vnull()
    if isinstance(value, bool): return vbool(value)
    if isinstance(value, int): return vint(value)
    if isinstance(value, str): return vstr(value)
    if isinstance(value, list): return varr([_json_value(v) for v in value])
    if isinstance(value, dict): return vobj([(k, _json_value(v)) for k, v in value.items()])
    raise ContextManagerContractError(f"unsupported payload value: {type(value)!r}")


def _decode_sort(raw: Any) -> Sort:
    if not isinstance(raw, dict): raise ContextManagerContractError("sort must be an object")
    if raw.get("kind") == "primitive" and set(raw) == {"kind", "name"} and isinstance(raw["name"], str):
        return PrimitiveSort(raw["name"])
    if raw.get("kind") == "region" and set(raw) == {"kind", "name"} and isinstance(raw["name"], str):
        return RegionSort(raw["name"])
    if raw.get("kind") == "function" and set(raw) == {"kind", "args", "return"} and isinstance(raw["args"], list):
        return FunctionSort(tuple(_decode_sort(v) for v in raw["args"]), _decode_sort(raw["return"]))
    raise ContextManagerContractError("unsupported or malformed enter-result sort")


def decode_context_manager_contract(canonical_bytes: bytes, member_cid: str) -> PublishedContextManagerContract:
    try: raw = json.loads(canonical_bytes)
    except (TypeError, ValueError) as exc: raise ContextManagerContractError("member is not JSON") from exc
    if not isinstance(raw, dict) or set(raw) != {"envelope", "header", "metadata"} or raw["metadata"] != {}:
        raise ContextManagerContractError("CM contract must be a layered member with empty metadata")
    envelope, header = raw["envelope"], raw["header"]
    if blake3_512_of(encode_jcs(_json_value(envelope)).encode()) != member_cid:
        raise ContextManagerContractError("member attestation CID does not match envelope")
    signing = vobj([("header", _json_value(header)), ("metadata", vobj([]))])
    if not ed25519_verify_string(envelope.get("signer", ""), envelope.get("signature", ""), encode_jcs(signing).encode()):
        raise ContextManagerContractError("member signature does not verify")
    expected = {"schemaVersion", "kind", "cid", "name", "kit", "bridgeSourceSymbol", "constructorSignature", "enter", "exit", "sourceWarrants"}
    if not isinstance(header, dict) or set(header) != expected or header.get("schemaVersion") != "1" or header.get("kind") != "context-manager-contract":
        raise ContextManagerContractError("malformed context-manager-contract header")
    payload = dict(header); claimed = payload.pop("cid")
    derived = blake3_512_of(encode_jcs(_json_value(payload)).encode())
    if claimed != derived: raise ContextManagerContractError("context-manager contract content CID does not match payload")
    sig = header["constructorSignature"]
    if not isinstance(sig, dict) or set(sig) != {"formals", "sorts"} or not isinstance(sig["formals"], list) or not isinstance(sig["sorts"], list) or len(sig["formals"]) != len(sig["sorts"]):
        raise ContextManagerContractError("malformed constructorSignature")
    if not all(isinstance(v, str) for v in sig["formals"]): raise ContextManagerContractError("constructor formals must be strings")
    enter, exit_ = header["enter"], header["exit"]
    if enter.get("outcome") != "total" or enter.get("result", {}).get("kind") != "projection" or enter["result"].get("projection") != ENTER_RESULT:
        raise ContextManagerContractError("enter testimony is not total enter_result projection")
    if exit_ != {"outcome": "total", "disposition": {"kind": "never-suppresses"}}:
        raise ContextManagerContractError("exit testimony is not total NeverSuppresses")
    if not isinstance(header["sourceWarrants"], list) or not all(isinstance(v, dict) for v in header["sourceWarrants"]):
        raise ContextManagerContractError("sourceWarrants must be an array of objects")
    if not all(isinstance(header[k], str) and header[k] for k in ("name", "kit", "bridgeSourceSymbol")):
        raise ContextManagerContractError("identity fields must be non-empty strings")
    return PublishedContextManagerContract(header["name"], header["kit"], header["bridgeSourceSymbol"], tuple(sig["formals"]), tuple(_decode_sort(v) for v in sig["sorts"]), _decode_sort(enter["result"]["sort"]), "never-suppresses", tuple(header["sourceWarrants"]), derived)
