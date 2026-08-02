"""Discrimination + stable-zero for construction→consumer codomain law.

Enrollment: tools/run_static_sole_construction_floors.sh
  R_construction_consumer_codomain discrimination + R=0.

ZERO IS BANKABLE EVIDENCE, NOT ABSENCE OF AN INSTRUMENT — but only under this
instrument's static reach. Do not read green as \"class closed forever\".
"""

from __future__ import annotations

import importlib.util
from pathlib import Path

_KIT = Path(__file__).resolve().parents[1]
_SCANNER_PATH = _KIT / "scripts" / "construction_consumer_codomain_law.py"
_SPEC = importlib.util.spec_from_file_location(
    "construction_consumer_codomain_law", _SCANNER_PATH
)
assert _SPEC is not None and _SPEC.loader is not None
_SCANNER = importlib.util.module_from_spec(_SPEC)
_SPEC.loader.exec_module(_SCANNER)


def test_discrimination_self_test_is_green() -> None:
    assert _SCANNER.discrimination_self_test() is True
    assert _SCANNER.main(["--self-test"]) == 0


def test_live_roots_are_stable_zero() -> None:
    """Tip production surface must stay at R=0 or CI reds on the fifth lie."""
    script = Path(_SCANNER_PATH).resolve()
    repo = script.parents[4]
    roots = [repo / p for p in _SCANNER._DEFAULT_PACKAGES]
    gaps, summary = _SCANNER.run(roots, repo)
    assert summary["R_total"] == 0, (
        f"R_total={summary['R_total']} gaps="
        f"{[g.to_dict() for g in gaps[:5]]}"
    )
    # Exit-code contract (same as CI axis) without re-printing the full report.
    assert (1 if gaps else 0) == 0
