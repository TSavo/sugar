"""Slice subscripts, read through the kit's one door.

These twins once drove the ``lift`` RPC method and read its ``ir`` document.
That method is deleted (#7864: mint is the only driver of the kit); what mint
reads is the ``sugar.enumerate`` universe scan, so the twins read that: one
``function-contract`` row per function, its halted arms as ``panicLoci``, and
one ``undecided`` row per operation nothing in the proof answers.
"""

from __future__ import annotations

from pathlib import Path

from sugar_lift_py_tests import lift_rpc


def _enumerate(level: str, project: Path, at=None) -> dict:
    captured: list = []
    original_send = lift_rpc._send
    lift_rpc._send = captured.append
    try:
        lift_rpc._dispatch_request(
            {
                "jsonrpc": "2.0",
                "id": 1,
                "method": "sugar.enumerate",
                "params": {
                    "level": level,
                    "workspace_root": str(project),
                    "at": at,
                    "seek": False,
                    "options": {},
                },
            },
        )
    finally:
        lift_rpc._send = original_send
    (response,) = captured
    assert "error" not in response, response
    return response["result"]


def _rows(project: Path, body: str) -> list[dict]:
    """Every row the universe scan states for a one-file project."""
    project.mkdir()
    (project / "test_slice_subscript.py").write_text(body, encoding="utf-8")
    (file_node,) = _enumerate("source_files", project)["nodes"]
    result = _enumerate("universe", project, at=file_node["memento"])
    assert result["gaps"] == []
    return [node["audit"] for node in result["nodes"]]


def _contract(rows: list[dict]) -> dict:
    (row,) = [row for row in rows if row["kind"] == "function-contract"]
    return row


def test_concrete_string_slice_is_decided_at_the_one_door(tmp_path: Path) -> None:
    """``'abcdef'[1:3]`` is ``'bc'``.  Truthful: the function's one row states
    the assertion's claim, nothing halts and nothing is left undecided.
    Lying (``== 'bd'``): the assertion halts, as its one panic locus."""
    truthful = _rows(
        tmp_path / "good",
        "def test_concrete_string_slice():\n    assert 'abcdef'[1:3] == 'bc'\n",
    )
    lying = _rows(
        tmp_path / "bad",
        "def test_concrete_string_slice():\n    assert 'abcdef'[1:3] == 'bd'\n",
    )

    (good,) = truthful
    assert good["kind"] == "function-contract"
    assert good["name"] == "test_concrete_string_slice"
    assert "inv" in good
    assert "panicLoci" not in good

    bad = _contract(lying)
    assert len(bad["panicLoci"]) == 1


def test_symbolic_slice_is_not_decided_in_the_functions_own_proof(
    tmp_path: Path,
) -> None:
    """``values[::2]`` slices a formal: the operation waits for a caller's
    actual, and the function's own proof has none (#7766).  So the scan states
    the function's one contract row and the slice as ``undecided`` members
    (``reason: unanswered``) at the file; it never states a result for it."""
    rows = _rows(
        tmp_path / "good",
        "def test_symbolic_slice(values):\n    assert values[::2] == values[::2]\n",
    )

    contract = _contract(rows)
    assert contract["name"] == "test_symbolic_slice"
    assert contract["formals"] == ["values"]
    undecided = [row for row in rows if row["kind"] == "undecided"]
    assert undecided, rows
    assert len(undecided) == len(rows) - 1
    for row in undecided:
        assert row["reason"] == {"unanswered": {}}
        assert row["site"]["file"] == "test_slice_subscript.py"
