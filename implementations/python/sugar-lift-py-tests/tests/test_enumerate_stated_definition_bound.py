"""A definition whose rows cannot be stated inline is refused by name.

A proof states every term inline (#7843): the fold resolves each term-ref a
row carries into its term before mint.  A row whose term DAG is small can
state a term many times its size (a subterm every arm shares, written once
per arm), and past the transport's finite-or-refuse bound the WHOLE file's
response was swapped for a marker with no ``kind``: mint ended the file on
``lift response missing `kind` field`` (pandas ``core/interchange/utils.py``
and ``io/formats/style_render.py``, run 43960179946).  Now the definition
past the bound is its own ``undecided`` row, by the one refusal rule, and
the file is served.  Twins at the real JSON-RPC door: past the bound the
function is refused by name; within it the same row is served as stated.
"""

from __future__ import annotations

import json

from sugar_lift_py_tests import lift_rpc, tree_enumerate
from sugar_lift_py_tests.ir import (
    TermTableBuilder,
    atomic,
    ctor,
    make_var,
    str_const,
)


def _doubled(depth: int):
    """A term whose DAG has ``depth + 1`` nodes and whose inline statement
    has ``2 ** depth`` leaves: each level names the one below twice."""
    term = make_var("x")
    for _ in range(depth):
        term = ctor("pair", [term, term])
    return term


class _Row:
    def __init__(self, term):
        self.term = term

    def to_rpc_with_term_table(self, table):
        return {
            "kind": "contract",
            "post": table.formula(atomic("=", [make_var("out"), self.term])),
        }


def _serve_universe(tmp_path, monkeypatch, depth: int) -> dict:
    subject = tmp_path / "subject.py"
    subject.write_text("def subject():\n    return 1\n", encoding="utf-8")

    def stated_contract_rows(fn, file_rel):
        return tree_enumerate.function_def_memento(fn, file_rel), [
            _Row(_doubled(depth))
        ]

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


def test_a_definition_past_the_bound_is_its_refused_member(tmp_path, monkeypatch):
    """POSITIVE. 2**12 leaves inline, past the bound: the function's one
    `undecided` row names the bound; the file is served, not ended."""
    response = _serve_universe(tmp_path, monkeypatch, depth=12)

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
    # The refused row states no term: nothing of the doubled term is carried.
    assert "termTable" not in result


def test_a_definition_within_the_bound_is_served_as_stated(tmp_path, monkeypatch):
    """DISCRIMINATING. The same row with 2**4 leaves states within the bound:
    it is served as the contract row, its term by reference through the
    response's own table, never refused for its shape."""
    response = _serve_universe(tmp_path, monkeypatch, depth=4)

    assert "error" not in response, response
    result = response["result"]
    (node,) = result["nodes"]
    audit = node["audit"]
    assert audit["kind"] == "contract"
    reference = audit["post"]["args"][1]
    assert reference["kind"] == "term-ref"
    assert reference["cid"] in result["termTable"]


def _resolved(value, nodes):
    if isinstance(value, dict) and value.get("kind") == "term-ref":
        node = nodes[value["cid"]]
        return _resolved(node, nodes)
    if isinstance(value, dict):
        return {key: _resolved(child, nodes) for key, child in value.items()}
    if isinstance(value, list):
        return [_resolved(child, nodes) for child in value]
    return value


def test_the_measure_is_the_resolved_statements_length() -> None:
    """The size the bound reads is exactly the compact serialization of the
    row with every term-ref resolved, as the fold resolves it -- read off the
    DAG, never by building the expansion."""
    table = TermTableBuilder()
    wire = [_Row(_doubled(6)).to_rpc_with_term_table(table), {"kind": "x", "n": []}]

    expanded = json.dumps(
        _resolved(wire, table.nodes), separators=(",", ":"), ensure_ascii=False
    ).encode("utf-8")

    assert tree_enumerate.stated_inline_bytes(wire, table.nodes) == len(expanded)
    assert len(table.nodes) < 12  # the DAG, not the 64 leaves


def test_a_lone_surrogate_is_measured_as_the_bytes_the_wire_carries() -> None:
    """pandas ``tests/base/test_unique.py`` (and four more files, lane run
    44005532504) hold ``"\\ud83d"``: the measure's plain ``.encode("utf-8")``
    raised, and the whole file's mint died with no proof.  The wire carries a
    lone surrogate as U+FFFD (``_rpc_canonical_bytes``, the bytes the term
    table mints CIDs from), so the measure counts exactly those bytes; it
    never counts the six-byte ``\\ud83d`` escape nor the string as absent."""
    table = TermTableBuilder()
    lone = "\ud83d!"
    row = _Row(ctor("pair", [str_const(lone), str_const(lone)]))
    wire = [row.to_rpc_with_term_table(table), {"kind": "x", "s": lone}]

    expanded = json.dumps(
        _resolved(wire, table.nodes), separators=(",", ":"), ensure_ascii=False
    )
    on_wire = expanded.replace("\ud83d", "�").encode("utf-8")

    measured = tree_enumerate.stated_inline_bytes(wire, table.nodes)
    assert measured == len(on_wire)
    escaped = expanded.replace("\ud83d", "\\ud83d").encode("utf-8")
    assert measured < len(escaped)


def _memento(line: int):
    from types import SimpleNamespace

    return SimpleNamespace(
        file="subject.py", span=SimpleNamespace(start_line=line, start_col=0)
    )


def test_a_definition_past_the_files_bound_is_refused_and_the_rest_served(
    monkeypatch,
) -> None:
    """numpy ``ma/tests/test_core.py`` (lane at 13e3413ad): every definition
    within its own bound, the file's response past the transport's, swapped
    whole (``emitted `kind: ""```).  Now the definition that would carry the
    file past ``STATED_FILE_BYTE_BOUND`` is refused by name, and a later one
    that still fits is served: a refused definition states nothing, so it
    spends none of the file's bound."""
    from sugar_source_tree.panic import SugarNotWritten

    table = TermTableBuilder()
    big = [_Row(_doubled(6))]
    one = tree_enumerate.stated_inline_bytes(
        [row.to_rpc_with_term_table(table) for row in big], table.nodes
    )
    small = [_Row(make_var("y"))]
    monkeypatch.setattr(tree_enumerate, "STATED_FILE_BYTE_BOUND", one + one // 2)
    stated = tree_enumerate.StatedBytes()

    served = tree_enumerate.stated_rows(big, table, _memento(1), stated)
    assert len(served) == 1 and stated.total == one

    try:
        tree_enumerate.stated_rows(big, table, _memento(9), stated)
    except SugarNotWritten as refusal:
        assert "bound of one file" in refusal.observed
    else:
        raise AssertionError("the definition past the file's bound was served")
    assert stated.total == one

    assert len(tree_enumerate.stated_rows(small, table, _memento(20), stated)) == 1
    assert one < stated.total <= tree_enumerate.STATED_FILE_BYTE_BOUND
