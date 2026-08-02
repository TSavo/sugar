"""Unit twins for the authenticated builtin resource lifecycle."""

from __future__ import annotations

import ast
import inspect

import pytest

from sugar_lift_py_tests.context_manager_contract import (
    NeverSuppresses,
    NeverSuppressesDispositionV1,
    ReturnTruthinessDispositionV1,
    RuntimeSelected,
)
from sugar_lift_py_tests.context_manager_resolution import SourceFragmentCoordinateV1
from sugar_lift_py_tests.effect import LoopControlEffect, RaiseEffect
from sugar_lift_py_tests.effect.authenticated_raise_locus import AuthenticatedRaiseLocus
from sugar_lift_py_tests.floor import ObjectValue, SymbolicValue, TermValue
from sugar_lift_py_tests.floor.block_value import BlockValue
from sugar_lift_py_tests.floor.call_site_value import ExitSuppressionContract
from sugar_lift_py_tests.floor.manager_coordinate import (
    ExitTracebackCoordinate,
    ExitTypeCoordinate,
    ExitValueCoordinate,
    ManagerCoordinate,
)
from sugar_lift_py_tests.floor.inv_value import InvValue
from sugar_lift_py_tests.floor.guarded_faces import GuardedFaces
from sugar_lift_py_tests.ir import atomic, make_var, not_
from sugar_lift_py_tests.outcome import Complete, Incomplete
from sugar_lift_py_tests.outcome import exit_disposition as exit_disposition_module
from sugar_lift_py_tests.outcome.exit_disposition import exit_disposition_effect
from sugar_lift_py_tests.outcome.exit_set import Completed, Halted, true_guard
from sugar_lift_py_tests.outcome.resource_bindings import ExitFaceBinding
from sugar_lift_py_tests.sugar.method_call_sugar import MethodCallSugar
from sugar_lift_py_tests.sugar.resource_coord_sugar import (
    ExitTracebackRefSugar,
    ExitTypeRefSugar,
    ExitValueRefSugar,
    ManagerRefSugar,
)
from sugar_lift_py_tests.sugar.sugar_base import Sugar
from sugar_lift_py_tests.sugar.with_resource_sugar import WithResourceSugar


def test_authenticated_pandas_303_builtin_open_resource_coordinate():
    """Real corpus half; native-definition lifecycle twins below are synthetic."""
    from sugar_lift_py_tests.authenticated_pytest import authenticated_pandas_corpus

    corpus = authenticated_pandas_corpus()
    assert (corpus.version, corpus.file_count) == ("3.0.3", 1421)
    relative = "tests/series/methods/test_to_csv.py"
    source = (corpus.root / relative).read_text(encoding="utf-8")
    site = next(
        node
        for node in ast.walk(ast.parse(source, filename=relative))
        if isinstance(node, ast.With)
        and node.lineno == 57
        and isinstance(node.items[0].context_expr, ast.Call)
    )
    item = site.items[0]
    assert ast.get_source_segment(source, item.context_expr) == (
        'open(path, "w", encoding="utf-8")'
    )
    assert ast.get_source_segment(source, item.optional_vars) == "outfile"


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
        super().__init__(Complete(BlockValue((), can_fall_through=True)), probe=probe)


class _Raise(_FixedSugar):
    def __init__(self, name: str, *, occurrence: str = "t.py:1:0", probe=None):
        from sugar_lift_py_tests.floor.ground_exit import _builtin_exception_identity

        coordinate, mro = _builtin_exception_identity(name)
        super().__init__(
            Incomplete(
                RaiseEffect(exception_type_coordinate=coordinate, occurrence=AuthenticatedRaiseLocus.of(occurrence), exception_name=name, exception_type_mro=mro)
            ),
            probe=probe,
        )


class _FloorValue:
    def __init__(self, label: str):
        self.label = label

    def to_term(self, *, owner: str):
        del owner
        from sugar_lift_py_tests.ir import str_const

        return str_const(self.label)


