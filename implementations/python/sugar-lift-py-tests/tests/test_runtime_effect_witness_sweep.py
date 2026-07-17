from __future__ import annotations

import ast
import inspect
from pathlib import Path

from sugar_lift_py_tests.effect import RuntimeEffect

PACKAGE = Path(__file__).resolve().parents[1] / "src" / "sugar_lift_py_tests"


def test_every_named_runtime_effect_construction_passes_a_witness() -> None:
    missing: list[str] = []
    for path in PACKAGE.rglob("*.py"):
        for node in ast.walk(ast.parse(path.read_text())):
            if not isinstance(node, ast.Call) or not isinstance(node.func, ast.Name):
                continue
            name = node.func.id
            if (
                name.endswith("RuntimeEffect")
                and name not in {"RuntimeEffect", "RuntimeEffectWitness"}
                and not any(keyword.arg == "witness" for keyword in node.keywords)
            ):
                missing.append(f"{path.relative_to(PACKAGE)}:{node.lineno}:{name}")
    assert missing == []


def test_every_named_runtime_effect_construction_names_its_runtime_operand() -> None:
    missing: list[str] = []
    for path in PACKAGE.rglob("*.py"):
        for node in ast.walk(ast.parse(path.read_text())):
            if not isinstance(node, ast.Call) or not isinstance(node.func, ast.Name):
                continue
            name = node.func.id
            if (
                name.endswith("RuntimeEffect")
                and name not in {"RuntimeEffect", "RuntimeEffectWitness"}
                and not any(
                    keyword.arg == "runtime_operand" for keyword in node.keywords
                )
            ):
                missing.append(f"{path.relative_to(PACKAGE)}:{node.lineno}:{name}")
    assert missing == []


def test_runtime_effect_witness_has_no_default() -> None:
    witness = inspect.signature(RuntimeEffect).parameters["witness"]
    assert witness.default is inspect.Parameter.empty


def test_runtime_effect_witness_cannot_be_built_from_ground_gap_operands() -> None:
    from sugar_lift_py_tests.effect import runtime_effect_witness
    from sugar_lift_py_tests.factory.source_fragment import SourceFragment

    site = SourceFragment.from_source("x = 1", "x.py")
    for operand in (0, False, "no reduced floor semantics"):
        try:
            runtime_effect_witness("py.gap", operand, site)
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
