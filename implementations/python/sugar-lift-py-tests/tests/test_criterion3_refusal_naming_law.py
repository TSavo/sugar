"""Lying twins for CRITERION-3 REFUSAL NAMING auditor."""

from __future__ import annotations

import importlib.util
from pathlib import Path
import sys

_SCRIPT = (
    Path(__file__).parents[1] / "scripts" / "criterion3_refusal_naming_law.py"
)
_SPEC = importlib.util.spec_from_file_location("criterion3_refusal_naming_law", _SCRIPT)
assert _SPEC is not None and _SPEC.loader is not None
LAW = importlib.util.module_from_spec(_SPEC)
sys.modules[_SPEC.name] = LAW
_SPEC.loader.exec_module(LAW)


def _classes(source: str) -> set[str]:
    return {
        finding.violation_class
        for finding in LAW.scan_python_source(source, "planted.py")
    }


def test_nameless_undecidable_observed_is_recognized() -> None:
    assert _classes(
        """
from sugar_source_tree.panic import SugarNotWritten
def refuse(site):
    raise SugarNotWritten(
        blame=site,
        owner="plant",
        observed="undecidable mapping key equality",
        requested="source-decided key",
        fix="name the key type",
    )
"""
    ) == {"REFUSAL-NAMING-NOTHING"}

    assert _classes(
        """
from sugar_lift_py_tests.gap.panic import construction_panic_gap
def refuse(site):
    construction_panic_gap(
        owner="plant",
        blame=site,
        observed="undischarged store over runtime-selected receiver",
        requested="decided receiver",
        fix="name the receiver type",
    )
"""
    ) == {"REFUSAL-NAMING-NOTHING"}


def test_named_artifact_undecidable_is_silent() -> None:
    source = """
from sugar_source_tree.panic import SugarNotWritten
def refuse(self, index, site):
    raise SugarNotWritten(
        blame=site,
        owner="plant",
        observed=(
            "undecided receiver runtime type: "
            f"{type(self).__name__}[{type(index).__name__}]"
        ),
        requested="source-authenticated subscript",
        fix="carry type testimony",
    )

def refuse_field(site):
    raise SugarNotWritten(
        blame=site,
        owner="plant",
        observed=(
            "undecided binary compare without authenticated "
            "exception_type_coordinate"
        ),
        requested="ground TypeError or named refusal",
        fix="do not mint nameless RaiseEffect",
    )
"""
    assert LAW.scan_python_source(source, "clean.py") == []


def test_report_names_axes_and_open_second() -> None:
    findings = LAW.scan_python_source(
        """
raise SugarNotWritten(
    blame=s, owner="o",
    observed="undecidable",
    requested="r", fix="f",
)
""",
        "weak.py",
    )
    rendered = LAW.format_report(findings)
    assert "R_refusals_naming_nothing = 1" in rendered
    assert "R_refusals_over_decidable_source = OPEN" in rendered
    assert "rung=auditor" in rendered
    assert "retire_when=" in rendered
