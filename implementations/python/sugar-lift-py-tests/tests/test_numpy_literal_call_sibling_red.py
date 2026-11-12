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

# The numpy literal-call twins that state "not bridged", by pytest name.
#
# The owner, 2026-11-11, asked whether the first 21 count as "not bridged"
# (assert ``open``) instead of red: "Yes, not bridged" (docs/path-forward.md, job
# number one, next to "Green means decided"). No numpy proof exists to import,
# so a numpy call is an edge nothing binds, and the lifter holds no numpy
# arithmetic of its own. Each twin asserts ``open`` for the truthful claim AND
# for the lying claim: neither proven nor refuted. A twin listed here is not
# green in the plan's sense (its claim is not decided), and it turns back into a
# ``sat`` / ``unsat`` twin on the day a numpy proof can be imported.
#
# The last four (division by zero, ``sin``, ``sqrt``, ``fft``) asserted ``error:``
# as "stays opaque". Asked the same day whether to treat them as not bridged
# too, the owner answered: "Yes, same rule". Each asserts ``open`` for the claim
# it always made AND for a contrary claim about the same call.
#
# Every test named here asserts its own membership, so a renamed or added case
# cannot state "not bridged" without being listed.
NOT_BRIDGED_NUMPY_TWINS: tuple[str, ...] = (
    "test_numpy_integer_literal_call_is_not_bridged[add-5-6]",
    "test_numpy_integer_literal_call_is_not_bridged[multiply-6-7]",
    "test_numpy_integer_literal_call_is_not_bridged[subtract--1-1]",
    "test_numpy_mod_and_floor_divide_literal_call_is_not_bridged[mod-7-3-1-2]",
    "test_numpy_mod_and_floor_divide_literal_call_is_not_bridged[mod--7-3-2--1]",
    "test_numpy_mod_and_floor_divide_literal_call_is_not_bridged[mod-7--3--2-1]",
    "test_numpy_mod_and_floor_divide_literal_call_is_not_bridged[floor_divide-7-3-2-3]",
    "test_numpy_mod_and_floor_divide_literal_call_is_not_bridged[floor_divide--7-3--3--2]",
    "test_numpy_mod_and_floor_divide_literal_call_is_not_bridged[floor_divide-7--3--3--2]",
    "test_numpy_maximum_and_minimum_literal_call_is_not_bridged[maximum-7-3-7-3]",
    "test_numpy_maximum_and_minimum_literal_call_is_not_bridged[maximum--7-3-3--7]",
    "test_numpy_maximum_and_minimum_literal_call_is_not_bridged[maximum-5-5-5-4]",
    "test_numpy_maximum_and_minimum_literal_call_is_not_bridged[minimum-7-3-3-7]",
    "test_numpy_maximum_and_minimum_literal_call_is_not_bridged[minimum--7-3--7-3]",
    "test_numpy_maximum_and_minimum_literal_call_is_not_bridged[minimum-5-5-5-4]",
    "test_numpy_divide_literal_call_is_not_bridged[7-2-3.5-3]",
    "test_numpy_divide_literal_call_is_not_bridged[-7-2--3.5-3.5]",
    "test_numpy_divide_literal_call_is_not_bridged[1-4-0.25-0.5]",
    "test_numpy_divide_literal_call_is_not_bridged[6-3-2-2.5]",
    "test_numpy_power_literal_call_is_not_bridged",
    "test_numpy_add_literal_call_is_not_bridged",
    "test_numpy_divide_by_zero_literal_call_is_not_bridged",
    "test_numpy_sin_sqrt_fft_literal_call_is_not_bridged[sin]",
    "test_numpy_sin_sqrt_fft_literal_call_is_not_bridged[sqrt]",
    "test_numpy_sin_sqrt_fft_literal_call_is_not_bridged[fft]",
)


