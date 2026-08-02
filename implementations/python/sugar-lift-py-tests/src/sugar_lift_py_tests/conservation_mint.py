"""Universal conservation seal for measurement artifacts.

A measured body has one entrance: a schema validator executes successfully,
then this module mints its witness and attaches it to ``ConservedBody``.  A
validator failure has one honest outcome, ``ConservationFailure``.  It carries
diagnostics only; the candidate measured payload is deliberately discarded so
raw in-memory magnitudes cannot cross the write boundary after validation red.
"""

from __future__ import annotations

import hashlib
import json
import re
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any

CONSERVATION_WITNESS_SCHEMA = "sugar.conservation-witness.v1"

_CID_PATTERN = re.compile(
    r"(?:blake3-512:[0-9a-f]{128}|sha256:[0-9a-f]{64})"
)
_WITNESS_AUTHORITY = object()


def _content_cid(data: bytes) -> str:
    try:
        import blake3  # type: ignore

        return "blake3-512:" + blake3.blake3(data, max_threads=1).digest(64).hex()
    except Exception:  # noqa: BLE001 - deterministic stdlib fallback
        return "sha256:" + hashlib.sha256(data).hexdigest()


def _canonical_key_manifest(
    keys: Sequence[Mapping[str, Any]],
) -> list[dict[str, Any]]:
    rows = [dict(key) for key in keys]
    return sorted(
        rows,
        key=lambda row: json.dumps(
            row, sort_keys=True, separators=(",", ":"), default=str
        ),
    )


def key_manifest_cid(keys: Sequence[Mapping[str, Any]]) -> str:
    """CID over canonical key members, never a count-only surrogate."""
    payload = json.dumps(
        {"keys": _canonical_key_manifest(keys)},
        sort_keys=True,
        separators=(",", ":"),
        default=str,
    ).encode("utf-8")
    return _content_cid(payload)


@dataclass(frozen=True, slots=True, init=False)
class ConservationWitnessV1:
    input_key_manifest_cid: str
    input_key_count: int
    output_key_manifest_cid: str
    output_key_count: int
    validator_stage_id: str
    validator_source_cid: str

    def __init__(
        self,
        *,
        input_key_manifest_cid: str,
        input_key_count: int,
        output_key_manifest_cid: str,
        output_key_count: int,
        validator_stage_id: str,
        validator_source_cid: str,
        _authority: object,
    ) -> None:
        if _authority is not _WITNESS_AUTHORITY:
            raise TypeError(
                "ConservationWitnessV1 is minted only by the shared validation door"
            )
        for name, cid in (
            ("inputKeyManifestCid", input_key_manifest_cid),
            ("outputKeyManifestCid", output_key_manifest_cid),
            ("validatorSourceCid", validator_source_cid),
        ):
            if not isinstance(cid, str) or not _CID_PATTERN.fullmatch(cid):
                raise ValueError(f"{name} is not a supported content CID: {cid!r}")
        for name, count in (
            ("inputKeyCount", input_key_count),
            ("outputKeyCount", output_key_count),
        ):
            if type(count) is not int or count < 0:
                raise ValueError(f"{name} must be a non-negative int")
        if not isinstance(validator_stage_id, str) or not validator_stage_id.strip():
            raise ValueError("validatorStageId must be non-empty")
        object.__setattr__(self, "input_key_manifest_cid", input_key_manifest_cid)
        object.__setattr__(self, "input_key_count", input_key_count)
        object.__setattr__(self, "output_key_manifest_cid", output_key_manifest_cid)
        object.__setattr__(self, "output_key_count", output_key_count)
        object.__setattr__(self, "validator_stage_id", validator_stage_id)
        object.__setattr__(self, "validator_source_cid", validator_source_cid)

    def to_wire(self) -> dict[str, Any]:
        return {
            "witnessSchema": CONSERVATION_WITNESS_SCHEMA,
            "inputKeyManifestCid": self.input_key_manifest_cid,
            "inputKeyCount": self.input_key_count,
            "outputKeyManifestCid": self.output_key_manifest_cid,
            "outputKeyCount": self.output_key_count,
            "validatorStageId": self.validator_stage_id,
            "validatorSourceCid": self.validator_source_cid,
            "status": "passed",
        }

    @classmethod
    def _from_wire(cls, value: Mapping[str, Any]) -> "ConservationWitnessV1":
        expected = {
            "witnessSchema",
            "inputKeyManifestCid",
            "inputKeyCount",
            "outputKeyManifestCid",
            "outputKeyCount",
            "validatorStageId",
            "validatorSourceCid",
            "status",
        }
        if set(value) != expected:
            raise ValueError(
                "conservationWitness fields differ from universal v1 contract"
            )
        if value.get("witnessSchema") != CONSERVATION_WITNESS_SCHEMA:
            raise ValueError("conservationWitness witnessSchema is unsupported")
        if value.get("status") != "passed":
            raise ValueError("conservationWitness status is not passed")
        return cls(
            input_key_manifest_cid=value.get("inputKeyManifestCid"),
            input_key_count=value.get("inputKeyCount"),
            output_key_manifest_cid=value.get("outputKeyManifestCid"),
            output_key_count=value.get("outputKeyCount"),
            validator_stage_id=value.get("validatorStageId"),
            validator_source_cid=value.get("validatorSourceCid"),
            _authority=_WITNESS_AUTHORITY,
        )


