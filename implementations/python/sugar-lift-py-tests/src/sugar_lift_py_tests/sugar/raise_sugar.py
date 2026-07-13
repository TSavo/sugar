from __future__ import annotations

from dataclasses import dataclass, field as dataclass_field

from sugar_lift_py_tests.claim import SugarRole
from sugar_lift_py_tests.effect import RaiseEffect
from sugar_lift_py_tests.floor import RaiseValue
from sugar_lift_py_tests.outcome import Complete, Outcome
from sugar_lift_py_tests.sugar.sugar_base import Sugar
from sugar_lift_py_tests.sugar.witnesses import _call_pair


@dataclass(frozen=True)
class RaiseSugar(Sugar, role=SugarRole.STATEMENT):
    """`raise ...` -- routeable Python raise exit (not Incomplete).

    Restored after the recognize-or-panic rebuild deleted the half-API form.
    Owns every Raise so bodies under ``pytest.raises`` / try are constructible.
    The block frontier carries ``RaiseValue``; rest after raise stays raw.
    """

    exception_name: str | None
    site: object = dataclass_field(compare=False)

    @classmethod
    def owns(cls, site) -> bool:
        return site.observed == "Raise"

    @classmethod
    def new(cls, site, ctx) -> "RaiseSugar":
        del ctx
        exc = site.raise_exc()
        return cls(
            exception_name=_exception_name(exc) if exc is not None else None,
            site=site,
        )

    @classmethod
    def witnesses(cls):
        # Raise is control-flow data; pair discriminates via try/except face when
        # present. Minimal: raise in a path that prevents a wrong return.
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

        if Path(self.site.filename).is_absolute():
            from sugar_lift_py_tests.factory import factory_panic_gap

            factory_panic_gap(
                owner="RaiseSugar",
                blame=str(self.site),
                observed="absolute source locus",
                requested="workspace-relative source locus",
                fix="route the source through the workspace-relative lift door",
            )

        blame = str(self.site)
        source_sha256 = None
        if self.site.source is not None:
            source_sha256 = hashlib.sha256(self.site.source.encode()).hexdigest()
        return Complete(
            RaiseValue(
                RaiseEffect(self.exception_name, blame, source_sha256),
                scope=ctx,
            )
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
