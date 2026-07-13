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


def test_runtime_effect_witness_has_no_default() -> None:
    witness = inspect.signature(RuntimeEffect).parameters["witness"]
    assert witness.default is inspect.Parameter.empty
