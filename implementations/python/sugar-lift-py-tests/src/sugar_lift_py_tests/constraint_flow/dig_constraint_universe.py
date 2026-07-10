from __future__ import annotations

from typing import Any

from ..factory.factory_gap import dig_boundary_panic
from ..factory.source_fragment import SourceFragment
from .constraint_dig_request import ConstraintDigRequest
from .constraint_universe import ConstraintUniverse
from .field_keyword_predicate import field_keyword_predicate


def walk_constraint_universe(
    tree: SourceFragment,
    dig: ConstraintDigRequest,
    *,
    source_memento: dict[str, Any],
    resolved_names: dict[str, str],
) -> ConstraintUniverse:
    owner, _, field = dig.fact_subject.partition(".")
    predicates: list[dict[str, Any]] = []
    proofir: list[dict[str, Any]] = []
    sugar_chain: list[str] = []
    dig_refusals: list = []

    for fragment in [tree, *tree.walk()]:
        if fragment.observed != "AnnAssign":
            continue
        try:
            target_id = fragment.annassign_target_id()
        except TypeError as exc:
            dig_boundary_panic(
                callee=dig.target_symbol,
                blame=fragment.blame,
                caught=type(exc).__name__,
                reason=f"constraint-universe candidate refused: {exc}",
            )
        if target_id != field:
            continue
        predicate, child_chain = field_keyword_predicate(
            fragment,
            owner=owner,
            resolved_names=resolved_names,
        )
        if predicate is None:
            continue
        sugar_chain.extend(child_chain)
        predicates.append(predicate)
        proofir.append(
            {
                "kind": "contract",
                "name": f"{owner}.{field}::universe",
                "post": predicate,
                "source": dict(source_memento),
                "warrantedBy": dig.to_json(),
            }
        )

    if sugar_chain:
        sugar_chain.append("python.body-universe.class")
    return ConstraintUniverse(
        predicates=predicates,
        proofir=proofir,
        effects=[],
        source_memento=dict(source_memento),
        sugar_chain=sugar_chain,
        warranted_by=dig,
        dig_refusals=dig_refusals,
    )
