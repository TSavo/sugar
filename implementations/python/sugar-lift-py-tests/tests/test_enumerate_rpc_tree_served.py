"""The enumeration RPC IS the source tree enumeration.

`_handle_enumerate` drives the ladder source_files -> functions -> call_sites
-> facts straight through the typed AST tree (SourceTree/SourceFile ->
node.sugar().desugar). The factory (`_lift_file_for_enumeration`) is never
consulted on this path -- proven here by a tripwire that raises if reached.

`assert 1 == 1` is the vendor stating a fact with no call site and no
contract: the atomic formula `=(1, 1)` reaches the wire as plain JSON.
"""

import tempfile
from pathlib import Path

from sugar_lift_py_tests import lift_rpc


def _run_ladder():
    captured = {}
    orig_send = lift_rpc._send_enumerate_result
    orig_factory = lift_rpc._lift_file_for_enumeration

    def _tripwire(*_a, **_k):
        raise AssertionError(
            "FACTORY CONSULTED: the tree-served enumeration leaked into "
            "_lift_file_for_enumeration"
        )

    lift_rpc._send_enumerate_result = lambda mid, nodes, gaps, **kw: captured.update(
        nodes=nodes, gaps=gaps
    )
    lift_rpc._lift_file_for_enumeration = _tripwire
    try:
        with tempfile.TemporaryDirectory() as root:
            Path(root, "t.py").write_text("def test_one():\n    assert 1 == 1\n")

            def enum(level, at=None):
                lift_rpc._handle_enumerate(
                    1,
                    {"level": level, "workspace_root": root, "at": at, "seek": False},
                )
                return captured["nodes"]

            file_at = enum("source_files")[0]["memento"]
            fn_at = enum("functions", file_at)[0]["memento"]
            cs_at = enum("call_sites", fn_at)[0]["memento"]
            return enum("facts", cs_at)[0]["payload"]
    finally:
        lift_rpc._send_enumerate_result = orig_send
        lift_rpc._lift_file_for_enumeration = orig_factory


def test_rpc_ladder_serves_the_fact_from_the_tree():
    payload = _run_ladder()
    assert payload is not None, "assert 1 == 1 must emit a fact, not silence"
    assert payload["kind"] == "atomic"
    assert payload["name"] == "="
    values = [arg["value"] for arg in payload["args"]]
    assert values == [1, 1], f"expected =(1, 1), got {payload}"


if __name__ == "__main__":
    test_rpc_ladder_serves_the_fact_from_the_tree()
    print("ok: RPC ladder serves =(1,1) from the tree, factory untouched")