def _parametric_exit(face_id="X", manager_slot="M", probe=None):
    """Prebuilt tree-shaped exit: M.__exit__(ExitTypeRef(X), …)."""
    return MethodCallSugar(
        receiver=ManagerRefSugar(slot_id=manager_slot, site=None),
        name="__exit__",
        args=(
            ExitTypeRefSugar(face_id=face_id, site=None),
            ExitValueRefSugar(face_id=face_id, site=None),
            ExitTracebackRefSugar(face_id=face_id, site=None),
        ),
        site=None,
    )


def _resource(
    *,
    manager=None,
    enter=None,
    exit=None,
    body=None,
    disposition=None,
    manager_slot_id="M",
    exit_face_id="X",
    enter_slot_id=None,
    exit_probe=None,
):
    exit_sugar = exit
    if exit_sugar is None:
        exit_sugar = _parametric_exit(
            face_id=exit_face_id, manager_slot=manager_slot_id
        )
        if exit_probe is not None:
            # Wrap to count desugars of the prebuilt exit sugar.
            inner = exit_sugar

            class _ProbeExit(Sugar):
                def desugar(self, ctx=None):
                    exit_probe.append(1)
                    return inner.desugar(ctx)

                @classmethod
                def witnesses(cls):
                    return ()

            exit_sugar = _ProbeExit()

    from dataclasses import replace
    from sugar_lift_py_tests.sugar.method_call_sugar import MethodCallSugar

    enter_definition = SourceFragmentCoordinateV1("blake3-512:" + "e" * 128, 1, 0, 1, 1)
    exit_definition = SourceFragmentCoordinateV1("blake3-512:" + "x" * 128, 2, 0, 2, 1)
    if isinstance(enter, MethodCallSugar):
        enter = replace(enter, native_definition_coordinate=enter_definition)
    if isinstance(exit_sugar, MethodCallSugar):
        exit_sugar = replace(exit_sugar, native_definition_coordinate=exit_definition)

    return WithResourceSugar(
        manager=manager
        or _FixedSugar(Complete(ObjectValue("native-resource", (), identity="mgr"))),
        manager_slot_id=manager_slot_id,
        enter=enter or _FixedSugar(Complete(_FloorValue("entered"))),
        exit=exit_sugar,
        exit_face_id=exit_face_id,
        body=body if body is not None else (_Pass(),),
        disposition=disposition or NeverSuppresses(),
        enter_slot_id=enter_slot_id,
        enter_definition=enter_definition,
        exit_definition=exit_definition,
        site=None,
    )


def test_runtime_selected_authenticates_completed_face_without_mutation():
    value = object()
    incoming = Completed(true_guard(), value)

    assert exit_disposition_effect(RuntimeSelected(), incoming) is None
    assert incoming.value is value


def test_runtime_selected_authenticates_halted_face_preserving_identity():
    effect = RaiseEffect.for_builtin("ValueError", occurrence="law.py:1:0")
    state = object()
    incoming = Halted(true_guard(), effect, state)

    assert exit_disposition_effect(RuntimeSelected(), incoming) is effect
    assert incoming.effect is effect
    assert incoming.state is state


def test_none_disposition_refuses_completed_face_without_mutation():
    value = object()
    incoming = Completed(true_guard(), value)

    with pytest.raises(TypeError) as raised:
        exit_disposition_effect(None, incoming)

    assert str(raised.value) == (
        "exit disposition must be NeverSuppresses, ExitSuppressionContract, "
        "RuntimeSelected, Suppresses, or EffectBoundaryDisposition; got NoneType"
    )
    assert incoming.value is value


def test_none_disposition_refuses_halted_face_without_mutation():
    effect = RaiseEffect.for_builtin("ValueError", occurrence="law.py:2:0")
    state = object()
    incoming = Halted(true_guard(), effect, state)

    with pytest.raises(TypeError) as raised:
        exit_disposition_effect(None, incoming)

    assert str(raised.value) == (
        "exit disposition must be NeverSuppresses, ExitSuppressionContract, "
        "RuntimeSelected, Suppresses, or EffectBoundaryDisposition; got NoneType"
    )
    assert incoming.effect is effect
    assert incoming.state is state


