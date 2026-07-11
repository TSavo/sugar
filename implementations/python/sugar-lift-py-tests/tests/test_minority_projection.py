"""The Minority Report is a projection of the collapse join: bodies are
function-contract rows; asked is a body hit by call_edges targetSymbol
call:<bridge_source_symbol>. un_asserted = present minus dug. Census is only
a cross-check -- disagreement is a finding."""

from __future__ import annotations

from sugar_lift_py_tests.idd.lift_coverage_accounting import account_lift_coverage
from sugar_lift_py_tests.idd.lift_coverage_census import census_source
from sugar_lift_py_tests.lift_rpc import lift_file_payload

_DEMO = (
    'def enc(x):\n'
    '    if x == "ccc":\n'
    '        return "yyy"\n'
    '    return x\n'
    '\n'
    'def A(z):\n'
    '    y = f(3)\n'
    '    assert y == 7\n'
    '    return z\n'
)


def _coverage(source: str, *, file: str = "demo.py"):
    payload = lift_file_payload(source, file)
    disk = census_source(source, file=file)
    return account_lift_coverage(disk, payload.to_rpc()), payload


def test_no_testimony_all_bodies_are_minority() -> None:
    cov, payload = _coverage(_DEMO)
    m = cov.to_json()["minority"]
    assert m["present"] == 2
    assert m["dug"] == 0
    assert m["un_asserted"] == 2
    names = {loc["name"] for loc in m["un_asserted_loci"]}
    assert names == {"enc", "A"}
    for loc in m["un_asserted_loci"]:
        assert loc["file"] == "demo.py"
        assert loc["line"] >= 1
        assert loc["name"]
    # A has call:f edge but f is not a present body -- still un_asserted.
    assert any(e["targetSymbol"] == "call:f" for e in payload.call_edges)
    assert cov.to_json().get("census_disagreement") is None


def test_testimony_digs_enc_out_of_the_minority() -> None:
    source = _DEMO + (
        '\ndef test_enc():\n'
        '    assert enc("ccc") == "yyy"\n'
    )
    cov, payload = _coverage(source)
    m = cov.to_json()["minority"]
    assert m["present"] == 2
    assert m["dug"] == 1
    assert m["un_asserted"] == 1
    assert {loc["name"] for loc in m["dug_loci"]} == {"enc"}
    assert {loc["name"] for loc in m["un_asserted_loci"]} == {"A"}
    assert any(e["targetSymbol"] == "call:enc" for e in payload.call_edges)
    # test_* is testimony, not a body -- census comparison excludes it.
    assert cov.to_json().get("census_disagreement") is None


def test_census_agreement_when_collapse_matches_production_bodies() -> None:
    cov, _ = _coverage(_DEMO)
    assert cov.census_disagreement is None
    assert "census_disagreement" not in cov.to_json()


def test_census_disagreement_when_ir_omits_a_body() -> None:
    # Honest constructible case: empty ir while census sees FunctionDefs.
    # (A factory panic on a def aborts the whole lift -- cannot use that.)
    source = "def orphan():\n    return 1\n"
    disk = census_source(source, file="t.py")
    cov = account_lift_coverage(disk, {"ir": [], "callEdges": []})
    assert cov.minority.present == 0
    disagreement = cov.to_json()["census_disagreement"]
    assert disagreement["census_present"] == 1
    assert disagreement["collapse_present"] == 0
    assert "orphan" in disagreement["census_names"]
