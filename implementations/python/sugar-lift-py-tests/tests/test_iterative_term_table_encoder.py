from __future__ import annotations

import json
import os
from pathlib import Path
import subprocess
import sys
from textwrap import dedent

from sugar_lift_py_tests.canonicalizer import encode_jcs, jcs_hash
from sugar_lift_py_tests.ir import (
    _Ctor,
    Term,
    TermTableBuilder,
    make_var,
    term_to_value,
)


def _spine(depth: int, *, name: str = "ssa") -> Term:
    term: Term = make_var("leaf")
    for index in range(depth):
        term = _Ctor(f"{name}:{index}", (term,))
    return term


def _subprocess_env() -> dict[str, str]:
    env = dict(os.environ)
    tests_pkg = Path(__file__).resolve().parents[1]
    source_root = tests_pkg / "src"
    # LiftReportPayloadDto imports pull sugar_lift_python_source transitively.
    python_source_root = tests_pkg.parent / "sugar-lift-python-source" / "src"
    env["PYTHONPATH"] = os.pathsep.join(
        [
            str(source_root),
            str(python_source_root),
            env.get("PYTHONPATH", ""),
        ]
    ).rstrip(os.pathsep)
    return env


def test_payload_to_rpc_encodes_a_5000_deep_spine_without_process_death() -> None:
    script = dedent("""
        from sugar_lift_py_tests.ir import _Ctor, make_var
        from sugar_lift_py_tests.kit_rpc import LiftReportPayloadDto

        term = make_var("leaf")
        for index in range(5_000):
            term = _Ctor(f"ssa:{index}", (term,))

        class DeepContract:
            name = "synthetic::deep-spine"

            def to_rpc_with_term_table(self, table):
                return {
                    "kind": "contract",
                    "name": self.name,
                    "inv": {
                        "kind": "atomic",
                        "name": "holds",
                        "args": [table.reference(term)],
                    },
                }

        wire = LiftReportPayloadDto(
            ir=[DeepContract()], source_ledger={}
        ).to_rpc()
        assert len(wire["termTable"]) == 5_001
        print("ENCODE-OK", len(wire["termTable"]))
        """)

    completed = subprocess.run(
        [sys.executable, "-c", script],
        env=_subprocess_env(),
        capture_output=True,
        text=True,
        timeout=20,
    )

    assert completed.returncode == 0, (
        f"deep payload encoder died with returncode={completed.returncode}\n"
        f"stdout:\n{completed.stdout}\nstderr:\n{completed.stderr}"
    )
    assert "ENCODE-OK 5001" in completed.stdout


class _RecursiveControlTable:
    """Bounded copy of the pre-#4573 writer for byte-identity testimony."""

    def __init__(self) -> None:
        self.nodes: dict[str, dict[str, object]] = {}

    def reference(self, term: Term) -> dict[str, str]:
        cid = jcs_hash(term_to_value(term))
        if cid not in self.nodes:
            self.nodes[cid] = self._node(term)
        return {"kind": "term-ref", "cid": cid}

    def _node(self, term: Term) -> dict[str, object]:
        if isinstance(term, _Ctor):
            return {
                "kind": "ctor",
                "name": term.name,
                "args": [self.reference(arg) for arg in term.args],
            }
        return json.loads(encode_jcs(term_to_value(term)))


def test_iterative_table_is_byte_identical_to_recursive_bounded_control() -> None:
    shared = _Ctor("shared", (make_var("x"),))
    control = _Ctor(
        "root",
        (
            _spine(40),
            _Ctor("branch", (shared, shared)),
            shared,
        ),
    )
    iterative = TermTableBuilder()
    recursive = _RecursiveControlTable()

    iterative_ref = iterative.reference(control)
    recursive_ref = recursive.reference(control)

    assert iterative_ref == recursive_ref
    assert encode_jcs(_json_value(iterative.nodes)) == encode_jcs(
        _json_value(recursive.nodes)
    )


def test_deep_pandas_shaped_construct_encodes_without_recursion() -> None:
    term = _spine(2_000, name="pandas:series:subscript")
    table = TermTableBuilder()

    root = table.reference(term)

    assert root["kind"] == "term-ref"
    assert len(table.nodes) == 2_001


def _rpc_spine(depth: int, *, name: str = "ssa") -> dict:
    term: dict = {"kind": "var", "name": "leaf"}
    for index in range(depth):
        term = {"kind": "ctor", "name": f"{name}:{index}", "args": [term]}
    return term


class _RecursiveControlRpcTable:
    """Bounded copy of the pre-#4573 residual reference_rpc writer."""

    def __init__(self) -> None:
        self.nodes: dict[str, dict[str, object]] = {}

    def reference_rpc(self, term: dict) -> dict[str, str]:
        from sugar_lift_py_tests.ir import _json_like_to_value

        cid = jcs_hash(_json_like_to_value(term))
        if cid not in self.nodes:
            kind = term.get("kind")
            if kind == "ctor":
                self.nodes[cid] = {
                    "kind": "ctor",
                    "name": term["name"],
                    "args": [self.reference_rpc(arg) for arg in term.get("args", [])],
                }
            else:
                self.nodes[cid] = json.loads(encode_jcs(_json_like_to_value(term)))
        return {"kind": "term-ref", "cid": cid}


def test_reference_rpc_encodes_a_5000_deep_spine_without_recursion() -> None:
    """Source-lifter door residual: reference_rpc must not native-recurse."""
    script = dedent("""
        from sugar_lift_py_tests.ir import TermTableBuilder

        term = {"kind": "var", "name": "leaf"}
        for index in range(5_000):
            term = {"kind": "ctor", "name": f"rpc-ssa:{index}", "args": [term]}

        table = TermTableBuilder()
        root = table.reference_rpc(term)
        assert root["kind"] == "term-ref"
        assert len(table.nodes) == 5_001
        print("RPC-ENCODE-OK", len(table.nodes))
        """)

    completed = subprocess.run(
        [sys.executable, "-c", script],
        env=_subprocess_env(),
        capture_output=True,
        text=True,
        timeout=20,
    )

    assert completed.returncode == 0, (
        f"deep reference_rpc encoder died with returncode={completed.returncode}\n"
        f"stdout:\n{completed.stdout}\nstderr:\n{completed.stderr}"
    )
    assert "RPC-ENCODE-OK 5001" in completed.stdout


def test_iterative_reference_rpc_is_byte_identical_to_recursive_bounded_control() -> (
    None
):
    shared = {"kind": "ctor", "name": "shared", "args": [{"kind": "var", "name": "x"}]}
    control = {
        "kind": "ctor",
        "name": "root",
        "args": [
            _rpc_spine(40),
            {"kind": "ctor", "name": "branch", "args": [shared, shared]},
            shared,
        ],
    }
    iterative = TermTableBuilder()
    recursive = _RecursiveControlRpcTable()

    iterative_ref = iterative.reference_rpc(control)
    recursive_ref = recursive.reference_rpc(control)

    assert iterative_ref == recursive_ref
    assert encode_jcs(_json_value(iterative.nodes)) == encode_jcs(
        _json_value(recursive.nodes)
    )


def _json_value(value: object):
    from sugar_lift_py_tests.ir import _json_like_to_value

    return _json_like_to_value(value)
