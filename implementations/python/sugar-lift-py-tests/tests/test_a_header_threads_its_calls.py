"""What a statement evaluates before its body is threaded before the body
reads the objects its calls reach (#7757, leftovers of #8136).

``If.substitute`` threaded its test's calls before either branch; a ``with``
item, a ``match`` subject, a ``for`` iterable, a ``while`` test and a
comprehension's first iterable did not, so their bodies read an object a
source call in the header changed as it stood before the statement.  Every
such header now goes through the one rule (``container_mutation.
thread_header``): the statement's substitution threads it before its body, and
the block threads it before the rest of the statement's calls
(``havoc_after``, ``threaded_header``).  A ``return`` operand's call is
threaded by the block after the statement, so a caller of the function sees
that the call may have changed its actual.

A call of a same-file function is joined at prove (#7757 step 5): no body is
followed to learn what it did, so the body reads the object as a call may
have left it (``ReceiverAfterCall``, the one exposure rule), never as it
stood before the header ran.
"""

from __future__ import annotations

from frame_fresh import fresh
from sugar_lift_py_tests.context_manager_resolution import TreeConstructionContextV1
from sugar_lift_py_tests.floor import TermValue
from sugar_lift_py_tests.floor.list_value import ListValue
from sugar_lift_py_tests.tree_enumerate import function_universe_outcome
from sugar_lift_python_source.canonical import blake3_512_of
from sugar_source_tree.container_mutation import _identity
from sugar_source_tree.nodes import FunctionDef
from sugar_source_tree.tree import SourceFile


def _function(source: str) -> FunctionDef:
    tree = SourceFile(
        (source, "header_calls.py", blake3_512_of(source.encode())),
        construction_context=TreeConstructionContextV1.for_source_call_construction(),
    )
    return next(node for node in tree.nodes() if isinstance(node, FunctionDef))


def _reads_after_the_helper(node) -> bool:
    """Whether some read under ``node`` denotes an object as a call of a
    source helper may have left it (``ReceiverAfterCall``)."""
    return any(
        getattr(_identity(child), "kind", None) == "ReceiverAfterCall"
        for child in node.walk()
    )


def _statement(rewritten, kind: str):
    return next(node for node in rewritten.walk() if node.kind == kind)


def test_a_with_body_reads_what_its_managers_call_did() -> None:
    # ``open_it`` appends to ``acc`` and hands it back as the manager: the
    # body reads ``acc`` after the append, never the ``[]`` before the with.
    rewritten = _function(
        "def f(use):\n"
        "    acc = []\n"
        "    with open_it(acc):\n"
        "        use(acc)\n"
        "def open_it(a):\n"
        "    a.append(1)\n"
        "    return a\n"
    ).substitute({})
    statement = _statement(rewritten, "With")
    (item,) = statement.items
    assert not _reads_after_the_helper(item)
    assert any(_reads_after_the_helper(inner) for inner in statement.body)


def test_a_match_case_reads_what_its_subjects_call_did() -> None:
    rewritten = _function(
        "def f(use):\n"
        "    acc = []\n"
        "    match g(acc):\n"
        "        case _:\n"
        "            use(acc)\n"
        "def g(a):\n"
        "    a.append(1)\n"
        "    return 0\n"
    ).substitute({})
    statement = _statement(rewritten, "Match")
    assert not _reads_after_the_helper(statement.subject)
    (case,) = statement.cases
    assert any(_reads_after_the_helper(inner) for inner in case.body)


def test_a_comprehension_element_reads_what_its_iterables_call_did() -> None:
    rewritten = _function(
        "def f(use):\n"
        "    acc = []\n"
        "    return [use(acc) for x in g(acc)]\n"
        "def g(a):\n"
        "    a.append(1)\n"
        "    return a\n"
    ).substitute({})
    comprehension = _statement(rewritten, "ListComp")
    assert _reads_after_the_helper(comprehension.elt)


_EMPTY = fresh(ListValue, ())
_ONE = fresh(ListValue, (TermValue(1),))


def test_a_caller_sees_what_a_returned_call_did_to_its_actual() -> None:
    # ``h(acc)`` may change ``acc``: ``f`` never reads it as the ``[]`` it
    # held before the call.  Before step 5 (#7757) ``g``'s and ``h``'s bodies
    # were followed and ``f`` read ``[1]``; the callees' contracts do not yet
    # state their effects on their actuals (step 7), so the value is not
    # decided here.
    from sugar_lift_py_tests.floor.return_value import ReturnValue
    from sugar_lift_py_tests.floor.universe_value import UniverseValue

    outcome = function_universe_outcome(
        _function(
            "def f():\n"
            "    acc = []\n"
            "    h(acc)\n"
            "    return acc\n"
            "def h(a):\n"
            "    return g(a)\n"
            "def g(a):\n"
            "    a.append(1)\n"
        )
    )
    # ``h(acc)`` is the one unanswered call: ``f`` completes on the face
    # where it completed, and halts on the other (``completed_value()`` reads
    # a sole completion, so the completed face is taken by itself).
    from sugar_lift_py_tests.outcome import Completed

    (completed,) = [face for face in outcome.exits if isinstance(face, Completed)]
    assert outcome.halts()
    universe = completed.value
    assert isinstance(universe, UniverseValue), outcome
    (returned,) = [
        entry for entry in universe.record.statements if isinstance(entry, ReturnValue)
    ]
    assert returned.value != _EMPTY
    assert returned.value != _ONE
