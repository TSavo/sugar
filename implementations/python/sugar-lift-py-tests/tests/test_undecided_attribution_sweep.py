"""Undecided attribution sweep — do not count source-undecided as missing Floor.

ImportMemberValue already wires subscript/attribute/contains into
FloorValue.undecided_* (#import-member ops). This file pins the *same* law for
other value types that still fell through to:

  write more Floor: implement {Type}.attribute

when the honest answer is "runtime type not lift-time decided".

Triage: vocabulary already exists on FloorValue; offenders were wrong entrance
(base construction-panic arm), not empty building.
"""

from __future__ import annotations

from types import SimpleNamespace

import pytest

from sugar_lift_py_tests.floor.import_alias_value import ImportAliasValue
from sugar_lift_py_tests.floor.mutable_global_value import MutableGlobalValue
from sugar_lift_py_tests.gap.panic import ConstructionPanic
from sugar_source_tree.fragment import SourceMemento
from sugar_source_tree.panic import SugarNotWritten

_CID = "blake3-512:" + ("ab" * 64)
_CID2 = "blake3-512:" + ("cd" * 64)


class _Site:
    def __str__(self) -> str:
        return "site:undecided_sweep.py:1:1"

    source_cid = _CID

    def is_within_annotation(self) -> bool:
        return False


def _alias() -> ImportAliasValue:
    return ImportAliasValue(name="os", bound_name="os", import_target="os")


def _mutable(*, kind: str = "list") -> MutableGlobalValue:
    memento = SourceMemento(
        file="mod.py",
        source_cid=_CID,
        cid=_CID2,
        start=0,
        end=1,
    )
    return MutableGlobalValue(
        name="g",
        kind=kind,
        pin_source_cid=_CID,
        binding_memento=memento,
    )


def test_import_alias_runtime_type_undecided() -> None:
    assert _alias().runtime_type_is_decided() is False


def test_import_alias_attribute_is_undecided_not_write_more_floor() -> None:
    """Was: ConstructionPanic write more Floor: implement ImportAliasValue.attribute."""
    v = _alias()
    site = _Site()
    with pytest.raises(SugarNotWritten, match="ImportAliasValue.attribute") as caught:
        v.attribute("path", site)
    msg = str(caught.value)
    assert "write more Floor" not in msg
    assert "undecided" in caught.value.observed.lower()


def test_import_alias_contains_is_undecided_not_write_more_floor() -> None:
    v = _alias()
    site = _Site()
    with pytest.raises(SugarNotWritten, match="ImportAliasValue.contains") as caught:
        v.contains(v, site)
    assert "write more Floor" not in str(caught.value)


def test_import_alias_subscript_still_undecided() -> None:
    v = _alias()
    site = _Site()
    with pytest.raises(SugarNotWritten, match="ImportAliasValue.subscript"):
        v.subscript(0, site)


def test_import_alias_getattr_static_is_undecided_not_construction_gap() -> None:
    """getattr_static used to construction_panic_gap; same undecided law."""
    v = _alias()
    site = _Site()
    with pytest.raises(SugarNotWritten, match="ImportAliasValue.getattr_static"):
        v.getattr_static("path", site)


def test_mutable_global_non_dict_contains_is_undecided_not_write_more_floor() -> None:
    """kind!=dict used super().contains → write more Floor: implement MutableGlobalValue.contains."""
    v = _mutable(kind="list")
    site = _Site()
    assert v.runtime_type_is_decided() is False
    with pytest.raises(SugarNotWritten, match="MutableGlobalValue.contains") as caught:
        v.contains(0, site)
    assert "write more Floor" not in str(caught.value)


def test_mutable_global_attribute_is_undecided_not_write_more_floor() -> None:
    v = _mutable(kind="dict")
    site = _Site()
    with pytest.raises(SugarNotWritten, match="MutableGlobalValue.attribute") as caught:
        v.attribute("keys", site)
    assert "write more Floor" not in str(caught.value)


def test_mutable_global_dict_contains_still_constructs() -> None:
    """Do not break decided dict membership on the pin."""
    from sugar_lift_py_tests.floor.term_value import TermValue
    from sugar_lift_py_tests.outcome import Complete

    v = _mutable(kind="dict")
    site_ok = SimpleNamespace(
        __str__=lambda self: "site:mod.py:1:1",
        source_cid=_CID,
    )
    outcome = v.contains(TermValue(1), site_ok)
    assert isinstance(outcome, Complete)


def test_no_construction_panic_on_alias_attribute() -> None:
    """Regression class: ConstructionPanic is the forbidden miscount costume."""
    v = _alias()
    site = _Site()
    with pytest.raises(SugarNotWritten):
        v.attribute("x", site)
    try:
        v.attribute("x", site)
    except ConstructionPanic:
        pytest.fail("ImportAliasValue.attribute must not ConstructionPanic")
    except SugarNotWritten:
        pass