def test_none_disposition_compatibility_paths_are_structurally_absent():
    module_tree = ast.parse(inspect.getsource(exit_disposition_module))

    none_arms = [
        node
        for node in ast.walk(module_tree)
        if isinstance(node, ast.Compare)
        and isinstance(node.left, ast.Name)
        and node.left.id == "disposition"
        and any(isinstance(op, ast.Is) for op in node.ops)
        and any(
            isinstance(comparator, ast.Constant) and comparator.value is None
            for comparator in node.comparators
        )
    ]
    production_mappers = [
        node
        for node in ast.walk(module_tree)
        if isinstance(node, ast.Call)
        and isinstance(node.func, ast.Name)
        and node.func.id == "RuntimeSelected"
    ]
    assert none_arms == []
    assert production_mappers == []


def test_manager_expression_evaluated_exactly_once():
    seen = []
    sugar = _resource(
        manager=_FixedSugar(
            Complete(ObjectValue("native-resource", (), identity="mgr")), probe=seen
        ),
        body=(_Pass(),),
    )
    sugar.desugar()
    assert seen == [1]


def test_parametric_exit_desugars_once_for_body_path():
    """Prebuilt exit sugar desugars once when the body path runs."""
    seen = []
    sugar = _resource(body=(_Raise("ValueError"),), exit_probe=seen)
    sugar.desugar()
    assert seen == [1]


def test_exit_face_binding_applied_per_face_without_rebuilding_exit():
    """Exit sugar desugars once; face kinds differ by ExitFaceBinding."""
    seen = []
    sugar = _resource(body=(_Raise("KeyError"),), exit_probe=seen)
    sugar.desugar()
    assert seen == [1]
    completed = ExitFaceBinding.from_body_exit(
        "X", Completed(true_guard(), BlockValue((), can_fall_through=True))
    )
    raised = ExitFaceBinding.from_body_exit(
        "X",
        Halted(
            true_guard(),
            RaiseEffect.for_builtin("KeyError", occurrence="k.py:1:0"),
        ),
    )
    assert completed.kind == "completed"
    assert raised.kind == "raised"
    assert completed.kind != raised.kind


def test_enter_halt_skips_body_and_exit():
    body_ran = []
    exit_ran = []
    enter_halt = RaiseEffect.for_builtin('OSError', occurrence='implementations/python/sugar-lift-py-tests/tests/test_with_resource_sugar.py:303:0')
    sugar = _resource(
        enter=_FixedSugar(Incomplete(enter_halt)),
        body=(_Pass(probe=body_ran),),
        exit_probe=exit_ran,
    )
    out = sugar.desugar()
    assert body_ran == []
    assert exit_ran == []
    reds = [e for e in out.value.contribution() if isinstance(e, Incomplete)]
    assert len(reds) == 1
    assert reds[0].effect == enter_halt


def test_completed_body_runs_exit_with_three_explicit_none_coordinates():
    """Face 2: normal completion authenticates all three None arguments."""
    out = _resource(body=(_Pass(),), exit=_FixedSugar(Complete(TermValue(0)))).desugar()
    invs = [entry for entry in out.value.contribution() if isinstance(entry, InvValue)]
    exit_facts = [
        inv
        for inv in invs
        if getattr(getattr(inv.formula, "args", (None,))[0], "name", None)
        in {"exit_type", "exit_value", "exit_traceback"}
    ]
    assert len(exit_facts) == 3
    assert {fact.formula.args[0].name for fact in exit_facts} == {
        "exit_type",
        "exit_value",
        "exit_traceback",
    }
    assert all(fact.formula.args[1].value == "None" for fact in exit_facts)


def test_raised_body_routes_exact_face_coordinates_to_exit():
    """Face 3: type/value/traceback coordinates share the exact raised face."""
    face_id = "raised-face-17"
    effect = RaiseEffect.for_builtin("ValueError",
        
        occurrence="source.py:17:8",
    )
    exit_sugar = _parametric_exit(face_id=face_id)
    type_coord, value_coord, traceback_coord = (
        argument.desugar().value for argument in exit_sugar.args
    )
    assert type_coord == ExitTypeCoordinate(face_id, None)
    assert value_coord == ExitValueCoordinate(face_id, None)
    assert traceback_coord == ExitTracebackCoordinate(face_id, None)

    binding = ExitFaceBinding.from_body_exit(face_id, Halted(true_guard(), effect))
    assert binding.face_id == face_id
    facts = binding.to_facts()
    assert {fact.formula.args[0].args[0].value for fact in facts} == {face_id}
    assert any(
        getattr(fact.formula.args[1], "value", None) == "ValueError" for fact in facts
    )
    assert any(
        getattr(fact.formula.args[1], "name", None) == "python:raise_effect_occurrence"
        and fact.formula.args[1].args[0].value == "source.py:17:8"
        for fact in facts
    )


