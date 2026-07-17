from __future__ import annotations

from dataclasses import dataclass, field as dataclass_field

from sugar_lift_py_tests.claim import SugarRole
from sugar_lift_py_tests.effect import RaiseEffect
from sugar_lift_py_tests.floor import (
    CallSiteValue,
    ExceptionCauseValue,
    ExceptionValue,
    NoneValue,
    RaiseValue,
)
from sugar_lift_py_tests.outcome import Complete, Outcome
from sugar_lift_py_tests.sugar.sugar_base import Sugar
from sugar_lift_py_tests.sugar.witnesses import _call_pair
from sugar_lift_py_tests.sugar_body import SugarBody


@dataclass(frozen=True)
class RaiseSugar(Sugar, role=SugarRole.STATEMENT):
    """`raise ...` -- routeable Python raise exit (not Incomplete).

    Constructor expressions reduce through their term sugar first. An exact
    ``ExceptionValue`` then becomes the carried raise effect; arbitrary call
    coordinates are not reclassified by spelling.
    """

    exception_name: str | None
    exception_body: SugarBody | None
    cause_body: SugarBody | None
    cause_site: object | None = dataclass_field(compare=False)
    site: object = dataclass_field(compare=False)
    build_context: object = dataclass_field(compare=False)

    @classmethod
    def owns(cls, site) -> bool:
        return site.observed == "Raise"

    @classmethod
    def new(cls, site, ctx) -> "RaiseSugar":
        exc = site.raise_exc()
        cause = site.raise_cause()
        return cls(
            exception_name=_exception_name(exc) if exc is not None else None,
            exception_body=(
                ctx.build_body(exc, SugarRole.TERM)
                if exc is not None and exc.observed == "Call"
                else None
            ),
            cause_body=(
                ctx.build_body(cause, SugarRole.TERM) if cause is not None else None
            ),
            cause_site=cause,
            site=site,
            build_context=ctx,
        )

    @classmethod
    def witnesses(cls):
        prefix = (
            "def A(z):\n"
            "    if z < 0:\n"
            '        raise ValueError("neg") from TypeError("cause")\n'
            "    return z\n"
            "\n"
        )
        return _call_pair(
            name="raise_return",
            owner_sugar="RaiseSugar",
            truthful=prefix + "def test_a():\n    assert A(1) == 1\n",
            lying=prefix + "def test_a():\n    assert A(1) == 0\n",
        )

    def desugar(self, ctx: object = None) -> Outcome:
        import hashlib
        from pathlib import Path

        if ctx is None:
            ctx = self.build_context

        if Path(self.site.filename).is_absolute():
            from sugar_lift_py_tests.factory import factory_panic_gap

            factory_panic_gap(
                owner="RaiseSugar",
                blame=self.site,
                observed="absolute source locus",
                requested="workspace-relative source locus",
                fix="route the source through the workspace-relative lift door",
            )

        source_sha256 = None
        if self.site.source is not None:
            source_sha256 = hashlib.sha256(self.site.source.encode()).hexdigest()

        if self.exception_body is None:
            raised = RaiseValue(
                RaiseEffect(self.exception_name, str(self.site), source_sha256),
                scope=ctx,
            )
            return self._attach_cause(raised, ctx)
        return self.exception_body.reduce(ctx).and_then(
            lambda value: self._constructed_raise(value, ctx, source_sha256)
        )

    def _constructed_raise(self, value, ctx, source_sha256: str | None) -> Outcome:
        if not isinstance(value, ExceptionValue):
            from sugar_lift_py_tests.factory import factory_panic_gap

            factory_panic_gap(
                owner="RaiseSugar",
                blame=self.site,
                observed=type(value).__name__,
                requested="constructed exception floor",
                fix=(
                    "construct an exact ExceptionValue before raise; "
                    "do not substitute arbitrary call coordinates"
                ),
            )
        effect = RaiseEffect(
            value.exception_name,
            str(self.site),
            source_sha256,
        )
        return self._attach_cause(
            RaiseValue(effect, scope=ctx, exception=value),
            ctx,
        )

    def _attach_cause(self, raised: RaiseValue, ctx: object) -> Outcome:
        if self.cause_body is None:
            return Complete(raised)
        return self.cause_body.reduce(
            ctx
        ).and_then(  # pyright: ignore[reportArgumentType]
            lambda value: self._constructed_cause(raised, value)
        )

    def _constructed_cause(self, raised: RaiseValue, value) -> Outcome:
        is_caught_exception = (
            isinstance(value, CallSiteValue) and value.target_name == "except"
        )
        if (
            not isinstance(value, (ExceptionValue, NoneValue))
            and not is_caught_exception
        ):
            from sugar_lift_py_tests.factory import factory_panic_gap

            factory_panic_gap(
                owner="RaiseSugar",
                blame=self.cause_site or self.site,
                observed=type(value).__name__,
                requested="constructed exception-cause floor",
                fix=(
                    "construct an exact exception instance, caught-exception "
                    "coordinate, or None before using it as an explicit cause"
                ),
            )
        return Complete(
            RaiseValue(
                raised.effect,
                scope=raised.scope,
                exception=raised.exception,
                cause=ExceptionCauseValue(value, self.cause_site),
            )
        )

    def walk_children(self):
        return tuple(
            body for body in (self.exception_body, self.cause_body) if body is not None
        )


def _exception_name(site) -> str | None:
    if site is None:
        return None
    if site.observed == "Call":
        return site.call_qualified_target_name() or site.call_target_name()
    if site.observed == "Name":
        return site.name_id()
    if site.observed == "Attribute":
        receiver = _exception_name(site.attr_receiver())
        if receiver is not None:
            return f"{receiver}.{site.attr_name()}"
        return site.attr_name()
    return None
