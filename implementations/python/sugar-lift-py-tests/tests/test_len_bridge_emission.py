from __future__ import annotations

import pytest

from sugar_lift_py_tests.lift_rpc import lift_file_payload


@pytest.mark.parametrize(
    "source",
    [
        "def test_len():\n    assert len([1, 2, 3]) == 3\n",
        "def test_len(xs):\n    assert len(xs) == 3\n",
    ],
)
def test_len_assertion_emits_call_len_bridge_for_computed_and_opaque_arms(
    source: str,
) -> None:
    payload = lift_file_payload(source, "test_len_bridge.py")

    assert [edge["targetSymbol"] for edge in payload.call_edges] == ["call:len"]


def test_non_call_assertion_emits_no_len_bridge() -> None:
    payload = lift_file_payload(
        "def test_value(x):\n    assert x == 3\n", "test_no_len_bridge.py"
    )

    assert payload.call_edges == []


def test_computed_len_return_emits_bridge_and_derived_grounding() -> None:
    payload = lift_file_payload(
        "def A():\n    return len([1, 2, 3])\n", "test_len_return.py"
    )

    assert payload.call_edges == [
        {
            "kind": "call-edge",
            "sourceContract": "A",
            "targetSymbol": "call:len",
        }
    ]
    assert len(payload.ir) == 1
    post = payload.ir[0].to_rpc()["post"]
    assert post["kind"] == "and"
    derived = post["operands"][1]
    assert derived["name"] == "="
    assert derived["args"][0]["name"] == "call:len"
    assert derived["args"][1]["value"] == 3
    exit_grounding = post["operands"][2]
    assert exit_grounding["args"][0]["name"] == "out"
    assert exit_grounding["args"][1]["value"] == 3


def test_opaque_len_return_emits_bridge_without_fabricated_grounding() -> None:
    payload = lift_file_payload(
        "def A(xs):\n    return len(xs)\n", "test_opaque_len_return.py"
    )

    assert payload.call_edges == [
        {
            "kind": "call-edge",
            "sourceContract": "A",
            "targetSymbol": "call:len",
        }
    ]
    assert [row.to_rpc()["kind"] for row in payload.ir] == ["function-contract"]
