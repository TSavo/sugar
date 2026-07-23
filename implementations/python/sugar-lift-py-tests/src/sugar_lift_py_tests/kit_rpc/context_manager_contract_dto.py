from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any

from sugar_lift_py_tests.context_manager_contract import (
    ContextManagerSemanticsV1,
    EffectBoundarySemanticsV1,
    ExceptionInfoBindingV1,
    ExpectsModeV1,
    FormalArgumentProjectionV1,
    NoBindingV1,
    NoMessagePatternV1,
    OptionalFormalArgumentProjectionV1,
    RaiseEffectKindV1,
    SuppressesModeV1,
    WarningEffectKindV1,
    WarningObservationBindingV1,
    EnterResultContractV1,
    ExitContractV1,
    NeverSuppressesDispositionV1,
    ProtocolResourceSemanticsV1,
    ImportSignatureV2,
    import_signature_to_value,
    decode_context_manager_semantics_v1,
    semantics_to_value,
)
from sugar_lift_py_tests.ir import Sort


@dataclass(frozen=True)
class ContextManagerContractIrV1:
    bridge_source_symbol: str
    import_signature: ImportSignatureV2
    payload: ContextManagerSemanticsV1
    source_warrants: tuple[str, ...]
    kind: str = "context-manager-contract"
    schema_version: str = "1"

    @classmethod
    def never_suppresses(
        cls, *, bridge_source_symbol: str, import_signature: ImportSignatureV2,
        enter_result_sort: Sort, source_warrants: tuple[str, ...],
    ) -> "ContextManagerContractIrV1":
        return cls(
            bridge_source_symbol=bridge_source_symbol,
            import_signature=import_signature,
            payload=ProtocolResourceSemanticsV1(
                enter=EnterResultContractV1(sort=enter_result_sort),
                exit=ExitContractV1(disposition=NeverSuppressesDispositionV1()),
            ),
            source_warrants=source_warrants,
        )

    @classmethod
    def effect_boundary(
        cls, *, bridge_source_symbol: str, import_signature: ImportSignatureV2,
        mode: ExpectsModeV1 | SuppressesModeV1,
        effect_kind: RaiseEffectKindV1 | WarningEffectKindV1,
        expected_type_operand: FormalArgumentProjectionV1,
        message_pattern_operand: NoMessagePatternV1 | OptionalFormalArgumentProjectionV1,
        binding: NoBindingV1 | ExceptionInfoBindingV1 | WarningObservationBindingV1,
        source_warrants: tuple[str, ...],
    ) -> "ContextManagerContractIrV1":
        return cls(
            bridge_source_symbol=bridge_source_symbol,
            import_signature=import_signature,
            payload=EffectBoundarySemanticsV1(
                mode=mode,
                effect_kind=effect_kind,
                expected_type_operand=expected_type_operand,
                message_pattern_operand=message_pattern_operand,
                binding=binding,
            ),
            source_warrants=source_warrants,
        )

    def to_rpc_with_term_table(self, _term_table: Any) -> dict[str, Any]:
        if not self.bridge_source_symbol:
            raise ValueError("bridgeSourceSymbol must be non-empty")
        if not all(w.startswith("blake3-512:") for w in self.source_warrants):
            raise ValueError("sourceWarrants must be CID references")
        payload = json.loads(_encode(semantics_to_value(self.payload)))
        if decode_context_manager_semantics_v1(payload, self.import_signature) != self.payload:
            raise ValueError("context-manager semantics failed canonical validation")
        return {
            "kind": self.kind,
            "schemaVersion": self.schema_version,
            "bridgeSourceSymbol": self.bridge_source_symbol,
            "importSignature": json.loads(_encode(import_signature_to_value(self.import_signature))),
            "payload": payload,
            "sourceWarrants": list(self.source_warrants),
        }


def _encode(value: Any) -> str:
    from sugar_lift_py_tests.canonicalizer import encode_jcs
    return encode_jcs(value)
