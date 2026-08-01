"""Explicit exception-cause composition through try/except + raise-from.

Concrete:

- ``raise Outer() from Inner()`` observed via ``except ... as e``
- ``raise Outer() from None`` suppresses chaining without erasing Outer
- halt while evaluating the cause prevents the outer raise

Laws:

- outer type + occurrence are distinct from cause type + occurrence
- handler-projected cause is the authentic routed RaiseEffect (ObservedEffectValue)
- never derive cause identity from the handler type / arm
- wrong-cause and wrong-occurrence twins refuse

Does not touch assertion managers, generator/resource code, or carrier/ExitSet.
"""

from __future__ import annotations

from types import SimpleNamespace

import pytest

from sugar_lift_py_tests.context_manager_resolution import TreeConstructionContextV1
from sugar_lift_py_tests.effect.raise_effect import RaiseEffect
from sugar_lift_py_tests.floor import CallSiteValue, NoneValue, StringValue
from sugar_lift_py_tests.floor.effect_coordinate import ObservedEffectValue
from sugar_lift_py_tests.ir import ctor
from sugar_lift_py_tests.outcome import Complete, Incomplete
from sugar_lift_py_tests.sugar.raise_sugar import RaiseSugar
from sugar_lift_py_tests.sugar.sugar_base import Sugar
from sugar_lift_python_source.canonical import blake3_512_of
from sugar_source_tree.tree import SourceFile


def _desugar(source: str, *, name: str = "raise_from_try.py"):
    tree = SourceFile(
        (source, name, blake3_512_of(source.encode("utf-8"))),
        construction_context=TreeConstructionContextV1.for_source_call_construction(),
    )
    function = next(tree.functions())
    return function.sugar().desugar()


def _halt_effect(outcome) -> RaiseEffect:
    """Project one RaiseEffect from Incomplete or a single-halt ExitSet."""
    from sugar_lift_py_tests.outcome.exit_set import ExitSet, Halted

    if isinstance(outcome, Incomplete):
        assert isinstance(outcome.effect, RaiseEffect), type(outcome.effect)
        return outcome.effect
    if isinstance(outcome, ExitSet):
        halted = [face for face in outcome.exits if isinstance(face, Halted)]
        assert len(halted) == 1, outcome.exits
        assert isinstance(halted[0].effect, RaiseEffect), type(halted[0].effect)
        return halted[0].effect
    raise AssertionError(f"expected Incomplete|ExitSet halt, got {type(outcome)}")


class Fixed(Sugar):
    def __init__(self, outcome):
        self.outcome = outcome

    def desugar(self, ctx=None):
        del ctx
        return self.outcome

    @classmethod
    def witnesses(cls):
        return ()


def _site(line: int = 1, col: int = 0, *, filename: str = "unit.py"):
    return SimpleNamespace(
        filename=filename,
        line=line,
        col=col,
        unit=SimpleNamespace(source="raise"),
    )


def _call_exception(name: str, message: str | None = None):
    args = (StringValue(message),) if message is not None else ()
    return CallSiteValue(
        target_name=name,
        arg_values=args,
        parameters=(),
        term=ctor(f"call:{name}", []),
        body=None,
    )


# ---------------------------------------------------------------------------
# raise Outer from e observed in except
# ---------------------------------------------------------------------------


def test_raise_outer_from_handler_binding_keeps_distinct_type_and_occurrence():
    """``raise RuntimeError from e``: outer ≠ cause type; outer occ ≠ cause occ."""
    source = (
        "def f():\n"
        "    try:\n"
        "        raise ValueError('inner')\n"
        "    except ValueError as e:\n"
        "        raise RuntimeError('outer') from e\n"
    )
    effect = _halt_effect(_desugar(source))

    assert effect.exception_name == "RuntimeError"
    assert "RuntimeError" in (effect.exception_name or "")

    # Cause is the authentic routed inner raise — ObservedEffectValue, not invented.
    assert isinstance(effect.cause_value, ObservedEffectValue)
    cause_effect = effect.cause_value.effect
    assert isinstance(cause_effect, RaiseEffect)
    assert cause_effect.exception_name == "ValueError"

    # Type + occurrence pairs are distinct; never collapse cause into outer.
    assert effect.exception_name != cause_effect.exception_name
    assert effect.occurrence != cause_effect.occurrence

    # Outer raised value is Outer; cause carries Inner's raised value.
    assert isinstance(effect.raised_value, CallSiteValue)
    assert effect.raised_value.target_name == "RuntimeError"
    assert isinstance(cause_effect.raised_value, CallSiteValue)
    assert cause_effect.raised_value.target_name == "ValueError"


