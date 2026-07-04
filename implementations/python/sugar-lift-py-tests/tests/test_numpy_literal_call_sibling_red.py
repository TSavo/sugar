from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path

import pytest

from sugar_lift_py_tests.witness_harness import (
    WitnessPipelineError,
    WitnessPipelineResult,
    run_source_through_real_solver,
)


@pytest.mark.parametrize(
    ("op", "truth", "lie"),
    [
        ("add", 5, 6),
        ("multiply", 6, 7),
        ("subtract", -1, 1),
    ],
)
def test_numpy_integer_literal_call_reduces_to_sibling_fact(
    tmp_path: Path, op: str, truth: int, lie: int
) -> None:
    """Computable integer ufuncs need a reduced-value sibling fact.

    Boundary: this pins only literal integer arithmetic. Floating/transcendental
    or analysis-heavy operations such as np.sin, np.sqrt, and np.fft remain
    opaque EUF until a deliberate numeric semantics slice teaches them.
    """

    truthful = _run_case(
        tmp_path / f"{op}-truthful",
        "import numpy as np\n"
        "\n"
        f"def test_np_{op}_truthful():\n"
        f"    assert np.{op}(2, 3) == {truth}\n",
    )
    lying = _run_case(
        tmp_path / f"{op}-lying",
        "import numpy as np\n"
        "\n"
        f"def test_np_{op}_lying():\n"
        f"    assert np.{op}(2, 3) == {lie}\n",
    )
    observed = {"truthful": truthful.to_json(), "lying": lying.to_json()}
    print(json.dumps(observed, indent=2, sort_keys=True))

    assert truthful.verdict == "sat"
    assert lying.verdict == "unsat"

    truthful_rows = _numpy_euf_rows(truthful.result, f"numpy.{op}")
    assert _rhs_values(truthful_rows) == [truth]
    assert _warrant_kinds(truthful_rows[0]) == {"Stated", "Derived"}

    lying_rows = _numpy_euf_rows(lying.result, f"numpy.{op}")
    assert _rhs_values(lying_rows) == [truth, lie]
    assert {_rhs_value(row): _warrant_kinds(row) for row in lying_rows} == {
        truth: {"Derived"},
        lie: {"Stated"},
    }


@pytest.mark.parametrize(
    ("op", "truth"),
    [
        ("add", 5),
        ("multiply", 6),
        ("subtract", -1),
    ],
)
def test_numpy_integer_literal_call_accepts_constant_bound_args(
    tmp_path: Path, op: str, truth: int
) -> None:
    observed = _run_case(
        tmp_path / f"{op}-bound",
        "import numpy as np\n"
        "\n"
        "left = 2\n"
        "right = 3\n"
        f"def test_np_{op}_bound():\n"
        f"    assert np.{op}(left, right) == {truth}\n",
    )
    print(json.dumps(observed.to_json(), indent=2, sort_keys=True))

    assert observed.verdict == "sat"
    rows = _numpy_euf_rows(observed.result, f"numpy.{op}")
    assert _rhs_values(rows) == [truth]
    assert _warrant_kinds(rows[0]) == {"Stated", "Derived"}


@pytest.mark.parametrize(
    ("op", "left", "right", "truth", "lie"),
    [
        ("mod", 7, 3, 1, 2),
        ("mod", -7, 3, 2, -1),
        ("mod", 7, -3, -2, 1),
        ("floor_divide", 7, 3, 2, 3),
        ("floor_divide", -7, 3, -3, -2),
        ("floor_divide", 7, -3, -3, -2),
    ],
)
def test_numpy_mod_and_floor_divide_follow_python_sign_convention(
    tmp_path: Path,
    op: str,
    left: int,
    right: int,
    truth: int,
    lie: int,
) -> None:
    truthful = _run_numpy_binary_case(
        tmp_path / f"{op}-{left}-{right}-truthful",
        op,
        left,
        right,
        truth,
    )
    lying = _run_numpy_binary_case(
        tmp_path / f"{op}-{left}-{right}-lying",
        op,
        left,
        right,
        lie,
    )
    observed = {"truthful": truthful.to_json(), "lying": lying.to_json()}
    print(json.dumps(observed, indent=2, sort_keys=True))

    assert truthful.verdict == "sat"
    assert lying.verdict == "unsat"

    truthful_rows = _numpy_euf_rows(truthful.result, f"numpy.{op}")
    assert _rhs_values(truthful_rows) == [truth]
    assert _warrant_kinds(truthful_rows[0]) == {"Stated", "Derived"}

    lying_rows = _numpy_euf_rows(lying.result, f"numpy.{op}")
    assert _rhs_values(lying_rows) == sorted([truth, lie])
    assert {_rhs_value(row): _warrant_kinds(row) for row in lying_rows} == {
        truth: {"Derived"},
        lie: {"Stated"},
    }


