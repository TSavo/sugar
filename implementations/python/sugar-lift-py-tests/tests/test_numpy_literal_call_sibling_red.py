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
    assert _rhs_values(truthful_rows) == [truth, truth]

    lying_rows = _numpy_euf_rows(lying.result, f"numpy.{op}")
    assert _rhs_values(lying_rows) == [truth, lie]


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
    assert _rhs_values(rows) == [truth, truth]


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
    assert _rhs_values(truthful_rows) == [truth, truth]

    lying_rows = _numpy_euf_rows(lying.result, f"numpy.{op}")
    assert _rhs_values(lying_rows) == sorted([truth, lie])


@pytest.mark.parametrize(
    ("op", "left", "right", "truth", "lie"),
    [
        ("maximum", 7, 3, 7, 3),
        ("maximum", -7, 3, 3, -7),
        ("maximum", 5, 5, 5, 4),
        ("minimum", 7, 3, 3, 7),
        ("minimum", -7, 3, -7, 3),
        ("minimum", 5, 5, 5, 4),
    ],
)
def test_numpy_maximum_and_minimum_reduce_to_sibling_fact(
    tmp_path: Path,
    op: str,
    left: int,
    right: int,
    truth: int,
    lie: int,
) -> None:
    """np.maximum/np.minimum over integer literals are total, dtype-safe order
    comparisons; the kit computes them with Python's own ``max``/``min`` and
    never imports or executes numpy."""

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
    assert _rhs_values(truthful_rows) == [truth, truth]

    lying_rows = _numpy_euf_rows(lying.result, f"numpy.{op}")
    assert _rhs_values(lying_rows) == sorted({truth, lie})


@pytest.mark.parametrize(
    ("left", "right", "truth", "lie"),
    [
        (7, 2, "3.5", "3"),
        (-7, 2, "-3.5", "3.5"),
        (1, 4, "0.25", "0.5"),
        (6, 3, "2", "2.5"),
    ],
)
def test_numpy_divide_reduces_to_sibling_fact(
    tmp_path: Path,
    left: int,
    right: int,
    truth: str,
    lie: str,
) -> None:
    """np.divide over literal numeric operands is IEEE-754 true division; the
    kit computes it with Python's own ``/`` and never imports or executes
    numpy.

    Boundary: division by zero is a permanent stop-line (see
    ``test_numpy_divide_by_zero_stays_opaque``), not a floored inf/nan value.
    """

    truthful = _run_numpy_divide_case(
        tmp_path / f"divide-{left}-{right}-truthful", left, right, truth
    )
    lying = _run_numpy_divide_case(
        tmp_path / f"divide-{left}-{right}-lying", left, right, lie
    )
    observed = {"truthful": truthful.to_json(), "lying": lying.to_json()}
    print(json.dumps(observed, indent=2, sort_keys=True))

    assert truthful.verdict == "sat"
    assert lying.verdict == "unsat"

    truthful_rows = _numpy_euf_rows(truthful.result, "numpy.divide")
    assert _real_rhs_values(truthful_rows) == [truth, truth]

    lying_rows = _numpy_euf_rows(lying.result, "numpy.divide")
    assert set(_real_rhs_values(lying_rows)) == {truth, lie}


def test_numpy_divide_by_zero_stays_opaque(tmp_path: Path) -> None:
    """Division by zero is a permanent stop-line: numpy's IEEE inf/nan/warning
    behavior is not reproduced, so no Derived sibling fact is fabricated."""

    observed = _run_case(
        tmp_path / "divide-by-zero",
        "import numpy as np\n"
        "\n"
        "def test_np_divide_by_zero():\n"
        "    assert np.divide(1, 0) == 1\n",
    )
    print(json.dumps(observed.to_json(), indent=2, sort_keys=True))

    assert observed.verdict.startswith("error:")
    assert len(_numpy_euf_rows(observed.result, "numpy.divide")) == 1


def _run_numpy_divide_case(
    project: Path,
    left: int,
    right: int,
    expected: str,
) -> CaseResult:
    return _run_case(
        project,
        "import numpy as np\n"
        "\n"
        f"def test_np_divide_{abs(left)}_{abs(right)}_"
        f"{abs(hash(expected)) % 100000}():\n"
        f"    assert np.divide({left}, {right}) == {expected}\n",
    )


def _real_rhs_values(rows: list[dict]) -> list[str]:
    return sorted(_real_rhs_value(row) for row in rows)


def _real_rhs_value(row: dict) -> str:
    # Int embeds in Real losslessly: an INTEGRAL divide result (e.g. 6/3 == 2)
    # projects through the Int ctor to agree with a plain-int sibling, while a
    # genuinely fractional result (e.g. 7/2 == 3.5) needs the Real ctor. Both
    # are the numeric RHS this helper compares against the source's decimal
    # literal text, so normalize to the same canonical string either way.
    rhs = row["inv"]["args"][1]
    assert rhs["kind"] == "const"
    assert rhs["sort"]["name"] in {"Int", "Real"}
    if rhs["sort"]["name"] == "Int":
        return str(rhs["value"])
    return rhs["value"]


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
    assert _rhs_values(truthful_rows) == [8, 8]

    lying_rows = _numpy_euf_rows(lying.result, "numpy.power")
    assert _rhs_values(lying_rows) == [8, 9]

    assert overflow.verdict.startswith("error:")
    assert len(_numpy_euf_rows(overflow.result, "numpy.power")) == 1


@pytest.mark.parametrize(
    ("label", "source"),
    [
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
    assert len(_all_euf_rows(observed.result)) == 1


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


def test_computed_sibling_is_structurally_derived() -> None:
    from sugar_lift_py_tests.factory.source_fragment import SourceFragment
    from sugar_lift_py_tests.floor import InvValue
    from sugar_lift_py_tests.ir import eq, num

    site = SourceFragment.from_source("assert 2 == 2\n", "vendor.py").statements()[0]
    inv = InvValue(
        eq(num(2), num(2)),
        site,
        derived_formulas=(eq(num(1), num(1)),),
    )

    stated, derived = inv.mint_contribution("f", ())
    assert stated.provenance().warrants[0].to_rpc()["kind"] == "Stated"
    assert derived.provenance().warrants[0].to_rpc() == {
        "kind": "Derived",
        "floorChain": ["OpaqueOpCallsite.computed"],
    }


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
    return [row for row in _all_euf_rows(result) if _row_callee(row) == callee]


def _all_euf_rows(result: WitnessPipelineResult | None) -> list[dict]:
    if result is None:
        return []
    return [
        row
        for row in result.lift_doc.get("ir", [])
        if isinstance(row, dict) and _row_callee(row) is not None
    ]


def _row_callee(row: dict) -> str | None:
    inv = row.get("inv") or {}
    args = inv.get("args") or []
    if len(args) != 2 or not isinstance(args[0], dict):
        return None
    name = args[0].get("name")
    if isinstance(name, str) and name.startswith("call:numpy."):
        return name.removeprefix("call:")
    return None


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
    provenance = row.get("proofirProvenance")
    if provenance is not None:
        return {warrant["kind"] for warrant in provenance["warrants"]}
    # Native stated assertions are the source-warranted row.  Computed sibling
    # facts carry ProofIR Derived provenance, so the two rows remain strictly
    # distinguishable after the factory rebuild stopped merging their warrants.
    assert row.get("sourceWarrants")
    return {"Stated"}
