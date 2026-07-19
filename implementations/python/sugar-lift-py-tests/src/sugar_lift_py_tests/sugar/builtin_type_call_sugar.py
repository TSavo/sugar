from __future__ import annotations

from dataclasses import dataclass

from sugar_lift_py_tests.claim import SugarRole
from sugar_lift_py_tests.recognition.callee_universe import CalleeUniverseRecognition
from sugar_lift_py_tests.sugar.call_sugar import CallSugar
from sugar_lift_py_tests.sugar.witnesses import _call_pair


@dataclass(frozen=True)
class BuiltinTypeCallSugar(CallSugar, role=SugarRole.TERM, comes_before=("CallSugar",)):
    """Authenticated bare-builtin ``type(value)`` call.

    The factory already authenticates the native call shape as a bare call with
    no receiver; this registered specialization gives the callee-universe walk
    a cited owner. A receiver-qualified or shadowed spelling remains outside
    this partition and stays on the ordinary call/loud path.
    """

    @classmethod
    def owns(cls, site) -> bool:
        if not (
            site.observed == "Call"
            and site.call_receiver() is None
            and site.call_target_name() == "type"
            and site.call_arg_count() == 1
            and not site.call_has_keywords()
        ):
            return False
        # Same unshadowed warrant as other bare-builtin coordinates: parameters
        # and late rebinds revoke, so floors stay loud under impostors.
        return CalleeUniverseRecognition.coordinate(site) == "type"

    @classmethod
    def new(cls, site, ctx):
        return super().new(site, ctx)

    def desugar(self, ctx: object = None):
        return super().desugar(ctx)

    @classmethod
    def witnesses(cls):
        return _call_pair(
            name="builtin_type_call_authentication",
            owner_sugar="BuiltinTypeCallSugar",
            truthful="def test_a():\n    assert type(1) is int\n",
            lying="def test_a():\n    assert type(1) is str\n",
        )
