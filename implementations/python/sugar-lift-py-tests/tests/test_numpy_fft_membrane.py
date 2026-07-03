from __future__ import annotations

import json
from pathlib import Path

from sugar_lift_py_tests.witness_harness import run_source_through_real_solver


def test_numpy_fft_projection_mints_as_opaque_membrane(tmp_path: Path) -> None:
    result = run_source_through_real_solver(
        tmp_path / "fft-truthful",
        _fft_source("1"),
    )

    trace = _trace(result)
    print(json.dumps(trace, indent=2, sort_keys=True))

    assert "ProjectedEqualityAssertionSugar" in result.selected_sugars
    assert "CallSugar" in result.selected_sugars
    assert _fft_projection_rows(result.lift_doc) == [_fft_contract(rhs=1)]
    assert _prove_statuses(result.prove_doc) == ["refused"]
    assert "single constraint has no sibling" in result.prove_doc["rows"][0]["reason"]
    assert not _euf_rows(result.lift_doc)
    assert not _derived_rows(result.lift_doc)


def test_numpy_fft_projection_twin_stays_stated_only(tmp_path: Path) -> None:
    result = run_source_through_real_solver(
        tmp_path / "fft-lying",
        _fft_source("2"),
    )

    trace = _trace(result)
    print(json.dumps(trace, indent=2, sort_keys=True))

    assert _fft_projection_rows(result.lift_doc) == [_fft_contract(rhs=2)]
    assert _prove_statuses(result.prove_doc) == ["refused"]
    assert "single constraint has no sibling" in result.prove_doc["rows"][0]["reason"]
    assert not _euf_rows(result.lift_doc)
    assert not _derived_rows(result.lift_doc)


def test_numpy_fft_no_longer_lands_in_unclassified_mint_failure(
    tmp_path: Path,
) -> None:
    result = run_source_through_real_solver(
        tmp_path / "fft-structural",
        _fft_source("1"),
    )

    trace = _trace(result)
    print(json.dumps(trace, indent=2, sort_keys=True))

    assert _fft_projection_rows(result.lift_doc)
    assert all(
        "add argument binding sugar for `numpy.fft.fft`"
        not in json.dumps(row, sort_keys=True)
        for row in result.lift_doc.get("factoryAudits", [])
    )


def _fft_source(rhs: str) -> str:
    return (
        "import numpy as np\n"
        "def test_fft():\n"
        f"    assert np.fft.fft([1, 0])[0] == {rhs}\n"
    )


def _fft_projection_rows(lift_doc: dict) -> list[dict]:
    return [
        row["inv"]
        for row in lift_doc["ir"]
        if row.get("sourceWarrants", [{}])[0].get("role")
        == "python.projected-equality-assertion-sugar"
    ]


def _fft_contract(*, rhs: int) -> dict:
    return {
        "kind": "atomic",
        "name": "=",
        "args": [
            {
                "kind": "ctor",
                "name": "py.subscript",
                "args": [
                    {
                        "kind": "ctor",
                        "name": "call:numpy.fft.fft",
                        "args": [
                            {
                                "kind": "ctor",
                                "name": "array",
                                "args": [
                                    {
                                        "kind": "const",
                                        "sort": {
                                            "kind": "primitive",
                                            "name": "Int",
                                        },
                                        "value": 1,
                                    },
                                    {
                                        "kind": "const",
                                        "sort": {
                                            "kind": "primitive",
                                            "name": "Int",
                                        },
                                        "value": 0,
                                    },
                                ],
                            }
                        ],
                    },
                    {
                        "kind": "const",
                        "sort": {"kind": "primitive", "name": "Int"},
                        "value": 0,
                    },
                ],
            },
            {
                "kind": "const",
                "sort": {"kind": "primitive", "name": "Int"},
                "value": rhs,
            },
        ],
    }


def _prove_statuses(prove_doc: dict) -> list[str]:
    return [row["status"] for row in prove_doc.get("rows", [])]


def _euf_rows(lift_doc: dict) -> list[dict]:
    return [
        row
        for row in lift_doc["ir"]
        if isinstance(row, dict) and "#euf#" in row.get("name", "")
    ]


def _derived_rows(lift_doc: dict) -> list[dict]:
    return [
        row
        for row in lift_doc["ir"]
        if "Derived" in _warrant_kinds(row)
    ]


def _warrant_kinds(row: dict) -> set[str]:
    provenance = row.get("proofirProvenance") or {}
    return {warrant.get("kind", "") for warrant in provenance.get("warrants", [])}


def _trace(result) -> dict:
    return {
        "selectedSugars": result.selected_sugars,
        "ir": result.lift_doc.get("ir", []),
        "factoryAudits": result.lift_doc.get("factoryAudits", []),
        "rows": result.prove_doc.get("rows", []),
    }