@dataclass(frozen=True, slots=True)
class ConservedBody:
    payload: Mapping[str, Any]
    witness: ConservationWitnessV1

    def to_wire(self) -> dict[str, Any]:
        body = dict(self.payload)
        if body.get("measurement") not in (None, "measured"):
            raise ValueError("ConservedBody payload contradicts measurement=measured")
        if "conservationWitness" in body:
            raise ValueError("ConservedBody payload may not supply its own witness")
        body["measurement"] = "measured"
        body["conservationWitness"] = self.witness.to_wire()
        return body


@dataclass(frozen=True, slots=True)
class ConservationFailure:
    validator_stage_id: str
    reason: str
    validator_source_cid: str | None = None

    def to_wire(self) -> dict[str, Any]:
        diagnostic: dict[str, Any] = {
            "validatorStageId": self.validator_stage_id,
            "reason": self.reason,
        }
        if self.validator_source_cid is not None:
            diagnostic["validatorSourceCid"] = self.validator_source_cid
        return {
            "kind": "measurement-conservation-failure-v1",
            "measurement": "unmeasured",
            "conservationFailure": diagnostic,
        }


def seal_after_validation(
    *,
    measured_payload: Mapping[str, Any],
    input_key_manifest: Sequence[Mapping[str, Any]],
    output_key_manifest: Sequence[Mapping[str, Any]],
    validator_stage_id: str,
    validator_source_path: Path,
    validate: Callable[[], object],
) -> ConservedBody | ConservationFailure:
    """Execute the schema validator, then construct exactly one outcome."""
    try:
        validator_source_cid = _content_cid(Path(validator_source_path).read_bytes())
    except OSError as error:
        return ConservationFailure(
            validator_stage_id=validator_stage_id,
            reason=f"{type(error).__name__}: validator source unavailable: {error}",
        )
    try:
        result = validate()
        if result is not None and result is not True:
            raise ValueError(
                f"validator returned non-pass result {type(result).__name__}={result!r}"
            )
    except Exception as error:  # noqa: BLE001 - failure is the typed outcome
        return ConservationFailure(
            validator_stage_id=validator_stage_id,
            validator_source_cid=validator_source_cid,
            reason=f"{type(error).__name__}: {error}",
        )
    witness = ConservationWitnessV1(
        input_key_manifest_cid=key_manifest_cid(input_key_manifest),
        input_key_count=len(input_key_manifest),
        output_key_manifest_cid=key_manifest_cid(output_key_manifest),
        output_key_count=len(output_key_manifest),
        validator_stage_id=validator_stage_id,
        validator_source_cid=validator_source_cid,
        _authority=_WITNESS_AUTHORITY,
    )
    return ConservedBody(payload=dict(measured_payload), witness=witness)


def decode_conserved_body(value: Mapping[str, Any]) -> ConservedBody:
    """Reject any measured/sealed body without the universal passed witness."""
    if value.get("measurement") != "measured":
        raise ValueError("body does not claim measurement=measured")
    raw_witness = value.get("conservationWitness")
    if not isinstance(raw_witness, Mapping):
        raise ValueError("measured body lacks conservationWitness")
    witness = ConservationWitnessV1._from_wire(raw_witness)
    payload = dict(value)
    payload.pop("conservationWitness", None)
    return ConservedBody(payload=payload, witness=witness)
