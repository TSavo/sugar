from __future__ import annotations

from typing import ClassVar

import hashlib
from dataclasses import dataclass, field as dataclass_field

from sugar_lift_py_tests.effect import (
    AuthenticatedRaiseLocus,
    RaiseEffect,
    UndeterminedRaiseEffect,
)
from sugar_lift_py_tests.outcome import ExitSet
from sugar_lift_py_tests.sugar.sugar_base import Sugar
from sugar_lift_py_tests.sugar.witnesses import typed_red_effect_witness


@dataclass(frozen=True)
class RaiseSugar(Sugar):
    """`raise <exc>` -- a statement that HALTS the block.

    A raise never states a fact and never returns a value: it exits. So it is
    the halt arm of ``match(Sugar) { Some => cite_or_effect, None => panic }`` --
    it desugars to a typed-red effect, ``ExitSet.halted(RaiseEffect)``, not to
    a completed floor value. Its halted arm bypasses the rest of the block (a
    RaiseEffect is not a store effect, so the rest stays unreduced); a matching
    ``TrySugar`` handler may later route it, and unrouted it is the block's exit.

    The exception child is built normally and carried on the effect.  Its
    structural name remains routing provenance only; spelling never creates
    or authenticates an exception value.
    """

    halts_at_statement_head: ClassVar[bool] = True

    exception: object | None
    cause: object | None
    exception_name: str | None
    site: object = dataclass_field(compare=False)
    in_flight_slot: str | None = None

    @classmethod
    def witnesses(cls):
        # The typed-red effect IS the discriminator: `raise ValueError` must
        # surface a RaiseEffect whose reason names ValueError; a lift that named
        # the wrong exception (KeyError) would make the lying arm match and fail.
        return typed_red_effect_witness(
            name="raise_named_exception",
            owner_sugar="RaiseSugar",
            source="def A():\n    raise ValueError\n",
            effect_class="RaiseEffect",
            reason_needle="raise ValueError",
            blame_needle="exits the current block",
            wrong_reason_needle="raise KeyError",
        )

    def _effect(self, raised_value, ctx, cause_value=None):
        """The effect this raise halts with when it throws ``raised_value``.

        The raised class is read off the constructed value -- the one reader
        for a raise, ``raise ... from`` and an exception group's member: its
        ``exception_type_identity`` (or ``exception_type_coordinate``), which
        the value's construction decided (``OSError(2, 'x')`` constructs a
        ``FileNotFoundError``).  A value that carries no class (an unanswered
        construction, an operand nothing typed) is the undetermined raise,
        never a guess.  blame is the construction locus; source_sha256 pins
        the text the raise lives in."""
        source = getattr(self.site.unit, "source", None)
        source_sha256 = (
            hashlib.sha256(source.encode()).hexdigest() if source is not None else None
        )
        blame = f"{self.site.filename}:{self.site.line}:{self.site.col}"
        context_effect = None
        if self.in_flight_slot is not None:
            from sugar_lift_py_tests.in_flight_effect import (
                resolve_in_flight_effect,
            )

            context_effect = resolve_in_flight_effect(
                ctx, self.in_flight_slot, blame=self.site
            )
        identity_reader = getattr(raised_value, "exception_type_identity", None)
        mro_reader = getattr(raised_value, "exception_type_mro", None)
        coordinate = (
            identity_reader()
            if identity_reader is not None
            else getattr(raised_value, "exception_type_coordinate", None)
        )
        if coordinate is None:
            # Do not mint RaiseEffect(None). Throwing is honorable when
            # identity is unfinished; UndeterminedRaiseEffect is the only
            # non-throw door that cannot impersonate authentication.
            return UndeterminedRaiseEffect(
                exception_name=self.exception_name,
                blame=blame,
                source_sha256=source_sha256,
                occurrence=_occurrence_key(blame),
                raised_value=raised_value,
                cause_value=cause_value,
                context_effect=context_effect,
                producer_node_owner="RaiseSugar.desugar",
            )
        mro = (
            mro_reader()
            if callable(mro_reader)
            else getattr(raised_value, "exception_type_mro", None)
        )
        return RaiseEffect(
            exception_type_coordinate=coordinate,
            occurrence=AuthenticatedRaiseLocus.of(blame),
            exception_name=self.exception_name,
            blame=blame,
            source_sha256=source_sha256,
            exception_type_mro=mro,
            raised_value=raised_value,
            cause_value=cause_value,
            context_effect=context_effect,
        )

    def constructed(self, ctx: object = None) -> ExitSet:
        """The exception this raise throws, as a member of the exception group
        an enclosing raise builds (``GroupedRaiseSugar``), without throwing it.

        The member's construction runs first: each halted arm of it (the
        construction raised, so no group is built) stays a halt; each
        completed arm answers the effect the member would raise with
        (``_effect``), carrying the arm's guard, faces and ``owed``.  A
        member that is itself a raised group instance is that group."""
        from sugar_lift_py_tests.floor.grouped_exception_value import (
            GroupedExceptionValue,
        )

        def member(raised_value):
            if isinstance(raised_value, GroupedExceptionValue):
                return ExitSet.completed(raised_value.effect)
            return ExitSet.completed(self._effect(raised_value, ctx))

        return self.exception.desugar(ctx).and_then(member)

    def desugar(self, ctx: object = None) -> ExitSet:
        if self.exception is None:
            # Bare re-raise: re-emit the authenticated in-flight effect. No new
            # occurrence is minted — identity is the handler-routed RaiseEffect.
            if self.in_flight_slot is None:
                from sugar_source_tree.panic import SugarNotWritten

                raise SugarNotWritten(
                    blame=self.site,
                    owner="RaiseSugar.desugar",
                    observed="bare raise lacks an authenticated in-flight effect slot",
                    requested="the enclosing handler's effect-slot coordinate",
                    fix="keep unowned bare raise loud",
                )
            from sugar_lift_py_tests.in_flight_effect import (
                resolve_in_flight_effect,
            )

            return ExitSet.halted(
                resolve_in_flight_effect(ctx, self.in_flight_slot, blame=self.site)
            )

        def halt(raised_value, cause_value=None):
            return ExitSet.halted(self._effect(raised_value, ctx, cause_value))

        def after_exception(raised_value):
            from sugar_lift_py_tests.floor.grouped_exception_value import (
                GroupedExceptionValue,
            )

            if isinstance(raised_value, GroupedExceptionValue):
                # Re-raising an authenticated group object raises that same
                # group tree; its leaves keep their RaiseEffect identity.
                if self.cause is not None or self.in_flight_slot is not None:
                    from sugar_source_tree.panic import SugarNotWritten

                    raise SugarNotWritten(
                        blame=self.site,
                        owner="RaiseSugar.desugar",
                        observed="group re-raise with a cause or in-flight context",
                        requested="group __cause__/__context__ semantics",
                        fix="keep group chaining loud",
                    )
                return ExitSet.halted(raised_value.effect)
            if self.cause is None:
                return halt(raised_value)
            return self.cause.desugar(ctx).and_then(
                lambda cause_value: halt(raised_value, cause_value)
            )

        return self.exception.desugar(ctx).and_then(after_exception)


def _occurrence_key(blame):
    """This evaluation of the raise (``occurrence.occurrence_key``)."""
    from sugar_lift_py_tests.occurrence import occurrence_key

    return None if blame is None else occurrence_key(blame)
