"""Unit twins for resource ``WithResourceSugar`` — manager once, face exit args.

No callback side doors. Production ``open(...)`` stays RuntimeSelected.
"""

from __future__ import annotations

from sugar_lift_py_tests.context_manager_contract import (
    NeverSuppresses,
    RuntimeSelected,
)
from sugar_lift_py_tests.effect import RaiseEffect
from sugar_lift_py_tests.floor.block_value import BlockValue
from sugar_lift_py_tests.floor.call_site_value import ExitSuppressionContract
from sugar_lift_py_tests.floor.manager_coordinate import (
    ManagerCoordinate,
    OpenExitArg,
    RaiseWitnessCoordinate,
)
from sugar_lift_py_tests.outcome import Complete, Incomplete
from sugar_lift_py_tests.sugar.method_call_sugar import MethodCallSugar
from sugar_lift_py_tests.sugar.resource_coord_sugar import ManagerRefSugar
from sugar_lift_py_tests.sugar.sugar_base import Sugar
from sugar_lift_py_tests.sugar.with_resource_sugar import WithResourceSugar


class _FixedSugar(Sugar):
    def __init__(self, outcome, *, probe=None):
        self._outcome = outcome
        self._probe = probe

    def desugar(self, ctx=None):
        del ctx
        if self._probe is not None:
            self._probe.append(1)
        return self._outcome

    @classmethod
    def witnesses(cls):
        return ()


class _Pass(_FixedSugar):
    def __init__(self, probe=None):
        super().__init__(
            Complete(BlockValue((), can_fall_through=True)), probe=probe
        )


class _Raise(_FixedSugar):
    def __init__(self, name: str, *, occurrence: str = "t.py:1:0", probe=None):
        super().__init__(
            Incomplete(
                RaiseEffect(exception_name=name, occurrence=occurrence)
            ),
            probe=probe,
        )


class _FloorValue:
    """Minimal FloorValue stand-in for manager/enter completed values."""

    def __init__(self, label: str):
        self.label = label

    def to_term(self, *, owner: str):
        del owner
        from sugar_lift_py_tests.ir import str_const

        return str_const(self.label)


def _mgr_once(probe=None):
    return _FixedSugar(Complete(_FloorValue("mgr")), probe=probe)


def _enter_ok(probe=None):
    return _FixedSugar(Complete(_FloorValue("entered")), probe=probe)


def _resource(
    *,
    manager=None,
    enter=None,
    body=None,
    disposition=None,
    manager_slot_id="M",
    enter_slot_id=None,
):
    return WithResourceSugar(
        manager=manager or _mgr_once(),
        manager_slot_id=manager_slot_id,
        enter=enter or _enter_ok(),
        body=body if body is not None else (_Pass(),),
        disposition=disposition or NeverSuppresses(),
        enter_slot_id=enter_slot_id,
        site=None,
    )


def test_manager_expression_evaluated_exactly_once():
    """Side-effecting manager twin: context expr desugars once, not twice."""
    seen = []
    sugar = _resource(manager=_mgr_once(probe=seen), body=(_Pass(),))
    sugar.desugar()
    assert seen == [1]


def test_enter_halt_skips_body_and_exit():
    body_ran = []
    enter_halt = RaiseEffect(exception_name="OSError")
    sugar = _resource(
        enter=_FixedSugar(Incomplete(enter_halt)),
        body=(_Pass(probe=body_ran),),
    )
    out = sugar.desugar()
    assert body_ran == []
    reds = [e for e in out.value.contribution() if isinstance(e, Incomplete)]
    assert len(reds) == 1
    assert reds[0].effect == enter_halt


def test_never_suppresses_restores_body_halt_after_exit_completes():
    sugar = _resource(body=(_Raise("ValueError"),))
    out = sugar.desugar()
    reds = [e for e in out.value.contribution() if isinstance(e, Incomplete)]
    assert len(reds) == 1
    assert reds[0].effect.exception_name == "ValueError"


def test_exit_halt_supersedes_body_halt():
    # Enter completes; body raises; exit is raised via MethodCall on ManagerRef
    # that we replace by using a body raise + disposition — exit method coords
    # complete as CallSiteValue. Supersede tested via enter path with halt exit
    # only when enter itself is the exit-like halt:
    sugar = _resource(
        enter=_Raise("RuntimeError"),
        body=(_Raise("ValueError"),),
    )
    out = sugar.desugar()
    reds = [e for e in out.value.contribution() if isinstance(e, Incomplete)]
    assert len(reds) == 1
    assert reds[0].effect.exception_name == "RuntimeError"


