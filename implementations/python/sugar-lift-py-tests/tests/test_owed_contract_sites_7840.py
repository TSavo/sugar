"""#7840: the 20 sites that rebuild an arm's ``pending_contracts`` as ``()``.

Tests only. Every site is struck for one reason: no source program can owe a
parameter contract, so no source program can reach a site with a non-empty
``pending_contracts`` to drop.

An owed parameter contract is a ``ContractConditionalConstructionV1``. Every
other spelling of one is derived from an existing one: ``demanded_under``,
``merge_pending``, ``weaken_pending``, ``rewrap_pending``, the
``outcome_to_exitset`` arm, and ``Incomplete.guarded``. The only originator is
``ContractConditionalConstructionV1.mint``. Since #6611 (2026-07-27, "Route
formal Subscript through caller discharge") nothing in the lifter calls it:
a formal operation such as ``p[0]`` owes a ``NativeOperationExitCarrierV1``
demand instead, and only unit tests construct the pending candidate directly.

The tests below are tripwires. If a source path starts minting owed contracts
again, they fail, and the 20 sites must then be read again.
"""

from __future__ import annotations

from pathlib import Path

import pytest


def _python_src_roots() -> list[Path]:
    root = Path(__file__).resolve().parents[2]
    return [path / "src" for path in sorted(root.iterdir()) if (path / "src").is_dir()]


def test_no_lifter_source_mints_an_owed_parameter_contract() -> None:
    offenders = []
    for src in _python_src_roots():
        for path in sorted(src.rglob("*.py")):
            text = path.read_text(encoding="utf-8")
            for needle in (
                "ContractConditionalConstructionV1.mint(",
                "ContractConditionalConstructionV1(",
            ):
                if needle in text:
                    offenders.append(f"{path.relative_to(src.parent.parent)}: {needle}")

    assert offenders == []


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


def _reduce_every_function(source: str) -> None:
    from sugar_lift_py_tests.tree_enumerate import function_universe_outcome
    from sugar_source_tree import nodes

    for node in _tree(source).nodes():
        if isinstance(node, nodes.FunctionDef):
            try:
                function_universe_outcome(node)
            except BaseException:  # noqa: BLE001 - a named refusal still mints nothing
                pass


def _count_constructions(monkeypatch) -> list:
    import sugar_lift_py_tests.caller_parameter_contract as contracts

    minted: list = []
    original = contracts.ContractConditionalConstructionV1.__init__

    def counting(self, *args, **kwargs):
        minted.append(self)
        return original(self, *args, **kwargs)

    monkeypatch.setattr(
        contracts.ContractConditionalConstructionV1, "__init__", counting
    )
    return minted


def test_the_counter_sees_a_minted_owed_contract(monkeypatch) -> None:
    """Positive control: a direct mint, as the unit tests do it, is counted."""
    import types

    from sugar_lift_py_tests.caller_parameter_contract import (
        ContractConditionalConstructionV1,
    )
    from sugar_lift_py_tests.context_manager_resolution import (
        SourceFragmentCoordinateV1,
    )
    from sugar_lift_py_tests.formal_parameter import FormalParameterCoordinateV1
    from sugar_lift_py_tests.ir import PrimitiveSort, atomic, ctor, make_var, num

    source = "blake3-512:" + "a" * 128
    owner = SourceFragmentCoordinateV1(source, 1, 0, 10, 4)
    coordinate = FormalParameterCoordinateV1.mint(
        owner_source_identity_cid=source,
        owner_definition_locus=owner,
        declaration_locus=SourceFragmentCoordinateV1(source, 1, 6, 1, 7),
        ordinal=0,
        parameter_kind="positional-or-keyword",
        declared_name="p",
        sort=PrimitiveSort("Value"),
    )
    span = types.SimpleNamespace(start_line=2, start_col=11, end_line=2, end_col=15)
    minted = _count_constructions(monkeypatch)

    ContractConditionalConstructionV1.mint(
        site=types.SimpleNamespace(source_cid=source, line_col_span=span),
        candidate=ctor("py.subscript", [make_var("p"), num(0)]),
        demand_formula=atomic("python:indexable", [make_var("p")]),
        value=None,
        coordinate=coordinate,
    )

    assert len(minted) == 1


# One program per family of #7840. A parameter contract would be owed inside
# the construct, by ``p[0]`` on the formal ``p``, and each claim depends on it.
# Each family has two callers: one whose actual satisfies the demand
# (truthful) and one whose actual violates it (lying).
_FAMILIES = {
    "if": (
        "def f(p, c):\n    if c:\n        return p[0]\n    return 0\n\n\n",
        "f({actual}, True)",
    ),
    "loop": (
        "def f(p, xs):\n    for x in xs:\n        y = p[0]\n    return 1\n\n\n",
        "f({actual}, [1])",
    ),
    "with": (
        "import contextlib\n\n\ndef f(p):\n    with contextlib.suppress(KeyError):\n"
        "        return p[0]\n    return 0\n\n\n",
        "f({actual})",
    ),
    "raise": ("def f(p):\n    raise ValueError(p[0])\n\n\n", "f({actual})"),
    "spread": ("def f(p):\n    return [*p[0]]\n\n\n", "f({actual})"),
    "store": (
        "class Box:\n    pass\n\n\ndef f(p):\n    b = Box()\n    b.x = p[0]\n"
        "    return b.x\n\n\n",
        "f({actual})",
    ),
    "routing": (
        "def f(p):\n    try:\n        return p[0]\n    except KeyError:\n"
        "        return 0\n\n\n",
        "f({actual})",
    ),
}


@pytest.mark.parametrize("half", ["truthful", "lying"])
@pytest.mark.parametrize("family", sorted(_FAMILIES))
def test_no_family_owes_a_parameter_contract_from_source(
    family: str, half: str, monkeypatch
) -> None:
    minted = _count_constructions(monkeypatch)
    callee, call = _FAMILIES[family]
    actual = "[1]" if half == "truthful" else "5"

    _reduce_every_function(
        callee
        + f"def test_f():\n    x = {call.format(actual=actual)}\n    assert 1 == 1\n"
    )
    # The formal alone, as the callee's own contract would see it.
    _reduce_every_function(
        callee + f"def test_f(q):\n    x = {call.format(actual='q')}\n"
    )

    assert minted == []
