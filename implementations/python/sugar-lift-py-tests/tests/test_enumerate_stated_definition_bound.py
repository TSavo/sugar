"""A definition whose term graph is past the transport's bound is refused by
name; a definition whose term written out is huge is not.

A proof carries its term graph (#7757): a row states each term by reference
and the response carries each term row once.  A term whose written-out form
doubles per level (a subterm both arms of a conditional share) is a few rows
of graph, so it is served as stated -- the 16 MiB bound no longer reads the
written-out form (#9151 read it, and refused 294 pandas/numpy functions whose
graphs are small).  The bound stays as a crash guard for the transport only:
past the transport's finite-or-refuse bound the WHOLE file's response was
swapped for a marker with no ``kind`` (run 43960179946), so a definition whose
graph alone is past it is its own ``undecided`` row, by the one refusal rule,
and the file is served.  Twins at the real JSON-RPC door.
"""

from __future__ import annotations

import json

from sugar_lift_py_tests import lift_rpc, tree_enumerate
from sugar_lift_py_tests.ir import TermTableBuilder, atomic, ctor, make_var


def _doubled(depth: int):
    """A term whose graph has ``depth + 1`` rows and whose written-out form
    has ``2 ** depth`` leaves: each level names the one below twice."""
    term = make_var("x")
    for _ in range(depth):
        term = ctor("pair", [term, term])
    return term


def _wide(width: int):
    """A term whose graph has ``width + 1`` rows: ``width`` distinct leaves."""
    return ctor("tuple", [make_var(f"v{index}") for index in range(width)])


class _Row:
    def __init__(self, term):
        self.term = term

    def to_rpc_with_term_table(self, table):
        return {
            "kind": "contract",
            "post": table.formula(atomic("=", [make_var("out"), self.term])),
        }


def _serve_universe(tmp_path, monkeypatch, term) -> dict:
    subject = tmp_path / "subject.py"
    subject.write_text("def subject():\n    return 1\n", encoding="utf-8")

    def stated_contract_rows(fn, file_rel):
        return tree_enumerate.function_def_memento(fn, file_rel), [_Row(term)]

    request = {
        "jsonrpc": "2.0",
        "id": 23,
        "method": "sugar.enumerate",
        "params": {
            "level": "universe",
            "workspace_root": str(tmp_path),
            "at": {"file": subject.name},
            "seek": False,
        },
    }
    requests = iter([request])
    sent = []
    monkeypatch.setattr(tree_enumerate, "STATED_DEFINITION_BYTE_BOUND", 4096)
    monkeypatch.setattr(tree_enumerate, "function_contract_rows", stated_contract_rows)
    monkeypatch.setattr(lift_rpc, "_recv", lambda: next(requests, None))
    monkeypatch.setattr(lift_rpc, "_send", sent.append)

    lift_rpc._serve()

    assert len(sent) == 1, sent
    return sent[0]


def test_a_doubling_term_is_served_as_its_graph(tmp_path, monkeypatch):
    """POSITIVE (#7757). 2**30 leaves written out, 31 rows of graph: within
    the bound, served as the contract row, its term by reference through the
    response's own table, never refused for the size of its expansion."""
    response = _serve_universe(tmp_path, monkeypatch, _doubled(30))

    assert "error" not in response, response
    result = response["result"]
    (node,) = result["nodes"]
    audit = node["audit"]
    assert audit["kind"] == "contract"
    reference = audit["post"]["args"][1]
    assert reference["kind"] == "term-ref"
    assert reference["cid"] in result["termTable"]
    assert len(result["termTable"]) <= 32 + 1


def test_a_definition_whose_graph_is_past_the_bound_is_its_refused_member(
    tmp_path, monkeypatch
):
    """DISCRIMINATING. 400 distinct leaves are 400 rows of graph, past the
    4096-byte bound: the function's one ``undecided`` row names the bound;
    the file is served, not ended."""
    response = _serve_universe(tmp_path, monkeypatch, _wide(400))

    assert "error" not in response, response
    result = response["result"]
    (node,) = result["nodes"]
    assert node["memento"]["source_function_name"] == "subject"
    audit = node["audit"]
    assert audit["kind"] == "undecided"
    assert audit["symbol"] == "python:subject.subject"
    refused = audit["reason"]["refused"]
    assert refused["owner"] == "tree_enumerate.stated_definition_bound"
    assert "4096-byte bound" in refused["observed"]
    # The refused row states no term: nothing of the graph is carried.
    assert "termTable" not in result


def test_the_measure_is_the_rows_and_their_graph_each_row_once() -> None:
    """The size the bound reads is the compact serialization of the rows as
    they stand plus each term row they reach, once -- never the written-out
    term."""
    table = TermTableBuilder()
    wire = [_Row(_doubled(6)).to_rpc_with_term_table(table), {"kind": "x", "n": []}]

    def compact(item) -> int:
        return len(
            json.dumps(item, separators=(",", ":"), ensure_ascii=False).encode()
        )

    expected = compact(wire) + sum(compact(row) for row in table.nodes.values())

    assert tree_enumerate.stated_graph_bytes(wire, table.nodes) == expected
    assert len(table.nodes) < 12  # the graph, not the 64 leaves