@pytest.mark.parametrize(
    ("op", "truth", "lie"),
    [
        ("add", 5, 6),
        ("multiply", 6, 7),
        ("subtract", -1, 1),
    ],
)
def test_numpy_integer_literal_call_is_not_bridged(
    request: pytest.FixtureRequest, tmp_path: Path, op: str, truth: int, lie: int
) -> None:
    """``np.add`` / ``np.multiply`` / ``np.subtract`` over integer literals are
    not bridged: no numpy proof exists to import, so nothing binds the call and
    the lifter does not compute numpy's result itself. The truthful claim and
    the lying claim are both ``open``.

    This turns back into a ``sat`` / ``unsat`` twin when a numpy proof can be
    imported.
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

    assert request.node.name in NOT_BRIDGED_NUMPY_TWINS
    assert truthful.verdict == "open"
    assert lying.verdict == "open"


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
def test_numpy_mod_and_floor_divide_literal_call_is_not_bridged(
    request: pytest.FixtureRequest,
    tmp_path: Path,
    op: str,
    left: int,
    right: int,
    truth: int,
    lie: int,
) -> None:
    """``np.mod`` / ``np.floor_divide`` over integer literals are not bridged:
    no numpy proof exists to import, so nothing binds the call and the lifter
    holds no sign convention for numpy. The truthful claim and the lying claim
    are both ``open``.

    This turns back into a ``sat`` / ``unsat`` twin when a numpy proof can be
    imported.
    """

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

    assert request.node.name in NOT_BRIDGED_NUMPY_TWINS
    assert truthful.verdict == "open"
    assert lying.verdict == "open"


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
def test_numpy_maximum_and_minimum_literal_call_is_not_bridged(
    request: pytest.FixtureRequest,
    tmp_path: Path,
    op: str,
    left: int,
    right: int,
    truth: int,
    lie: int,
) -> None:
    """``np.maximum`` / ``np.minimum`` over integer literals are not bridged: no
    numpy proof exists to import, so nothing binds the call and the kit does
    not stand in Python's own ``max`` / ``min`` for numpy's. The truthful claim
    and the lying claim are both ``open``.

    This turns back into a ``sat`` / ``unsat`` twin when a numpy proof can be
    imported.
    """

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

    assert request.node.name in NOT_BRIDGED_NUMPY_TWINS
    assert truthful.verdict == "open"
    assert lying.verdict == "open"


@pytest.mark.parametrize(
    ("left", "right", "truth", "lie"),
    [
        (7, 2, "3.5", "3"),
        (-7, 2, "-3.5", "3.5"),
        (1, 4, "0.25", "0.5"),
        (6, 3, "2", "2.5"),
    ],
)
def test_numpy_divide_literal_call_is_not_bridged(
    request: pytest.FixtureRequest,
    tmp_path: Path,
    left: int,
    right: int,
    truth: str,
    lie: str,
) -> None:
    """``np.divide`` over literal numeric operands is not bridged: no numpy
    proof exists to import, so nothing binds the call and the kit does not
    stand in Python's own ``/`` for numpy's division. The truthful claim and
    the lying claim are both ``open``.

    This turns back into a ``sat`` / ``unsat`` twin when a numpy proof can be
    imported.
    """

    truthful = _run_numpy_divide_case(
        tmp_path / f"divide-{left}-{right}-truthful", left, right, truth
    )
    lying = _run_numpy_divide_case(
        tmp_path / f"divide-{left}-{right}-lying", left, right, lie
    )
    observed = {"truthful": truthful.to_json(), "lying": lying.to_json()}
    print(json.dumps(observed, indent=2, sort_keys=True))

    assert request.node.name in NOT_BRIDGED_NUMPY_TWINS
    assert truthful.verdict == "open"
    assert lying.verdict == "open"


def test_numpy_divide_by_zero_literal_call_is_not_bridged(
    request: pytest.FixtureRequest, tmp_path: Path
) -> None:
    """``np.divide(1, 0)`` is not bridged: no numpy proof exists to import, so
    nothing binds the call, and what numpy does on division by zero (inf, nan,
    a warning) is numpy's knowledge, not the lifter's. With nothing bound the
    lifter cannot tell this call from ``np.divide(7, 2)``. The stated claim
    (``== 1``) and the contrary claim (``== 2``) are both ``open``.

    This turns back into a decided twin when a numpy proof can be imported;
    what each claim states then is whatever that proof says about division by
    zero.
    """

    stated = _run_case(
        tmp_path / "divide-by-zero-stated",
        "import numpy as np\n"
        "\n"
        "def test_np_divide_by_zero():\n"
        "    assert np.divide(1, 0) == 1\n",
    )
    contrary = _run_case(
        tmp_path / "divide-by-zero-contrary",
        "import numpy as np\n"
        "\n"
        "def test_np_divide_by_zero():\n"
        "    assert np.divide(1, 0) == 2\n",
    )
    observed = {"stated": stated.to_json(), "contrary": contrary.to_json()}
    print(json.dumps(observed, indent=2, sort_keys=True))

    assert request.node.name in NOT_BRIDGED_NUMPY_TWINS
    assert stated.verdict == "open"
    assert contrary.verdict == "open"


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


def test_numpy_power_literal_call_is_not_bridged(
    request: pytest.FixtureRequest,
    tmp_path: Path,
) -> None:
    """``np.power`` over integer literals is not bridged: no numpy proof exists
    to import, so nothing binds the call and the lifter does not compute the
    power itself. The truthful claim and the lying claim are both ``open``.

    The overflow claim (``np.power(2, 63) == 0``) is ``open`` for the same
    reason: where an integer power stops being int64-exact is numpy's
    knowledge, and with nothing bound the lifter cannot tell that call from
    ``np.power(2, 3)``.

    This turns back into a ``sat`` / ``unsat`` twin when a numpy proof can be
    imported; what the overflow claim states then is whatever that proof says
    about it.
    """

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

    assert request.node.name in NOT_BRIDGED_NUMPY_TWINS
    assert truthful.verdict == "open"
    assert lying.verdict == "open"
    assert overflow.verdict == "open"


@pytest.mark.parametrize(
    ("label", "call", "stated_rhs", "contrary_rhs"),
    [
        pytest.param("sin", "np.sin(0)", "0", "1", id="sin"),
        pytest.param("sqrt", "np.sqrt(4)", "2", "3", id="sqrt"),
        pytest.param("fft", "np.fft.fft([1, 2])", "[1, 2]", "[2, 1]", id="fft"),
    ],
)
def test_numpy_sin_sqrt_fft_literal_call_is_not_bridged(
    request: pytest.FixtureRequest,
    tmp_path: Path,
    label: str,
    call: str,
    stated_rhs: str,
    contrary_rhs: str,
) -> None:
    """``np.sin`` / ``np.sqrt`` / ``np.fft.fft`` over literals are not bridged:
    no numpy proof exists to import, so nothing binds the call and the lifter
    holds no numpy semantics of its own. The stated claim and a contrary claim
    about the same call (a different right-hand side) are both ``open``.

    This turns back into a decided twin when a numpy proof can be imported.
    """

    def source(rhs: str) -> str:
        return (
            "import numpy as np\n"
            "\n"
            f"def test_np_{label}_opaque():\n"
            f"    assert {call} == {rhs}\n"
        )

    stated = _run_case(tmp_path / f"{label}-stated", source(stated_rhs))
    contrary = _run_case(tmp_path / f"{label}-contrary", source(contrary_rhs))
    observed = {"stated": stated.to_json(), "contrary": contrary.to_json()}
    print(json.dumps(observed, indent=2, sort_keys=True))

    assert request.node.name in NOT_BRIDGED_NUMPY_TWINS
    assert stated.verdict == "open"
    assert contrary.verdict == "open"


def test_numpy_add_literal_call_is_not_bridged(
    request: pytest.FixtureRequest, tmp_path: Path
) -> None:
    """``np.add(2, 3)`` is not bridged: no numpy proof exists to import, so
    nothing binds the call. The truthful claim (``== 5``) and the lying claim
    (``== 6``) are both ``open``.

    This turns back into a ``sat`` / ``unsat`` twin when a numpy proof can be
    imported.
    """

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

    assert request.node.name in NOT_BRIDGED_NUMPY_TWINS
    assert observed == {"truthful": "open", "lying": "open"}


def test_computed_sibling_is_structurally_derived() -> None:
    from sugar_lift_py_tests.floor import InvValue
    from sugar_lift_py_tests.ir import eq, num

    class _Site:
        filename = "vendor.py"
        line = 1
        col = 0

    site = _Site()
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


def test_identical_stated_and_computed_equality_retains_both_warrants() -> None:
    from sugar_lift_py_tests.floor import InvValue
    from sugar_lift_py_tests.ir import eq, num

    class _Site:
        filename = "vendor.py"
        line = 1
        col = 0

    site = _Site()
    formula = eq(num(2), num(2))
    inv = InvValue(formula, site, derived_formulas=(formula,))

    (mint,) = inv.mint_contribution("f", ())
    declaration = mint.to_declaration()

    assert declaration["inv"]["kind"] == "and"
    assert [atom["name"] for atom in declaration["inv"]["operands"]] == ["=", "="]
    assert [
        warrant["kind"] for warrant in declaration["proofirProvenance"]["warrants"]
    ] == ["Stated", "Derived"]


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
