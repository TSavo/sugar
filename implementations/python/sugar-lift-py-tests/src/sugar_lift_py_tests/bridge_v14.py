# SPDX-License-Identifier: MIT OR Apache-2.0
#
# v1.4 BridgeDeclaration: layered envelope/header/body, tagged-union target.
#
# Per protocol/specs/2026-05-03-bridge-target-dimensionality.md §1.R1-R6.
# Canonical reference: rust/sugar-claim-envelope/src/lib.rs fn mint_bridge_v14.

import base64
from dataclasses import dataclass, field
from typing import Optional, Literal, Union
from ..canonicalizer import Jcs, Blake3
from ..signing import ed25519_sign, ed25519_pubkey_string

# ── Tagged-union target ─────────────────────────


@dataclass
class BridgeTarget:
    kind: Literal["contract", "contractSet"]
    cid: str

    def to_dict(self):
        return {"kind": self.kind, "cid": self.cid}

    @classmethod
    def contract(cls, cid: str) -> "BridgeTarget":
        return cls(kind="contract", cid=cid)

    @classmethod
    def contract_set(cls, cid: str) -> "BridgeTarget":
        return cls(kind="contractSet", cid=cid)


# ── Mint inputs ─────────────────────────────────


@dataclass
class MintBridgeV14Args:
    # header
    name: str
    source_symbol: str
    source_layer: str
    source_contract_cid: str
    target: BridgeTarget

    # metadata (None = omit)
    target_witness_cid: Optional[str] = None
    target_binary_cid: Optional[str] = None
    target_layer: Optional[str] = None
    target_contract_set_cid: Optional[str] = None
    produced_by: Optional[str] = None
    produced_at: Optional[str] = None

    # envelope
    declared_at: str = ""


@dataclass
class MintedV14:
    canonical_bytes: bytes
    cid: str


# ── Mint function ──────────────────────────────

FOUNDATION_SEED = bytes([0x42] * 32)


def mint_bridge_v14(
    args: MintBridgeV14Args, seed: bytes = FOUNDATION_SEED
) -> MintedV14:
    # Build header (7 canonical fields per spec §1.R3)
    header = {
        "schemaVersion": "1",
        "kind": "bridge",
        "name": args.name,
        "sourceSymbol": args.source_symbol,
        "sourceLayer": args.source_layer,
        "sourceContractCid": args.source_contract_cid,
        "target": args.target.to_dict(),
    }

    # Build metadata (omit None fields per §1.R2)
    meta = {}
    if args.target_witness_cid:
        meta["targetWitnessCid"] = args.target_witness_cid
    if args.target_binary_cid:
        meta["targetBinaryCid"] = args.target_binary_cid
    if args.target_layer:
        meta["targetLayer"] = args.target_layer
    if args.target_contract_set_cid:
        meta["targetContractSetCid"] = args.target_contract_set_cid
    if args.produced_by:
        meta["producedBy"] = args.produced_by
    if args.produced_at:
        meta["producedAt"] = args.produced_at

    # Sign: JCS({header, metadata})
    sig_payload = {"header": header, "metadata": meta}
    sig_payload_jcs = Jcs.encode_utf8(sig_payload)
    sig = ed25519_sign(seed, sig_payload_jcs)
    sig_str = f"ed25519:{base64.b64encode(sig).decode()}"

    # Build envelope
    pubkey = ed25519_pubkey_string(seed)
    envelope = {
        "signer": pubkey,
        "declaredAt": args.declared_at,
        "signature": sig_str,
    }

    # Full memento: {envelope, header, metadata}
    memento = {"envelope": envelope, "header": header, "metadata": meta}
    canonical = Jcs.encode_utf8(memento)
    cid = Blake3.hex(canonical)

    return MintedV14(canonical_bytes=canonical, cid=cid)
