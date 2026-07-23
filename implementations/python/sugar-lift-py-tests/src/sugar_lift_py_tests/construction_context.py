"""Explicit semantic-construction authority handle (With v2 law 10)."""
from dataclasses import dataclass
from .context_manager_resolution import ResolvedContractRefsV1
from .with_manager_authority import WithManagerAuthoritiesV1

@dataclass(frozen=True)
class ConstructionContextV1:
    """Workspace-scoped immutable authority; never process ambient."""
    generation_cid: str
    contract_refs: ResolvedContractRefsV1
    with_authorities: WithManagerAuthoritiesV1

    @classmethod
    def bind(cls, refs: ResolvedContractRefsV1, authorities: WithManagerAuthoritiesV1):
        if refs.table_cid != authorities.table_cid:
            raise ValueError("construction context generation mismatch")
        return cls(refs.table_cid, refs, authorities)
