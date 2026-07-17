"""#4013: structured FactoryPanic front ranking for isolation + fatal recensus."""

from __future__ import annotations

from sugar_lift_py_tests.factory.factory_gap_info import (
    FactoryGapInfo,
    GapKind,
    GapLocus,
)
from sugar_lift_py_tests.idd.factory_panic_fronts import (
    FINGERPRINT_FIELDS,
    fingerprint_from_gap,
    fingerprint_from_panic_info,
    fingerprint_label,
    rank_factory_panic_fronts,
)


def test_fingerprint_from_typed_gap_info_matches_json() -> None:
    info = FactoryGapInfo(
        owner="TemporalContext",
        blame="x.py:1:1",
        observed="result",
        requested="value",
        fix="bind result on every continuing path",
        gap_kind=GapKind.FLOOR,
        gap_locus=GapLocus.CONSTRUCTION,
    )
    expected = (
        "TemporalContext",
        "Floor",
        "Construction",
        "result",
        "value",
    )
    assert fingerprint_from_panic_info(info) == expected
    assert fingerprint_from_gap(info.to_json()) == expected
    assert fingerprint_label(expected) == (
        "TemporalContext / Floor / Construction / result / value"
    )
    assert FINGERPRINT_FIELDS == (
        "owner",
        "gap_kind",
        "gap_locus",
        "observed",
        "requested",
    )


def test_rank_factory_panic_fronts_orders_owner_families_and_exact_fronts() -> None:
    rows = [
        {
            "file": "numpy/a.py",
            "owner": "TemporalContext",
            "gap": {
                "owner": "TemporalContext",
                "gap_kind": "Floor",
                "gap_locus": "Construction",
                "observed": "result",
                "requested": "value",
            },
        },
        {
            "file": "numpy/b.py",
            "owner": "TemporalContext",
            "gap": {
                "owner": "TemporalContext",
                "gap_kind": "Floor",
                "gap_locus": "Construction",
                "observed": "lib",
                "requested": "value",
            },
        },
        {
            "file": "numpy/c.py",
            "owner": "TemporalContext",
            "gap": {
                "owner": "TemporalContext",
                "gap_kind": "Floor",
                "gap_locus": "Construction",
                "observed": "result",
                "requested": "value",
            },
        },
        {
            "file": "numpy/d.py",
            "owner": "WithSugar",
            "gap": {
                "owner": "WithSugar",
                "gap_kind": "Floor",
                "gap_locus": "Construction",
                "observed": "raise-carrying callsite with-body",
                "requested": "dig manager().__exit__ exception suppression contract",
            },
        },
    ]
    ranking = rank_factory_panic_fronts(rows)

    assert ranking["R_live_factory_panic_files"] == 4
    assert ranking["owner_family_count"] == 2
    assert ranking["exact_front_count"] == 3
    assert ranking["owners"] == {"TemporalContext": 3, "WithSugar": 1}

    families = ranking["owner_families"]
    assert families[0]["owner"] == "TemporalContext"
    assert families[0]["count"] == 3
    assert families[0]["representative_files"][:2] == ["numpy/a.py", "numpy/b.py"]
    assert families[1]["owner"] == "WithSugar"
    assert families[1]["count"] == 1

    fronts = ranking["exact_fronts"]
    assert fronts[0]["count"] == 2
    assert fronts[0]["owner"] == "TemporalContext"
    assert fronts[0]["observed"] == "result"
    assert fronts[0]["label"] == (
        "TemporalContext / Floor / Construction / result / value"
    )
    assert fronts[0]["representative_files"] == ["numpy/a.py", "numpy/c.py"]
    assert sum(row["count"] for row in fronts) == 4
    assert sum(row["count"] for row in families) == 4


def test_rank_accepts_fingerprint_tuples_for_isolation_rows() -> None:
    rows = [
        {
            "file": "f.py",
            "owner": "ForSugar.static_unfold",
            "fingerprint": (
                "ForSugar.static_unfold",
                "Floor",
                "Construction",
                "statically finite iterable with 2000 elements",
                "at most 1024 concrete loop self-applications",
            ),
        }
    ]
    ranking = rank_factory_panic_fronts(rows)
    assert ranking["R_live_factory_panic_files"] == 1
    assert ranking["exact_fronts"][0]["owner"] == "ForSugar.static_unfold"
    assert "2000" in ranking["exact_fronts"][0]["observed"]


def test_empty_ranking_is_stable_zero() -> None:
    ranking = rank_factory_panic_fronts([])
    assert ranking["R_live_factory_panic_files"] == 0
    assert ranking["owner_families"] == []
    assert ranking["exact_fronts"] == []
    assert ranking["owners"] == {}
