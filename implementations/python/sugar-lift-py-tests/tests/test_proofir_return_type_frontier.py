from __future__ import annotations

import pytest

from sugar_lift_py_tests.factory.factory_gap import factory_panic
from sugar_lift_py_tests.factory.literal_call_report import (
    _require_proofir_emission_node,
)
from sugar_lift_py_tests.proofir import (
    CallTerm,
    ConstTerm,
    ConstructionSite,
    EqualityFact,
    IntSort,
    Provenance,
    Stated,
)


def _provenance() -> Provenance:
    site = ConstructionSite(path="tests/proofir_return_type_frontier.py", line=12)
    return Provenance(
        node_class="EqualityFact",
        construction_site=site,
        warrant=Stated(locus=site),
    )


def test_proofir_return_type_seam_accepts_typed_node() -> None:
    call_term = CallTerm("h", (ConstTerm(5, sort=IntSort()),), sort=IntSort())
    node = EqualityFact(
        call_term=call_term,
        rhs_term=ConstTerm(6, sort=IntSort()),
        provenance=_provenance(),
    )

    assert (
        _require_proofir_emission_node(
            node,
            construction_site="tests:typed-node",
            replacement="EqualityFact",
        )
        is node
    )


def test_proofir_return_type_seam_refuses_raw_dict() -> None:
    with pytest.raises(factory_panic, match="EqualityFact"):
        _require_proofir_emission_node(
            {"kind": "contract", "inv": {"kind": "atomic", "name": "=", "args": []}},
            construction_site="tests:raw-dict",
            replacement="EqualityFact",
        )