def test_handler_state_projects_authentic_cause_not_handler_type():
    """Cause identity is the routed body raise, never the except-arm type spelling.

    ``except ValueError as e`` must not make the cause type 'ValueError' because
    the arm wrote ValueError — only because the body raised that authenticated
    occurrence. Twin: wrong arm type leaves the body raise unmatched (no outer).
    """
    truthful = (
        "def f():\n"
        "    try:\n"
        "        raise KeyError('inner')\n"
        "    except KeyError as e:\n"
        "        raise RuntimeError('outer') from e\n"
    )
    effect = _halt_effect(_desugar(truthful))
    assert isinstance(effect.cause_value, ObservedEffectValue)
    assert effect.cause_value.effect.exception_name == "KeyError"
    # Occurrence is the body raise site, not the except clause / outer site.
    body_occ = effect.cause_value.effect.occurrence
    assert body_occ != effect.occurrence

    # Wrong-arm twin: except ValueError does not catch KeyError — no outer raise.
    wrong_arm = (
        "def f():\n"
        "    try:\n"
        "        raise KeyError('inner')\n"
        "    except ValueError as e:\n"
        "        raise RuntimeError('outer') from e\n"
    )
    residual = _halt_effect(_desugar(wrong_arm))
    assert residual.exception_name == "KeyError"
    assert residual.cause_value is None  # unmatched body raise, not outer-from-e
    # Must not invent an outer RuntimeError from the handler spelling.
    assert residual.exception_name != "RuntimeError"


def test_cause_is_same_occurrence_as_routed_body_raise():
    """Handler binding's cause.effect is the identical body RaiseEffect occurrence."""
    source = (
        "def f():\n"
        "    try:\n"
        "        raise TypeError('inner')\n"
        "    except TypeError as e:\n"
        "        raise OSError('outer') from e\n"
    )
    effect = _halt_effect(_desugar(source))
    assert isinstance(effect.cause_value, ObservedEffectValue)
    # Also carried as context_effect (Python __context__) when in-flight slot active.
    if effect.context_effect is not None:
        assert effect.context_effect.occurrence == effect.cause_value.effect.occurrence
        assert (
            effect.context_effect.exception_name
            == effect.cause_value.effect.exception_name
        )
    # Authenticity: cause is ObservedEffectValue with the slot + exact effect.
    assert effect.cause_value.slot_id
    assert effect.cause_value.effect.exception_name == "TypeError"


# ---------------------------------------------------------------------------
# from None — explicit suppress chaining without erasing outer
# ---------------------------------------------------------------------------


def test_from_none_suppresses_chaining_without_erasing_outer():
    """``raise Outer from None`` constructs None cause; outer type+occ survive."""
    source = (
        "def f():\n"
        "    try:\n"
        "        raise ValueError('inner')\n"
        "    except ValueError as e:\n"
        "        raise RuntimeError('outer') from None\n"
    )
    effect = _halt_effect(_desugar(source))

    assert effect.exception_name == "RuntimeError"
    assert isinstance(effect.raised_value, CallSiteValue)
    assert effect.raised_value.target_name == "RuntimeError"

    # Explicit None is a constructed NoneValue — not absent cause, not the handler.
    assert isinstance(effect.cause_value, NoneValue)
    assert effect.cause_value is not None  # sentinel is the value, not host None

    # Chaining suppressed: cause is not the inner ValueError / ObservedEffectValue.
    assert not isinstance(effect.cause_value, ObservedEffectValue)
    assert not isinstance(effect.cause_value, RaiseEffect)

    # Outer not erased by suppress.
    assert effect.exception_name != "ValueError"
    assert effect.raised_value.arg_values == (StringValue("outer"),)


def test_from_none_twin_is_not_absent_from_clause():
    """Discrimination: bare raise (no from) leaves cause_value host-None."""
    bare = _halt_effect(
        _desugar("def f():\n    raise ValueError('outer')\n", name="bare.py")
    )
    assert bare.cause_value is None

    explicit = _halt_effect(
        _desugar(
            "def f():\n    raise ValueError('outer') from None\n",
            name="explicit_none.py",
        )
    )
    assert isinstance(explicit.cause_value, NoneValue)
    assert bare.cause_value is not explicit.cause_value


# ---------------------------------------------------------------------------
# Cause-evaluation failure prevents outer raise
# ---------------------------------------------------------------------------