def test_falsy_source_exit_preserves_the_exact_original_halt():
    """Face 4: falsity restores the same effect and pre-effect state objects."""
    from sugar_lift_py_tests.outcome.exit_set import ExitSet

    effect = RaiseEffect.for_builtin("ValueError", occurrence="body.py:4:2")
    state = ObjectValue("native-resource", (), identity="before-raise")
    incoming = Halted(true_guard(), effect, state)
    routed = ExitSet((incoming,)).and_exit_truthiness(
        ExitSet.completed(TermValue(False)), site="exit-site"
    )
    assert len(routed.exits) == 1
    surviving = routed.exits[0]
    assert isinstance(surviving, Halted)
    assert surviving.effect is effect
    assert surviving.state is state


def test_truthy_source_exit_suppresses_the_original_raise():
    """Face 5: source-testified truth consumes the raised edge."""
    from sugar_lift_py_tests.outcome.exit_set import ExitSet

    effect = RaiseEffect.for_builtin("ValueError", occurrence="body.py:5:2")
    routed = ExitSet((Halted(true_guard(), effect),)).and_exit_truthiness(
        ExitSet.completed(TermValue(True)), site="exit-site"
    )
    assert all(not isinstance(face, Halted) for face in routed.exits)


def test_undecided_source_exit_keeps_both_faces_factored():
    """Face 6: UNKNOWN truth is neither false nor true; both arms survive."""
    from sugar_lift_py_tests.outcome.exit_set import ExitSet

    effect = RaiseEffect.for_builtin("ValueError", occurrence="body.py:6:2")
    routed = ExitSet((Halted(true_guard(), effect),)).and_exit_truthiness(
        ExitSet.completed(SymbolicValue(make_var("exit_result"))), site="exit-site"
    )
    assert {type(face) for face in routed.exits} == {Completed, Halted}
    halted = next(face for face in routed.exits if isinstance(face, Halted))
    assert halted.effect is effect
    assert len({partition for face in routed.exits for partition in face.faces}) == 2


def test_never_suppresses_restores_body_halt():
    sugar = _resource(body=(_Raise("ValueError"),))
    out = sugar.desugar()
    reds = [e for e in out.value.contribution() if isinstance(e, Incomplete)]
    assert any(r.effect.exception_name == "ValueError" for r in reds)


def test_typed_never_suppresses_preserves_conditional_raise_and_normal_face():
    guard = atomic("with_body_guard", [make_var("state")])
    effect = RaiseEffect.for_builtin("ValueError", occurrence="body.py:4:8")

    class _ConditionalRaise(Sugar):
        def desugar(self, ctx=None):
            del ctx
            return Complete(
                GuardedFaces(
                    guard=guard,
                    entries=(Incomplete(effect).guarded(guard),),
                    then_exits=True,
                    else_exits=False,
                    can_fall_through=True,
                    continuation_guard=not_(guard),
                )
            )

        @classmethod
        def witnesses(cls):
            return ()

    exit_runs = []
    out = _resource(
        body=(_ConditionalRaise(),),
        disposition=NeverSuppressesDispositionV1(),
        exit_probe=exit_runs,
    ).desugar()
    contributions = out.value.contribution()
    raises = [
        entry
        for entry in contributions
        if isinstance(entry, Incomplete) and entry.effect == effect
    ]
    assert len(raises) == 1
    assert raises[0].branch_conditions == (guard,)
    assert out.value.can_fall_through
    assert exit_runs == [1]
    assert all(entry is not None for entry in contributions)