def test_numpy_power_reduces_only_when_integer_result_is_int64_exact(
    tmp_path: Path,
) -> None:
    truthful = _run_numpy_binary_case(tmp_path / "power-truthful", "power", 2, 3, 8)
    lying = _run_numpy_binary_case(tmp_path / "power-lying", "power", 2, 3, 9)
    overflow = _run_numpy_binary_case(
        tmp_path / "power-overflow",
        "power",
        2,
        63,
        0,
    )
    observed = {
        "truthful": truthful.to_json(),
        "lying": lying.to_json(),
        "overflow": overflow.to_json(),
    }
    print(json.dumps(observed, indent=2, sort_keys=True))

    assert truthful.verdict == "sat"
    assert lying.verdict == "unsat"

    truthful_rows = _numpy_euf_rows(truthful.result, "numpy.power")
    assert _rhs_values(truthful_rows) == [8]
    assert _warrant_kinds(truthful_rows[0]) == {"Stated", "Derived"}

    lying_rows = _numpy_euf_rows(lying.result, "numpy.power")
    assert _rhs_values(lying_rows) == [8, 9]
    assert {_rhs_value(row): _warrant_kinds(row) for row in lying_rows} == {
        8: {"Derived"},
        9: {"Stated"},
    }

    assert overflow.verdict.startswith("error:")
    assert not any(
        "Derived" in _warrant_kinds(row)
        for row in _numpy_euf_rows(overflow.result, "numpy.power")
    )


@pytest.mark.parametrize(
    ("label", "source"),
    [
        (
            "divide",
            "import numpy as np\n"
            "\n"
            "def test_np_divide_opaque():\n"
            "    assert np.divide(4, 2) == 2\n",
        ),
        (
            "sin",
            "import numpy as np\n"
            "\n"
            "def test_np_sin_opaque():\n"
            "    assert np.sin(0) == 0\n",
        ),
        (
            "sqrt",
            "import numpy as np\n"
            "\n"
            "def test_np_sqrt_opaque():\n"
            "    assert np.sqrt(4) == 2\n",
        ),
        (
            "fft",
            "import numpy as np\n"
            "\n"
            "def test_np_fft_opaque():\n"
            "    assert np.fft.fft([1, 2]) == [1, 2]\n",
        ),
    ],
)
def test_uncomputed_numpy_ops_stay_opaque(
    tmp_path: Path, label: str, source: str
) -> None:
    observed = _run_case(tmp_path / label, source)
    print(json.dumps(observed.to_json(), indent=2, sort_keys=True))

    assert observed.verdict.startswith("error:")
    assert not any(
        "Derived" in _warrant_kinds(row) for row in _all_euf_rows(observed.result)
    )


def test_numpy_add_literal_call_reduces_to_sibling_fact(tmp_path: Path) -> None:
    observed = {
        "truthful": _run_case(
            tmp_path / "truthful",
            "import numpy as np\n"
            "\n"
            "def test_np_add_truthful():\n"
            "    assert np.add(2, 3) == 5\n",
        ).verdict,
        "lying": _run_case(
            tmp_path / "lying",
            "import numpy as np\n"
            "\n"
            "def test_np_add_lying():\n"
            "    assert np.add(2, 3) == 6\n",
        ).verdict,
    }
    print(json.dumps(observed, indent=2, sort_keys=True))

    assert observed == {"truthful": "sat", "lying": "unsat"}


@dataclass(frozen=True)
class CaseResult:
    verdict: str
    result: WitnessPipelineResult | None

    def to_json(self) -> dict[str, object]:
        return {
            "verdict": self.verdict,
            "eufRows": [_summarize_euf_row(row) for row in _all_euf_rows(self.result)],
        }


def _run_case(project: Path, source: str) -> CaseResult:
    try:
        result = run_source_through_real_solver(project, source)
        try:
            return CaseResult(result.verdict, result)
        except WitnessPipelineError as exc:
            return CaseResult(f"error: {exc}", result)
    except WitnessPipelineError as exc:
        return CaseResult(f"error: {exc}", None)


def _run_numpy_binary_case(
    project: Path,
    op: str,
    left: int,
    right: int,
    expected: int,
) -> CaseResult:
    return _run_case(
        project,
        "import numpy as np\n"
        "\n"
        f"def test_np_{op}_{abs(left)}_{abs(right)}_{abs(expected)}():\n"
        f"    assert np.{op}({left}, {right}) == {expected}\n",
    )


def _numpy_euf_rows(result: WitnessPipelineResult | None, callee: str) -> list[dict]:
    return [
        row
        for row in _all_euf_rows(result)
        if row.get("name", "").startswith(f"{callee}#euf#")
    ]


def _all_euf_rows(result: WitnessPipelineResult | None) -> list[dict]:
    if result is None:
        return []
    return [
        row
        for row in result.lift_doc.get("ir", [])
        if isinstance(row, dict)
        and isinstance(row.get("name"), str)
        and "#euf#" in row["name"]
    ]


def _summarize_euf_row(row: dict) -> dict[str, object]:
    return {
        "name": row["name"],
        "rhs": _rhs_summary(row),
        "warrants": sorted(_warrant_kinds(row)),
    }


def _rhs_summary(row: dict) -> object:
    rhs = row["inv"]["args"][1]
    if rhs.get("kind") == "const" and rhs.get("sort", {}).get("name") == "Int":
        return rhs["value"]
    return rhs.get("name") or rhs.get("kind") or rhs


def _rhs_values(rows: list[dict]) -> list[int]:
    return sorted(_rhs_value(row) for row in rows)


def _rhs_value(row: dict) -> int:
    rhs = row["inv"]["args"][1]
    assert rhs["kind"] == "const"
    assert rhs["sort"]["name"] == "Int"
    return rhs["value"]


def _warrant_kinds(row: dict) -> set[str]:
    return {warrant["kind"] for warrant in row["proofirProvenance"]["warrants"]}