def test_halt_while_evaluating_cause_prevents_outer_raise():
    """If the cause expression halts, the outer RaiseEffect is never emitted."""
    outer = _call_exception("RuntimeError", "outer")
    cause_halt = Incomplete(
        RaiseEffect.for_builtin("KeyError",
            
            blame="unit.py:9:4",
            occurrence="unit.py:9:4",
            raised_value=_call_exception("KeyError", "cause-boom"),
        )
    )
    sugar = RaiseSugar(
        exception=Fixed(Complete(outer)),
        cause=Fixed(cause_halt),
        exception_name="RuntimeError",
        site=_site(1, 0),
    )
    outcome = sugar.desugar()
    effect = _halt_effect(outcome)

    # Cause evaluation's halt is the exit — not RuntimeError outer.
    assert effect.exception_name == "KeyError"
    assert effect.occurrence_id == "unit.py:9:4"
    assert effect.exception_name != "RuntimeError"
    # Outer was constructed as Complete but never wrapped into a raise halt.
    assert not (
        isinstance(effect.raised_value, CallSiteValue)
        and effect.raised_value.target_name == "RuntimeError"
        and effect.exception_name == "RuntimeError"
    )


def test_successful_cause_then_outer_is_the_compose_twin():
    """Positive twin of cause-halt: both arms succeed → outer halt with cause."""
    outer = _call_exception("RuntimeError", "outer")
    cause = _call_exception("KeyError", "inner")
    sugar = RaiseSugar(
        exception=Fixed(Complete(outer)),
        cause=Fixed(Complete(cause)),
        exception_name="RuntimeError",
        site=_site(3, 4, filename="compose.py"),
    )
    effect = _halt_effect(sugar.desugar())
    assert effect.exception_name == "RuntimeError"
    assert effect.occurrence_id == "compose.py:3:4"
    assert isinstance(effect.cause_value, CallSiteValue)
    assert effect.cause_value.target_name == "KeyError"
    assert effect.cause_value is not effect.raised_value


# ---------------------------------------------------------------------------
# Wrong-cause / wrong-occurrence twins
# ---------------------------------------------------------------------------


def test_wrong_cause_type_twin_is_not_the_routed_inner():
    """Lying twin: cause must be the body raise type, not a fabricated sibling."""
    source = (
        "def f():\n"
        "    try:\n"
        "        raise ValueError('inner')\n"
        "    except ValueError as e:\n"
        "        raise RuntimeError('outer') from e\n"
    )
    effect = _halt_effect(_desugar(source))
    cause = effect.cause_value
    assert isinstance(cause, ObservedEffectValue)
    # Refuse: claiming the cause is TypeError when body raised ValueError.
    assert cause.effect.exception_name != "TypeError"
    assert cause.effect.exception_name == "ValueError"
    # Refuse: claiming cause is the outer itself.
    assert cause.effect.exception_name != effect.exception_name
    assert cause.effect.occurrence != effect.occurrence


def test_wrong_occurrence_twin_refuses_handler_site_as_cause_locus():
    """Cause occurrence is the body raise site, never the outer raise / except line."""
    source = (
        "def f():\n"
        "    try:\n"
        "        raise ValueError('inner')\n"
        "    except ValueError as e:\n"
        "        raise RuntimeError('outer') from e\n"
    )
    effect = _halt_effect(_desugar(source, name="occ.py"))
    cause_occ = effect.cause_value.effect.occurrence
    outer_occ = effect.occurrence
    assert cause_occ != outer_occ
    # Body raise is earlier in the source than the outer raise line.
    # Format is file:line:col — line numbers must differ.
    cause_line = int(cause_occ.split(":")[1])
    outer_line = int(outer_occ.split(":")[1])
    assert cause_line < outer_line
    # Never the except line as cause occurrence either (except is line 4).
    assert cause_line == 3  # raise ValueError in the fixture


def test_unit_raise_from_none_matches_try_composition_none_law():
    """Unit RaiseSugar from None agrees with try-composition from None."""
    outer = _call_exception("RuntimeError", "outer")
    sugar = RaiseSugar(
        exception=Fixed(Complete(outer)),
        cause=Fixed(Complete(NoneValue())),
        exception_name="RuntimeError",
        site=_site(1, 0),
    )
    effect = _halt_effect(sugar.desugar())
    assert effect.exception_name == "RuntimeError"
    assert isinstance(effect.cause_value, NoneValue)
