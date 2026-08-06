"""``call_occurrence`` answers WHERE, never WHETHER-THERE-IS-A-CONTEXT.

A call's occurrence is a pure function of ``(unit.source_cid, line_col_span())``.
It takes no construction context as input and both mint sites in
``Call._construct_sugar`` computed it identically. But it was minted only under
``isinstance(context, TreeConstructionContextV1)``, and downstream code then
read ``coordinate is not None`` as "there is a context" -- the comment at the
``source_call_frame_table`` argument said so in writing.

So one field carried two answers:

    None  ==  "this call occupies no span of any source"     (never true)
    None  ==  "this tree was opened without a context"       (the real meaning)

That is #7394's conflation -- absence and lookup-failure sharing one
representation -- sitting inside the node whose whole job is to report
occurrences. And it is not hypothetical: ``_require_construction_context``
refuses only ``None`` and returns ``object``, so a context of any other type is
within the door's contract and silently produces a call with no occurrence.

These teeth pin the two claims separately. The context witness is now the
context itself; the coordinate answers only "where is this node".
"""

from __future__ import annotations

from sugar_lift_py_tests.lift_rpc import tree_construction_context_for_workspace
from sugar_lift_python_source.source_oracle import workspace_path_source
from sugar_source_tree.reporter import CollectingReporter
from sugar_source_tree.tree import SourceFile

SOURCE = '''\
def target(value):
    return value


JOINED = target("a")
'''


class _OtherContextType:
    """The SAME context, wrapped so it is not a ``TreeConstructionContextV1``.

    Every attribute read reaches the identical underlying object, so the only
    controlled variable is the context's TYPE. ``_require_construction_context``
    admits this -- it refuses ``None`` and nothing else -- which is exactly why
    the constructed value must not encode "is this the type I expected" in a
    field that means "where is this call".
    """

    def __init__(self, inner) -> None:
        self._inner = inner

    def __getattr__(self, name):
        return getattr(self._inner, name)


def _walk(node):
    yield node
    for field in getattr(node, "_child_fields", ()):
        value = getattr(node, field, None)
        for child in value if isinstance(value, tuple) else (value,):
            if hasattr(child, "_child_fields"):
                yield from _walk(child)


def _open(tmp_path, context):
    path = tmp_path / "subject.py"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(SOURCE)
    return SourceFile(
        workspace_path_source(str(path), root=str(tmp_path)),
        reporter=CollectingReporter(),
        construction_context=context,
    )


def _call_occurrences(source_file):
    """``{node: (its own occurrence, the occurrence it CONSTRUCTED)}``."""
    out = {}
    for node in _walk(source_file.root):
        if type(node).__name__ != "Call":
            continue
        constructed = getattr(node.sugar(), "call_occurrence", "<field absent>")
        span = node.line_col_span()
        out[(span.start_line, span.start_col)] = (
            node.source_occurrence(),
            constructed,
        )
    return out


def test_the_occurrence_is_a_pure_function_of_the_source(tmp_path) -> None:
    """It takes no context input, so no context can change it.

    Non-vacuity is built in: the assert compares against a coordinate that must
    exist, and the fixture is asserted to contain a call at all.
    """
    context = tree_construction_context_for_workspace(tmp_path / "a")
    contexted = _open(tmp_path / "a", context)
    othertype = _open(tmp_path / "b", _OtherContextType(context))

    own_a = {c: v[0] for c, v in _call_occurrences(contexted).items()}
    own_b = {c: v[0] for c, v in _call_occurrences(othertype).items()}
    assert own_a, "no Call in the fixture -- nothing measured"
    assert own_a == own_b, (
        "the node's own occurrence changed with the construction context, so it "
        f"is not a pure function of the source: {own_a} vs {own_b}"
    )


def test_a_constructed_call_always_carries_its_own_occurrence(tmp_path) -> None:
    """THE tooth. One variable: the context's type. Same object underneath.

    A ``None`` here does not mean "this call occupies no span" -- nothing does.
    It means the field was being read as a context witness, and a caller
    downstream cannot tell the two apart.
    """
    context = tree_construction_context_for_workspace(tmp_path / "a")
    rows = {
        "TreeConstructionContextV1": _call_occurrences(_open(tmp_path / "a", context)),
        "another context type": _call_occurrences(
            _open(tmp_path / "b", _OtherContextType(context))
        ),
    }

    print("\n=== call_occurrence on the constructed value ===")
    for label, table in rows.items():
        for coordinate, (own, constructed) in sorted(table.items()):
            print(f"    {label:28} line {coordinate[0]}:{coordinate[1]}")
            print(f"      node's own  : {own}")
            print(f"      constructed : {constructed}")

    for label, table in rows.items():
        assert table, f"no Call constructed under {label} -- nothing measured"
        for coordinate, (own, constructed) in sorted(table.items()):
            if constructed == "<field absent>":
                continue  # a MethodCallSugar carries no call_occurrence at all
            assert constructed == own, (
                f"under {label}, the call at line {coordinate[0]}:{coordinate[1]} "
                f"constructed call_occurrence={constructed!r} but its own "
                f"occurrence is {own!r}. `None` here says 'this call occupies no "
                f"span of any source', which is never true -- the field is "
                f"carrying the answer to 'was a context of the expected type "
                f"seated', and no caller downstream can tell those apart."
            )
