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


def _scan(project: Path, body: str) -> dict:
    """The universe scan of a one-file project: its rows and its term table."""
    project.mkdir()
    (project / "test_slice_subscript.py").write_text(body, encoding="utf-8")
    (file_node,) = _enumerate("source_files", project)["nodes"]
    result = _enumerate("universe", project, at=file_node["memento"])
    assert result["gaps"] == []
    return result


def _rows(project: Path, body: str) -> list[dict]:
    """Every row the universe scan states for a one-file project."""
    return [node["audit"] for node in _scan(project, body)["nodes"]]


def _string_constants(formula: dict, table: dict) -> set[str]:
    """Every string constant a wire formula reaches through the term table."""
    found: set[str] = set()
    formulas = [formula]
    terms: list[dict] = []
    while formulas:
        current = formulas.pop()
        terms.extend(current.get("args", ()))
        formulas.extend(current.get("operands", ()))
        if "body" in current:
            formulas.append(current["body"])
    while terms:
        term = terms.pop()
        node = table[term["cid"]] if term.get("kind") == "term-ref" else term
        if node.get("kind") == "const" and isinstance(node.get("value"), str):
            found.add(node["value"])
        terms.extend(node.get("args", ()))
    return found


def _contract(rows: list[dict]) -> dict:
    (row,) = [row for row in rows if row["kind"] == "function-contract"]
    return row


def test_concrete_string_slice_is_decided_at_the_one_door(tmp_path: Path) -> None:
    """``'abcdef'[1:3]`` is ``'bc'``: the slice is decided at the lift, and it
    cannot raise, so it adds no halted arm.

    The comparison is not folded at the lift: a string equality is a fact the
    assertion states (``ff8cd13b0``, the ruling that deleted the
    ``StringValue.equals`` fold).  An assert in a function body is a halt of
    that function (#8961, ``assert_sugar.halts_where_its_asserts_fail``): under
    the complement of its fact the function halts with ``AssertionError`` at
    the ``assert``.  So each twin states exactly one panic locus, the assert's
    at line 2, and none for the slice.  The truthful twin's claim is ``'bc' ==
    'bc'``.  The lying twin's claim is ``'bc' == 'bd'``, an equality of two
    distinct string constants that no model satisfies, so prove refutes it and
    it is never ``sat``."""
    truthful = _scan(
        tmp_path / "good",
        "def test_concrete_string_slice():\n    assert 'abcdef'[1:3] == 'bc'\n",
    )
    lying = _scan(
        tmp_path / "bad",
        "def test_concrete_string_slice():\n    assert 'abcdef'[1:3] == 'bd'\n",
    )

    (good,) = [node["audit"] for node in truthful["nodes"]]
    assert good["kind"] == "function-contract"
    assert good["name"] == "python:test_slice_subscript.test_concrete_string_slice"
    assert "inv" in good
    (good_locus,) = good["panicLoci"]
    assert (good_locus["file"], good_locus["line"]) == ("test_slice_subscript.py", 2)
    good_strings = _string_constants(good["inv"], truthful["termTable"])
    assert "bc" in good_strings
    assert "bd" not in good_strings
    assert "abcdef" not in good_strings

    (bad,) = [node["audit"] for node in lying["nodes"]]
    assert bad["kind"] == "function-contract"
    (bad_locus,) = bad["panicLoci"]
    assert (bad_locus["file"], bad_locus["line"]) == ("test_slice_subscript.py", 2)
    bad_strings = _string_constants(bad["inv"], lying["termTable"])
    assert {"bc", "bd"} <= bad_strings
    assert "abcdef" not in bad_strings
    assert bad["inv"] != good["inv"]


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
    assert contract["name"] == "python:test_slice_subscript.test_symbolic_slice"
    assert contract["formals"] == ["values"]
    undecided = [row for row in rows if row["kind"] == "undecided"]
    assert undecided, rows
    assert len(undecided) == len(rows) - 1
    for row in undecided:
        assert row["reason"] == {"unanswered": {}}
        assert row["site"]["file"] == "test_slice_subscript.py"
