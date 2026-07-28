"""Implicit exception context and re-raise composition.

Concrete cases:

- ``raise Second()`` inside ``except First:`` — implicit context (not explicit from)
- bare ``raise`` inside a handler — identical incoming effect, no new occurrence
- ``raise Second() from None`` — suppress chaining presentation; primary survives
- terminal ``finally: raise`` — supersedes body exit; truthful context when produced

Twins reject swapped primary/context, fabricated context outside a handler, and
bare re-raise without an active exception.

Never derive exception identity from handler spelling. Does not touch ExitSet
algebra, carrier, or assertion/resource machinery.
"""

from __future__ import annotations

from types import SimpleNamespace

import pytest

from sugar_lift_py_tests.context_manager_resolution import TreeConstructionContextV1
from sugar_lift_py_tests.effect.raise_effect import RaiseEffect
from sugar_lift_py_tests.floor import CallSiteValue, NoneValue, StringValue
from sugar_lift_py_tests.ir import ctor
from sugar_lift_py_tests.outcome import Complete, Incomplete
from sugar_lift_py_tests.outcome.exit_set import ExitSet, Halted
from sugar_lift_py_tests.sugar.raise_sugar import RaiseSugar
from sugar_lift_py_tests.sugar.sugar_base import Sugar
from sugar_lift_python_source.canonical import blake3_512_of
from sugar_source_tree.panic import SugarNotWritten
from sugar_source_tree.tree import SourceFile


def _desugar(source: str, *, name: str = "context_reraise.py"):
    tree = SourceFile(
        (source, name, blake3_512_of(source.encode("utf-8"))),
        construction_context=TreeConstructionContextV1.for_source_call_construction(),
    )
    return next(tree.functions()).sugar().desugar()


def _halt_effect(outcome) -> RaiseEffect:
    if isinstance(outcome, Incomplete):
        assert isinstance(outcome.effect, RaiseEffect), type(outcome.effect)
        return outcome.effect
    if isinstance(outcome, ExitSet):
        halted = [face for face in outcome.exits if isinstance(face, Halted)]
        assert len(halted) == 1, outcome.exits
        assert isinstance(halted[0].effect, RaiseEffect), type(halted[0].effect)
        return halted[0].effect
    raise AssertionError(f"expected halt Incomplete|ExitSet, got {type(outcome)}")


def _halt_face(outcome) -> Halted | Incomplete:
    if isinstance(outcome, Incomplete):
        return outcome
    if isinstance(outcome, ExitSet):
        halted = [face for face in outcome.exits if isinstance(face, Halted)]
        assert len(halted) == 1, outcome.exits
        return halted[0]
    raise AssertionError(type(outcome))


class Fixed(Sugar):
    def __init__(self, outcome):
        self.outcome = outcome

    def desugar(self, ctx=None):
        del ctx
        return self.outcome

    @classmethod
    def witnesses(cls):
        return ()


def _site(*, filename="unit.py", line=1, col=0):
    return SimpleNamespace(
        filename=filename,
        line=line,
        col=col,
        unit=SimpleNamespace(source="raise"),
    )


def _call_exc(name: str, message: str | None = None):
    args = (StringValue(message),) if message is not None else ()
    return CallSiteValue(
        target_name=name,
        arg_values=args,
        parameters=(),
        term=ctor(f"call:{name}", []),
        body=None,
    )


# ---------------------------------------------------------------------------
# Implicit context: raise Second inside except First
# ---------------------------------------------------------------------------


def test_implicit_context_second_outgoing_first_authenticated_context():
    """``raise Second`` in ``except First``: Second primary; First is context."""
    source = (
        "def f():\n"
        "    try:\n"
        "        raise ValueError('first')\n"
        "    except ValueError:\n"
        "        raise RuntimeError('second')\n"
    )
    effect = _halt_effect(_desugar(source))

    assert effect.exception_name == "RuntimeError"
    assert effect.occurrence is not None
    assert isinstance(effect.raised_value, CallSiteValue)
    assert effect.raised_value.target_name == "RuntimeError"

    # Implicit context — not explicit from-cause.
    assert effect.cause_value is None
    assert isinstance(effect.context_effect, RaiseEffect)
    assert effect.context_effect.exception_name == "ValueError"
    assert effect.context_effect.occurrence is not None

    # Distinct type + occurrence pairs.
    assert effect.exception_name != effect.context_effect.exception_name
    assert effect.occurrence != effect.context_effect.occurrence


