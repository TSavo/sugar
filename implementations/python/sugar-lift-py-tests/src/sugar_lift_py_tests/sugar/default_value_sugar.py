"""A function's defaults are evaluated once, at its ``def`` statement.

Python evaluates each default expression when the ``def`` statement runs, left
to right, and stores the values on the function; every call that omits the
formal binds that same object (the language reference, "Function
definitions").  So ``x = 1; def f(a=x): return a; x = 2; f()`` is 1, a default
that raises raises at the ``def`` statement whether or not ``f`` is ever
called, and a mutable default is shared by every call.

The law has two halves, and this module owns both:

- **The statement evaluates.** ``DefinitionDefaultsSugar`` is an undecorated
  ``def`` statement in a body, or a class-body method's
  (``nodes._definition_defaults_sugar``): it evaluates each default where
  the statement stands, through the one assignment door
  (``evaluate_assignment_values``), and binds each completed value under the
  default's key (``nodes._default_evaluation_key``).  Every face of a
  default is the statement's.
- **A call reads the key.** ``DefaultValueSugar`` is what a frame binds a
  formal the call omits to (``SourceVisibleCallFrameV1.bind_actuals``, the one
  binder every call form reaches through ``object_value.bind_call``): the
  value bound under the key, the same object for every call.

The values reach the call's binding by one of four routes, each the value the
statement evaluated once: the temporal the statement's own reduction bound
them in (a call in the body that ran the ``def``); a value that carries them,
bound by ``bind_call`` (``bind_carried_defaults``): a lambda value
(``LambdaSugar``), a decorated ``def``'s function value, which its statement
built after evaluating the defaults and before applying its decorators
(``DecoratorApplicationSugar``), and a method's class
(``ClassDefinitionValue.method_defaults``), which a class call reads for its
``__init__`` and ``__new__`` from the class statement's one outcome
(``ClassConstructorBodySugar.bind_class_call``); and, for a module ``def`` called
after import, the module run that ran its statement, read at the frame entry
(``call_site_sugar.with_module_final_globals``).  A default expression is
never evaluated at a call: a call where none of these bound the key is
refused by name.
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
    statement or lambda expression bound under the default's key
    (``evaluation``), read where the call runs (``evaluation_read_here``).
    Where nothing bound the key the call is refused by name: the default
    expression is evaluated only by its statement."""

    evaluation: str
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
        from sugar_lift_py_tests.source_call_frame import SourceCallBindingGap

        raise SourceCallBindingGap(
            "default not bound where the call runs: no def statement or "
            f"lambda expression evaluation reached the call ({self.evaluation})"
        )

    def bound_value(self, ctx):
        """The value the ``def`` statement or lambda expression bound under
        the key where the call runs, or None where nothing bound it."""
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
