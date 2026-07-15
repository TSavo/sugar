"""Pytest wrapper for the stringly node-kind census (Phase 0 instrument).

The campaign starts with R>0, so this is a RATCHET, not a zero gate: the
current offender multiset is pinned in stringly_kind_census.json. A NEW
stringly comparison against `.observed` / `operator_kind()` fails immediately
with the NodeKind/OperatorKind member to use instead; draining pinned debt
requires re-pinning via

    python -m sugar_lift_py_tests.audit_only.collect_stringly_kind_gaps --write-current

so R shrinks on the record. Retirement path: once R=0 and signatures are
pyright-typed (`observed -> NodeKind`), the census collapses to an empty pin
and stays as the regression tripwire.
"""

from __future__ import annotations

from sugar_lift_py_tests.audit_only import collect_stringly_kind_gaps as census


def test_stringly_kind_census_self_test() -> None:
    assert census.self_test() == 0


def test_stringly_kind_census_path_identity_is_host_independent() -> None:
    windows_path = r"src\sugar_lift_py_tests\factory\source_fragment.py"
    posix_path = "src/sugar_lift_py_tests/factory/source_fragment.py"
    canonical = census._canonical_identity_path(windows_path)

    assert canonical == posix_path
    assert census._stable_digest(canonical, 'site.observed == "Name"') == (
        census._stable_digest(posix_path, 'site.observed == "Name"')
    )


def test_stringly_kind_census_matches_pinned_multiset() -> None:
    assert census.DEFAULT_CENSUS.exists(), "missing pinned census; run --write-current"
    expected = census.load_expected(census.DEFAULT_CENSUS)
    observed = census.collect()
    assert census.compare(expected, observed) == 0, (
        "stringly node-kind census drifted from the pin; new offenders must use "
        "NodeKind/OperatorKind members, drained debt must be re-pinned with "
        "--write-current"
    )
