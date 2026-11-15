from __future__ import annotations

import ast
from pathlib import Path


from sugar_lift_py_tests.repo_root import sugar_lift_py_tests_package_root

ROOT = sugar_lift_py_tests_package_root() / "src" / "sugar_lift_py_tests"


# The one lawful constructor bundle for a RuntimeEffect: each returns the
# ``runtime_operand`` and its ``witness`` together.
_EVIDENCE_BUNDLES = frozenset(
    {"runtime_effect_evidence", "runtime_effect_evidence_from_terms"}
)


def _carries_witness(call: ast.Call) -> bool:
    """The call states its witness: by name, or by spreading the evidence
    bundle that builds it (``**runtime_effect_evidence(...)``). Any other
    ``**`` spread states nothing this check can read."""
    for keyword in call.keywords:
        if keyword.arg == "witness":
            return True
        if (
            keyword.arg is None
            and isinstance(keyword.value, ast.Call)
            and isinstance(keyword.value.func, ast.Name)
            and keyword.value.func.id in _EVIDENCE_BUNDLES
        ):
            return True
    return False


def test_datetime_dig_conditional_effects_have_explicit_witnesses() -> None:
    missing = []
    for relative in (
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
                    if not _carries_witness(node):
                        missing.append(f"{relative}:{node.lineno}:{node.func.id}")
    assert missing == []
