"""A generator expression's per-member halts leave where it is pulled, not
where it is made (#7757: a halt is never dropped, and never placed where
Python does not raise it).

Python evaluates a generator expression's outermost iterable and runs
``iter`` on it where the generator is made; each ``next`` of that iterator
and each element expression run when a consumer pulls (``list(g)``, ``for x
in g``, ``sum(g)``, ``next(g)``).  #8844 stated the per-member ``next`` halt,
and the element's halts with it, at the generator's creation, so a ``try``
around the consumption never took them and a generator never consumed
halted anyway.  A generator pulled later now carries its pull
(``GeneratorValue.pulled``) and states it at the consumer.
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


_ELEMENT_CALL = "h(x)"


def _element_call_span(source: str) -> tuple[int, int]:
    """The ``[start, end)`` of the element's ``h(x)`` call in ``source``:
    the one inside the generator's parentheses, never ``def h(x)``."""
    start = source.index("(" + _ELEMENT_CALL + " for") + 1
    return start, start + len(_ELEMENT_CALL)


def _element_halts(outcome, source: str) -> list:
    """The halts the element's call of ``h`` left by: an unanswered call's
    halt (owner ``UnknownCallee:<target>``) whose site is that ``h(x)`` call
    in the source.  The halt is identified by the call it was raised at, not
    by how the target is spelt: with no workspace the target is ``h``'s
    content-addressed definition site (``<source cid>@0:33#...``), with one
    it is ``h``'s join symbol, and neither names ``h`` the same way (the
    scorecard at d95c22a49 and CI run 43789294103 read the stated halt as
    dropped).  A halt dropped at the pull still leaves no halt at that
    site, so the pulled test still fails then."""
    span = _element_call_span(source)
    found = []
    for halt in outcome.halts():
        effect = halt.effect
        owner = str(getattr(effect, "producer_node_owner", "") or "")
        if not owner.startswith("UnknownCallee:"):
            continue
        site_span = getattr(getattr(effect, "site", None), "span", None)
        if site_span is None:
            continue
        if (site_span.start, site_span.end) == span:
            found.append(halt)
    return found


def _described(outcome) -> str:
    """Every exit of ``outcome``, one line each: a halt's owner and effect,
    a completion's value type, and what the outcome owes, so a failure names
    what the pull left by instead of a truncated ``ExitSet`` repr."""
    lines = []
    for exit_ in outcome.exits:
        effect = getattr(exit_, "effect", None)
        if effect is None:
            value = getattr(exit_, "value", None)
            lines.append(f"{type(exit_).__name__}: value={type(value).__name__}")
        else:
            owner = getattr(effect, "producer_node_owner", None)
            lines.append(
                f"{type(exit_).__name__}: owner={owner!r} "
                f"effect={type(effect).__name__} {effect!r}"
            )
    lines.append(f"owed={outcome.owed_items()!r}")
    return "\n".join(lines)


_H ="def h(x):\n    raise ValueError(x)\n\n\n"


def test_a_generator_never_pulled_states_no_member_halt() -> None:
    source = (
        _H + "def f():\n"
        "    xs = [1, 2]\n"
        "    g = (h(x) for x in xs)\n"
        "    return 1\n"
    )
    outcome = _outcome(source, "f")
    assert not _element_halts(outcome, source), _described(outcome)


def test_a_generator_pulled_by_a_for_states_the_member_halt_there() -> None:
    source = (
        _H + "def f():\n"
        "    xs = [1, 2]\n"
        "    g = (h(x) for x in xs)\n"
        "    for y in g:\n"
        "        pass\n"
        "    return 1\n"
    )
    outcome = _outcome(source, "f")
    assert _element_halts(outcome, source), _described(outcome)


def test_a_generator_made_in_a_list_call_halts_there() -> None:
    # Consumed whole in place: the pull is the call that made it.
    outcome = _outcome(
        _H + "def f():\n    xs = [1, 2]\n    return list(h(x) for x in xs)\n",
        "f",
    )
    assert outcome.halts(), outcome


_HANDLED = (
    _H + "def test_f():\n"
    "    xs = [1, 2]\n"
    "    g = (h(x) for x in xs)\n"
    "    ok = False\n"
    "    try:\n"
    "        list(g)\n"
    "    except ValueError:\n"
    "        ok = True\n"
    "    assert ok == {x}\n"
)


def test_the_handler_around_the_pull_is_never_ruled_out(tmp_path: Path) -> None:
    # Python: ``list(g)`` pulls ``h(1)``, which raises inside the ``try``,
    # and the handler runs.  Stated at the generator's creation, outside the
    # ``try``, the raise refuted every claim after it.
    result = run_source_through_real_solver(tmp_path / "t", _HANDLED.format(x="True"))
    assert result.verdict != "unsat"


def test_the_lie_that_the_handler_never_runs_is_never_sat(tmp_path: Path) -> None:
    result = run_source_through_real_solver(tmp_path / "l", _HANDLED.format(x="False"))
    assert result.verdict != "sat"
