"""#4783 — ``nonlocal`` is an epistemic gap, not a RuntimeEffect.

Gate: would perfect machinery still fail to decide ``nonlocal x`` at lift time?
No. The declaration is lexically decidable; the kit simply has not constructed
enclosing-frame rebinding yet. That is a factory None-arm / construction gap
(``FactoryPanic``), never a ``RuntimeEffect`` (fake green: panic mass drops
with no constructed-or-genuinely-runtime mass up).

Until a ``NonlocalSugar`` honestly models shared-scope binding (analogous to
``GlobalRoute``), the shape must remain unowned so the factory panics loud.
"""

from __future__ import annotations

import pytest
from factory_reduce import compose_block

from sugar_lift_py_tests.factory.factory_gap import FactoryPanic
from sugar_lift_py_tests.lift_rpc import audit_lift_file, lift_file_payload


def test_nonlocal_declaration_factory_panics_not_runtime_effect() -> None:
    with pytest.raises(FactoryPanic) as raised:
        compose_block("    nonlocal shared\n    shared = 2\n    return shared\n")

    info = raised.value.info
    assert info.observed == "Nonlocal"
    assert info.requested == "statement"
    assert "create" in info.fix and "nonlocal" in info.fix


def test_nonlocal_mutation_runtime_effect_is_not_enrolled() -> None:
    """Shell deleted: the #4745 fake effect class must stay gone."""
    import sugar_lift_py_tests.effect as effect_pkg

    assert not hasattr(effect_pkg, "NonlocalMutationRuntimeEffect")
    assert "NonlocalMutationRuntimeEffect" not in effect_pkg.__all__


def test_production_lift_panics_on_nonlocal_statement() -> None:
    source = "def A():\n    nonlocal shared\n    shared = 2\n    return shared\n"

    with pytest.raises(FactoryPanic) as raised:
        lift_file_payload(source, "nonlocal_gap.py")

    assert raised.value.info.observed == "Nonlocal"
    assert raised.value.info.blame == "nonlocal_gap.py:2:4"


def test_recovered_audit_records_nonlocal_as_construction_panic() -> None:
    source = "def A():\n    nonlocal shared\n    return shared\n"

    wire = audit_lift_file(source, "nonlocal_gap.py", recover_panics=True).to_rpc()

    assert wire["status"] == "failed"
    assert len(wire["panics"]) == 1
    assert wire["panics"][0]["gap"]["observed"] == "Nonlocal"
    assert wire["effects"] == []
