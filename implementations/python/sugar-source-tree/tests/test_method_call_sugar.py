"""The attribute callee: `<receiver>.<name>(<args>)` -- the census's largest
family (61%). A composition: receiver reduces like any value; the call stands as
the method coordinate `call:<name>(receiver, args)`; chains compose; the
receiver rides as runtime_dispatch_receiver for a future type-aware dig."""

import tempfile
from pathlib import Path

from sugar_lift_py_tests.lift_rpc import open_source_file_for_construction
from sugar_lift_py_tests.outcome import Completed, ExitSet
from sugar_lift_py_tests.outcome.exit_set import _is_true
from sugar_source_tree.reporter import CollectingReporter

from native_carrier_testimony import undecided_function_value


def _fn(src):
    """The one function of ``src``, opened through the one construction door
    under its own workspace: an ``assert`` halts at a ground exit whose
    locus is workspace-relative (``ground_exit``)."""
    root = Path(tempfile.mkdtemp())
    path = root / "m.py"
    path.write_text(src, encoding="utf-8")
    source_file = open_source_file_for_construction(
        path, root=root, reporter=CollectingReporter()
    )
    return next(source_file.functions())


def _called(term):
    """The call a ``python:call_result(<call term>, <occurrence>)`` names:
    one evaluation of a call nothing answered (``_occurrence_result``)."""
    assert term.name == "python:call_result", term
    return term.args[0]


def _out(src):
    """The call term the function returns.

    A method call nothing answers is the unanswered call's two faces
    (``UnknownCalleeCallV1``): it completes only under its own completes
    atom, with ``python:call_result(<call term>, <occurrence>)`` as its
    value, and its halt is kept beside it."""
    outcome = _fn(src).sugar().desugar()
    assert isinstance(outcome, ExitSet), outcome
    assert any(
        str(getattr(halt.effect, "producer_node_owner", "")).startswith(
            "UnknownCallee:"
        )
        for halt in outcome.halts()
    ), outcome.exits
    completed = [e for e in outcome.normalize().exits if isinstance(e, Completed)]
    assert len(completed) == 1, outcome.exits
    assert not _is_true(completed[0].guard), completed[0].guard
    return _called(completed[0].value.post().args[1])


def test_method_call_is_the_method_coordinate():
    # A method on a formal is the dispatched call (``receiver_dispatch``).
    t = _out("def A(z):\n    return z.bit_length()\n")
    assert t.name == "call:dispatch:bit_length"
    assert t.args[0].name == "z"  # the receiver is the first coordinate operand


def test_method_chains_compose():
    # z.get(k).strip() -> call:strip(call_result(call:dispatch:get(z, k, ...)))
    t = _out("def A(z, k):\n    return z.get(k).strip()\n")
    assert t.name == "call:strip"
    inner = _called(t.args[0])
    assert inner.name == "call:dispatch:get"
    assert inner.args[0].name == "z" and inner.args[1].name == "k"


def test_assert_consumes_the_coordinate():
    # The equality over the formal is the undecided equality's two faces: the
    # universe completes under its own completes atom (#7757, audit row NEW-1).
    inv = undecided_function_value(
        _fn("def A(s):\n    assert s.upper() == s\n    return s\n"),
        owner="UndecidedCompare:Eq",
    ).invs()[0]
    # Keyed per evaluation (#7757 NEW-1): the truth of
    # ``python:compare_result("Eq", call:upper(s), s, <key>)``.
    assert inv.name == "python:truth_result"
    compared = inv.args[0]
    assert compared.name == "python:compare_result"
    assert compared.args[0].value == "Eq"
    assert _called(compared.args[1]).name == "call:dispatch:upper"


def test_keyword_args_lift():
    t = _out("def A(z):\n    return z.get(1, default=2)\n")
    assert t.name == "call:dispatch:get"
    (kwarg,) = [arg for arg in t.args if arg.name == "py.kwarg"]
    assert kwarg.args[0].value == "default"
    assert kwarg.args[1].value == 2


def _attribute_operations(node, found, depth=0):
    """Every ``python:attribute_result("<name>", <receiver>, <key>)`` in
    ``node`` -- a parameter's read, keyed per evaluation
    (``floor_value.undecided_attribute_result``): ``(receiver name,
    attribute name)``."""
    if depth > 64:
        return found
    if getattr(node, "name", None) == "python:attribute_result":
        found.append((getattr(node.args[1], "name", None), node.args[0].value))
    for child in (
        *(getattr(node, "args", ()) or ()),
        *(getattr(node, "operands", ()) or ()),
    ):
        _attribute_operations(child, found, depth + 1)
    return found


def test_spread_keyword_args_build_reference_method_call():
    """Expected shape changed (#7757 audit 2 row NEW-1): the callee read
    ``z.get`` on the formal ``z`` was an ``attribute_named`` carrier waiting
    on a caller's actual.  It is the one two-faced undecided read
    (``SymbolicValue.attribute``): its halt, naming ``z`` and ``get``, is
    kept, and nothing completes with one value."""
    outcome = _fn("def A(z, d):\n    return z.get(1, **d)\n").sugar().desugar()
    assert isinstance(outcome, ExitSet), outcome
    assert outcome.completed_value() is None
    (halt,) = [
        face
        for face in outcome.halts()
        if face.effect.producer_node_owner == "SymbolicValue.attribute"
    ]
    assert _attribute_operations(halt.guard, []) == [("z", "get")]


def test_spread_call_is_a_constructed_method_argument_coordinate():
    t = _out(
        "def A(cls, values):\n"
        "    value = str(*values)\n"
        "    return str.__new__(cls, value)\n"
    )

    assert t.name == "call:__new__"
    spread = _called(t.args[2])
    assert spread.name == "python:call"
    assert spread.args[0].value == "str"
    assert spread.args[1].name == "python:starred_arg"
    assert spread.args[1].args[0].name == "values"


if __name__ == "__main__":
    test_method_call_is_the_method_coordinate()
    test_method_chains_compose()
    test_assert_consumes_the_coordinate()
    test_keyword_args_lift()
    print("ok: method calls -- coordinate, chains, assert; kwargs/computed loud")
