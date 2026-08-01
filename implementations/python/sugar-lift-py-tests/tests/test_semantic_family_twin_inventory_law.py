"""Twins for the semantic-family twin inventory instrument (criterion 5).

Measurement only: does not drain missing twins. Proves the auditor teeth.
"""

from __future__ import annotations

import ast
import importlib.util
from pathlib import Path
import sys

_SCRIPT = (
    Path(__file__).resolve().parents[1]
    / "scripts"
    / "semantic_family_twin_inventory_law.py"
)
_SPEC = importlib.util.spec_from_file_location(
    "semantic_family_twin_inventory_law", _SCRIPT
)
assert _SPEC is not None and _SPEC.loader is not None
LAW = importlib.util.module_from_spec(_SPEC)
sys.modules[_SPEC.name] = LAW
_SPEC.loader.exec_module(LAW)


def test_planted_truthful_only_family_is_red() -> None:
    """Lying twin of the instrument: a family with only a truthful face is red."""
    source = '''
class OnlyTruthfulSugar:
    @classmethod
    def witnesses(cls):
        return WitnessSource(source="assert True", expected="sat")
'''
    tree = ast.parse(source)
    class_node = tree.body[0]
    witnesses = LAW._method(class_node, "witnesses")
    has_t, has_l, opt = LAW._classify_witnesses_method(witnesses)
    status = LAW._status(has_t, has_l, opt)
    assert status == "truthful_only" or (
        has_t and not has_l and not opt
    ), (status, has_t, has_l, opt)
    assert LAW._status(True, False, False) == "truthful_only"
    assert LAW.FamilyTwinStatus(
        catalog="sugar",
        family="OnlyTruthfulSugar",
        path="planted.py",
        line=1,
        has_truthful=True,
        has_lying=False,
        status="truthful_only",
        plant="plant lying",
    ).missing_lying


def test_planted_both_faces_is_green_for_that_family() -> None:
    """Truthful twin of the classifier: pair constructors count as both faces."""
    source = '''
class BothFacesSugar:
    @classmethod
    def witnesses(cls):
        return _call_pair(
            name="x",
            owner_sugar="BothFacesSugar",
            truthful="def test_a():\\n    assert A(1)==1\\n",
            lying="def test_a():\\n    assert A(1)==2\\n",
        )
'''
    tree = ast.parse(source)
    class_node = tree.body[0]
    witnesses = LAW._method(class_node, "witnesses")
    has_t, has_l, opt = LAW._classify_witnesses_method(witnesses)
    assert (has_t, has_l, opt) == (True, True, False)
    assert LAW._status(has_t, has_l, opt) == "both"


def test_live_catalog_enumerates_from_source_not_hand_list() -> None:
    """Enrollment is existence: inventory walks sugar/ + ProofIR registry."""
    sugar_root = (
        Path(__file__).resolve().parents[1]
        / "src"
        / "sugar_lift_py_tests"
        / "sugar"
    )
    proofir_root = (
        Path(__file__).resolve().parents[1]
        / "src"
        / "sugar_lift_py_tests"
        / "proofir"
        / "nodes"
    )
    rows = LAW.inventory(sugar_root=sugar_root, proofir_nodes_root=proofir_root)
    assert rows, "live catalog must be non-empty"
    sugar_names = {r.family for r in rows if r.catalog == "sugar"}
    # Live enrollment: IntLiteralSugar is a catalog family with both faces.
    assert "IntLiteralSugar" in sugar_names
    int_lit = next(r for r in rows if r.family == "IntLiteralSugar")
    assert int_lit.status == "both"
    # ProofIR registry is live, not hand-listed in this test file.
    proofir = [r for r in rows if r.catalog == "proofir"]
    assert proofir
    assert all(r.status == "both" for r in proofir), proofir


def test_report_names_r_axis_and_plant_recipe() -> None:
    planted = [
        LAW.FamilyTwinStatus(
            catalog="sugar",
            family="MissingLyingSugar",
            path="sugar/missing.py",
            line=3,
            has_truthful=True,
            has_lying=False,
            status="truthful_only",
            plant="plant a LYING twin",
        )
    ]
    rendered = LAW.format_report(planted)
    assert "R_families_without_lying_twin = 1" in rendered
    assert "MissingLyingSugar" in rendered
    assert "plant a LYING twin" in rendered
