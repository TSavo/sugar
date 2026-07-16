"""A test function is testimony, not a contract. Its asserts are the vendor
facts -- the rows the join runs on. A coordinate-less ground tautology folds
to support before mint (known gap; T's ruling not yet honored for folded
grounds)."""

from __future__ import annotations

from sugar_lift_py_tests.canonicalizer import blake3_512_of
from sugar_lift_py_tests.lift_rpc import lift_file_payload


def test_vendor_assert_mints_assertion_row_not_a_universe() -> None:
    source = (
        "def enc(x):\n"
        '    if x == "ccc":\n'
        '        return "yyy"\n'
        "    return x\n"
        "\n"
        "def test_enc():\n"
        '    assert enc("ccc") == "yyy"\n'
    )
    payload = lift_file_payload(source, "vendor.py")
    kinds = [row.kind for row in payload.ir]
    assert kinds.count("function-contract") == 1

    # ONE function-contract (enc only); test_enc is testimony (no contract row).
    fn_rows = [row for row in payload.ir if row.kind == "function-contract"]
    assert len(fn_rows) == 1
    assert fn_rows[0].name in {"enc", "vendor.enc"}

    assertion_rows = [row for row in payload.ir if row.kind == "contract"]
    # Ground callsite py.eq mints under the `#euf#` key so ambient dual join works.
    assert len(assertion_rows) == 1
    fact = assertion_rows[0]
    assert "#euf#" in fact.name
    assert fact.name.endswith("::assertion")
    assert fact.name.startswith("enc#euf#") or fact.name.startswith("vendor.enc#euf#")
    assert fact.inv is not None
    assert fact.post is None
    assert fact.source_warrants[0].source_cid == blake3_512_of(
        b'assert enc("ccc") == "yyy"'
    )


def test_ground_tautology_assert_vanishes_into_support_known_gap() -> None:
    # CHOICE (i): ground-true folds to Support before testimony can mint.
    # T ruled the vendor carries even a trivial axiom; the fold erases it.
    # Pin ZERO fact rows and name the gap until a per-body-mode ruling lands.
    source = "def test_trivial():\n    assert 1 == 1\n"
    payload = lift_file_payload(source, "t.py")
    assert [row.kind for row in payload.ir] == []
    assert not any(row.name.endswith("::assertion") for row in payload.ir)


def test_test_function_mints_no_function_contract() -> None:
    source = "def test_only():\n" '    assert enc("a") == "b"\n'
    payload = lift_file_payload(source, "t.py")
    assert not any(row.kind == "function-contract" for row in payload.ir)


def test_two_asserts_mint_two_assertion_rows() -> None:
    source = "def test_pair():\n" "    assert f(1) == 2\n" "    assert g(3) == 4\n"
    payload = lift_file_payload(source, "t.py")
    assertion_rows = [row for row in payload.ir if row.kind == "contract"]
    assert len(assertion_rows) == 2
    names = {row.name for row in assertion_rows}
    assert any(n.startswith("f#euf#") for n in names)
    assert any(n.startswith("g#euf#") for n in names)
    assert all(row.inv is not None for row in assertion_rows)
