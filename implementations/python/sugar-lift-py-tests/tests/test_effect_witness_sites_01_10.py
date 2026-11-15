from __future__ import annotations

import ast
from pathlib import Path


from sugar_lift_py_tests.repo_root import sugar_lift_py_tests_package_root

ROOT = sugar_lift_py_tests_package_root() / "src" / "sugar_lift_py_tests" / "floor"

# The one lawful constructor bundle for a RuntimeEffect: it builds the operand
# and the witness bound to it together (``effect/runtime_effect.py``).
EVIDENCE_DOORS = {"runtime_effect_evidence", "runtime_effect_evidence_from_terms"}


def _states_its_witness(call: ast.Call) -> bool:
    """The effect is built with a witness in the source: ``witness=...``
    spelled out, or the evidence bundle spread (``**runtime_effect_evidence(
    ...)``), which carries the witness and nothing else can fill."""
    for keyword in call.keywords:
        if keyword.arg == "witness":
            return True
        if (
            keyword.arg is None
            and isinstance(keyword.value, ast.Call)
            and isinstance(keyword.value.func, ast.Name)
            and keyword.value.func.id in EVIDENCE_DOORS
        ):
            return True
    return False


def _missing(source: str, name: str) -> list[str]:
    missing = []
    for node in ast.walk(ast.parse(source)):
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Name):
            if (
                node.func.id.endswith("RuntimeEffect")
                and node.func.id != "RuntimeEffect"
            ):
                if not _states_its_witness(node):
                    missing.append(f"{name}:{node.lineno}")
    return missing


def test_first_ten_effect_sites_have_explicit_witnesses() -> None:
    missing = []
    for name in ("list_value.py", "none_value.py"):
        missing.extend(_missing((ROOT / name).read_text(), name))
    assert missing == []


def test_the_recognizer_catches_an_effect_built_without_a_witness() -> None:
    """Lying twin: an effect with no witness, or one spreading something that
    is not the evidence bundle, is named."""
    bare = "SubscriptStoreRuntimeEffect('reason', runtime_operand=operand)\n"
    assert _missing(bare, "bare.py") == ["bare.py:1"]
    other_spread = "SubscriptStoreRuntimeEffect('reason', **fields(operand))\n"
    assert _missing(other_spread, "spread.py") == ["spread.py:1"]
    explicit = "SubscriptStoreRuntimeEffect('reason', operand, witness=w)\n"
    assert _missing(explicit, "explicit.py") == []
    bundle = (
        "SubscriptStoreRuntimeEffect('reason', "
        "**runtime_effect_evidence('py.setitem', index, site))\n"
    )
    assert _missing(bundle, "bundle.py") == []
