"""Floor: raw-AST exit-disposition side door is gone.

Construction admits NeverSuppresses only via authenticated
``ContextManagerContractRefV1`` (prebound contract-ref table). Re-parsing
foreign modules with ``ast.walk`` / ``parsed_tree`` to invent
``NeverSuppresses`` from foreign ``__exit__`` is poison — not a construction
authority.

This module pins the side door's absence. Behavioral honest-loud residuals
(``RuntimeSelectedContextManager`` / ``ContextManagerResolutionConstructionGap``)
for unauthenticated managers live under sugar-source-tree
(``test_with_resource_disposition`` / ``test_with_authenticated_contract_ref``).
"""

from __future__ import annotations

import importlib.util
from pathlib import Path


PYTHON_ROOT = Path(__file__).resolve().parents[2]
PROOF_MODULE = (
    PYTHON_ROOT
    / "sugar-lift-py-tests"
    / "src"
    / "sugar_lift_py_tests"
    / "exit_disposition_proof.py"
)
MEASURE_SCRIPT = (
    PYTHON_ROOT
    / "sugar-lift-py-tests"
    / "scripts"
    / "measure_exit_disposition_delta.py"
)
WITH_NODES = (
    PYTHON_ROOT
    / "sugar-source-tree"
    / "src"
    / "sugar_source_tree"
    / "nodes.py"
)
PRODUCTION_ROOTS = (
    PYTHON_ROOT / "sugar-lift-py-tests" / "src" / "sugar_lift_py_tests",
    PYTHON_ROOT / "sugar-source-tree" / "src" / "sugar_source_tree",
)

# Tokens that reconstitute the raw-AST manager→NeverSuppresses side door.
_FORBIDDEN_SIDE_DOOR_TOKENS = (
    "prove_exit_disposition_from_manager_expr",
    "resolve_definition_memento_from_manager_expr",
    "ExitDispositionProof",
    "prove_never_suppresses_for_class",
    "prove_exit_function_ast",
    "prove_from_definition_memento",
    "ExitDispositionUnproven",
    "DefinitionMemento",
)


def test_exit_disposition_proof_module_is_gone():
    """R_exit_disposition_raw_ast_module: module file must not exist."""
    assert not PROOF_MODULE.exists(), (
        f"raw-AST exit disposition side door still present: {PROOF_MODULE}. "
        "NeverSuppresses admission is only via authenticated ContextManagerContractRefV1."
    )
    assert (
        importlib.util.find_spec("sugar_lift_py_tests.exit_disposition_proof") is None
    ), "package still exports sugar_lift_py_tests.exit_disposition_proof"


def test_exit_disposition_measure_script_is_gone():
    """R_exit_disposition_raw_ast_measure: census script over the side door is gone."""
    assert not MEASURE_SCRIPT.exists(), (
        f"exit-disposition measure script still present: {MEASURE_SCRIPT}. "
        "It counted NeverSuppresses greened by re-parsing foreign __exit__."
    )


def test_with_construct_sugar_does_not_call_raw_ast_exit_proof():
    """With construction path must not mention the deleted side-door APIs."""
    text = WITH_NODES.read_text(encoding="utf-8")
    start = text.find("class With(Statement):")
    assert start != -1, "With statement class missing from nodes.py"
    end = text.find("\nclass AsyncWith", start)
    with_body = text[start:end] if end != -1 else text[start:]
    hits = [tok for tok in _FORBIDDEN_SIDE_DOOR_TOKENS if tok in with_body]
    assert hits == [], (
        "With construction reintroduced raw-AST exit disposition tokens: "
        f"{hits}"
    )
    assert "exit_disposition_proof" not in with_body
    # No fresh raw-AST greening authority under another name in With.
    assert "import ast" not in with_body
    assert "parsed_tree" not in with_body
    assert "ast.walk" not in with_body


def test_production_roots_have_zero_exit_disposition_side_door_imports():
    """R_exit_disposition_raw_ast_imports: no production import of the side door."""
    offenders: list[str] = []
    for root in PRODUCTION_ROOTS:
        for path in sorted(root.rglob("*.py")):
            text = path.read_text(encoding="utf-8")
            if "exit_disposition_proof" in text or any(
                tok in text for tok in _FORBIDDEN_SIDE_DOOR_TOKENS
            ):
                offenders.append(str(path.relative_to(PYTHON_ROOT)))
    assert offenders == [], (
        "production still references raw-AST exit disposition side door:\n"
        + "\n".join(offenders)
    )


def test_with_only_admits_never_suppresses_via_authenticated_disposition_type():
    """NeverSuppresses on the With arm is the authenticated disposition type only.

    Replacement architecture: ``ContextManagerContractRefV1`` +
    ``NeverSuppressesDispositionV1`` from the prebound table. No manager-expr
    reparse, no foreign ``__exit__`` return walk.
    """
    text = WITH_NODES.read_text(encoding="utf-8")
    start = text.find("class With(Statement):")
    end = text.find("\nclass AsyncWith", start)
    with_body = text[start:end] if end != -1 else text[start:]
    assert "NeverSuppressesDispositionV1" in with_body
    assert "ContextManagerContractRefV1" in with_body
    assert "RuntimeSelectedContextManager" in with_body
    # Greening authority is the injected table, not a source proof helper.
    assert "_require_narrow_cm_ref" in with_body
    assert "prove_exit" not in with_body
    assert "DefinitionMemento" not in with_body
