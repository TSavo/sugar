from __future__ import annotations

import hashlib
from dataclasses import dataclass, field as dataclass_field

from sugar_lift_py_tests.effect import RaiseEffect, UndeterminedRaiseEffect
from sugar_lift_py_tests.outcome import Incomplete, Outcome
from sugar_lift_py_tests.sugar.sugar_base import Sugar
from sugar_lift_py_tests.sugar.witnesses import typed_red_effect_witness


@dataclass(frozen=True)
class RaiseSugar(Sugar):
    """`raise <exc>` -- a statement that HALTS the block.

    A raise never states a fact and never returns a value: it exits. So it is
    the halt arm of ``match(Sugar) { Some => cite_or_effect, None => panic }`` --
    it desugars to a typed-red effect, ``Incomplete(RaiseEffect)``, not to a
    ``Complete`` floor value. Its ``follow`` halts the block (a RaiseEffect is
    not a store effect, so the rest of the block stays unreduced); a matching
    ``TrySugar`` handler may later route it, and unrouted it is the block's exit.

    The exception child is built normally and carried on the effect.  Its
    structural name remains routing provenance only; spelling never creates
    or authenticates an exception value.
    """

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

    def desugar(self, ctx: object = None) -> Outcome:
        # The halt: an Incomplete carrying the named raise effect. blame is the
        # construction locus; source_sha256 pins the text the raise lives in.
        source = getattr(self.site.unit, "source", None)
        source_sha256 = (
            hashlib.sha256(source.encode()).hexdigest() if source is not None else None
        )
        blame = f"{self.site.filename}:{self.site.line}:{self.site.col}"

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

            return Incomplete(
                resolve_in_flight_effect(ctx, self.in_flight_slot, blame=self.site)
            )

        def halt(raised_value, cause_value=None):
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
                from sugar_lift_py_tests.effect.raise_effect import (
                    UndeterminedRaiseEffect,
                )

                return Incomplete(
                    UndeterminedRaiseEffect(
                        exception_name=self.exception_name,
                        blame=blame,
                        source_sha256=source_sha256,
                        occurrence=blame,
                        raised_value=raised_value,
                        cause_value=cause_value,
                        context_effect=context_effect,
                        producer_node_owner="RaiseSugar.desugar",
                    )
                )
            return Incomplete(
                RaiseEffect(exception_type_coordinate=coordinate, occurrence=AuthenticatedRaiseLocus.of(blame), exception_name=self.exception_name, blame=blame, source_sha256=source_sha256, exception_type_mro=mro_reader() if callable(mro_reader) else getattr(raised_value, 'exception_type_mro', None), raised_value=raised_value, cause_value=cause_value, context_effect=context_effect)
            )

        def after_exception(raised_value):
            if self.cause is None:
                return halt(raised_value)
            return self.cause.desugar(ctx).and_then(
                lambda cause_value: halt(raised_value, cause_value)
            )

        return self.exception.desugar(ctx).and_then(after_exception)
