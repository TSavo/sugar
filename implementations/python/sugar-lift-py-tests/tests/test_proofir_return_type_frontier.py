from __future__ import annotations

import pytest

from sugar_lift_py_tests.factory.factory_gap import FactoryGap
from sugar_lift_py_tests.factory.literal_call_report import (
    _require_proofir_emission_node,
    euf_call_term,
    euf_callsite_name,
)
from sugar_lift_py_tests.ir import num
from sugar_lift_py_tests.proofir import (
    ConstructionSite,
    EqualityFact,
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
    call_term = euf_call_term("h", [num(5)])
    node = EqualityFact(
        euf_key=euf_callsite_name("h", call_term, suffix="::assertion"),
        call_term=call_term,
        rhs_term=num(6),
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
    with pytest.raises(FactoryGap, match="EqualityFact"):
        _require_proofir_emission_node(
            {"kind": "contract", "inv": {"kind": "atomic", "name": "=", "args": []}},
            construction_site="tests:raw-dict",
            replacement="EqualityFact",
        )