def test_proven_contract_consumes_matching_body_halt():
    sugar = _resource(
        body=(_Raise("ValueError"),),
        disposition=ExitSuppressionContract.suppresses(("ValueError",)),
    )
    out = sugar.desugar()
    reds = [
        e
        for e in out.value.contribution()
        if isinstance(e, Incomplete)
        and getattr(e.effect, "exception_name", None) == "ValueError"
    ]
    assert reds == []


def test_runtime_selected_not_guessed():
    sugar = _resource(
        body=(_Raise("ValueError"),),
        disposition=RuntimeSelected(),
    )
    out = sugar.desugar()
    reds = [
        e
        for e in out.value.contribution()
        if isinstance(e, Incomplete)
        and getattr(e.effect, "exception_name", None) == "ValueError"
    ]
    assert len(reds) == 1


@pytest.mark.parametrize(
    ("exit_value", "halt_count"), [(TermValue(1), 0), (TermValue(0), 1)]
)
def test_native_exit_return_truthiness_decides_raise_suppression(
    exit_value, halt_count
):
    """Synthetic extension: the native definition's real return decides."""
    out = _resource(
        body=(_Raise("ValueError"),),
        exit=_FixedSugar(Complete(exit_value)),
        disposition=ReturnTruthinessDispositionV1(),
    ).desugar()
    raises = [
        entry
        for entry in out.value.contribution()
        if isinstance(entry, Incomplete)
        and getattr(entry.effect, "exception_name", None) == "ValueError"
    ]
    assert len(raises) == halt_count


def test_native_undecided_exit_return_keeps_both_suppression_faces():
    """Load-bearing lying twin: unknown truth may never swallow the halt."""
    out = _resource(
        body=(_Raise("ValueError"),),
        exit=_FixedSugar(Complete(SymbolicValue(make_var("exit_result")))),
        disposition=ReturnTruthinessDispositionV1(),
    ).desugar()
    contributions = out.value.contribution()
    assert any(
        isinstance(entry, Incomplete)
        and getattr(entry.effect, "exception_name", None) == "ValueError"
        for entry in contributions
    )
    assert out.value.can_fall_through


def test_truthy_native_exit_runs_but_cannot_suppress_loop_transfer():
    """Truthy exit suppresses exceptions, never break/continue/return control."""
    cid = "blake3-512:" + "a" * 128
    transfer = LoopControlEffect("break", cid, cid)
    exit_runs = []
    out = _resource(
        body=(_FixedSugar(Incomplete(transfer)),),
        exit=_FixedSugar(Complete(TermValue(1)), probe=exit_runs),
        disposition=ReturnTruthinessDispositionV1(),
    ).desugar()
    assert exit_runs == [1]
    assert any(
        isinstance(entry, Incomplete) and entry.effect == transfer
        for entry in out.value.contribution()
    )


def test_native_exit_runs_on_early_return_value():
    from sugar_lift_py_tests.floor import ReturnValue

    exit_runs = []
    out = _resource(
        body=(_FixedSugar(Complete(ReturnValue(TermValue(7)))),),
        exit=_FixedSugar(Complete(TermValue(0)), probe=exit_runs),
        disposition=ReturnTruthinessDispositionV1(),
    ).desugar()
    assert exit_runs == [1]
    assert any(isinstance(entry, ReturnValue) for entry in out.value.contribution())


def test_completed_body_survives_never_suppresses():
    sugar = _resource(body=(_Pass(),))
    out = sugar.desugar()
    reds = [
        e
        for e in out.value.contribution()
        if isinstance(e, Incomplete)
        and getattr(getattr(e, "effect", None), "exception_name", None)
    ]
    assert reds == []


