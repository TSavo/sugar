from __future__ import annotations

import ast
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1] / "src" / "sugar_lift_py_tests" / "floor"
WALL_CARRIERS = ("dict_value.py", "call_site_value.py", "symbolic_value.py")


def test_wall_carrier_runtime_effects_all_pass_explicit_witnesses() -> None:
    missing: list[str] = []
    for filename in WALL_CARRIERS:
        path = ROOT / filename
        for node in ast.walk(ast.parse(path.read_text(encoding="utf-8"))):
            if not isinstance(node, ast.Call):
                continue
            name = node.func.id if isinstance(node.func, ast.Name) else ""
            if name.endswith("RuntimeEffect") and name != "RuntimeEffect":
                if not any(keyword.arg == "witness" for keyword in node.keywords):
                    missing.append(f"{filename}:{node.lineno}:{name}")
    assert missing == []
