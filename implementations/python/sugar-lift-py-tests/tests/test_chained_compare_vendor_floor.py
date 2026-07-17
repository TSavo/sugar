from __future__ import annotations

from pathlib import Path

import pytest

from factory_reduce import reduce_value

from sugar_lift_py_tests.floor import PredicateValue
from sugar_lift_py_tests.idd.lift_coverage_accounting import account_lift_coverage
from sugar_lift_py_tests.idd.lift_coverage_census import census_source
from sugar_lift_py_tests.lift_rpc import audit_lift_file

VENDOR = Path(__file__).parent / "vendor"
REQUESTS_INIT = VENDOR / "requests-2.34.2" / "requests" / "__init__.py"

# SHA-pinned datetime claim lines for chained-compare and abs families (#4190).
# Issue prose named pre-pin line numbers; the pin maps them to these loci.
DATETIME_CHAIN_LINES = {67, 75, 81, 83, 160}
DATETIME_ABS_LINES = {690, 692, 700, 705, 712, 716, 734, 735}
REQUESTS_CHAIN_LINES = {85, 90}


def _axis(source: str, file: str) -> dict:
    payload, gaps = audit_lift_file(source, file)
    assert gaps == []
    rpc = payload.to_rpc()
    return account_lift_coverage(census_source(source, file=file), rpc).to_json()[
        "assertions"
    ]


def test_datetime_53_scalar_chain_with_assert_message_lifts_and_cites() -> None:
    source = "\n" * 50 + (
        "def _days_in_month(year, month):\n"
        '    "year, month -> number of days in that month in that year."\n'
        "    assert 1 <= month <= 12, month\n"
        "    return 31\n"
    )
    axis = _axis(source, "/tmp/cpython-3.11-datetime.py")

    assert axis["lifted_cited"] == 1
    assert axis["refused_loud"] == 0
    assert axis["silently_unaccounted"] == 0
    assert axis["lifted_loci"][0]["line"] == 53


def test_datetime_144_chain_with_call_bound_lifts_and_cites() -> None:
    source = "\n" * 142 + (
        "def _ord_to_ymd(year, month, n):\n"
        "    assert 0 <= n < _days_in_month(year, month)\n"
        "    return n\n"
    )
    axis = _axis(source, "/tmp/cpython-3.11-datetime.py")

    assert axis["lifted_cited"] == 1
    assert axis["refused_loud"] == 0
    assert axis["silently_unaccounted"] == 0
    assert axis["lifted_loci"][0]["line"] == 144


def test_requests_85_tuple_lexicographic_chain_lifts_and_cites() -> None:
    source = "\n" * 82 + (
        "def check_compatibility(major, minor, patch):\n"
        "    # chardet_version >= 3.0.2, < 8.0.0\n"
        "    assert (3, 0, 2) <= (major, minor, patch) < (8, 0, 0)\n"
        "    return 1\n"
    )
    axis = _axis(source, "requests/__init__.py")

    assert axis["lifted_cited"] == 1
    assert axis["refused_loud"] == 0
    assert axis["silently_unaccounted"] == 0
    assert axis["lifted_loci"][0]["line"] == 85


@pytest.mark.parametrize(
    ("file", "line", "signature", "assertion"),
    [
        (
            "/tmp/cpython-3.11-datetime.py",
            60,
            "def _days_before_month(year, month):",
            "assert 1 <= month <= 12, 'month must be in 1..12'",
        ),
        (
            "/tmp/cpython-3.11-datetime.py",
            65,
            "def _days_in_year(year, month):",
            "assert 1 <= month <= 12, 'month must be in 1..12'",
        ),
        (
            "/tmp/cpython-3.11-datetime.py",
            67,
            "def _check_date_fields(year, month, day, dim):",
            "assert 1 <= day <= dim, ('day must be in 1..%d' % dim)",
        ),
        (
            "requests/__init__.py",
            90,
            "def check_compatibility(major, minor, patch):",
            "assert (2, 0, 0) <= (major, minor, patch) < (4, 0, 0)",
        ),
    ],
)
def test_remaining_real_vendor_chain_loci_lift_and_cite(
    file: str, line: int, signature: str, assertion: str
) -> None:
    source = "\n" * (line - 2) + f"{signature}\n    {assertion}\n    return 1\n"
    axis = _axis(source, file)

    assert axis["lifted_cited"] == 1
    assert axis["refused_loud"] == 0
    assert axis["silently_unaccounted"] == 0
    assert axis["lifted_loci"][0]["line"] == line


def test_chain_with_unliftable_operand_stays_refused_loud() -> None:
    source = "def f(x):\n    assert 0 < (yield x) < 10\n    return x\n"
    file = "unliftable.py"
    axis = _axis(source, file)

    assert axis["lifted_cited"] == 0
    assert axis["refused_loud"] == 1
    assert axis["silently_unaccounted"] == 0
    assert axis["refused_loci"][0]["line"] == 2


def test_try_assign_survives_except_return_for_post_try_use() -> None:
    """Real-path geometry behind requests cryptography_version_list (#4190)."""
    source = (
        "def f(s):\n"
        "    try:\n"
        "        xs = list(map(int, s.split('.')))\n"
        "    except ValueError:\n"
        "        return\n"
        "    assert xs < [1, 3, 4]\n"
    )
    axis = _axis(source, "try_assign.py")
    assert axis["lifted_cited"] == 1
    assert axis["refused_loud"] == 0
    assert axis["silently_unaccounted"] == 0


def test_full_datetime_chain_and_abs_loci_lift(
    cpython_311_datetime_path: Path,
) -> None:
    source = cpython_311_datetime_path.read_text(encoding="utf-8")
    file = str(cpython_311_datetime_path)
    axis = _axis(source, file)
    lifted = {locus["line"] for locus in axis["lifted_loci"]}

    assert axis["stated"] == 45
    assert axis["lifted_cited"] == 45
    assert axis["refused_loud"] == 0
    assert axis["silently_unaccounted"] == 0
    assert DATETIME_CHAIN_LINES <= lifted
    assert DATETIME_ABS_LINES <= lifted


def test_full_requests_chain_loci_lift() -> None:
    source = REQUESTS_INIT.read_text(encoding="utf-8")
    file = str(REQUESTS_INIT.resolve())
    axis = _axis(source, file)
    lifted = {locus["line"] for locus in axis["lifted_loci"]}

    assert axis["stated"] == 5
    assert axis["lifted_cited"] == 5
    assert axis["refused_loud"] == 0
    assert axis["silently_unaccounted"] == 0
    assert REQUESTS_CHAIN_LINES <= lifted


def test_shared_call_operand_is_built_and_cited_once() -> None:
    value = reduce_value("0 < f() < 10")

    assert isinstance(value, PredicateValue)
    assert value.formula.kind == "and"
    assert len(value.formula.operands) == 2
    assert len(value.operand_callsites) == 1
    assert value.operand_callsites[0].target_name == "f"
