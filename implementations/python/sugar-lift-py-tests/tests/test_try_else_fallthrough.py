"""try/else — genuine fall-through only, exact pre-exit state.

Laws (standing lane after #6725):

1. ``else`` runs only on a genuine body Completed fall-through (no raise).
2. ``else`` never runs after a body halt — whether the halt is caught or not.
3. ``else`` reduces against the exact pre-exit body state (body bindings visible).
4. Handler path does not feed else (else is not a second handler).
5. Guarded alternatives: complete face takes else; halt face takes handler —
   they do not cross.

Does not touch ExitSet algebra, carrier, or assertion/resource routing.
"""

from __future__ import annotations

from sugar_lift_py_tests.context_manager_resolution import TreeConstructionContextV1
from sugar_lift_py_tests.effect.raise_effect import RaiseEffect
from sugar_lift_py_tests.floor.return_value import ReturnValue
from sugar_lift_py_tests.outcome import Complete, Incomplete
from sugar_lift_py_tests.outcome.exit_set import ExitSet, Halted
from sugar_lift_python_source.canonical import blake3_512_of
from sugar_source_tree.tree import SourceFile


def _desugar(source: str, *, name: str = "try_else.py"):
    tree = SourceFile(
        (source, name, blake3_512_of(source.encode("utf-8"))),
        construction_context=TreeConstructionContextV1.for_source_call_construction(),
    )
    return list(tree.functions())[-1].sugar().desugar()


def _return_values(outcome) -> list:
    assert isinstance(outcome, Complete), outcome
    return [
        s.value.value if hasattr(s.value, "value") else s.value
        for s in outcome.value.record.statements
        if isinstance(s, ReturnValue)
    ]


def _halt_effect(outcome) -> RaiseEffect:
    if isinstance(outcome, Incomplete):
        assert isinstance(outcome.effect, RaiseEffect), type(outcome.effect)
        return outcome.effect
    if isinstance(outcome, ExitSet):
        halted = [face for face in outcome.exits if isinstance(face, Halted)]
        assert len(halted) == 1, outcome.exits
        assert isinstance(halted[0].effect, RaiseEffect)
        return halted[0].effect
    raise AssertionError(f"expected halt, got {type(outcome)}")


# ---------------------------------------------------------------------------
# else runs only on genuine body fall-through
# ---------------------------------------------------------------------------


def test_else_runs_on_raise_free_body_fallthrough():
    """Body completes without raise → else runs; else return is the exit."""
    outcome = _desugar(
        "def f():\n"
        "    try:\n"
        "        x = 1\n"
        "    except ValueError:\n"
        "        return 0\n"
        "    else:\n"
        "        return 2\n",
        name="else_fallthrough.py",
    )
    assert _return_values(outcome) == [2]


def test_else_does_not_run_when_raise_is_caught():
    """Caught body halt is still a halt — handler wins, else is skipped."""
    outcome = _desugar(
        "def f():\n"
        "    try:\n"
        "        raise ValueError\n"
        "    except ValueError:\n"
        "        return 1\n"
        "    else:\n"
        "        return 2\n",
        name="else_not_after_caught.py",
    )
    vals = _return_values(outcome)
    assert vals == [1], vals
    assert 2 not in vals


def test_else_does_not_run_when_raise_is_uncaught():
    """Unmatched halt propagates — else never sees the incomplete path."""
    outcome = _desugar(
        "def f():\n"
        "    try:\n"
        "        raise ValueError\n"
        "    except KeyError:\n"
        "        return 1\n"
        "    else:\n"
        "        return 2\n",
        name="else_not_after_uncaught.py",
    )
    effect = _halt_effect(outcome)
    assert effect.exception_name == "ValueError"


# ---------------------------------------------------------------------------
# Exact pre-exit state: else sees body bindings, not handler bindings
# ---------------------------------------------------------------------------


def test_else_sees_exact_body_pre_exit_binding():
    """else reduces against body completion state — ``y`` from body is visible."""
    outcome = _desugar(
        "def f():\n"
        "    try:\n"
        "        y = 5\n"
        "    except ValueError:\n"
        "        pass\n"
        "    else:\n"
        "        return y\n",
        name="else_body_state.py",
    )
    assert _return_values(outcome) == [5]


def test_else_path_does_not_run_after_handler_so_handler_local_is_not_else_exit():
    """Handler local ``z`` is not an else exit — else is skipped on halt."""
    outcome = _desugar(
        "def f():\n"
        "    try:\n"
        "        raise ValueError\n"
        "    except ValueError as e:\n"
        "        z = 9\n"
        "    else:\n"
        "        return z\n",
        name="else_not_handler_local.py",
    )
    # else did not run: no return 9 from else.
    if isinstance(outcome, Complete):
        assert 9 not in _return_values(outcome)
    else:
        # Halted residual would also prove else didn't complete the function.
        assert not isinstance(outcome, Complete)


# ---------------------------------------------------------------------------
# Guarded alternatives: complete face → else; halt face → handler
# ---------------------------------------------------------------------------


def test_else_and_handler_are_guarded_alternatives_not_cross_fed():
    """Static partition twin via two separate sources (complete vs halt).

    Complete body takes else; halt body takes handler. Cross-feeding would
    make both return the same arm on both sources.
    """
    complete = _desugar(
        "def f():\n"
        "    try:\n"
        "        x = 1\n"
        "    except ValueError:\n"
        "        return 0\n"
        "    else:\n"
        "        return 2\n",
        name="alt_complete.py",
    )
    halt = _desugar(
        "def f():\n"
        "    try:\n"
        "        raise ValueError\n"
        "    except ValueError:\n"
        "        return 0\n"
        "    else:\n"
        "        return 2\n",
        name="alt_halt.py",
    )
    assert _return_values(complete) == [2]
    assert _return_values(halt) == [0]
