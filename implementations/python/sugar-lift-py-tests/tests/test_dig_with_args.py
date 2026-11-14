"""The universe cue at a call site serves the callee's ONE contract.

The caller's fact is a REFERENCE (`call:A(...) == 6`). The dig at that call
site serves A's abstract contract, whatever the actuals are: a contract is
applied in one place, at prove (the nine steps, step 6 and step 9). The seek
path's own application (`applied_contract_rows`: bind the actuals, reduce the
callee body again) is deleted (#7757 item 12).
"""

import tempfile
from pathlib import Path

from sugar_lift_py_tests import lift_rpc


def _enumerate(src):
    captured = {}
    orig = lift_rpc._send_enumerate_result
    lift_rpc._send_enumerate_result = lambda mid, nodes, gaps, **kw: captured.update(
        nodes=nodes, gaps=gaps, kw=kw
    )
    try:
        root = tempfile.mkdtemp()
        Path(root, "t.py").write_text(src)

        def enum(level, at=None, seek=False):
            lift_rpc._handle_enumerate(
                1, {"level": level, "workspace_root": root, "at": at, "seek": seek}
            )
            return captured["nodes"], captured["gaps"], captured["kw"]

        files, _, _ = enum("source_files")
        fns, _, _ = enum("functions", files[0]["memento"])
        caller = [n for n in fns if "test_a" in str(n["memento"])][0]
        cs, _, _ = enum("call_sites", caller["memento"])
        uni, gaps, kw = enum("universe", cs[0]["memento"], seek=True)
        return uni, gaps, kw
    finally:
        lift_rpc._send_enumerate_result = orig


def _resolved_post(uni, kw):
    table = kw["term_tables"][0]  # cid -> value

    def resolve(v):
        if isinstance(v, dict):
            if v.get("kind") == "term-ref":
                return resolve(table[v["cid"]])
            return {k: resolve(x) for k, x in v.items()}
        if isinstance(v, list):
            return [resolve(x) for x in v]
        return v

    return resolve(uni[0]["audit"]["post"])


SUM_HELPER = (
    "def A(xs):\n"
    "    total = 0\n"
    "    for x in xs:\n"
    "        total = total + x\n"
    "    return total\n\n"
)


def _abstract_fold_post(uni, kw):
    assert len(uni) == 1
    post = _resolved_post(uni, kw)
    assert post["name"] == "="
    right = post["args"][1]
    assert right.get("kind") == "ctor" and right["name"] == "call:py.fold.Add"


def test_ground_args_serve_the_abstract_contract():
    # A([1, 2, 3]): the seek no longer reduces A's body under these actuals;
    # it serves the same contract a hole argument gets.
    uni, gaps, kw = _enumerate(
        SUM_HELPER + "def test_a():\n    assert A([1, 2, 3]) == 6\n"
    )
    assert not gaps
    _abstract_fold_post(uni, kw)


def test_hole_args_serve_the_abstract_contract():
    uni, _gaps, kw = _enumerate(
        SUM_HELPER + "def test_a(ys):\n    assert A(ys) == 6\n"
    )
    _abstract_fold_post(uni, kw)


WHILE_HELPER = (
    "def A(n):\n"
    "    i = 0\n"
    "    while i < n:\n"
    "        i = i + 1\n"
    "    return i\n\n"
)


def test_a_ground_call_never_gets_an_applied_answer():
    # A ground call no longer reduces A's body a second time under A(3): the
    # cue is A's abstract contract, or a named gap when A has none. It is
    # never the applied literal `out == 3`.
    uni, gaps, kw = _enumerate(
        WHILE_HELPER + "def test_a():\n    assert A(3) == 3\n"
    )
    if not uni:
        assert gaps, "a callee with no contract is a named gap, never a silent empty"
        return
    post = _resolved_post(uni, kw)
    assert post["args"][1].get("value") != 3
