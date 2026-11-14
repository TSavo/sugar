"""A function's defaults are evaluated once, at its ``def`` statement.

Python evaluates each default expression when the ``def`` statement runs, left
to right, and stores the values on the function; every call that omits the
formal binds that same object (the language reference, "Function
definitions").  So ``x = 1; def f(a=x): return a; x = 2; f()`` is 1, a default
that raises raises at the ``def`` statement whether or not ``f`` is ever
called, and a mutable default is shared by every call.

The law has two halves, and this module owns both:

- **The statement evaluates.** ``DefinitionDefaultsSugar`` is an undecorated
  ``def`` statement in a body (``nodes._definition_defaults_sugar``): it
  evaluates each default where the statement stands, through the one
  assignment door (``evaluate_assignment_values``), and binds each completed
  value under the default's key (``nodes._default_evaluation_key``).  Every
  face of a default is the statement's.
- **A call reads the key.** ``DefaultValueSugar`` is what a frame binds a
  formal the call omits to (``SourceVisibleCallFrameV1.bind_actuals``, the one
  binder every call form reaches through ``object_value.bind_call``): the
  value bound under the key, the same object for every call.

A lambda's defaults follow the same law: the lambda expression evaluates them
where it is evaluated (``LambdaSugar``), under the same per-formal keys, and
its value carries them (``LambdaCallable.defaults``); every call binds what
the value carries (``bind_carried_defaults``, from ``object_value.bind_call``)
before the frame reads the keys.  A lambda's default expression is never
evaluated at a call: a call whose callee carries no value for the key is
refused by name.

Where no reduction running the ``def`` statement bound the key -- a module
or class-body ``def``, whose statement is not reduced in the temporal of a
call made after import, or a function called outside the frame that ran its
``def`` -- the default expression is evaluated where the call stands, as it
was before (#7757 residue).
"""

from __future__ import annotations

from dataclasses import dataclass, field as dataclass_field
from typing import ClassVar

from sugar_lift_py_tests.outcome import ExitSet
from sugar_lift_py_tests.sugar.sugar_base import Sugar
from sugar_lift_py_tests.sugar.witnesses import NotVerdictBearing


@dataclass(frozen=True)
class DefinitionDefaultsSugar(Sugar):
    """An undecorated ``def`` statement with defaults: each default evaluated
    here, once, left to right, its completed value bound under its key.

    ``values`` are the default sugars (substituted in the scope the statement
    runs in); ``evaluations`` holds ``(key, value index)`` per default.  The
    statement binds no name of its own here: substitution bound the name to
    the definition (``nodes._local_definition_binding``), and its body runs
    only at a call."""

    values: tuple
    evaluations: tuple
    site: object = dataclass_field(compare=False)
    # Evaluating the defaults is the statement's only work before it binds.
    halts_at_statement_head: ClassVar[bool] = True

    @classmethod
    def witnesses(cls):
        return NotVerdictBearing(
            sugar_name=cls.__name__,
            floor_name="definition default evaluation",
            reason=(
                "the defaults' own sugars own their faces; this evaluates them "
                "once at the def statement and binds each under its key"
            ),
        )

    def desugar(self, ctx: object = None) -> ExitSet:
        from sugar_lift_py_tests.sugar.assigned_value import (
            evaluate_assignment_values,
        )

        return evaluate_assignment_values(
            self.values, ctx, evaluations=self.evaluations, site=self.site
        )


@dataclass(frozen=True)
class DefaultValueSugar(Sugar):
    """The value a call binds to a formal it omits: what the ``def``
    statement bound under the default's key (``evaluation``), read where the
    call runs (``evaluation_read_here``).  ``value`` is the default
    expression's own sugar, evaluated only where no reduction running the
    statement bound the key (see the module docstring); None for a lambda's
    default, which only the lambda expression evaluates."""

    evaluation: str
    value: Sugar | None
    site: object = dataclass_field(compare=False)

    @classmethod
    def witnesses(cls):
        return NotVerdictBearing(
            sugar_name=cls.__name__,
            floor_name="definition default read",
            reason="reads the value its def statement bound under the default's key",
        )

    def desugar(self, ctx: object = None) -> ExitSet:
        bound = self.bound_value(ctx)
        if bound is not None:
            return ExitSet.completed(bound)
        if self.value is None:
            from sugar_lift_py_tests.source_call_frame import SourceCallBindingGap

            raise SourceCallBindingGap(
                "lambda default not carried by the called lambda value"
            )
        return self.value.desugar(ctx)

    def bound_value(self, ctx):
        """The value the ``def`` statement bound under the key where the call
        runs, or None where no reduction running the statement bound it."""
        temporal = getattr(ctx, "temporal", None) if ctx is not None else None
        if temporal is None:
            return None
        from sugar_lift_py_tests.sugar.evaluation_ref_sugar import (
            evaluation_read_here,
        )

        return temporal.value_if_bound(evaluation_read_here(temporal, self.evaluation))


def bind_carried_defaults(ctx, defaults):
    """``ctx`` with each ``(key, value)`` a called lambda value carries
    (``LambdaCallable.defaults``) bound under its key, where the call binds
    its actuals: the values its lambda expression evaluated, read by the
    frame's ``DefaultValueSugar``.  ``ctx`` itself when nothing is carried."""
    if not defaults:
        return ctx
    from sugar_lift_py_tests.floor.scope_rebind import ScopeRebinds

    return ScopeRebinds(tuple(defaults)).extend_scope(ctx)
