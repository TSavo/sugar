"""Imported Name/Attribute VALUE occurrences get final-checked receipts.

A value-use receipt authenticates together: exact source occurrence, import
binding, exported member coordinate, consumer source CID, and value-use role.
Call-target receipts are a disjoint surface; neither substitutes for the other.
Shadowing, reassignment, wildcard ambiguity, and tampering do not authorize a
value.  No AST-scan fallback, first-candidate, or spelling resolver.
"""

from __future__ import annotations

from dataclasses import replace
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


def test_package_init_relative_import_owns_exact_member_value_use(
    tmp_path: Path,
) -> None:
    package = tmp_path / "renamed_package"
    package.mkdir()
    path = package / "__init__.py"
    source, source_cid = _write(
        path,
        "from . import helper\n\nclass C:\n    A = B = helper.FLAG\n",
    )

    receipts, _ = authenticated_import_value_use_receipts(
        tmp_path, path, source, source_cid, module_identities={}
    )

    member = tuple(
        receipt
        for receipt in receipts
        if receipt.target_symbol == "python:renamed_package.helper.FLAG"
    )
    assert len(member) == 1
    assert member[0].use["exportedMemberPath"] == ["FLAG"]
    assert _site_key(member[0]) == (4, 12, 4, 23)


def test_package_relative_member_receipts_refuse_cross_package_substitution(
    tmp_path: Path,
) -> None:
    receipts = []
    for package_name in ("first_package", "second_package"):
        package = tmp_path / package_name
        package.mkdir()
        path = package / "__init__.py"
        source, source_cid = _write(
            path, "from . import helper\nvalue = helper.FLAG\n"
        )
        rows, _ = authenticated_import_value_use_receipts(
            tmp_path, path, source, source_cid, module_identities={}
        )
        receipts.append(next(row for row in rows if row.use["exportedMemberPath"]))

    first, second = receipts
    assert first.target_symbol == "python:first_package.helper.FLAG"
    assert second.target_symbol == "python:second_package.helper.FLAG"
    assert first.import_binding.cid != second.import_binding.cid
    assert first.use["cid"] != second.use["cid"]
    with pytest.raises(ValueError, match="cites another binding"):
        replace(first, import_binding=second.import_binding)


def test_non_init_module_relative_import_keeps_parent_package(
    tmp_path: Path,
) -> None:
    package = tmp_path / "sibling_control"
    package.mkdir()
    path = package / "consumer.py"
    source, source_cid = _write(
        path, "from . import helper\nvalue = helper.FLAG\n"
    )

    rows, _ = authenticated_import_value_use_receipts(
        tmp_path, path, source, source_cid, module_identities={}
    )
    member = tuple(row for row in rows if row.use["exportedMemberPath"])
    assert len(member) == 1
    assert member[0].target_symbol == "python:sibling_control.helper.FLAG"


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
    assert set(outcomes.values()) == {"shadowed-non-import"}


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


def test_value_relabeled_as_call_contract_refused_with_real_authority(
    tmp_path: Path,
) -> None:
    """Lying twin: value receipt → call-contract-demand (roles stripped, CID recomputed).

    Must refuse under real mint authority — observing output-set disjointness
    is not enough; substitution is attempted at __post_init__.
    """
    from sugar_lift_py_tests import import_binding as ib

    path = tmp_path / "sub_value_as_call.py"
    source, source_cid = _write(path, "from pkg import f\nx = f\n")
    value_receipts, _ = authenticated_import_value_use_receipts(
        tmp_path, path, source, source_cid, module_identities={}
    )
    value = value_receipts[0]
    # Strip value-only fields; recompute use CID — the advisor hole shape.
    forged_use = {
        key: val
        for key, val in value.use.items()
        if key not in {"cid", "role", "sourceCid", "exportedMemberPath"}
    }
    forged_use_cid = {**forged_use, "cid": ib._hash(forged_use)}
    forged_demand = {
        key: val
        for key, val in value.demand.items()
        if key
        not in {
            "role",
            "sourceCid",
            "exportedMemberPath",
            "authenticatedImportUse",
            "kind",
        }
    }
    forged_demand["kind"] = "call-contract-demand"
    forged_demand["authenticatedImportUse"] = forged_use_cid
    # No importSignature added — pure relabel of a value receipt.
    with pytest.raises(ValueError, match="requires importSignature|unadmitted kind"):
        AuthenticatedImportUseV1(
            import_binding=value.import_binding,
            target_symbol=value.target_symbol,
            use=forged_use_cid,
            demand=forged_demand,
            root=tmp_path,
            path=path,
            source=source,
            source_cid=source_cid,
            module_identities={},
            _authority=ib._IMPORT_AUTHORITY,
        )


