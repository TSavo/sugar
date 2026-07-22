from __future__ import annotations

import hashlib
from dataclasses import dataclass, field as dataclass_field

from sugar_lift_py_tests.effect import RaiseEffect
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
    exception_name: str | None
    site: object = dataclass_field(compare=False)

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

        def halt(raised_value=None):
            return Incomplete(
                RaiseEffect(
                    exception_name=self.exception_name,
                    blame=blame,
                    source_sha256=source_sha256,
                    # Occurrence is the raise site — not a type-level identity.
                    occurrence=blame,
                    raised_value=raised_value,
                )
            )

        if self.exception is None:
            return halt()
        return self.exception.desugar(ctx).and_then(halt)
