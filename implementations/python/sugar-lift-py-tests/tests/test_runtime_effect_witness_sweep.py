from __future__ import annotations

import ast
import inspect
from pathlib import Path
from typing import Iterator

from sugar_lift_py_tests.effect import RuntimeEffect

PACKAGE = Path(__file__).resolve().parents[1] / "src" / "sugar_lift_py_tests"
EVIDENCE_DOORS = {
    "runtime_effect_evidence",
    "runtime_effect_evidence_from_terms",
}


def _runtime_effect_constructor_sites() -> Iterator[tuple[Path, ast.Call]]:
    for path in PACKAGE.rglob("*.py"):
        for node in ast.walk(ast.parse(path.read_text())):
            if (
                isinstance(node, ast.Call)
                and isinstance(node.func, ast.Name)
                and node.func.id.endswith("RuntimeEffect")
                and node.func.id not in {"RuntimeEffect", "RuntimeEffectWitness"}
            ):
                yield path, node


def test_every_named_runtime_effect_construction_passes_a_witness() -> None:
    missing: list[str] = []
    for path, node in _runtime_effect_constructor_sites():
        assert isinstance(node.func, ast.Name)
        name = node.func.id
        if not any(
            keyword.arg == "witness"
            or (
                keyword.arg is None
                and isinstance(keyword.value, ast.Call)
                and isinstance(keyword.value.func, ast.Name)
                and keyword.value.func.id in EVIDENCE_DOORS
            )
            for keyword in node.keywords
        ):
            missing.append(f"{path.relative_to(PACKAGE)}:{node.lineno}:{name}")
    assert missing == []


def test_every_named_runtime_effect_construction_uses_the_evidence_door() -> None:
    missing: list[str] = []
    for path, node in _runtime_effect_constructor_sites():
        assert isinstance(node.func, ast.Name)
        name = node.func.id
        evidence_doors = [
            keyword.value.func.id
            for keyword in node.keywords
            if (
                keyword.arg is None
                and isinstance(keyword.value, ast.Call)
                and isinstance(keyword.value.func, ast.Name)
                and keyword.value.func.id in EVIDENCE_DOORS
            )
        ]
        if len(evidence_doors) != 1 or any(
            keyword.arg in {"runtime_operand", "witness"} for keyword in node.keywords
        ):
            missing.append(f"{path.relative_to(PACKAGE)}:{node.lineno}:{name}")
    assert missing == []


def test_every_runtime_effect_constructor_wrong_twin_refutes() -> None:
    from sugar_lift_py_tests.effect import (
        runtime_effect_evidence,
        runtime_effect_evidence_from_terms,
    )
    from sugar_lift_py_tests.factory.factory_gap import FactoryPanic
    from sugar_lift_py_tests.factory.source_fragment import SourceFragment
    from sugar_lift_py_tests.ir import ctor, num

    site = SourceFragment.from_source("effect()", "wrong_twin.py")
    sites = list(_runtime_effect_constructor_sites())
    assert sites, "the total invariant must enumerate live constructor sites"
    for path, node in sites:
        door_names = [
            keyword.value.func.id
            for keyword in node.keywords
            if (
                keyword.arg is None
                and isinstance(keyword.value, ast.Call)
                and isinstance(keyword.value.func, ast.Name)
                and keyword.value.func.id in EVIDENCE_DOORS
            )
        ]
        assert (
            len(door_names) == 1
        ), f"{path.relative_to(PACKAGE)}:{node.lineno} bypasses the evidence door"
        try:
            if door_names[0] == "runtime_effect_evidence":
                runtime_effect_evidence("wrong_twin", 0, site)
            else:
                runtime_effect_evidence_from_terms(
                    ctor("wrong_twin", [num(0)]), 0, site
                )
        except FactoryPanic:
            continue
        raise AssertionError(
            f"{path.relative_to(PACKAGE)}:{node.lineno}: ground wrong twin "
            "minted RuntimeEffect evidence"
        )


def test_runtime_effect_witness_has_no_default() -> None:
    witness = inspect.signature(RuntimeEffect).parameters["witness"]
    assert witness.default is inspect.Parameter.empty


def test_runtime_effect_operand_has_no_default() -> None:
    operand = inspect.signature(RuntimeEffect).parameters["runtime_operand"]
    assert operand.default is inspect.Parameter.empty


def test_runtime_effect_witness_cannot_be_built_from_ground_gap_operands() -> None:
    from sugar_lift_py_tests.effect import RuntimeOperand, runtime_effect_witness
    from sugar_lift_py_tests.factory.source_fragment import SourceFragment
    from sugar_lift_py_tests.ir import ctor, num, str_const

    site = SourceFragment.from_source("x = 1", "x.py")
    for term in (
        num(0),
        str_const("no reduced floor semantics"),
        ctor("gap.description", [str_const("unrecognized AST shape")]),
    ):
        try:
            RuntimeOperand(term)  # type: ignore[call-arg]
        except TypeError as exc:
            assert "_seal" in str(exc)
        else:
            raise AssertionError(f"direct RuntimeOperand bypassed the door: {term!r}")
    for operand in (0, False, "no reduced floor semantics"):
        try:
            runtime_effect_witness("py.gap", operand, site)  # type: ignore[arg-type]
        except TypeError as exc:
            assert "genuine runtime-dependent operand" in str(exc)
        else:
            raise AssertionError(f"ground gap operand minted a witness: {operand!r}")


def test_no_runtime_effect_witness_helper_passes_a_string_locus_literal() -> None:
    """String loci are fabricated addresses — the door demands SourceFragment."""
    fabricated: list[str] = []
    for path in PACKAGE.rglob("*.py"):
        tree = ast.parse(path.read_text())
        for node in ast.walk(tree):
            if not isinstance(node, ast.Call):
                continue
            name = None
            if isinstance(node.func, ast.Name):
                name = node.func.id
            if name != "runtime_effect_witness":
                continue
            if len(node.args) < 3:
                continue
            site = node.args[2]
            if isinstance(site, ast.Constant) and isinstance(site.value, str):
                fabricated.append(
                    f"{path.relative_to(PACKAGE)}:{node.lineno}:string-locus"
                )
    assert fabricated == []
