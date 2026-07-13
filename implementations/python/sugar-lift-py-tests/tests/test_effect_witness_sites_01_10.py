from __future__ import annotations

import ast
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1] / "src" / "sugar_lift_py_tests" / "floor"


def test_first_ten_effect_sites_have_explicit_witnesses() -> None:
    missing = []
    for name in ("array_literal.py", "list_value.py", "none_value.py"):
        for node in ast.walk(ast.parse((ROOT / name).read_text())):
            if isinstance(node, ast.Call) and isinstance(node.func, ast.Name):
                if (
                    node.func.id.endswith("RuntimeEffect")
                    and node.func.id != "RuntimeEffect"
                ):
                    if not any(kw.arg == "witness" for kw in node.keywords):
                        missing.append(f"{name}:{node.lineno}")
    assert missing == []