def test_implicit_context_is_distinct_from_explicit_from_cause():
    """Implicit context_effect ≠ explicit cause_value paths."""
    implicit = _halt_effect(
        _desugar(
            "def f():\n"
            "    try:\n"
            "        raise ValueError('first')\n"
            "    except ValueError:\n"
            "        raise RuntimeError('second')\n",
            name="implicit.py",
        )
    )
    explicit = _halt_effect(
        _desugar(
            "def f():\n"
            "    try:\n"
            "        raise ValueError('first')\n"
            "    except ValueError as e:\n"
            "        raise RuntimeError('second') from e\n",
            name="explicit.py",
        )
    )
    # Implicit: no constructed cause; has context.
    assert implicit.cause_value is None
    assert isinstance(implicit.context_effect, RaiseEffect)
    # Explicit from e: cause is projected ObservedEffectValue; may also carry context.
    assert explicit.cause_value is not None
    assert not isinstance(explicit.cause_value, NoneValue)
    # Both preserve First as authenticated ValueError occurrence.
    assert implicit.context_effect.exception_name == "ValueError"
    from sugar_lift_py_tests.floor.effect_coordinate import ObservedEffectValue

    assert isinstance(explicit.cause_value, ObservedEffectValue)
    assert explicit.cause_value.effect.exception_name == "ValueError"


# ---------------------------------------------------------------------------
# Bare re-raise
# ---------------------------------------------------------------------------


def test_bare_reraise_preserves_identical_incoming_effect_occurrence():
    """Bare ``raise`` re-emits the in-flight effect — no new occurrence mint."""
    source = (
        "def f():\n"
        "    try:\n"
        "        raise ValueError('first')\n"
        "    except ValueError:\n"
        "        raise\n"
    )
    effect = _halt_effect(_desugar(source, name="bare.py"))
    assert effect.exception_name == "ValueError"
    # Occurrence is the body raise site (line of raise ValueError), not bare raise.
    assert effect.occurrence is not None
    body_line = int(effect.occurrence.split(":")[1])
    # bare.py: raise ValueError on line 3, bare raise on line 5.
    assert body_line == 3, effect.occurrence
    assert not effect.occurrence.endswith(":5:8")
    assert not effect.occurrence.endswith(":5:9")


def test_bare_reraise_is_exact_inflight_effect_identity():
    """Unit: resolve_in_flight returns the identical RaiseEffect object."""
    from sugar_lift_py_tests.context import ReduceContext
    from sugar_lift_py_tests.in_flight_effect import (
        bind_in_flight_effect,
        resolve_in_flight_effect,
    )

    incoming = RaiseEffect(
        exception_name="ValueError",
        blame="body.py:1:0",
        occurrence="body.py:1:0",
        raised_value=_call_exc("ValueError", "first"),
    )
    ctx = bind_in_flight_effect(
        ReduceContext.root(owner="bare-reraise"),
        "handler-slot",
        incoming,
        blame=None,
    )
    sugar = RaiseSugar(
        exception=None,
        cause=None,
        exception_name=None,
        site=_site(filename="handler.py", line=9, col=8),
        in_flight_slot="handler-slot",
    )
    outcome = sugar.desugar(ctx)
    assert isinstance(outcome, Incomplete)
    assert outcome.effect is incoming
    assert outcome.effect.occurrence == "body.py:1:0"
    # Handler site is NOT written onto the effect.
    assert "handler.py" not in (outcome.effect.occurrence or "")


def test_bare_reraise_without_active_exception_is_loud():
    """Twin: bare raise outside a handler refuses — no fabricated in-flight."""
    sugar = RaiseSugar(
        exception=None,
        cause=None,
        exception_name=None,
        site=_site(filename="orphan.py", line=1, col=0),
        in_flight_slot=None,
    )
    with pytest.raises(SugarNotWritten) as caught:
        sugar.desugar()
    assert "in-flight" in caught.value.observed or "bare raise" in caught.value.observed
    assert caught.value.owner == "RaiseSugar.desugar"


# ---------------------------------------------------------------------------
# from None — suppress chaining presentation, keep primary
# ---------------------------------------------------------------------------


def test_from_none_suppresses_chaining_without_erasing_primary():
    """``raise Second from None``: primary Second; cause is explicit NoneValue."""
    source = (
        "def f():\n"
        "    try:\n"
        "        raise ValueError('first')\n"
        "    except ValueError:\n"
        "        raise RuntimeError('second') from None\n"
    )
    effect = _halt_effect(_desugar(source))
    assert effect.exception_name == "RuntimeError"
    assert isinstance(effect.raised_value, CallSiteValue)
    assert effect.raised_value.target_name == "RuntimeError"
    # Explicit suppress: cause is NoneValue, not the First raise.
    assert isinstance(effect.cause_value, NoneValue)
    # Primary not erased; First is not the outgoing exception_name.
    assert effect.exception_name != "ValueError"
    # Implicit context may still be authenticated (Python __context__ with
    # __suppress_context__); it is not the explicit cause.
    if effect.context_effect is not None:
        assert effect.context_effect.exception_name == "ValueError"
        assert effect.cause_value is not effect.context_effect


