from __future__ import annotations

import pytest

from sugar_lift_py_tests.factory import FactoryPanic, factory_panic_gap
from sugar_lift_py_tests.kit_rpc import RecoveredAuditDto
from sugar_lift_py_tests.lift_rpc import audit_lift_file


SOURCE = "from fixture_module import VALUE\n\ndef read():\n    return VALUE\n"


def _panic_resolver(import_target, ctx):
    del import_target, ctx
    factory_panic_gap(
        owner="seeding-fixture",
        blame="seeded.py:1:0",
        observed="VALUE",
        requested="resolved import value",
        fix="hold this seeding gap at the recovered-audit door",
    )


def test_recovery_holds_seeding_panic_as_counted_locus(monkeypatch) -> None:
    monkeypatch.setattr(
        "sugar_lift_py_tests.sugar.install_source_dig.resolve_install_source_value",
        _panic_resolver,
    )

    recovered = audit_lift_file(SOURCE, "seeded.py", recover_panics=True)
    assert isinstance(recovered, RecoveredAuditDto)
    seed = next(row for row in recovered.panics if row.gap["owner"] == "seeding-fixture")
    assert seed.locus == "seeded.py:1:0"
    assert seed.gap["observed"] == "VALUE"


def test_normal_lift_keeps_seeding_panic_fail_fast(monkeypatch) -> None:
    monkeypatch.setattr(
        "sugar_lift_py_tests.sugar.install_source_dig.resolve_install_source_value",
        _panic_resolver,
    )

    with pytest.raises(FactoryPanic, match="owner=seeding-fixture"):
        audit_lift_file(SOURCE, "seeded.py", hold_panic=False)
