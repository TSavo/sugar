from __future__ import annotations

from dataclasses import dataclass
import json
from typing import Any

from sugar_lift_py_tests.context_manager_contract import (
    ContextManagerSemanticsV1,
    EnterResultContractV1,
    ExitContractV1,
    NeverSuppressesDispositionV1,
    semantics_to_value,
)
from sugar_lift_py_tests.ir import Sort, sort_to_value


@dataclass(frozen=True)
class ImportSignatureV1:
    formals: tuple[str, ...]
    sorts: tuple[Sort, ...]

    def __post_init__(self) -> None:
        if len(self.formals) != len(self.sorts):
            raise ValueError("import signature formals/sorts length mismatch")


@dataclass(frozen=True)
class ContextManagerContractIrV1:
    bridge_source_symbol: str
    import_signature: ImportSignatureV1
    payload: ContextManagerSemanticsV1
    source_warrants: tuple[str, ...]
    kind: str = "context-manager-contract"
    schema_version: str = "1"

    @classmethod
    def never_suppresses(
        cls, *, bridge_source_symbol: str, import_signature: ImportSignatureV1,
        enter_result_sort: Sort, source_warrants: tuple[str, ...],
    ) -> "ContextManagerContractIrV1":
        return cls(
            bridge_source_symbol=bridge_source_symbol,
            import_signature=import_signature,
            payload=ContextManagerSemanticsV1(
                enter=EnterResultContractV1(sort=enter_result_sort),
                exit=ExitContractV1(disposition=NeverSuppressesDispositionV1()),
            ),
            source_warrants=source_warrants,
        )

    def to_rpc_with_term_table(self, _term_table: Any) -> dict[str, Any]:
        if not self.bridge_source_symbol:
            raise ValueError("bridgeSourceSymbol must be non-empty")
        if not all(w.startswith("blake3-512:") for w in self.source_warrants):
            raise ValueError("sourceWarrants must be CID references")
        return {
            "kind": self.kind,
            "schemaVersion": self.schema_version,
            "bridgeSourceSymbol": self.bridge_source_symbol,
            "importSignature": {
                "formals": list(self.import_signature.formals),
                "sorts": [json.loads(_encode(sort_to_value(v))) for v in self.import_signature.sorts],
            },
            "payload": json.loads(_encode(semantics_to_value(self.payload))),
            "sourceWarrants": list(self.source_warrants),
        }


def _encode(value: Any) -> str:
    from sugar_lift_py_tests.canonicalizer import encode_jcs
    return encode_jcs(value)
