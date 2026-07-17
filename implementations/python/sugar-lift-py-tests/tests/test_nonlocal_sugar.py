"""A ``nonlocal`` declaration names an enclosing lexical binding.

The read-only declaration is statically decidable. Cross-frame mutation remains
construct-or-panic until the mutation floor can carry the updated enclosing
frame back to its caller; it is never a RuntimeEffect.
"""

from __future__ import annotations

import pytest
from sugar_lift_py_tests.factory.factory_gap import FactoryPanic
from sugar_lift_py_tests.idd.sugar_witness_instruments import evaluate_seed_witnesses
from sugar_lift_py_tests.lift_rpc import audit_lift_file, lift_file_payload
from sugar_lift_py_tests.sugar.nonlocal_sugar import NonlocalSugar


def test_read_only_nonlocal_declaration_routes_enclosing_binding() -> None:
    source = (
        "def A(z):\n"
        "    shared = z\n"
        "    def inner():\n"
        "        nonlocal shared\n"
        "        return shared\n"
        "    return inner()\n"
        "\n"
        "def test_a():\n"
        "    assert A(5) == 5\n"
    )

    payload = lift_file_payload(source, "nonlocal_read.py")

    assert payload.effects == []
    assert payload.ir


def test_nonlocal_mutation_runtime_effect_is_not_enrolled() -> None:
    """Shell deleted: the #4745 fake effect class must stay gone."""
    import sugar_lift_py_tests.effect as effect_pkg

    assert not hasattr(effect_pkg, "NonlocalMutationRuntimeEffect")
    assert "NonlocalMutationRuntimeEffect" not in effect_pkg.__all__


def test_nonlocal_read_witness_truthful_sat_and_lying_unsat(tmp_path) -> None:
    witness = NonlocalSugar.witnesses()
    assert witness.name == "nonlocal_enclosing_read"

    report = evaluate_seed_witnesses((witness,), tmp_path)

    assert report.is_zero


def test_nonlocal_mutation_stays_loud_at_cross_frame_owner() -> None:
    source = (
        "def A(z):\n"
        "    shared = z\n"
        "    def inner():\n"
        "        nonlocal shared\n"
        "        shared = 2\n"
        "        return shared\n"
        "    return inner()\n"
        "\n"
        "def test_a():\n"
        "    assert A(5) == 2\n"
    )

    with pytest.raises(FactoryPanic) as raised:
        lift_file_payload(source, "nonlocal_gap.py")

    assert raised.value.info.owner == "NonlocalRoute"
    assert raised.value.info.observed == "shared"
    assert raised.value.info.requested == "enclosing-frame mutation"
    assert raised.value.info.blame == "shared"


def test_nonlocal_augmented_mutation_stays_loud_at_cross_frame_owner() -> None:
    source = (
        "def A(z):\n"
        "    shared = z\n"
        "    def inner():\n"
        "        nonlocal shared\n"
        "        shared += 1\n"
        "        return shared\n"
        "    return inner()\n"
        "\n"
        "def test_a():\n"
        "    assert A(5) == 6\n"
    )

    with pytest.raises(FactoryPanic) as raised:
        lift_file_payload(source, "nonlocal_aug_gap.py")

    assert raised.value.info.owner == "NonlocalRoute"
    assert raised.value.info.observed == "shared"
    assert raised.value.info.requested == "enclosing-frame mutation"


def test_nonlocal_route_does_not_leak_into_nested_function_locals() -> None:
    source = (
        "def A(z):\n"
        "    shared = z\n"
        "    def middle():\n"
        "        nonlocal shared\n"
        "        def inner():\n"
        "            shared = 3\n"
        "            return shared\n"
        "        return inner()\n"
        "    return middle()\n"
        "\n"
        "def test_a():\n"
        "    assert A(5) == 3\n"
    )

    payload = lift_file_payload(source, "nonlocal_nested.py")

    assert payload.effects == []
    assert payload.ir


def test_unbound_nonlocal_declaration_stays_loud() -> None:
    source = "def A():\n    nonlocal missing\n    return missing\n"

    wire = audit_lift_file(source, "nonlocal_unbound.py", recover_panics=True).to_rpc()

    assert wire["status"] == "failed"
    assert len(wire["panics"]) == 1
    assert wire["panics"][0]["gap"]["owner"] == "NonlocalSugar"
    assert wire["panics"][0]["gap"]["observed"] == "missing"
    assert wire["panics"][0]["gap"]["requested"] == "bound enclosing lexical name"
    assert wire["effects"] == []
