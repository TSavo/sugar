# SPDX-License-Identifier: MIT OR Apache-2.0
"""Final residual: try/except bare-return tail + nested freeze_time exc_info."""

from __future__ import annotations

from collections import Counter
from pathlib import Path

from sugar_lift_py_tests.idd.lift_coverage_accounting import account_lift_coverage
from sugar_lift_py_tests.idd.lift_coverage_census import census_source
from sugar_lift_py_tests.lift_rpc import lift_file_payload


def test_try_except_bare_return_then_assert_lifts() -> None:
    src = """
def test_skip_keys(s):
    try:
        s.dumps(None, skipkeys=True)
    except TypeError:
        return
    assert s.loads(s.dumps({(): 1})) == {}
"""
    rpc = lift_file_payload(src, "skip.py").to_rpc()
    ax = account_lift_coverage(census_source(src, file="skip.py"), rpc).to_json()[
        "assertions"
    ]
    assert ax["silently_unaccounted"] == 0
    assert ax["lifted_cited"] == 1
    assert ax["refused_loud"] == 0
    assert any("assertion" in str(r.get("name")) for r in (rpc.get("ir") or []))


def test_exc_info_survives_outer_freeze_time_with() -> None:
    src = """
def test_future_age(signer):
    signed = signer.sign("value")
    with freeze_time("1971-05-31"):
        with pytest.raises(SignatureExpired) as exc_info:
            signer.unsign(signed, max_age=10)
    assert isinstance(exc_info.value.date_signed, datetime)
"""
    rpc = lift_file_payload(src, "freeze.py").to_rpc()
    ax = account_lift_coverage(census_source(src, file="freeze.py"), rpc).to_json()[
        "assertions"
    ]
    assert ax["silently_unaccounted"] == 0
    assert ax["lifted_cited"] >= 1
    assert ax["refused_loud"] == 0


def test_itsdangerous_sdist_full_lift() -> None:
    root = Path(
        "/opt/data/tmp/sugar-sources-cache/itsdangerous/2.2.0/src/tests/"
        "test_itsdangerous"
    )
    if not root.is_dir():
        return
    totals = Counter()
    for f in sorted(root.glob("test_*.py")):
        src = f.read_text(encoding="utf-8")
        rpc = lift_file_payload(src, str(f)).to_rpc()
        ax = account_lift_coverage(census_source(src, file=str(f)), rpc).to_json()[
            "assertions"
        ]
        for k in ("stated", "lifted_cited", "refused_loud", "silently_unaccounted"):
            totals[k] += ax.get(k, 0)
    assert totals["silently_unaccounted"] == 0
    assert totals["refused_loud"] == 0
    assert totals["lifted_cited"] == totals["stated"] == 57