# ---------------------------------------------------------------------------
# Terminal finally raise
# ---------------------------------------------------------------------------


def test_terminal_finally_raise_supersedes_incoming_body_exit():
    """``finally: raise Second`` supersedes body First as the outgoing primary."""
    source = (
        "def f():\n"
        "    try:\n"
        "        raise ValueError('body')\n"
        "    finally:\n"
        "        raise RuntimeError('finally')\n"
    )
    effect = _halt_effect(_desugar(source, name="fin.py"))
    assert effect.exception_name == "RuntimeError"
    assert effect.occurrence is not None
    # Primary is the finally raise site, not the body raise.
    fin_line = int(effect.occurrence.split(":")[1])
    assert fin_line == 5, effect.occurrence  # raise RuntimeError in fixture
    assert effect.exception_name != "ValueError"


def test_terminal_finally_raise_retains_truthful_body_context():
    """Finally raise should retain body First as authenticated context.

    Banks red if TrySugar finally reduces without binding the pre-finally halt
    as in-flight context (shared finally algebra, not ExitSet).
    """
    source = (
        "def f():\n"
        "    try:\n"
        "        raise ValueError('body')\n"
        "    finally:\n"
        "        raise RuntimeError('finally')\n"
    )
    effect = _halt_effect(_desugar(source, name="fin_ctx.py"))
    assert effect.exception_name == "RuntimeError"
    if effect.context_effect is None:
        pytest.fail(
            "MISSING PRODUCER (TrySugar finally / in-flight context):\n"
            "  observed: terminal finally raise has context_effect=None\n"
            "  expected: RuntimeError primary with authenticated ValueError "
            "context_effect (body occurrence), distinct from explicit from-cause\n"
            "  owned: TrySugar finalbody reduction must bind the pre-finally "
            "halt effect as in-flight when reducing finally statements — not "
            "ExitSet.and_finally (frozen); not RaiseSugar alone\n"
            "  fix: reduce finalbody under bind_in_flight_effect(ctx, slot, "
            "incoming.effect) per halted face, or attach truthful context when "
            "cleanup halt supersedes"
        )
    assert isinstance(effect.context_effect, RaiseEffect)
    assert effect.context_effect.exception_name == "ValueError"
    assert effect.context_effect.occurrence != effect.occurrence
    assert effect.cause_value is None  # implicit context, not from-cause


# ---------------------------------------------------------------------------
# Twins
# ---------------------------------------------------------------------------


def test_twin_swapped_primary_and_context_refused():
    """Outgoing primary is Second; context is First — not swapped."""
    effect = _halt_effect(
        _desugar(
            "def f():\n"
            "    try:\n"
            "        raise ValueError('first')\n"
            "    except ValueError:\n"
            "        raise RuntimeError('second')\n"
        )
    )
    assert effect.exception_name == "RuntimeError"
    assert effect.context_effect.exception_name == "ValueError"
    # Refuse swapped reading.
    assert not (
        effect.exception_name == "ValueError"
        and effect.context_effect.exception_name == "RuntimeError"
    )


def test_twin_fabricated_context_outside_handler_refused():
    """Raise outside a handler has no implicit context_effect."""
    effect = _halt_effect(
        _desugar("def f():\n    raise RuntimeError('alone')\n", name="alone.py")
    )
    assert effect.exception_name == "RuntimeError"
    assert effect.context_effect is None
    assert effect.cause_value is None


def test_twin_handler_spelling_does_not_mint_context_type():
    """Context type is the body raise, not the except-arm type text."""
    # Body raises KeyError; arm says Exception (base) — context is still KeyError.
    source = (
        "def f():\n"
        "    try:\n"
        "        raise KeyError('first')\n"
        "    except Exception:\n"
        "        raise RuntimeError('second')\n"
    )
    effect = _halt_effect(_desugar(source))
    assert effect.exception_name == "RuntimeError"
    assert isinstance(effect.context_effect, RaiseEffect)
    assert effect.context_effect.exception_name == "KeyError"
    assert effect.context_effect.exception_name != "Exception"