def test_resource_exit_runs_on_the_completed_and_the_halted_face(monkeypatch):
    """LAW (E1): `__exit__` runs on EVERY outgoing body edge, not the happy one.

    Pinned through `and_exit`, which is the ONE algebra that carries the
    contract: it hands each incoming face -- completed or halted -- to the
    disposition, and the disposition decides only whether that face leaves as a
    completion or a halt. Observing WHICH method the router calls would pin the
    mechanism instead of the law, so this asserts the faces that reach the
    contract and the verdicts that come back.
    """
    from sugar_lift_py_tests.outcome.exit_set import ExitSet

    original = ExitSet.and_exit
    incoming_kinds = []

    def observe(incoming, exit_es, *, disposition):
        incoming_kinds.append(type(incoming.exits[0]))
        return original(incoming, exit_es, disposition=disposition)

    monkeypatch.setattr(ExitSet, "and_exit", observe)

    completed = _resource(body=(_Pass(),)).desugar()
    halted = _resource(body=(_Raise("ValueError"),)).desugar()

    assert incoming_kinds == [Completed, Halted]
    assert completed.value.can_fall_through
    assert any(
        isinstance(entry, Incomplete)
        and getattr(entry.effect, "exception_name", None) == "ValueError"
        for entry in halted.value.contribution()
    )


def test_lying_resource_exit_cannot_skip_the_halted_face(monkeypatch):
    """BITE: a completion-only exit implementation changes the result."""
    from sugar_lift_py_tests.outcome.exit_set import ExitSet

    original = ExitSet.and_exit

    def completion_only(incoming, exit_es, *, disposition):
        if isinstance(incoming.exits[0], Halted):
            return ExitSet.completed("exit-skipped")
        return original(incoming, exit_es, disposition=disposition)

    monkeypatch.setattr(ExitSet, "and_exit", completion_only)
    out = _resource(body=(_Raise("ValueError"),)).desugar()

    with pytest.raises(AssertionError):
        assert any(
            isinstance(entry, Incomplete)
            and getattr(entry.effect, "exception_name", None) == "ValueError"
            for entry in out.value.contribution()
        )


def test_never_suppresses_needs_no_second_cleanup_algebra():
    """LAW: `and_exit` under NeverSuppresses IS `and_finally`, face for face.

    #6401 proposed routing NeverSuppresses through `and_finally` so cleanup ran
    on both edges. It already does: for both spellings of the contract, on a
    completed AND a halted body face, the two produce identical exits. Routing
    one disposition through a different algebra would therefore have changed
    nothing except adding an asker -- a branch on WHAT KIND the disposition is,
    which is the shape the floor exists to delete.

    This twin is why that branch is not in the tree.
    """
    from sugar_lift_py_tests.outcome.exit_set import ExitSet

    exit_es = ExitSet((Completed(true_guard(), _FloorValue("exited")),))
    faces = (
        Completed(true_guard(), _FloorValue("body")),
        Halted(
            true_guard(), RaiseEffect.for_builtin('ValueError', occurrence='implementations/python/sugar-lift-py-tests/tests/test_with_resource_sugar.py:637:0'), _FloorValue("pre")
        ),
    )
    for disposition in (NeverSuppresses(), NeverSuppressesDispositionV1()):
        for face in faces:
            through_exit = ExitSet((face,)).and_exit(exit_es, disposition=disposition)
            through_finally = ExitSet((face,)).and_finally(lambda: exit_es)
            assert (
                through_exit.exits == through_finally.exits
            ), f"{type(disposition).__name__} / {type(face).__name__} diverged"


def test_lying_the_equivalence_is_specific_to_never_suppresses():
    """BITE: `and_finally` is NOT a general substitute for `and_exit`.

    A suppressing contract consumes the halt; shared cleanup restores it. If
    the equivalence above held for every disposition, routing everything
    through `and_finally` would be safe -- it is not, and that is exactly why
    the rejected branch needed a kind test to stay correct.
    """
    from sugar_lift_py_tests.outcome.exit_set import ExitSet

    from sugar_lift_py_tests.floor.ground_exit import _builtin_exception_identity

    exit_es = ExitSet((Completed(true_guard(), _FloorValue("exited")),))
    _, mro = _builtin_exception_identity("ValueError")
    halted = Halted(
        true_guard(),
        RaiseEffect.for_builtin("ValueError",
            
            exception_type_mro=mro,
            occurrence="equiv.py:1:0",
        ),
        _FloorValue("pre"),
    )
    suppressing = ExitSuppressionContract.suppresses(("ValueError",))

    through_exit = ExitSet((halted,)).and_exit(exit_es, disposition=suppressing)
    through_finally = ExitSet((halted,)).and_finally(lambda: exit_es)

    assert through_exit.exits != through_finally.exits


