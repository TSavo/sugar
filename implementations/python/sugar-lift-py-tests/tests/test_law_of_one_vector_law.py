"""Model A parent: cites children only — never a second recognition walk."""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path


from sugar_lift_py_tests.repo_root import resolve_repo_root, sugar_lift_py_tests_package_root

_SCRIPT = sugar_lift_py_tests_package_root() / "scripts" / "law_of_one_vector_law.py"
_SPEC = importlib.util.spec_from_file_location("law_of_one_vector_law", _SCRIPT)
assert _SPEC is not None and _SPEC.loader is not None
LAW = importlib.util.module_from_spec(_SPEC)
sys.modules[_SPEC.name] = LAW
_SPEC.loader.exec_module(LAW)


def test_parent_has_no_scan_python_source_reimplementation() -> None:
    """Lying twin of dual production: parent must not own an AST offender walk."""
    src = Path(LAW.__file__).read_text(encoding="utf-8") if LAW.__file__ else ""
    # Model A forbids a parent re-scan API for MatchDecided/spelling/swallow classes
    assert "def scan_python_source" not in src
    assert "MatchDecided(False) outside" not in src
    assert "FABRICATED-MEANING" not in src or "Model A" in src
    assert "cite only" in src.lower() or "Model A" in src


def test_report_separates_product_and_instrument_layers() -> None:
    repo = resolve_repo_root()
    citations = LAW.collect_citations(repo)
    rendered = LAW.format_report(citations)
    assert "R_product_second_mechanism_cited" in rendered
    assert "R_instrument_self_sealing_cited" in rendered
    assert "Model A" in rendered
    assert "climb:" in rendered
    assert "membrane:" in rendered
    # enrollment: every collector produces a citation row
    assert len(citations) == len(LAW.COLLECTORS)


def test_missing_owner_is_red_not_zero() -> None:
    """Enrollment is existence: a missing child cannot report R=0."""
    from dataclasses import replace

    # Simulate by calling collector against empty temp "repo"
    import tempfile

    with tempfile.TemporaryDirectory() as tmp:
        c = LAW._cite_self_sealing(Path(tmp))
    assert c.status == "missing_owner"
    assert c.R == -1


def test_self_sealing_citation_uses_child_r_only() -> None:
    repo = resolve_repo_root()
    c = LAW._cite_self_sealing(repo)
    assert c.status == "ok"
    assert c.axis == "self_sealing"
    assert "self_sealing_instrument_law" in c.owner
    # R is non-negative integer produced by child
    assert isinstance(c.R, int) and c.R >= 0
