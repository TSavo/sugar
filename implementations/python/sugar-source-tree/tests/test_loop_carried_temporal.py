"""Loop-carried bindings advance per iteration and halt at the live snapshot.

Each file is opened through the one construction door under a workspace
root, as the lift opens it: a loop run in hand ends at its iterator's own
``StopIteration``, which cites a workspace-relative locus."""

from __future__ import annotations

import tempfile
from pathlib import Path

from sugar_lift_py_tests.effect import RaiseEffect
from sugar_lift_py_tests.lift_rpc import open_source_file_for_construction
from sugar_lift_py_tests.outcome import ExitSet
from sugar_lift_py_tests.sugar.function_universe_sugar import _ReducedBlock


def _function(source: str):
    root = Path(tempfile.mkdtemp(prefix="loop-carried-"))
    path = root / "subject.py"
    path.write_text(source, encoding="utf-8")
    return next(open_source_file_for_construction(path, root=root).functions())


def test_concrete_loop_rebinds_carried_value_each_iteration() -> None:
    post = (
        _function(
            "def arbitrary():\n"
            "    carried = 0\n"
            "    for item in (1, 2, 3):\n"
            "        carried = carried + item\n"
            "    return carried\n"
        )
        .sugar()
        .desugar()
        .completed_value()
        .post()
    )
    assert post.args[1].value == 6


_HALTING = (
    "def arbitrary(limit, stop):\n"
    "    carried = 0\n"
    "    while carried < limit:\n"
    "        carried = carried + 1\n"
    "        if carried == stop:\n"
    "            raise ValueError(carried)\n"
    "        carried = 99\n"
    "    return carried\n"
)


def test_mid_iteration_halt_retains_exact_pre_halt_binding_snapshot() -> None:
    function = _function(_HALTING)
    constructed = function.sugar()

    loop = constructed.statements[1]
    assert len(loop.outward_faces) == 1
    snapshot = loop.outward_faces[0].state
    assert len(snapshot) == 1
    # ``carried`` at the raise is what ``carried = carried + 1`` bound: a
    # reference to THAT statement's evaluation (its target's span), never to
    # the later ``carried = 99`` store and never the pre-loop ``0``.
    state = snapshot[0].state
    assert type(state).__name__ == "EvaluationRef", state
    assert state.span.start == _HALTING.index("carried = carried + 1")
    assert state.span.start != _HALTING.index("carried = 99")
    assert state.span.start != _HALTING.index("carried = 0")

    # The raise is kept where the function is reduced: a ``ValueError`` halt
    # whose state is the record it halted with.
    outcome = function.sugar().desugar()
    assert isinstance(outcome, ExitSet), outcome
    raised = [
        halt
        for halt in outcome.halts()
        if isinstance(halt.effect, RaiseEffect)
        and halt.effect.exception_name == "ValueError"
    ]
    assert raised, outcome.halts()
    assert all(isinstance(halt.state, _ReducedBlock) for halt in raised)
