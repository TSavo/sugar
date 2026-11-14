"""A call cited off the enrolled population may raise; it is never total.

``call-target-off-population`` means the export door authenticated the
callee's defining source (stdlib, an unenrolled distribution) and the
population membrane declined to project it. Inside an enrolled dependency body
``CallSiteSugar`` used to collect such a call as an ordinary completion, so
``textwrap.dedent('x')`` in a ``@contextmanager``'s enter was claimed never to
raise and ``f`` always returned 7. It is now two-faced (the #7585 law): it
completes under ``python:off_population_call.completes(...)`` and halts with an
``UndeterminedRaiseEffect`` under the complement.

A bare expression statement in a generator manager whose value is two-faced
also used to hand the call's ExitSet to the consumer as if it were the
machine's next transition (``observed: CallSiteValue``); a completed face now
advances the machine and a halted face leaves it at the statement.
"""

from __future__ import annotations

import pytest

from sugar_lift_py_tests.effect.raise_effect import UndeterminedRaiseEffect
from sugar_lift_py_tests.outcome import Completed, Halted, outcome_to_exitset
from sugar_lift_py_tests.sugar.with_source_resource_sugar import WithSourceResourceSugar
from sugar_source_tree.nodes import FunctionDef

from test_contextmanager_generator_protocol import _function_rows, _imported

_ATOM = "python:off_population_call.completes"


def _manager(enter: str) -> str:
    return (
        "from contextlib import contextmanager\n"
        "import textwrap\n"
        "@contextmanager\n"
        "def cm():\n"
        f"    {enter}\n"
        "    yield 1\n"
    )


def _faces(tree):
    func = next(n for n in tree.nodes() if isinstance(n, FunctionDef) and n.name == "f")
    return outcome_to_exitset(func.sugar().desugar()).exits


@pytest.mark.parametrize(
    "enter",
    ("textwrap.dedent('x')", "v = textwrap.dedent('x')"),
    ids=("expression", "assignment"),
)
def test_an_off_population_call_in_enter_is_two_faced(tmp_path, enter):
    opened = _imported(tmp_path, _manager(enter), "pass", contextlib_enrolled=True)
    assert _function_rows(*opened) == (
        WithSourceResourceSugar,
        [("halt", None), ("return", 7)],
    )
    faces = _faces(opened[0])
    (halt,) = [face for face in faces if isinstance(face, Halted)]
    (done,) = [face for face in faces if isinstance(face, Completed)]
    assert isinstance(halt.effect, UndeterminedRaiseEffect)
    assert halt.effect.producer_node_owner == "OffPopulationCall:python:textwrap.dedent"
    assert _ATOM in repr(done.guard) and _ATOM in repr(halt.guard)
    assert "'not'" in repr(halt.guard) and "'not'" not in repr(done.guard)


def test_the_completed_face_still_runs_the_body_and_the_halt_skips_it(tmp_path):
    opened = _imported(
        tmp_path,
        _manager("textwrap.dedent('x')"),
        "raise KeyError('k')",
        contextlib_enrolled=True,
    )
    # The enter halt never reaches the body; the completed enter runs it and
    # the body's KeyError propagates (the generator does not catch it).
    effects = []
    for face in _faces(opened[0]):
        if isinstance(face, Halted):
            effects.append(face.effect)
            continue
        # A completed arm that cannot fall through carries its raise as an
        # all-halting entry of its record; it never returns.
        from sugar_lift_py_tests.outcome import ExitSet

        statements = face.value.record.statements
        assert not any(type(e).__name__ in ("ReturnValue", "GuardedReturn") for e in statements)
        effects.extend(
            halt.effect
            for e in statements
            if isinstance(e, ExitSet) and e.halts() == e.exits
            for halt in e.halts()
        )
    kinds = sorted(
        type(e).__name__ + ":" + str(getattr(e, "exception_name", None)) for e in effects
    )
    assert kinds == ["RaiseEffect:KeyError", "UndeterminedRaiseEffect:None"]