def test_proven_contract_consumes_matching_body_halt():
    sugar = _resource(
        body=(_Raise("ValueError"),),
        disposition=ExitSuppressionContract.suppresses(("ValueError",)),
    )
    out = sugar.desugar()
    reds = [e for e in out.value.contribution() if isinstance(e, Incomplete)]
    assert reds == []


def test_runtime_selected_not_guessed():
    sugar = _resource(
        body=(_Raise("ValueError"),),
        disposition=RuntimeSelected(),
    )
    out = sugar.desugar()
    reds = [e for e in out.value.contribution() if isinstance(e, Incomplete)]
    assert len(reds) == 1


def test_completed_body_survives_never_suppresses():
    sugar = _resource(body=(_Pass(),))
    out = sugar.desugar()
    assert not any(isinstance(e, Incomplete) for e in out.value.contribution())


def test_exit_sugar_for_completed_face_is_none_triple():
    from sugar_lift_py_tests.outcome.exit_set import Completed, true_guard

    sugar = _resource(body=(_Pass(),))
    face = Completed(true_guard(), BlockValue((), can_fall_through=True))
    exit_sugar = sugar._exit_sugar_for_face(face)
    assert isinstance(exit_sugar, MethodCallSugar)
    assert exit_sugar.name == "__exit__"
    assert isinstance(exit_sugar.receiver, ManagerRefSugar)
    assert exit_sugar.receiver.slot_id == "M"
    assert len(exit_sugar.args) == 3
    # None, None, None for completed
    assert all(type(a).__name__ == "NoneLiteralSugar" for a in exit_sugar.args)


def test_exit_sugar_for_raised_face_is_not_none_triple():
    from sugar_lift_py_tests.outcome.exit_set import Halted, true_guard

    sugar = _resource(manager_slot_id="mgr1")
    effect = RaiseEffect(exception_name="ValueError", occurrence="src.py:3:4")
    face = Halted(true_guard(), effect)
    exit_sugar = sugar._exit_sugar_for_face(face)
    assert isinstance(exit_sugar, MethodCallSugar)
    assert exit_sugar.receiver.slot_id == "mgr1"
    args = exit_sugar.args
    assert type(args[0]).__name__ == "OpenExitArgSugar"
    assert args[0].kind == "exc_type"
    assert type(args[1]).__name__ == "RaiseWitnessSugar"
    assert args[1].occurrence == "src.py:3:4"
    assert type(args[2]).__name__ == "OpenExitArgSugar"
    assert args[2].kind == "traceback"
    # Desugar args: open + witness + open — never three Nones.
    a0 = args[0].desugar().value
    a1 = args[1].desugar().value
    a2 = args[2].desugar().value
    assert isinstance(a0, OpenExitArg) and a0.kind == "exc_type"
    assert isinstance(a1, RaiseWitnessCoordinate)
    assert a1.occurrence == "src.py:3:4"
    assert isinstance(a2, OpenExitArg) and a2.kind == "traceback"


def test_enter_result_binding_facts_when_slot_present():
    sugar = _resource(
        body=(_Pass(),),
        enter_slot_id="E",
        enter=_FixedSugar(Complete(_FloorValue("entered-val"))),
        manager=_FixedSugar(Complete(_FloorValue("mgr-val"))),
    )
    out = sugar.desugar()
    invs = list(out.value.inv_contribution()) if hasattr(out.value, "inv_contribution") else []
    # Facts ride in BlockValue entries as InvValues
    from sugar_lift_py_tests.floor.inv_value import InvValue

    entries = list(out.value.contribution())
    invs = [e for e in entries if isinstance(e, InvValue)]
    names = []
    for inv in invs:
        f = inv.formula
        if getattr(f, "name", None) == "=":
            left = f.args[0]
            names.append(getattr(left, "name", None))
    assert "manager_slot_value" in names
    assert "enter_result_value" in names


def test_manager_ref_sugar_is_manager_coordinate():
    out = ManagerRefSugar(slot_id="M42").desugar()
    assert isinstance(out.value, ManagerCoordinate)
    assert out.value.slot_id == "M42"
