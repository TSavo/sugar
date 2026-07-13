from __future__ import annotations

import ast
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1] / "src" / "sugar_lift_py_tests"


def test_datetime_dig_conditional_effects_have_explicit_witnesses() -> None:
    missing = []
    for relative in (
        "sugar/install_source_dig.py",
        "floor/guarded_value.py",
        "floor/predicate_value.py",
        "sugar/if_exp_sugar.py",
    ):
        for node in ast.walk(ast.parse((ROOT / relative).read_text())):
            if isinstance(node, ast.Call) and isinstance(node.func, ast.Name):
                if (
                    node.func.id.endswith("RuntimeEffect")
                    and node.func.id != "RuntimeEffect"
                ):
                    if not any(keyword.arg == "witness" for keyword in node.keywords):
                        missing.append(f"{relative}:{node.lineno}:{node.func.id}")
    assert missing == []
