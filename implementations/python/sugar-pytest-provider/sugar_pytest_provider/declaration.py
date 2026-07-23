from dataclasses import dataclass
from typing import Any, Protocol, Sequence

PROVIDER_KIT_ID = "python-pytest-provider"
PROVIDER_EXPORT = "pytest.raises"
# Stable provider-owned identity; the corresponding private key is supplied
# by deployment, never minted or substituted by Rust.
PROVIDER_SIGNER_CID = "ed25519:provider-pytest-key"

@dataclass(frozen=True)
class PytestRaisesContractSlot:
    """Shape adapter for 6640's EffectBoundaryV1 (payload still external).

    The provider supplies no semantics here until the shared decoder/publisher
    lands.  The fields mirror the finalized contract: ordered call parameters,
    formal projections 0/1, Expects/raise, and exception-info binding.
    """
    mode: str
    effect_kind: str
    parameters: Sequence[Any]
    expected_type_formal: int
    message_pattern_formal: int | None
    binding: str
    payload: Any = None

    def validate_shape(self) -> None:
        if (self.mode, self.effect_kind, self.expected_type_formal, self.binding) != (
            "expects", "raise", 0, "exception-info"):
            raise ValueError("not the finalized pytest.raises EffectBoundary shape")
        if self.message_pattern_formal not in (None, 1):
            raise ValueError("pytest.raises match must project formal 1")
        if len(self.parameters) != 2:
            raise ValueError("pytest.raises requires ordered parameters 0,1")

@dataclass(frozen=True)
class ProviderDeclaration:
    provider_kit_id: str
    provider_signer_cid: str
    bridge_source_symbol: str
    contract: PytestRaisesContractSlot

def pytest_raises_declaration(*, contract_payload: Any) -> ProviderDeclaration:
    if contract_payload is None:
        raise ValueError("pytest.raises EffectBoundary payload is not finalized")
    if not isinstance(contract_payload, PytestRaisesContractSlot):
        raise TypeError("provider payload must be the shared EffectBoundary slot")
    contract_payload.validate_shape()
    return ProviderDeclaration(PROVIDER_KIT_ID, PROVIDER_SIGNER_CID, PROVIDER_EXPORT, contract_payload)
