"""The python-bind surface constructs through ``sugar.enumerate`` only.

The promotion proof is deliberately whole-population: folding per-file
``universe`` rows over the sealed ``source_files`` census must reproduce the
retired handler's whole-population result.  A per-file/per-file comparison is
not sufficient evidence for a lift migration.
"""

from __future__ import annotations

from pathlib import Path

from sugar_lift_python_source.bind_rpc import (
    ENUMERATE_RPC_METHOD,
    dispatch,
    kit_declaration_result,
)
from sugar_lift_python_source.source_oracle import path_source


def _enumerate(root: Path, level: str, *, at: dict | None = None) -> dict:
    params: dict = {"level": level, "workspace_root": str(root)}
    if at is not None:
        params["at"] = at
    return dispatch(
        {
            "jsonrpc": "2.0",
            "id": 1,
            "method": ENUMERATE_RPC_METHOD,
            "params": params,
        }
    )


def _write_population(root: Path) -> None:
    (root / "alpha.py").write_text(
        "# concept: alpha\ndef alpha(x: int) -> int:\n    return x\n",
        encoding="utf-8",
    )
    (root / "beta.py").write_text(
        "# concept: beta\ndef beta(y: int) -> int:\n    return y\n",
        encoding="utf-8",
    )


def test_bind_declaration_advertises_enumerate_and_retires_lift() -> None:
    names = {method["name"] for method in kit_declaration_result()["rpc"]["methods"]}

    assert ENUMERATE_RPC_METHOD in names
    assert "lift" not in names


def test_bind_source_files_seals_the_whole_python_population(tmp_path: Path) -> None:
    _write_population(tmp_path)
    (tmp_path / "notes.txt").write_text("not source", encoding="utf-8")

    result = _enumerate(tmp_path, "source_files")["result"]

    assert [node["memento"]["file"] for node in result["nodes"]] == [
        "alpha.py",
        "beta.py",
    ]
    assert result["gaps"] == []
    _source, _filename, alpha_cid = path_source(str(tmp_path / "alpha.py"))
    assert result["nodes"][0]["memento"]["source_cid"] == alpha_cid


def test_bind_population_fold_equals_whole_population_legacy(tmp_path: Path) -> None:
    """The true migration contract: population legacy == enumerated fold."""
    _write_population(tmp_path)

    census = _enumerate(tmp_path, "source_files")["result"]
    folded = [
        node["audit"]
        for file_node in census["nodes"]
        for node in _enumerate(tmp_path, "universe", at=file_node["memento"])["result"][
            "nodes"
        ]
    ]
    legacy = dispatch(
        {
            "jsonrpc": "2.0",
            "id": 2,
            "method": "lift",
            "params": {"workspace_root": str(tmp_path), "source_paths": ["."]},
        }
    )["result"]["ir"]

    assert len(legacy) == 2, "the promotion control must carry real claim mass"
    assert folded == legacy


def test_bind_universe_refuses_a_stale_source_identity(tmp_path: Path) -> None:
    _write_population(tmp_path)
    alpha = _enumerate(tmp_path, "source_files")["result"]["nodes"][0]["memento"]
    (tmp_path / "alpha.py").write_text(
        "# concept: changed\ndef alpha(x: int) -> int:\n    return x + 1\n",
        encoding="utf-8",
    )

    result = _enumerate(tmp_path, "universe", at=alpha)["result"]

    assert result["nodes"] == []
    assert len(result["gaps"]) == 1
    assert "source identity" in result["gaps"][0]["reason"]


def test_bind_declares_no_parameter_contract_link_units(tmp_path: Path) -> None:
    response = _enumerate(tmp_path, "parameter-contract-link-units")

    assert response["result"] == {"rows": []}


def test_bind_refuses_an_unowned_enumeration_level(tmp_path: Path) -> None:
    response = _enumerate(tmp_path, "facts")

    assert response["error"]["code"] == -32602
    assert "false zero" in response["error"]["message"]
