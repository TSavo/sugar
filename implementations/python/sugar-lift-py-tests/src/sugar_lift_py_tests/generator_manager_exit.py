"""``contextlib._GeneratorContextManager.__exit__`` over a generator machine.

``@contextlib.contextmanager`` wraps a generator function in
``_GeneratorContextManager``. Its ``__exit__`` is source in the stdlib
(CPython 3.13 ``Lib/contextlib.py``), and this module is that source applied to
a ``GeneratorConstructionV1`` suspended at its yield:

    def __exit__(self, typ, value, traceback):
        if typ is None:
            try:
                next(self.gen)
            except StopIteration:
                return False
            else:
                try:
                    raise RuntimeError("generator didn't stop")
                finally:
                    self.gen.close()
        else:
            ...
            try:
                self.gen.throw(value)
            except StopIteration as exc:
                return exc is not value
            except RuntimeError as exc:
                if exc is value: ... return False
                if isinstance(value, StopIteration) and exc.__cause__ is value:
                    ... return False
                raise
            except BaseException as exc:
                if exc is not value:
                    raise
                ... return False
            try:
                raise RuntimeError("generator didn't stop after throw()")
            finally:
                self.gen.close()

So, per body exit:

- a body that completes (or leaves by return/break/continue, which are not
  exceptions) resumes the generator: it must finish (``__exit__`` returns
  ``False``); a second yield raises ``RuntimeError`` after closing it; a raise
  from the generator propagates out of ``__exit__``;
- a body exception is thrown in at the yield: a generator that finishes after
  catching it suppresses it (``True``); a generator that lets the SAME
  exception out does not (``False``, the With re-raises the original); any
  other exception propagates; a second yield raises ``RuntimeError``.

A ``StopIteration`` raised inside a generator frame becomes ``RuntimeError``
(PEP 479); ``exc is not value`` and the ``__cause__`` arm make a thrown
``StopIteration`` that comes back propagate as itself.

The RuntimeError texts are OBSERVED from the running ``contextlib``, never
transcribed, exactly like ``generator_entry_refusal``.

The result is the exit's own ExitSet: ``Completed`` faces carry the returned
``TermValue(bool)`` for ``and_exit_truthiness``, ``Halted`` faces are raises
out of ``__exit__``. No face is invented: an undecided generator transition
stays a loud ``SugarNotWritten``.
"""

from __future__ import annotations

import contextlib
from dataclasses import dataclass
from functools import lru_cache


@dataclass(frozen=True)
class GeneratorExitRefusalsV1:
    """What ``contextlib`` raises when a managed generator misbehaves at exit."""

    exception_name: str
    did_not_stop: str
    did_not_stop_after_throw: str
    stop_iteration_conversion_name: str
    stop_iteration_conversion: str


@contextlib.contextmanager
def _yields_twice():
    yield
    yield  # pragma: no cover - reached only by the observation below


@contextlib.contextmanager
def _yields_after_throw():
    try:
        yield
    except LookupError:
        pass
    yield  # pragma: no cover


@contextlib.contextmanager
def _raises_stop_iteration():
    yield
    raise StopIteration  # pragma: no cover - converted by PEP 479


def _observe(manager, raise_in_body: bool) -> BaseException:
    try:
        with manager():
            if raise_in_body:
                raise LookupError
    except Exception as raised:
        return raised
    raise AssertionError(
        "contextlib no longer refuses this generator at exit; the conversion "
        "this module observes is gone and the lift must be re-derived"
    )


@lru_cache(maxsize=1)
def observed_exit_refusals() -> GeneratorExitRefusalsV1:
    """Run the vendor's ``__exit__`` once per refusal and record what it raised."""
    stopped = _observe(_yields_twice, False)
    thrown = _observe(_yields_after_throw, True)
    converted = _observe(_raises_stop_iteration, False)
    if type(stopped) is not type(thrown):
        raise AssertionError("contextlib exit refusals no longer share one type")
    return GeneratorExitRefusalsV1(
        exception_name=type(stopped).__name__,
        did_not_stop=str(stopped),
        did_not_stop_after_throw=str(thrown),
        stop_iteration_conversion_name=type(converted).__name__,
        stop_iteration_conversion=str(converted),
    )


