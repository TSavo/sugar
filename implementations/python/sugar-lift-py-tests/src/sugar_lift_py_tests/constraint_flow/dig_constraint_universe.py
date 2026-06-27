from __future__ import annotations

import ast
from typing import Any

from .constraint_dig_request import ConstraintDigRequest
from .constraint_universe import ConstraintUniverse
from .field_keyword_predicate import field_keyword_predicate


def walk_constraint_universe(
    tree: ast.Module,
    dig: ConstraintDigRequest,
    *,
    source_memento: dict[str, Any],
    resolved_names: dict[str, str],
) -> ConstraintUniverse:
    owner, _, field = dig.fact_subject.partition(".")
    predicates: list[dict[str, Any]] = []
    proofir: list[dict[str, Any]] = []
    sugar_chain: list[str] = []

    for node in ast.walk(tree):
        if not isinstance(node, ast.AnnAssign):
            continue
        if not isinstance(node.target, ast.Name) or node.target.id != field:
            continue
        predicate, child_chain = field_keyword_predicate(
            node,
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
    )
