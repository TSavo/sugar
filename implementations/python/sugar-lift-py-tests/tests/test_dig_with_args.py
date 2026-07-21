"""The dig-with-args: a call IS substitution, drained at the universe cue.

The caller's fact is a REFERENCE (`call:A(array(1,2,3)) == 6`); the dig at that
call site serves A's contract AS APPLIED -- ground args substitute into the
callee body, the loop unrolls there, and the fold coordinate collapses to the
literal: post `out == 6`. An arg still carrying a hole (a free name) leaves the
abstract contract standing -- the callable floor.
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


def test_ground_args_serve_the_applied_contract():
    # A([1, 2, 3]) dug -> the fold collapses: post out == 6.
    uni, gaps, kw = _enumerate(
        SUM_HELPER + "def test_a():\n    assert A([1, 2, 3]) == 6\n"
    )
    assert len(uni) == 1 and not gaps
    post = _resolved_post(uni, kw)
    assert post["name"] == "="
    assert post["args"][0] == {"kind": "var", "name": "out"}
    assert post["args"][1]["value"] == 6


def test_hole_args_serve_the_abstract_contract():
    # A(ys) where ys is the caller's own formal: the pre is still a hole, so
    # the curried (abstract) contract stands -- post over the fold coordinate,
    # not a literal.
    uni, gaps, kw = _enumerate(
        SUM_HELPER + "def test_a(ys):\n    assert A(ys) == 6\n"
    )
    assert len(uni) == 1
    post = _resolved_post(uni, kw)
    assert post["name"] == "="
    right = post["args"][1]
    assert right.get("kind") == "ctor" and right["name"] == "call:py.fold.Add"


if __name__ == "__main__":
    test_ground_args_serve_the_applied_contract()
    test_hole_args_serve_the_abstract_contract()
    test_applied_dig_fires_even_when_the_abstract_universe_is_a_gap()
    print("ok: dig-with-args -- ground fills and collapses, a hole stays curried")


WHILE_HELPER = (
    "def A(n):\n"
    "    i = 0\n"
    "    while i < n:\n"
    "        i = i + 1\n"
    "    return i\n\n"
)


def test_applied_dig_fires_even_when_the_abstract_universe_is_a_gap():
    # The symbolic while has NO abstract universe (loud) -- but a ground call
    # fills n, the condition grounds, and the existing unroll fires: the dig
    # serves out == 3. A symbolic while needed no coordinate; it was a
    # substitute all along.
    uni, gaps, kw = _enumerate(WHILE_HELPER + "def test_a():\n    assert A(3) == 3\n")
    assert len(uni) == 1
    post = _resolved_post(uni, kw)
    assert post["args"][1]["value"] == 3
