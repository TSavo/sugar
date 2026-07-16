# SPDX-License-Identifier: MIT OR Apache-2.0
"""Focused join: collapse call edges seal against imported contract bindings."""

from sugar_lift_py_tests.factory.call_edge_bindings import (
    binding_for_bridge_symbol,
    bridge_symbol_match_candidates,
    resolve_call_edges_against_bindings,
)


def test_bridge_symbol_match_candidates_strip_call_and_method_prefixes() -> None:
    assert bridge_symbol_match_candidates("call:sum") == {"call:sum", "sum"}
    assert bridge_symbol_match_candidates("method:sum") == {
        "method:sum",
        "sum",
        "call:sum",
    }


def test_call_sum_edge_joins_call_sum_vendor_binding() -> None:
    bindings = [
        {
            "name": "pandas.Series.sum",
            "contract_cid": "blake3-512:contract",
            "target_proof_cid": "blake3-512:vendor-proof",
            "bridgeSourceSymbol": "call:sum",
            "has_post": True,
        }
    ]
    edges = [
        {
            "kind": "call-edge",
            "sourceContract": "test_sum",
            "targetSymbol": "call:sum",
            "callSiteLocus": {"file": "t.py", "line": 6, "col": 12},
        }
    ]
    resolved = resolve_call_edges_against_bindings(edges, bindings)
    assert len(resolved) == 1
    edge = resolved[0]
    assert edge["targetSymbol"] == "call:sum"
    assert edge["targetContract"] == "pandas.Series.sum"
    assert edge["targetContractCid"] == "blake3-512:contract"
    assert edge["targetProofCid"] == "blake3-512:vendor-proof"


def test_method_sum_edge_also_joins_call_sum_vendor_binding() -> None:
    """#3668 method: spelling still joins the EUF call: vendor BSS."""
    bindings = [
        {
            "name": "pandas.Series.sum",
            "contract_cid": "blake3-512:contract",
            "target_proof_cid": "blake3-512:vendor-proof",
            "bridgeSourceSymbol": "call:sum",
        }
    ]
    binding = binding_for_bridge_symbol(bindings, "method:sum")
    assert binding is not None
    assert binding["target_proof_cid"] == "blake3-512:vendor-proof"


def test_call_load_edge_joins_numpy_load_vendor_binding_by_leaf() -> None:
    """Bare call:load still seals against bridgeSourceSymbol numpy.load."""
    bindings = [
        {
            "name": "lib._npyio_impl.load",
            "contract_cid": "blake3-512:contract",
            "target_proof_cid": "blake3-512:vendor-proof",
            "bridgeSourceSymbol": "numpy.load",
            "has_pre": True,
        }
    ]
    edges = [
        {
            "kind": "call-edge",
            "sourceContract": "test_load",
            "targetSymbol": "call:load",
        }
    ]
    resolved = resolve_call_edges_against_bindings(edges, bindings)
    assert resolved[0]["targetProofCid"] == "blake3-512:vendor-proof"
    assert resolved[0]["targetContract"] == "lib._npyio_impl.load"


def test_unmatched_edge_stays_unsealed() -> None:
    edges = [
        {
            "kind": "call-edge",
            "sourceContract": "test_x",
            "targetSymbol": "call:unknown",
        }
    ]
    resolved = resolve_call_edges_against_bindings(edges, [])
    assert resolved == edges
    assert "targetProofCid" not in resolved[0]