def test_call_relabeled_as_value_use_refused_with_real_authority(
    tmp_path: Path,
) -> None:
    """Lying twin: call receipt → import-value-use-demand without value role fields."""
    from sugar_lift_py_tests import import_binding as ib

    path = tmp_path / "sub_call_as_value.py"
    source, source_cid = _write(path, "from pkg import f\nf(1)\n")
    call_receipts, _ = authenticated_import_use_receipts(
        tmp_path, path, source, source_cid, module_identities={}
    )
    call = call_receipts[0]
    forged_demand = dict(call.demand)
    forged_demand["kind"] = "import-value-use-demand"
    # Keep call use shape (no role / exportedMemberPath / sourceCid on use).
    with pytest.raises(ValueError, match="requires value-use role"):
        AuthenticatedImportUseV1(
            import_binding=call.import_binding,
            target_symbol=call.target_symbol,
            use=call.use,
            demand=forged_demand,
            root=tmp_path,
            path=path,
            source=source,
            source_cid=source_cid,
            module_identities={},
            _authority=ib._IMPORT_AUTHORITY,
        )


def test_call_receipt_carries_exact_multi_segment_export_path(tmp_path: Path) -> None:
    path = tmp_path / "multi_hop_call.py"
    source, source_cid = _write(path, "import os\nos.path.dirname('a/b')\n")

    receipts, outcomes = authenticated_import_use_receipts(
        tmp_path, path, source, source_cid, module_identities={}
    )

    assert set(outcomes.values()) == {"authenticated-import-use"}
    assert len(receipts) == 1
    receipt = receipts[0]
    assert receipt.demand["kind"] == "call-contract-demand"
    assert receipt.target_symbol == "python:os.path.dirname"
    assert receipt.use["useSite"] == receipt.demand["useSite"]


def test_shadowed_multi_segment_call_head_has_no_import_receipt(tmp_path: Path) -> None:
    path = tmp_path / "shadowed_multi_hop_call.py"
    source, source_cid = _write(
        path,
        "import os\ndef use(os):\n    return os.path.dirname('a/b')\n",
    )

    receipts, outcomes = authenticated_import_use_receipts(
        tmp_path, path, source, source_cid, module_identities={}
    )

    assert receipts == []
    assert outcomes == {}


def test_forged_binding_head_with_real_authority_refused(tmp_path: Path) -> None:
    """Lying twin: targetSymbol head forged; real binding CID + path still refuse.

    endswith(exportedMemberPath) would accept python:other.box_expected with a
    binding for python:pkg — exact composition must not.
    """
    from sugar_lift_py_tests import import_binding as ib

    path = tmp_path / "forge_head.py"
    source, source_cid = _write(
        path,
        "import pkg as tm\nactual = tm.box_expected\n",
    )
    receipts, _ = authenticated_import_value_use_receipts(
        tmp_path, path, source, source_cid, module_identities={}
    )
    attr = [r for r in receipts if r.target_symbol == "python:pkg.box_expected"]
    assert len(attr) == 1
    honest = attr[0]
    # Change only the binding head in targetSymbol; keep real binding + path.
    forged_target = "python:other.box_expected"
    assert forged_target.endswith(".box_expected")
    assert forged_target != honest.target_symbol
    forged_demand = dict(honest.demand)
    forged_demand["targetSymbol"] = forged_target
    with pytest.raises(
        ValueError,
        match="targetSymbol disagrees with binding target and exportedMemberPath",
    ):
        AuthenticatedImportUseV1(
            import_binding=honest.import_binding,
            target_symbol=forged_target,
            use=honest.use,
            demand=forged_demand,
            root=tmp_path,
            path=path,
            source=source,
            source_cid=source_cid,
            module_identities={},
            _authority=ib._IMPORT_AUTHORITY,
        )


def test_unadmitted_demand_kind_refused_with_real_authority(tmp_path: Path) -> None:
    """Unknown demand kinds fall through no longer — closed admission only."""
    from sugar_lift_py_tests import import_binding as ib

    path = tmp_path / "unknown_kind.py"
    source, source_cid = _write(path, "from pkg import f\nx = f\n")
    value = authenticated_import_value_use_receipts(
        tmp_path, path, source, source_cid, module_identities={}
    )[0][0]
    forged_demand = dict(value.demand)
    forged_demand["kind"] = "forged-third-surface-demand"
    with pytest.raises(ValueError, match="unadmitted kind"):
        AuthenticatedImportUseV1(
            import_binding=value.import_binding,
            target_symbol=value.target_symbol,
            use=value.use,
            demand=forged_demand,
            root=tmp_path,
            path=path,
            source=source,
            source_cid=source_cid,
            module_identities={},
            _authority=ib._IMPORT_AUTHORITY,
        )


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
    with pytest.raises(ValueError, match="cannot carry value-use role|cannot carry a use role"):
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