def is_exception_effect(effect) -> bool:
    """A raise (leaf, group, or of an undetermined class): what ``throw`` takes."""
    from sugar_lift_py_tests.effect import GroupedRaiseEffect, RaiseEffect
    from sugar_lift_py_tests.effect.raise_effect import UndeterminedRaiseEffect

    return isinstance(effect, (RaiseEffect, GroupedRaiseEffect, UndeterminedRaiseEffect))


def _is_stop_iteration(effect) -> bool:
    from sugar_lift_py_tests.effect import RaiseEffect

    if not isinstance(effect, RaiseEffect):
        return False
    if effect.exception_name == "StopIteration":
        return True
    # A subclass converts too: read the authenticated ancestry, never a name.
    return any("StopIteration" in repr(term) for term in effect.exception_type_mro or ())


def _refusal(message: str, *, blame: str, context_effect=None):
    from sugar_lift_py_tests.effect import RaiseEffect

    refusals = observed_exit_refusals()
    return RaiseEffect.for_builtin(
        refusals.exception_name,
        occurrence=f"generator-manager-exit:{message}:{blame}",
        blame=blame,
        raised_value=message,
        context_effect=context_effect,
    )


def _pep479(effect, *, blame: str):
    """A StopIteration leaving a generator frame is RuntimeError (PEP 479)."""
    from sugar_lift_py_tests.effect import RaiseEffect

    refusals = observed_exit_refusals()
    return RaiseEffect.for_builtin(
        refusals.stop_iteration_conversion_name,
        occurrence=f"generator-stop-iteration:{blame}",
        blame=blame,
        raised_value=refusals.stop_iteration_conversion,
        context_effect=effect,
    )


def _loud(observed: str, *, blame: str):
    from sugar_source_tree.panic import SugarNotWritten

    raise SugarNotWritten(
        blame=blame,
        owner="generator_manager_exit",
        observed=observed,
        requested="an exhaustive GeneratorConstructionV1 transition at __exit__",
        fix="construct the transition or retain this typed loud boundary",
    )


def generator_manager_exit(machine, body_face, *, blame: str):
    """``_GeneratorContextManager.__exit__`` for one body exit, as an ExitSet."""
    from sugar_lift_py_tests.outcome.exit_set import Halted

    if isinstance(body_face, Halted) and is_exception_effect(body_face.effect):
        return _after_throw(machine.throw(body_face.effect), body_face.effect, blame)
    return _after_next(machine.resume(), blame)


def _bool_exit(value: bool):
    from sugar_lift_py_tests.floor import TermValue
    from sugar_lift_py_tests.outcome.exit_set import ExitSet

    return ExitSet.completed(TermValue(value))


def _after_next(after, blame: str):
    """``next(self.gen)``: finish -> False; yield -> refuse; raise -> propagate."""
    from sugar_lift_py_tests.generator_construction import (
        GeneratorConstructionV1,
        GeneratorTerminationV1,
        GeneratorTransitionGapV1,
        YieldEffect,
    )
    from sugar_lift_py_tests.outcome.exit_set import ExitSet

    if isinstance(after, GeneratorTerminationV1):
        return _bool_exit(False)
    if isinstance(after, GeneratorConstructionV1):
        # A step completed and left the machine runnable (a nested cleanup
        # ran): ``next`` continues to the generator's next suspension.
        return _after_next(after.resume(), blame)
    if isinstance(after, YieldEffect):
        return _after_refused_yield(
            after.machine, observed_exit_refusals().did_not_stop, blame
        )
    if isinstance(after, ExitSet):
        return _map_exits(after, lambda value: _after_next(value, blame), blame)
    if isinstance(after, GeneratorTransitionGapV1):
        _loud(after.observed, blame=blame)
    _loud(f"post-yield resume returned {type(after).__name__}", blame=blame)


