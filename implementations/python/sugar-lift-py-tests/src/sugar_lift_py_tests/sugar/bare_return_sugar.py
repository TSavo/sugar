from __future__ import annotations

from dataclasses import dataclass, field as dataclass_field

from sugar_lift_py_tests.claim import SugarRole
from sugar_lift_py_tests.floor import NoneValue, ReturnValue
from sugar_lift_py_tests.outcome import Complete, Outcome
from sugar_lift_py_tests.sugar.sugar_base import Sugar
from sugar_lift_py_tests.sugar.witnesses import _call_pair


@dataclass(frozen=True)
class BareReturnSugar(Sugar, role=SugarRole.STATEMENT):
    """Bare ``return`` — Python's explicit return of None (not invented).

    Distinct from ``return <expr>`` (ReturnSugar). Owns only value-less Return
    and emits ``ReturnValue(NoneValue())``.
    """

    site: object = dataclass_field(compare=False)

    @classmethod
    def owns(cls, site) -> bool:
        return site.observed == "Return" and site.return_value() is None

    @classmethod
    def new(cls, site, ctx) -> "BareReturnSugar":
        del ctx
        return cls(site=site)

    @classmethod
    def witnesses(cls):
        return _call_pair(
            name="bare_return_none",
            owner_sugar="BareReturnSugar",
            truthful=(
                "def A(z):\n"
                "    if z == 0:\n"
                "        return\n"
                "    return 1\n"
                "\n"
                "def test_a():\n"
                "    assert A(0) is None\n"
            ),
            lying=(
                "def A(z):\n"
                "    if z == 0:\n"
                "        return\n"
                "    return 1\n"
                "\n"
                "def test_a():\n"
                "    assert A(0) == 1\n"
            ),
        )

    def desugar(self, ctx: object = None) -> Outcome:
        del ctx
        return Complete(ReturnValue(NoneValue()))

    def walk_children(self):
        return ()
