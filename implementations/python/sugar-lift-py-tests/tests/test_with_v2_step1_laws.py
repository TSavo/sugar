"""RED migration instruments for With Authority v2 (#6088, step 1)."""
from pathlib import Path
import ast
import pytest

ROOT = Path(__file__).parents[1] / "src" / "sugar_lift_py_tests"
AUTH = ROOT / "with_manager_authority.py"

def _files():
    return tuple(ROOT.rglob("*.py"))

def _authority_door_names(text: str):
    tree = ast.parse(text)
    found = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.ClassDef) and ("Authority" in node.name or "Membrane" in node.name):
            found.add(node.name)
        if isinstance(node, ast.AnnAssign) and isinstance(node.target, ast.Name):
            if "Authority" in ast.unparse(node.annotation):
                found.add(ast.unparse(node.annotation))
    return found

def _consumer_manifest_refs():
    needles = ("default_community_manifest", "row_for_spelling", "community_context_managers.json", "manager-spelling-table")
    return [(p, needle) for p in _files() for needle in needles if needle in p.read_text(encoding="utf-8")]

@pytest.mark.xfail(strict=True, reason="With v2 migration debt: secondary authority remains")
def test_single_authority_law_is_red_and_has_a_renamed_door_planted_twin():
    assert _authority_door_names(AUTH.read_text(encoding="utf-8")) <= {"ResolvedContextManager", "WithManagerAuthoritiesV1"}
    planted = "class RenamedMembraneAuthority: pass\nDoor = RenamedMembraneAuthority\n"
    assert _authority_door_names(planted) - {"ResolvedContextManager", "WithManagerAuthoritiesV1"}

@pytest.mark.xfail(strict=True, reason="With v2 migration debt: consumer manifest enrollment remains")
def test_no_consumer_enrollment_law_is_red_and_detects_renamed_manifest_provenance():
    assert not _consumer_manifest_refs()
    planted = "def bind():\n    renamed_manifest = default_community_manifest()\n    return renamed_manifest.row_for_spelling('x')\n"
    assert any(name in planted for name in ("default_community_manifest", "row_for_spelling"))
