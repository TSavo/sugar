"""callEdges project from the collapse: CallSiteValues carry coordinates; the
universe concatenates each entry's edge_contribution. No walker invents join
keys -- carried, projected."""

from __future__ import annotations

from sugar_lift_py_tests.lift_rpc import lift_file_payload

_SOURCE = "def A(z):\n    y = f(3)\n    assert y == 7\n    return z\n"


def test_one_call_projects_one_edge() -> None:
    edges = lift_file_payload(_SOURCE, "vendor.py").call_edges
    assert len(edges) == 1
    edge = edges[0]
    assert edge["kind"] == "call-edge"
    assert edge["sourceContract"] == "A"
    assert edge["targetSymbol"] == "call:f"
    assert edge["callSiteLocus"]["file"] == "vendor.py"
    assert edge["callSiteLocus"]["line"] == 2
    assert "targetContract" not in edge
    assert "targetContractCid" not in edge
    assert "targetProofCid" not in edge


def test_no_calls_yields_no_edges() -> None:
    source = "def A(z):\n    return z\n"
    assert lift_file_payload(source, "t.py").call_edges == []


def test_two_calls_yield_two_edges() -> None:
    source = (
        "def A(z):\n"
        "    y = f(3)\n"
        "    w = g(4)\n"
        "    assert y == 7\n"
        "    assert w == 8\n"
        "    return z\n"
    )
    edges = lift_file_payload(source, "t.py").call_edges
    assert len(edges) == 2
    symbols = {edge["targetSymbol"] for edge in edges}
    assert symbols == {"call:f", "call:g"}
    assert all(edge["sourceContract"] == "A" for edge in edges)