def _after_throw(after, thrown, blame: str):
    """``self.gen.throw(value)``: finish -> True; same exception -> False."""
    from sugar_lift_py_tests.generator_construction import (
        GeneratorConstructionV1,
        GeneratorTerminationV1,
        GeneratorTransitionGapV1,
        YieldEffect,
    )
    from sugar_lift_py_tests.outcome.exit_set import ExitSet

    if isinstance(after, GeneratorTerminationV1):
        return _bool_exit(True)
    if isinstance(after, YieldEffect):
        return _after_refused_yield(
            after.machine, observed_exit_refusals().did_not_stop_after_throw, blame
        )
    if isinstance(after, ExitSet):
        return _map_exits(
            after,
            lambda value: _after_throw(value, thrown, blame),
            blame,
            thrown=thrown,
        )
    if isinstance(after, GeneratorConstructionV1):
        # A throw that left the machine runnable (a handler completed, or a
        # nested cleanup ran): the generator continues to its next suspension.
        return _after_throw(after.resume(), thrown, blame)
    if isinstance(after, GeneratorTransitionGapV1):
        _loud(after.observed, blame=blame)
    _loud(f"throw returned {type(after).__name__}", blame=blame)


def _after_refused_yield(machine, message: str, blame: str):
    """``raise RuntimeError(...)`` with ``finally: self.gen.close()``."""
    from sugar_lift_py_tests.generator_construction import (
        GeneratorTerminationV1,
        GeneratorTransitionGapV1,
    )
    from sugar_lift_py_tests.outcome.exit_set import Completed, ExitSet, Halted

    refusal = _refusal(message, blame=blame)
    closed = machine.close()
    if isinstance(closed, GeneratorTerminationV1):
        return ExitSet.halted(refusal)
    if isinstance(closed, GeneratorTransitionGapV1):
        _loud(closed.observed, blame=blame)
    if not isinstance(closed, ExitSet):
        _loud(f"close returned {type(closed).__name__}", blame=blame)
    exits = []
    for face in closed.exits:
        if isinstance(face, Halted):
            # A raise from close() supersedes the RuntimeError in flight.
            exits.append(face)
            continue
        exits.append(Halted(face.guard, refusal, None, face.faces, face.owed))
    return ExitSet(tuple(exits)).normalize()


def _map_exits(exit_set, on_completed, blame: str, *, thrown=None):
    """Map a machine ExitSet face by face, keeping every guard and face key."""
    from sugar_lift_py_tests.outcome.exit_set import Completed, ExitSet, Halted

    parts = []
    for face in exit_set.exits:
        if isinstance(face, Halted):
            effect = face.effect
            if thrown is not None and (effect is thrown or effect == thrown):
                # ``exc is value``: the generator let the thrown exception out.
                parts.append(_guard_with(_bool_exit(False), face))
                continue
            if _is_stop_iteration(effect):
                effect = _pep479(effect, blame=blame)
            parts.append(
                ExitSet(
                    (
                        Halted(
                            face.guard,
                            effect,
                            face.state,
                            face.faces,
                            face.owed,
                        ),
                    )
                )
            )
            continue
        if not isinstance(face, Completed):
            _loud(type(face).__name__, blame=blame)
        mapped = on_completed(face.value)
        parts.append(_guard_with(mapped, face))
    if not parts:
        return ExitSet(())
    result = parts[0]
    for part in parts[1:]:
        result = result.union(part)
    return result.normalize()


def _guard_with(exit_set, face):
    """``exit_set`` continuing beneath the mapped ``face``, completed or halted.

    Composed through ``ExitSet.sequence`` (``consume=`` for a halted face the
    mapping owns): the face's guard and testimony ride onto every exit, and so
    do its debts.
    """
    from sugar_lift_py_tests.outcome.exit_set import ExitSet

    return ExitSet((face,)).sequence(
        lambda _value: exit_set, consume=lambda _halt: exit_set
    )
