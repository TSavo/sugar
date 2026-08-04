"""Permanent floor: construction never enters through the bare door.

``SourceFile.from_path`` builds a tree with no construction context. That is a
legitimate door -- demand scans, roll-call discharge and parse-only corpus emit
all use it correctly. Constructing through it does not fail; it LIES, because a
context-less tree paints every ``with`` ``RuntimeSelectedContextManager``
regardless of resolvability.

The law is proved on the incident it exists to prevent, not on a synthetic
stand-in: ``test_the_historical_probe_is_caught`` feeds the scanner the actual
shape of ``panic_probe.py``, the probe that reported eleven residual floor pairs
of which five were artifacts of this door.

Zero is MEASURED here, never inferred from a missing run -- the live scan runs
against the real packages, and a planted offender must still trip the same
scanner.
"""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path


from sugar_lift_py_tests.repo_root import sugar_lift_py_tests_package_root

_KIT = sugar_lift_py_tests_package_root()
_SCANNER_PATH = _KIT / "scripts" / "construction_context_door_law.py"
_SPEC = importlib.util.spec_from_file_location(
    "construction_context_door_law", _SCANNER_PATH
)
assert _SPEC is not None and _SPEC.loader is not None
_SCANNER = importlib.util.module_from_spec(_SPEC)
# Registered before execution: the scanner declares a frozen dataclass, and
# dataclasses resolve field types through sys.modules[cls.__module__].
sys.modules[_SPEC.name] = _SCANNER
_SPEC.loader.exec_module(_SCANNER)


def _offenders(source: str):
    return _SCANNER.offenders_in_source(source, path="<twin>")


# -- the law proved on the incident, not a synthetic --------------------------


def test_the_historical_probe_is_caught() -> None:
    """The guard proven on the artifact it exists to prevent.

    This is the shape of panic_probe.py as it was actually written and run:
    a bare door, then `.sugar()` over every function, then a DesugarAxis
    measurement. It produced five residual pairs that had to be withdrawn.
    """
    found = _offenders(_SCANNER.HISTORICAL_PROBE)

    assert len(found) == 1
    assert found[0].scope == "main"
    assert found[0].door_lines and found[0].construction_lines


def test_the_production_door_is_not_caught() -> None:
    """The replacement must be clean, or the law has no achievable green."""
    assert _offenders(_SCANNER.PRODUCTION_DOOR) == []


# -- both halves are required -------------------------------------------------


def test_the_bare_door_alone_is_clean() -> None:
    """A demand scan opens the door and never constructs. That is correct use."""
    assert _offenders(_SCANNER.DEMAND_SCAN_ONLY) == []


def test_construction_alone_is_clean() -> None:
    """Constructing over a file that came from elsewhere is not this law's business."""
    assert _offenders(_SCANNER.CONSTRUCTION_ONLY) == []


def test_the_two_halves_together_are_the_offence() -> None:
    """The discrimination: neither half alone, both together."""
    door = _offenders(_SCANNER.DEMAND_SCAN_ONLY)
    construction = _offenders(_SCANNER.CONSTRUCTION_ONLY)
    both = _offenders(_SCANNER.HISTORICAL_PROBE)

    assert door == [] and construction == []
    assert len(both) == 1


# -- granularity: the function, never the module ------------------------------


def test_a_nested_scope_does_not_blame_its_parent() -> None:
    """Module-level granularity would produce a false population.

    `lift_rpc` opens the bare door in a demand scan and in a roll-call
    discharge, and constructs in unrelated functions elsewhere. A law that
    named it would be allowlisted within a week, which is how a law dies.
    """
    assert _offenders(_SCANNER.NESTED_SCOPES) == []


def test_the_real_demand_scan_and_roll_call_stay_clean() -> None:
    """Pinned on the live module, not a paraphrase of it."""
    lift_rpc = (_KIT / "src" / "sugar_lift_py_tests" / "lift_rpc.py").read_text(
        encoding="utf-8"
    )

    assert "SourceFile.from_path" in lift_rpc, "fixture stale: the door moved"
    assert _SCANNER.offenders_in_source(lift_rpc, path="lift_rpc.py") == []


# -- zero is measured, and a planted offender still trips it ------------------


def test_live_packages_hold_at_zero() -> None:
    offenders, unreadable = _SCANNER.scan_roots([_KIT.parent])

    assert offenders == [], [o.to_json() for o in offenders]
    assert unreadable == []


def test_a_planted_offender_trips_the_live_scan(tmp_path: Path) -> None:
    """Zero measured over a tree that cannot fail proves nothing."""
    planted = tmp_path / "probe.py"
    planted.write_text(_SCANNER.HISTORICAL_PROBE, encoding="utf-8")

    offenders, unreadable = _SCANNER.scan_roots([tmp_path])

    assert len(offenders) == 1
    assert offenders[0].scope == "main"
    assert unreadable == []


def test_an_unparseable_file_is_reported_not_skipped(tmp_path: Path) -> None:
    """A file the scanner cannot read is never counted as clean."""
    (tmp_path / "broken.py").write_text("def (\n", encoding="utf-8")

    offenders, unreadable = _SCANNER.scan_roots([tmp_path])

    assert offenders == []
    assert len(unreadable) == 1
    assert "syntax" in unreadable[0]["reason"]


def test_the_scanner_self_test_and_cli_agree() -> None:
    assert _SCANNER.self_test() == 0
    assert _SCANNER.main(["--self-test"]) == 0
