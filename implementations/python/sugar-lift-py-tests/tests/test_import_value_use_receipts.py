"""Imported Name/Attribute VALUE occurrences get final-checked receipts.

A value-use receipt authenticates together: exact source occurrence, import
binding, exported member coordinate, consumer source CID, and value-use role.
Call-target receipts are a disjoint surface; neither substitutes for the other.
Shadowing, reassignment, wildcard ambiguity, and tampering do not authorize a
value.  No AST-scan fallback, first-candidate, or spelling resolver.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from sugar_lift_py_tests.import_binding import (
    AuthenticatedImportUseV1,
    authenticated_import_use_receipts,
    authenticated_import_value_use_receipts,
)
from sugar_lift_python_source.source_oracle import path_source


def _write(path: Path, text: str) -> tuple[str, str]:
    path.write_text(text, encoding="utf-8")
    source, _, source_cid = path_source(str(path))
    return source, source_cid


def _site_key(receipt: AuthenticatedImportUseV1) -> tuple[int, int, int, int]:
    site = receipt.use["useSite"]
    return (
        site["startLine"],
        site["startCol"],
        site["endLine"],
        site["endCol"],
    )


def test_value_use_receipt_changes_when_source_moves(tmp_path: Path) -> None:
    """Moving an imported Name value use changes the receipt useSite/CID."""
    early = tmp_path / "early.py"
    late = tmp_path / "late.py"
    early_src, early_cid = _write(early, "from pkg import f\nx = f\n")
    late_src, late_cid = _write(late, "from pkg import f\n\nx = f\n")

    early_receipts, _ = authenticated_import_value_use_receipts(
        tmp_path, early, early_src, early_cid, module_identities={}
    )
    late_receipts, _ = authenticated_import_value_use_receipts(
        tmp_path, late, late_src, late_cid, module_identities={}
    )

    early_f = [r for r in early_receipts if r.target_symbol == "python:pkg.f"]
    late_f = [r for r in late_receipts if r.target_symbol == "python:pkg.f"]
    assert len(early_f) == 1
    assert len(late_f) == 1
    assert early_f[0].use["useSite"] != late_f[0].use["useSite"]
    assert early_f[0].use["cid"] != late_f[0].use["cid"]
    assert (
        early_f[0].use["useSite"]["startLine"]
        != late_f[0].use["useSite"]["startLine"]
    )


def test_non_imported_name_gets_no_value_use_receipt(tmp_path: Path) -> None:
    path = tmp_path / "local.py"
    source, source_cid = _write(
        path,
        "def f():\n    return 1\n\nx = f\n",
    )
    receipts, outcomes = authenticated_import_value_use_receipts(
        tmp_path, path, source, source_cid, module_identities={}
    )
    assert receipts == []
    assert outcomes == {}


def test_tampered_source_cid_refuses_value_use_receipts(tmp_path: Path) -> None:
    path = tmp_path / "consumer.py"
    source, honest_cid = _write(path, "from pkg import f\nx = f\n")
    lying = "blake3-512:" + "0" * 128
    assert lying != honest_cid
    with pytest.raises(ValueError, match="authenticated import-use source CID is stale"):
        authenticated_import_value_use_receipts(
            tmp_path, path, source, lying, module_identities={}
        )


def test_same_name_shadowing_does_not_authorize_value_use(tmp_path: Path) -> None:
    """Local assignment after import shadows the import for value uses."""
    path = tmp_path / "shadow.py"
    source, source_cid = _write(
        path,
        "from pkg import f\n"
        "f = 1\n"
        "x = f\n",
    )
    receipts, _ = authenticated_import_value_use_receipts(
        tmp_path, path, source, source_cid, module_identities={}
    )
    assert receipts == []


def test_reassignment_does_not_authorize_value_use(tmp_path: Path) -> None:
    """After reassignment, later loads are non-import and mint no value receipt."""
    path = tmp_path / "reassign.py"
    source, source_cid = _write(
        path,
        "from pkg import f\n"
        "g = f\n"  # honest value use of import
        "f = g\n"
        "y = f\n",  # reassigned — not import-bound
    )
    receipts, _ = authenticated_import_value_use_receipts(
        tmp_path, path, source, source_cid, module_identities={}
    )
    # Only the honest load of imported f (as g = f) authorizes.
    assert len(receipts) == 1
    assert receipts[0].target_symbol == "python:pkg.f"
    assert receipts[0].use["useSite"]["startLine"] == 2


def test_wildcard_import_does_not_authorize_value_use(tmp_path: Path) -> None:
    """``import *`` is not a unique binding; value uses stay unauthorized."""
    path = tmp_path / "star.py"
    source, source_cid = _write(
        path,
        "from pkg import *\n"
        "x = f\n",
    )
    receipts, outcomes = authenticated_import_value_use_receipts(
        tmp_path, path, source, source_cid, module_identities={}
    )
    assert receipts == []
    assert outcomes == {}


def test_chained_attribute_coordinates_without_spelling_resolution(
    tmp_path: Path,
) -> None:
    """Each Attribute in a chain keeps its own exact coordinate and path."""
    path = tmp_path / "chain.py"
    source, source_cid = _write(
        path,
        "import os\n"
        "x = os.path.join\n",
    )
    receipts, _ = authenticated_import_value_use_receipts(
        tmp_path, path, source, source_cid, module_identities={}
    )
    by_target = {r.target_symbol: r for r in receipts}
    assert set(by_target) == {
        "python:os",
        "python:os.path",
        "python:os.path.join",
    }
    assert by_target["python:os"].use["exportedMemberPath"] == []
    assert by_target["python:os.path"].use["exportedMemberPath"] == ["path"]
    assert by_target["python:os.path.join"].use["exportedMemberPath"] == [
        "path",
        "join",
    ]
    # Distinct exact occurrences — not one first-candidate for the chain.
    sites = {_site_key(r) for r in receipts}
    assert len(sites) == 3
    for receipt in receipts:
        assert receipt.use["role"] == "value-use"
        assert receipt.use["sourceCid"] == source_cid
        assert receipt.import_binding.to_value()["sourceCid"] == source_cid
        receipt.revalidate()


def test_value_use_role_and_identity_fields_are_authenticated(
    tmp_path: Path,
) -> None:
    path = tmp_path / "role.py"
    source, source_cid = _write(
        path,
        "import unprivileged as tm\nactual = tm.box_expected\n",
    )
    receipts, _ = authenticated_import_value_use_receipts(
        tmp_path, path, source, source_cid, module_identities={}
    )
    attr = [
        r for r in receipts if r.target_symbol == "python:unprivileged.box_expected"
    ]
    assert len(attr) == 1
    receipt = attr[0]
    assert receipt.use["role"] == "value-use"
    assert receipt.demand["role"] == "value-use"
    assert receipt.demand["kind"] == "import-value-use-demand"
    assert receipt.use["sourceCid"] == source_cid
    assert receipt.use["useSite"]["sourceCid"] == source_cid
    assert receipt.use["exportedMemberPath"] == ["box_expected"]
    assert receipt.use["importBindingCid"] == receipt.import_binding.cid
    assert receipt.use["useSite"]["startLine"] == 2
    assert receipt.use["useSite"]["endLine"] == 2
    receipt.revalidate()


def test_call_and_value_receipt_sets_are_disjoint(tmp_path: Path) -> None:
    """Call-target and value-use coordinates never share a receipt set."""
    path = tmp_path / "mixed.py"
    source, source_cid = _write(
        path,
        "import pkg as tm\n"
        "from pkg import f\n"
        "x = f\n"
        "y = tm.box_expected\n"
        "f(1)\n"
        "tm.box_expected((1,), tm.array)\n",
    )
    call_receipts, call_outcomes = authenticated_import_use_receipts(
        tmp_path, path, source, source_cid, module_identities={}
    )
    value_receipts, value_outcomes = authenticated_import_value_use_receipts(
        tmp_path, path, source, source_cid, module_identities={}
    )

    assert call_receipts
    assert value_receipts
    assert all(r.demand["kind"] == "call-contract-demand" for r in call_receipts)
    assert all(r.demand["kind"] == "import-value-use-demand" for r in value_receipts)
    assert all(r.use.get("role") != "value-use" for r in call_receipts)
    assert all(r.use["role"] == "value-use" for r in value_receipts)

    call_sites = {_site_key(r) for r in call_receipts}
    value_sites = {_site_key(r) for r in value_receipts}
    assert call_sites.isdisjoint(value_sites)
    assert set(call_outcomes).isdisjoint(set(value_outcomes))

    targets = {r.target_symbol for r in value_receipts}
    assert "python:pkg.f" in targets
    assert "python:pkg.box_expected" in targets
    assert "python:pkg.array" in targets

    for receipt in (*call_receipts, *value_receipts):
        receipt.revalidate()


def test_nearby_call_receipt_does_not_authorize_value_use(tmp_path: Path) -> None:
    """A Call-target receipt at a call site never appears on the value surface."""
    path = tmp_path / "call_only.py"
    source, source_cid = _write(
        path,
        "from pkg import f\n"
        "f(1)\n",
    )
    call_receipts, call_outcomes = authenticated_import_use_receipts(
        tmp_path, path, source, source_cid, module_identities={}
    )
    value_receipts, value_outcomes = authenticated_import_value_use_receipts(
        tmp_path, path, source, source_cid, module_identities={}
    )
    assert len(call_receipts) == 1
    call = call_receipts[0]
    call_key = _site_key(call)
    assert call_outcomes[call_key] == "authenticated-import-use"
    # Call coordinate is not a value-use outcome.
    assert call_key not in value_outcomes
    assert all(_site_key(r) != call_key for r in value_receipts)
    # Name load of f (Call.func) may be a value use — distinct coordinate.
    for value in value_receipts:
        assert value.demand["kind"] == "import-value-use-demand"
        assert value.use["role"] == "value-use"
        assert _site_key(value) != call_key


def test_call_receipt_cannot_substitute_for_value_use(tmp_path: Path) -> None:
    """Lying twin: minting a value-use demand from a call row is refused."""
    path = tmp_path / "sub_call.py"
    source, source_cid = _write(path, "from pkg import f\nf(1)\n")
    call_receipts, _ = authenticated_import_use_receipts(
        tmp_path, path, source, source_cid, module_identities={}
    )
    call = call_receipts[0]
    # Strip call-only fields and claim value-use role — must not mint.
    forged_use = {
        key: value
        for key, value in call.use.items()
        if key != "cid"
    }
    forged_use["role"] = "value-use"
    forged_use["sourceCid"] = source_cid
    forged_use["exportedMemberPath"] = []
    from sugar_lift_py_tests.import_binding import _hash

    forged_use_with_cid = {**forged_use, "cid": _hash(forged_use)}
    forged_demand = {
        "schemaVersion": "1",
        "kind": "import-value-use-demand",
        "role": "value-use",
        "sourceCid": source_cid,
        "authenticatedImportUse": forged_use_with_cid,
        "importBinding": call.import_binding.to_value(),
        "targetSymbol": call.target_symbol,
        "exportedMemberPath": [],
        "importBindingCid": call.import_binding.cid,
        "useSite": call.use["useSite"],
    }
    # Authority token is private — public construction without mint authority fails.
    with pytest.raises(ValueError, match="not minted by the lexical pass"):
        AuthenticatedImportUseV1(
            import_binding=call.import_binding,
            target_symbol=call.target_symbol,
            use=forged_use_with_cid,
            demand=forged_demand,
            root=tmp_path,
            path=path,
            source=source,
            source_cid=source_cid,
            module_identities={},
            _authority=object(),
        )
    # Even with the real binding, value revalidation does not contain the call row.
    call.revalidate()
    value_receipts, value_outcomes = authenticated_import_value_use_receipts(
        tmp_path, path, source, source_cid, module_identities={}
    )
    assert _site_key(call) not in value_outcomes
    assert all(r.demand != call.demand for r in value_receipts)


def test_value_receipt_cannot_substitute_for_call_target(tmp_path: Path) -> None:
    """Lying twin: a value-use receipt is not a call-contract demand."""
    path = tmp_path / "sub_value.py"
    source, source_cid = _write(path, "from pkg import f\nx = f\n")
    value_receipts, value_outcomes = authenticated_import_value_use_receipts(
        tmp_path, path, source, source_cid, module_identities={}
    )
    call_receipts, call_outcomes = authenticated_import_use_receipts(
        tmp_path, path, source, source_cid, module_identities={}
    )
    assert value_receipts
    assert call_receipts == []
    value = value_receipts[0]
    value_key = _site_key(value)
    assert value_key in value_outcomes
    assert value_key not in call_outcomes
    assert value.demand["kind"] == "import-value-use-demand"
    assert value.use["role"] == "value-use"
    # Call surface has no receipt for a pure value load.
    assert all(r.demand["kind"] != "import-value-use-demand" for r in call_receipts)
    value.revalidate()


def test_forged_value_role_on_call_shape_is_refused_at_mint(tmp_path: Path) -> None:
    """Call-contract demand cannot carry value-use role even with authority."""
    from sugar_lift_py_tests import import_binding as ib

    path = tmp_path / "forge_role.py"
    source, source_cid = _write(path, "from pkg import f\nf(1)\n")
    call_receipts, _ = authenticated_import_use_receipts(
        tmp_path, path, source, source_cid, module_identities={}
    )
    call = call_receipts[0]
    forged_use = {k: v for k, v in call.use.items() if k != "cid"}
    forged_use["role"] = "value-use"
    forged_use_cid = {**forged_use, "cid": ib._hash(forged_use)}
    forged_demand = dict(call.demand)
    forged_demand["authenticatedImportUse"] = forged_use_cid
    forged_demand["role"] = "value-use"
    with pytest.raises(ValueError, match="cannot carry value-use role"):
        AuthenticatedImportUseV1(
            import_binding=call.import_binding,
            target_symbol=call.target_symbol,
            use=forged_use_cid,
            demand=forged_demand,
            root=tmp_path,
            path=path,
            source=source,
            source_cid=source_cid,
            module_identities={},
            _authority=ib._IMPORT_AUTHORITY,
        )
