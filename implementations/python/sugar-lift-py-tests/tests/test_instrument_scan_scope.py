"""Teeth for InstrumentScanScope — wrong-population class (vendor 23→~0 et al.).

Plant instrument-self and auth-pin inventory under a declared root; scope must
refuse to count them. Empty declared_roots is unconstructible.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from sugar_lift_py_tests.idd.instrument_scan_scope import (
    AUTH_PIN_INVENTORY_BASENAMES,
    InstrumentScanScope,
    InstrumentScanScopeError,
    instrument_scan_scope,
    require_declared_roots,
)


def test_empty_declared_roots_unconstructible(tmp_path: Path) -> None:
    with pytest.raises(InstrumentScanScopeError, match="non-empty"):
        instrument_scan_scope(
            declared_roots=(),
            instrument_self=tmp_path / "scanner.py",
        )


def test_direct_scope_without_seal_refuses(tmp_path: Path) -> None:
    with pytest.raises(InstrumentScanScopeError, match="sealed"):
        InstrumentScanScope(
            declared_roots=(tmp_path,),
            instrument_self_paths=frozenset({tmp_path / "s.py"}),
            self_exclusion=True,
            auth_pin_exclusion=True,
            _seal=object(),
        )


def test_empty_instrument_self_unconstructible(tmp_path: Path) -> None:
    with pytest.raises(InstrumentScanScopeError, match="instrument_self"):
        instrument_scan_scope(
            declared_roots=(tmp_path,),
            instrument_self=(),
        )


def test_scope_fields_always_exclude(tmp_path: Path) -> None:
    self_mod = tmp_path / "law.py"
    self_mod.write_text("#\n", encoding="utf-8")
    scope = instrument_scan_scope(
        declared_roots=(tmp_path,),
        instrument_self=self_mod,
    )
    assert scope.self_exclusion is True
    assert scope.auth_pin_exclusion is True


def test_planted_instrument_self_is_not_admitted(tmp_path: Path) -> None:
    """Tooth: instrument scanning its own source must not count it."""
    root = tmp_path / "pop"
    root.mkdir()
    scanner = root / "vendor_special_case_law.py"
    scanner.write_text(
        "VENDORS = {'numpy', 'pandas'}\n",
        encoding="utf-8",
    )
    product = root / "sugar_ok.py"
    product.write_text("x = 1\n", encoding="utf-8")

    scope = instrument_scan_scope(
        declared_roots=(root,),
        instrument_self=scanner,
    )
    assert scope.admits(product) is True
    assert scope.admits(scanner) is False
    admitted = {p.name for p in scope.iter_python_files()}
    assert admitted == {"sugar_ok.py"}
    assert "vendor_special_case_law.py" not in admitted


def test_planted_auth_pin_inventory_is_not_admitted(tmp_path: Path) -> None:
    """Tooth: auth-pin modules that name numpy/pandas pins must not count."""
    root = tmp_path / "pop"
    root.mkdir()
    assert "authenticated_pytest.py" in AUTH_PIN_INVENTORY_BASENAMES
    pin = root / "authenticated_pytest.py"
    pin.write_text(
        'pins = {"numpy": "1.0", "pandas": "2.0"}\n',
        encoding="utf-8",
    )
    body = root / "no_call_body_attribution.py"
    body.write_text('AUTHENTICATED_PANDAS = "3.0.3"\n', encoding="utf-8")
    product = root / "floor_value.py"
    product.write_text("class Floor: pass\n", encoding="utf-8")

    scope = instrument_scan_scope(
        declared_roots=(root,),
        instrument_self=tmp_path / "scanner.py",
    )
    (tmp_path / "scanner.py").write_text("# scanner\n", encoding="utf-8")
    # rebuild with resolved self
    scope = instrument_scan_scope(
        declared_roots=(root,),
        instrument_self=tmp_path / "scanner.py",
    )
    assert scope.admits(product) is True
    assert scope.admits(pin) is False
    assert scope.admits(body) is False
    admitted = {p.name for p in scope.iter_python_files()}
    assert admitted == {"floor_value.py"}


def test_provenance_carries_declared_roots_and_exclusions(tmp_path: Path) -> None:
    root = tmp_path / "r"
    root.mkdir()
    self_mod = tmp_path / "law.py"
    self_mod.write_text("#\n", encoding="utf-8")
    scope = instrument_scan_scope(
        declared_roots=(root,),
        instrument_self=self_mod,
    )
    prov = scope.to_provenance()
    assert prov["selfExclusion"] is True
    assert prov["authPinExclusion"] is True
    assert any(str(root) in s for s in prov["declaredRoots"])  # type: ignore[operator]
    assert "authenticated_pytest.py" in prov["authPinInventoryBasenames"]


def test_require_declared_roots_refuses_empty() -> None:
    with pytest.raises(InstrumentScanScopeError, match="non-empty"):
        require_declared_roots(())
