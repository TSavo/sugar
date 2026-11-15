"""The ``source-enter-faces`` completion round-trips through contract JSON."""

from __future__ import annotations

from sugar_lift_py_tests.context_manager_contract import (
    NeverSuppressesDispositionV1,
    SourceEnterFacesCompletionV1,
)


def test_enter_completion_round_trips_through_contract_json() -> None:
    from sugar_lift_py_tests.context_manager_contract import (
        EnterResultContractV1,
        ExitContractV1,
        ProtocolResourceSemanticsV1,
        _decode_protocol_resource,
        semantics_to_value,
    )
    from sugar_lift_py_tests.canonicalizer import encode_jcs
    from sugar_lift_py_tests.ir import PrimitiveSort
    import json

    semantics = ProtocolResourceSemanticsV1(
        EnterResultContractV1(PrimitiveSort("Value"), SourceEnterFacesCompletionV1()),
        ExitContractV1(NeverSuppressesDispositionV1()),
    )
    raw = json.loads(encode_jcs(semantics_to_value(semantics)))
    assert raw["enter"]["completion"] == {"kind": "source-enter-faces"}
    assert _decode_protocol_resource(raw) == semantics
