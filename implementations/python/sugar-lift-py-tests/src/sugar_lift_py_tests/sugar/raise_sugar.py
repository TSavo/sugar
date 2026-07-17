from __future__ import annotations

from dataclasses import dataclass, field as dataclass_field

from sugar_lift_py_tests.claim import SugarRole
from sugar_lift_py_tests.effect import RaiseEffect
from sugar_lift_py_tests.floor import ExceptionValue, RaiseValue
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
    has_explicit_cause: bool
    site: object = dataclass_field(compare=False)
    build_context: object = dataclass_field(compare=False)

    @classmethod
    def owns(cls, site) -> bool:
        return site.observed == "Raise"

    @classmethod
    def new(cls, site, ctx) -> "RaiseSugar":
        exc = site.raise_exc()
        return cls(
            exception_name=_exception_name(exc) if exc is not None else None,
            exception_body=(
                ctx.build_body(exc, SugarRole.TERM)
                if exc is not None and exc.observed == "Call"
                else None
            ),
            has_explicit_cause=site.raise_cause() is not None,
            site=site,
            build_context=ctx,
        )

    @classmethod
    def witnesses(cls):
        prefix = (
            "def A(z):\n"
            "    if z < 0:\n"
            '        raise ValueError("neg")\n'
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

        if self.has_explicit_cause:
            from sugar_lift_py_tests.factory import factory_panic_gap

            factory_panic_gap(
                owner="RaiseSugar",
                blame=self.site,
                observed="raise ... from ...",
                requested="an explicit exception-cause floor",
                fix="construct and carry the cause separately from the raised exception",
            )

        source_sha256 = None
        if self.site.source is not None:
            source_sha256 = hashlib.sha256(self.site.source.encode()).hexdigest()

        if self.exception_body is None:
            return Complete(
                RaiseValue(
                    RaiseEffect(self.exception_name, str(self.site), source_sha256),
                    scope=ctx,
                )
            )
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
        return Complete(RaiseValue(effect, scope=ctx, exception=value))

    def walk_children(self):
        return (self.exception_body,) if self.exception_body is not None else ()


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