def test_exit_face_binding_completed_is_none_triple():
    face = Completed(true_guard(), BlockValue((), can_fall_through=True))
    binding = ExitFaceBinding.from_body_exit("X", face)
    assert binding.kind == "completed"
    facts = binding.to_facts()
    assert len(facts) == 3
    # All consequents bind to "None"
    for inv in facts:
        assert inv.formula.args[1].value == "None"


def test_exit_face_binding_raised_is_not_none_triple():
    effect = RaiseEffect.for_builtin("ValueError", occurrence="src.py:3:4")
    face = Halted(true_guard(), effect)
    binding = ExitFaceBinding.from_body_exit("X", face)
    assert binding.kind == "raised"
    facts = binding.to_facts()
    vals = [inv.formula.args[1] for inv in facts]
    # type named, value occurrence, tb open — not three Nones
    assert not all(getattr(v, "value", None) == "None" for v in vals)
    assert any(getattr(v, "value", None) == "ValueError" for v in vals)
    assert any(
        getattr(v, "name", None) == "python:raise_effect_occurrence" for v in vals
    )


def test_enter_result_and_manager_binding_facts():
    sugar = _resource(
        body=(_Pass(),),
        enter_slot_id="E",
        enter=_FixedSugar(
            Complete(ObjectValue("native-resource", (), identity="entered-val"))
        ),
        manager=_FixedSugar(
            Complete(ObjectValue("native-resource", (), identity="mgr-val"))
        ),
    )
    out = sugar.desugar()
    invs = [e for e in out.value.contribution() if isinstance(e, InvValue)]
    names = []
    for inv in invs:
        f = inv.formula
        if getattr(f, "kind", None) == "implies":
            f = f.operands[1]
        if getattr(f, "name", None) == "=":
            names.append(getattr(f.args[0], "name", None))
    assert "manager_slot_value" in names
    assert "enter_result_value" in names
    assert "exit_type" in names  # completed face testimony
    enter_fact = next(
        inv
        for inv in invs
        if getattr(inv.formula.args[0], "name", None) == "enter_result_value"
    )
    assert enter_fact.formula.args[1].name == "py.object.identity"
    assert enter_fact.formula.args[1].args[1].value == "entered-val"


def test_parametric_exit_args_are_exit_refs():
    exit_sugar = _parametric_exit(face_id="face1", manager_slot="m1")
    assert isinstance(exit_sugar, MethodCallSugar)
    assert exit_sugar.name == "__exit__"
    assert isinstance(exit_sugar.receiver, ManagerRefSugar)
    assert [type(a).__name__ for a in exit_sugar.args] == [
        "ExitTypeRefSugar",
        "ExitValueRefSugar",
        "ExitTracebackRefSugar",
    ]
    assert exit_sugar.args[0].desugar().value.face_id == "face1"
    assert isinstance(exit_sugar.args[0].desugar().value, ExitTypeCoordinate)
    assert isinstance(exit_sugar.args[1].desugar().value, ExitValueCoordinate)
    assert isinstance(exit_sugar.args[2].desugar().value, ExitTracebackCoordinate)


def test_manager_ref_sugar_is_manager_coordinate():
    out = ManagerRefSugar(slot_id="M42").desugar()
    assert isinstance(out.value, ManagerCoordinate)
    assert out.value.slot_id == "M42"


def test_with_resource_desugar_does_not_construct_sugars():
    """Law: desugar must not build sugars or import sugar constructors."""
    src = inspect.getsource(WithResourceSugar.desugar)
    forbidden = (
        "MethodCallSugar",
        "RaiseWitnessSugar",
        "OpenExitArgSugar",
        "NoneLiteralSugar",
        "ManagerRefSugar",
        "ExitTypeRefSugar",
        "ExitValueRefSugar",
        "ExitTracebackRefSugar",
        "_exit_sugar_for_face",
        "sugar.method_call",
        "sugar.resource_coord",
        "sugar.none_literal",
    )
    for token in forbidden:
        assert token not in src, f"desugar must not reference {token!r}"
    assert not hasattr(WithResourceSugar, "_exit_sugar_for_face")
