"""#7840, inventory item 43: the owed parameter contract is gone.

An owed parameter contract was a ``ContractConditionalConstructionV1`` carried
on an arm's ``pending_contracts``. Since #6611 (2026-07-27, "Route formal
Subscript through caller discharge") nothing in the lifter minted one: a formal
operation such as ``p[0]`` owes a ``NativeOperationExitCarrierV1`` demand
instead. #7840 struck the 20 sites that rebuilt the slot as ``()``; item 43
deleted the class, the slot on ``Incomplete``, ``Halted`` and ``Completed``,
and every piece of carrier code that existed only to carry it.

The tests below are tripwires. If a second representation of an owed contract
comes back, they fail.
"""

from __future__ import annotations

import dataclasses
from pathlib import Path

import pytest


def _python_src_roots() -> list[Path]:
    root = Path(__file__).resolve().parents[2]
    return [path / "src" for path in sorted(root.iterdir()) if (path / "src").is_dir()]


def test_no_lifter_source_names_the_owed_contract() -> None:
    offenders = []
    for src in _python_src_roots():
        for path in sorted(src.rglob("*.py")):
            text = path.read_text(encoding="utf-8")
            for needle in ("ContractConditionalConstructionV1", "pending_contracts"):
                if needle in text:
                    offenders.append(f"{path.relative_to(src.parent.parent)}: {needle}")

    assert offenders == []


def test_the_class_is_gone() -> None:
    import sugar_lift_py_tests.caller_parameter_contract as contracts

    assert not hasattr(contracts, "ContractConditionalConstructionV1")


@pytest.mark.parametrize("arm", ["Incomplete", "Halted", "Completed"])
def test_no_arm_carries_an_owed_contract_slot(arm: str) -> None:
    import sugar_lift_py_tests.outcome as outcome

    names = {field.name for field in dataclasses.fields(getattr(outcome, arm))}
    assert "pending_contracts" not in names


def _tree(source: str):
    from sugar_lift_python_source.canonical import blake3_512_of
    from sugar_lift_py_tests.context_manager_resolution import (
        TreeConstructionContextV1,
    )
    from sugar_source_tree.tree import SourceFile

    return SourceFile(
        (source, "test_witness.py", blake3_512_of(source.encode())),
        construction_context=TreeConstructionContextV1.for_test_without_workspace(),
    )


def _link_unit_of_f(source: str):
    """The link unit the ``parameter-contract-link-units`` level would enrol for
    ``f``, or ``None`` where that level enrols none (a refusal, or not a
    completed universe)."""
    from sugar_lift_py_tests.floor.universe_value import UniverseValue
    from sugar_lift_py_tests.outcome import Complete
    from sugar_lift_py_tests.tree_enumerate import (
        function_def_memento,
        function_universe_outcome,
    )
    from sugar_source_tree import nodes

    (fn,) = [
        node
        for node in _tree(source).nodes()
        if isinstance(node, nodes.FunctionDef) and node.name == "f"
    ]
    try:
        outcome = function_universe_outcome(fn)
    except Exception:  # noqa: BLE001 - a refusal enrols no link unit, so owes nothing
        return None
    if not isinstance(outcome, Complete) or not isinstance(
        outcome.value, UniverseValue
    ):
        return None
    return outcome.value.link_unit_projection(
        function_def_memento(fn, "test_witness.py").to_rpc()
    )


# One program per family of #7840. A parameter contract would have been owed
# inside the construct, by ``p[0]`` on the formal ``p``.
_FAMILIES = {
    "bare": "def f(p):\n    return p[0]\n",
    "if": "def f(p, c):\n    if c:\n        return p[0]\n    return 0\n",
    "loop": "def f(p, xs):\n    for x in xs:\n        y = p[0]\n    return 1\n",
    "with": (
        "import contextlib\n\n\ndef f(p):\n    with contextlib.suppress(KeyError):\n"
        "        return p[0]\n    return 0\n"
    ),
    "raise": "def f(p):\n    raise ValueError(p[0])\n",
    "spread": "def f(p):\n    return [*p[0]]\n",
    "store": (
        "class Box:\n    pass\n\n\ndef f(p):\n    b = Box()\n    b.x = p[0]\n"
        "    return b.x\n"
    ),
    "routing": (
        "def f(p):\n    try:\n        return p[0]\n    except KeyError:\n"
        "        return 0\n"
    ),
}


@pytest.mark.parametrize("family", sorted(_FAMILIES))
def test_no_family_link_unit_owes_a_parameter_contract(family: str) -> None:
    unit = _link_unit_of_f(_FAMILIES[family])
    if unit is None:
        return
    assert unit.candidates == ()
    assert unit.parameter_owned_contract.declared_demand_cids == ()
    assert unit.to_value()["candidates"] == []


def test_a_formal_subscript_still_enrols_its_link_unit() -> None:
    """Positive control: the enrolment row itself survives, owing nothing."""
    unit = _link_unit_of_f(_FAMILIES["bare"])
    assert unit is not None
    assert len(unit.parameter_owned_contract.formal_coordinates) == 1
