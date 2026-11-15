from __future__ import annotations

import ast
from pathlib import Path


from sugar_lift_py_tests.repo_root import sugar_lift_py_tests_package_root

ROOT = sugar_lift_py_tests_package_root() / "src" / "sugar_lift_py_tests" / "floor"
WALL_CARRIERS = ("dict_value.py", "call_site_value.py", "symbolic_value.py")

# The constructor bundles of a RuntimeEffect (``effect.runtime_effect``): each
# returns the ``runtime_operand`` and the ``witness`` built from it, so a site
# that spreads one passes its witness explicitly.
EVIDENCE_BUNDLES = {"runtime_effect_evidence", "runtime_effect_evidence_from_terms"}


def _passes_a_witness(call: ast.Call) -> bool:
    """``witness=...`` spelled at the site, or the one evidence bundle spread
    into it (``**runtime_effect_evidence(...)``)."""
    for keyword in call.keywords:
        if keyword.arg == "witness":
            return True
        if (
            keyword.arg is None
            and isinstance(keyword.value, ast.Call)
            and isinstance(keyword.value.func, ast.Name)
            and keyword.value.func.id in EVIDENCE_BUNDLES
        ):
            return True
    return False


def _sites_without_a_witness(source: str, label: str) -> list[str]:
    missing: list[str] = []
    for node in ast.walk(ast.parse(source)):
        if not isinstance(node, ast.Call):
            continue
        name = node.func.id if isinstance(node.func, ast.Name) else ""
        if name.endswith("RuntimeEffect") and name != "RuntimeEffect":
            if not _passes_a_witness(node):
                missing.append(f"{label}:{node.lineno}:{name}")
    return missing


def test_wall_carrier_runtime_effects_all_pass_explicit_witnesses() -> None:
    missing: list[str] = []
    for filename in WALL_CARRIERS:
        path: Path = ROOT / filename
        missing.extend(
            _sites_without_a_witness(path.read_text(encoding="utf-8"), filename)
        )
    assert missing == []


def test_a_site_with_no_witness_is_named() -> None:
    """The lying twin: a site that passes neither is found, and a spread of
    anything but the evidence bundle is not taken for one."""
    lying = (
        "AppendRuntimeEffect('no witness')\n"
        "AppendRuntimeEffect('other spread', **fields)\n"
        "AppendRuntimeEffect('bundle', **runtime_effect_evidence('py.append', v, s))\n"
        "AppendRuntimeEffect('keyword', witness=w, runtime_operand=o)\n"
    )
    assert _sites_without_a_witness(lying, "lying.py") == [
        "lying.py:1:AppendRuntimeEffect",
        "lying.py:2:AppendRuntimeEffect",
    ]
