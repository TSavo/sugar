"""``str.join`` iterates its argument through the one iterator path and
checks each member is a ``str`` (#7757, step 6; a halt is never dropped).

``sep.join(it)`` over an iterable the cited fold did not decide (a formal, a
call's result, a container holding an opaque member) completed as the
``STR_JOIN`` coordinate with no halt.  CPython's ``PyUnicode_Join`` runs
``iter`` and every ``next`` on it, either of which may raise, and raises
``TypeError`` for a member that is not a ``str``.  It now runs
``iterator_operation.iterated`` then ``stepped`` (a generator is pulled
there, as any consumer pulls it), and each member not known to be a ``str``
is a two-faced ``TypeError`` halt that owes the undecided member
(``string_value._joined``).
"""

from __future__ import annotations

from pathlib import Path

from sugar_lift_py_tests.witness_harness import run_source_through_real_solver


def _outcome(source: str, name: str):
    from sugar_lift_py_tests.context_manager_resolution import (
        TreeConstructionContextV1,
    )
    from sugar_lift_py_tests.tree_enumerate import function_universe_outcome
    from sugar_lift_python_source.canonical import blake3_512_of
    from sugar_source_tree.nodes import FunctionDef
    from sugar_source_tree.tree import SourceFile

    tree = SourceFile(
        (source, "test_witness.py", blake3_512_of(source.encode())),
        construction_context=TreeConstructionContextV1.for_test_without_workspace(),
    )
    (function,) = tuple(
        node
        for node in tree.nodes()
        if isinstance(node, FunctionDef) and node.name == name
    )
    return function_universe_outcome(function)


def test_a_member_not_known_to_be_a_str_may_raise_type_error() -> None:
    # ``[x]`` is a list in hand whose member's type is not decided: iterating
    # it cannot raise, and its member's ``str`` check is a ``TypeError`` face.
    from sugar_lift_py_tests.outcome import Halted

    outcome = _outcome('def f(x):\n    return "".join([x])\n', "f")
    raised = [
        exit_.effect
        for exit_ in outcome.exits
        if isinstance(exit_, Halted)
        and getattr(exit_.effect, "exception_name", None) == "TypeError"
    ]
    assert raised, outcome


_COMPLETES = """\
def f(xs):
    return "".join(xs)


def test_f():
    completed = False
    try:
        f([1, 2])
        completed = True
    except Exception:
        pass
    assert completed == {v}
"""


def test_a_claim_that_join_over_a_formal_always_completes_is_never_sat(
    tmp_path: Path,
) -> None:
    # ``f``'s contract owes its formal's iteration and each member's ``str``
    # check: the claim that ``f`` completed is never satisfiable on that
    # contract (Python raises ``TypeError`` for ``[1, 2]``).
    result = run_source_through_real_solver(
        tmp_path / "l", _COMPLETES.format(v="True")
    )
    assert result.verdict != "sat"


def test_the_raise_join_states_is_never_refuted(tmp_path: Path) -> None:
    # The halt is a face of ``f``'s contract, so the truthful claim that the
    # handler ran is never ``unsat``.
    result = run_source_through_real_solver(
        tmp_path / "t", _COMPLETES.format(v="False")
    )
    assert result.verdict != "unsat"
