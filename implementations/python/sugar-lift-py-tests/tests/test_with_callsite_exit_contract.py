from __future__ import annotations

from dataclasses import dataclass, replace
from pathlib import Path

from factory_reduce import compose_block
import pytest

from sugar_lift_py_tests.claim import SugarRole
from sugar_lift_py_tests.context import FactoryBuildContext
from sugar_lift_py_tests.effect import GetattrRuntimeEffect, runtime_effect_evidence
from sugar_lift_py_tests.factory import FactoryPanic, SourceFragment
from sugar_lift_py_tests.factory.build import default_catalog
from sugar_lift_py_tests.floor import (
    BlockValue,
    BuiltinExceptionClassValue,
    CallSiteValue,
    FloorValue,
    GuardedValue,
    InvValue,
    ObjectMethodValue,
    ObjectValue,
    RaiseValue,
    RaisesWithValue,
    ReturnValue,
    SymbolicValue,
    TermValue,
)
from sugar_lift_py_tests.floor.call_site_value import ExitSuppressionContract
from sugar_lift_py_tests.ir import atomic, ctor, make_var, py_raises
from sugar_lift_py_tests.lift_rpc import lift_file_payload
from sugar_lift_py_tests.outcome import Complete, Incomplete
from sugar_lift_py_tests.sugar_body import SugarBody
from sugar_lift_py_tests.sugar.method_call_sugar import (
    _static_exit_suppression_contract,
)
from sugar_lift_py_tests.sugar.with_sugar import WithSugar, _entry_carries_raise
from sugar_lift_py_tests.sugar.witnesses import SugarWitnessPair
from sugar_lift_py_tests.witness_harness import run_source_through_real_solver


@dataclass(frozen=True)
class _StaticValueSugar:
    value: FloorValue
    events: list[str] | None = None
    label: str = ""

    def desugar(self, ctx=None):
        del ctx
        if self.events is not None:
            self.events.append(self.label)
        return Complete(self.value)


@dataclass(frozen=True)
class _EffectSugar:
    effect: object

    def desugar(self, ctx=None):
        del ctx
        return Incomplete(self.effect)


@dataclass(frozen=True)
class _PanicIfReducedSugar:
    def desugar(self, ctx=None):
        del ctx
        from sugar_lift_py_tests.factory import factory_panic_gap

        factory_panic_gap(
            owner="SequentialDigBody",
            blame="manager.py:1",
            observed="opaque producer body",
            requested="manager result",
            fix="use the exact exit contract when no entered value is demanded",
        )


def _expr_body(expr: str) -> SugarBody:
    ctx = FactoryBuildContext(filename="manager.py", catalog=default_catalog())
    suite = SourceFragment.from_source(expr, "manager.py").statements()[0]
    return ctx.build_body(suite.statements()[0].expr_value(), SugarRole.TERM)


def _manager_callsite(
    *,
    exit_expr: str | None,
    enter_expr: str = "1",
    exit_value: FloorValue | None = None,
    class_name: str = "Manager",
    events: list[str] | None = None,
    exit_contract: ExitSuppressionContract | None = None,
) -> CallSiteValue:
    enter_body = _expr_body(enter_expr)
    if events is not None:
        enter_body = SugarBody(
            _StaticValueSugar(TermValue(1), events, f"enter:{class_name}"),
            SugarRole.TERM,
        )
    methods = [
        ObjectMethodValue(
            name="__enter__",
            parameters=("self",),
            body=enter_body,
        )
    ]
    if exit_expr is not None or exit_value is not None:
        exit_body = (
            _expr_body(exit_expr)
            if exit_value is None
            else SugarBody(_StaticValueSugar(exit_value), SugarRole.TERM)
        )
        if events is not None:
            exit_value = exit_body.reduce(None).value
            exit_body = SugarBody(
                _StaticValueSugar(exit_value, events, f"exit:{class_name}"),
                SugarRole.TERM,
            )
        methods.append(
            ObjectMethodValue(
                name="__exit__",
                parameters=("self", "exc_type", "exc", "tb"),
                body=exit_body,
            )
        )
    result = ObjectValue(
        class_name=class_name,
        fields=(),
        methods=tuple(methods),
        identity=f"{class_name}-result",
    )
    return CallSiteValue(
        target_name="manager",
        arg_values=(),
        parameters=(),
        term=ctor("call:manager", []),
        body=SugarBody(
            _StaticValueSugar(result, events, f"manager:{class_name}"), SugarRole.TERM
        ),
        exit_suppression=exit_contract,
    )


def _opaque_manager_callsite(
    exit_contract: ExitSuppressionContract | None,
) -> CallSiteValue:
    return CallSiteValue(
        target_name="managed",
        arg_values=(),
        parameters=(),
        term=ctor("call:managed", []),
        body=None,
        exit_suppression=exit_contract,
    )


def test_guarded_callsite_managers_join_entered_values_before_body() -> None:
    guard = atomic("manager-choice", [])
    block = compose_block(
        "    with manager as entered:\n" "        return entered\n",
        binds={
            "manager": GuardedValue(
                guard,
                _manager_callsite(exit_expr="False", class_name="Left"),
                _manager_callsite(
                    exit_expr="False", enter_expr="2", class_name="Right"
                ),
            )
        },
    )

    assert block.statements == (
        ReturnValue(GuardedValue(guard, TermValue(1), TermValue(2))),
    )


def test_guarded_manager_with_unconstructed_face_stays_loud() -> None:
    guard = atomic("manager-choice", [])

    with pytest.raises(FactoryPanic) as raised:
        compose_block(
            "    with manager:\n" "        return 1\n",
            binds={
                "manager": GuardedValue(
                    guard,
                    _manager_callsite(exit_expr="False"),
                    TermValue(0),
                )
            },
        )

    assert raised.value.info.owner == "WithSugar"
    assert raised.value.info.observed == "TermValue"
    assert raised.value.info.requested == "context manager data-model methods"


def test_guarded_manager_witness_truthful_sat_lying_unsat(tmp_path: Path) -> None:
    witnesses = WithSugar.witnesses()
    pair = next(
        witness
        for witness in witnesses
        if isinstance(witness, SugarWitnessPair)
        and witness.name == "with_guarded_manager_enter"
    )

    truthful = run_source_through_real_solver(
        tmp_path / "truthful", pair.truthful.source
    )
    lying = run_source_through_real_solver(tmp_path / "lying", pair.lying.source)

    assert truthful.verdict == pair.truthful.expected == "sat"
    assert lying.verdict == pair.lying.expected == "unsat"


def test_nonraising_opaque_manager_witness_truthful_sat_lying_unsat(
    tmp_path: Path,
) -> None:
    pair = next(
        witness
        for witness in WithSugar.witnesses()
        if isinstance(witness, SugarWitnessPair)
        and witness.name == "with_nonraising_opaque_manager"
    )

    truthful = run_source_through_real_solver(
        tmp_path / "truthful", pair.truthful.source
    )
    lying = run_source_through_real_solver(tmp_path / "lying", pair.lying.source)

    assert truthful.verdict == pair.truthful.expected == "sat"
    assert lying.verdict == pair.lying.expected == "unsat"


def test_truthy_exact_exit_suppresses_raise_from_attached_manager_body() -> None:
    block = compose_block(
        "    with manager as entered:\n"
        "        raise ValueError('boom')\n"
        "    return entered\n",
        binds={"manager": _manager_callsite(exit_expr="1")},
    )

    assert isinstance(block, BlockValue)
    assert block.statements == (ReturnValue(TermValue(1)),)


def test_false_exact_exit_preserves_original_raise_outcome() -> None:
    block = compose_block(
        "    with manager:\n" "        raise ValueError('boom')\n",
        binds={"manager": _manager_callsite(exit_expr="False")},
    )

    assert isinstance(block, BlockValue)
    assert len(block.statements) == 1
    assert isinstance(block.statements[0], RaiseValue)
    assert block.statements[0].effect.exception_name == "ValueError"


def test_symbolic_exit_truth_does_not_forge_suppression() -> None:
    block = compose_block(
        "    with manager:\n" "        raise ValueError('boom')\n",
        binds={
            "manager": _manager_callsite(
                exit_expr=None,
                exit_value=SymbolicValue(ctor("exit-result", [])),
            )
        },
    )

    assert isinstance(block, BlockValue)
    assert len(block.statements) == 1
    assert isinstance(block.statements[0], RaiseValue)
    assert block.statements[0].effect.exception_name == "ValueError"


def test_missing_exact_exit_keeps_named_floor_loud() -> None:
    with pytest.raises(FactoryPanic) as raised:
        compose_block(
            "    with manager:\n" "        raise ValueError('boom')\n",
            binds={"manager": _manager_callsite(exit_expr=None)},
        )

    assert raised.value.info.owner == "WithSugar"
    assert "__exit__" in raised.value.info.requested


def test_body_none_raise_keeps_named_exit_floor_loud() -> None:
    manager = replace(_manager_callsite(exit_expr="True"), body=None)

    with pytest.raises(FactoryPanic) as raised:
        compose_block(
            "    with manager:\n" "        raise ValueError('boom')\n",
            binds={"manager": manager},
        )

    assert raised.value.info.owner == "WithSugar"
    assert "__exit__" in raised.value.info.requested


def test_exact_exit_contract_avoids_unneeded_manager_result_dig() -> None:
    manager = CallSiteValue(
        target_name="managed",
        arg_values=(),
        parameters=(),
        term=ctor("call:managed", []),
        body=SugarBody(_PanicIfReducedSugar(), SugarRole.TERM),
        exit_suppression=ExitSuppressionContract.never_suppresses(),
    )

    block = compose_block(
        "    with manager:\n" "        raise ValueError('boom')\n",
        binds={"manager": manager},
    )

    assert isinstance(block.statements[0], RaiseValue)
    assert block.statements[0].effect.exception_name == "ValueError"


def test_missing_exit_contract_still_demands_manager_result() -> None:
    manager = CallSiteValue(
        target_name="managed",
        arg_values=(),
        parameters=(),
        term=ctor("call:managed", []),
        body=SugarBody(_PanicIfReducedSugar(), SugarRole.TERM),
        exit_suppression=None,
    )

    with pytest.raises(FactoryPanic) as raised:
        compose_block(
            "    with manager:\n" "        raise ValueError('boom')\n",
            binds={"manager": manager},
        )

    assert raised.value.info.owner == "SequentialDigBody"


def test_source_contextmanager_contract_witness_truthful_and_lying(
    tmp_path: Path,
) -> None:
    pair = next(
        witness
        for witness in WithSugar.witnesses()
        if isinstance(witness, SugarWitnessPair)
        and witness.name == "with_source_contextmanager_contract"
    )

    truthful = run_source_through_real_solver(
        tmp_path / "truthful", pair.truthful.source
    )
    lying = run_source_through_real_solver(tmp_path / "lying", pair.lying.source)

    assert truthful.verdict == "sat"
    assert lying.verdict == "unsat"


def test_proven_named_exit_contract_suppresses_matching_raise() -> None:
    block = compose_block(
        "    with manager:\n" "        raise ValueError('boom')\n" "    return 7\n",
        binds={
            "manager": _opaque_manager_callsite(
                ExitSuppressionContract.suppresses(("ValueError",))
            )
        },
    )

    assert block.statements == (ReturnValue(TermValue(7)),)


def test_proven_non_suppressing_exit_contract_preserves_raise() -> None:
    block = compose_block(
        "    with manager:\n" "        raise ValueError('boom')\n",
        binds={
            "manager": _opaque_manager_callsite(
                ExitSuppressionContract.never_suppresses()
            )
        },
    )

    assert isinstance(block.statements[0], RaiseValue)
    assert block.statements[0].effect.exception_name == "ValueError"


def test_unproven_exit_contract_keeps_named_floor_loud() -> None:
    with pytest.raises(FactoryPanic) as raised:
        compose_block(
            "    with manager:\n" "        raise ValueError('boom')\n",
            binds={"manager": _opaque_manager_callsite(None)},
        )

    assert raised.value.info.owner == "WithSugar"
    assert "__exit__" in raised.value.info.requested


def test_nested_pytest_raises_does_not_escape_to_outer_manager() -> None:
    block = compose_block(
        "    with manager:\n"
        "        with pytest.raises(ValueError):\n"
        "            raise ValueError('boom')\n"
        "    return 1\n",
        binds={"manager": _opaque_manager_callsite(None)},
    )

    assert block.statements[-1] == ReturnValue(TermValue(1))


def test_raises_with_value_is_a_consumed_raise_not_a_propagating_raise() -> None:
    entry = RaisesWithValue(
        raises_inv=InvValue(py_raises(ctor("python:type", [])), "inner.py:1"),
        body_entries=(),
        as_name=None,
        as_value=None,
    )

    assert _entry_carries_raise(entry) is False


def test_contextlib_suppress_constructs_named_static_contract() -> None:
    contract = _static_exit_suppression_contract(
        "contextlib.suppress",
        (
            BuiltinExceptionClassValue(
                name="ValueError", bases=(), record=BlockValue(())
            ),
        ),
    )

    assert contract is not None
    assert contract.exception_names == frozenset({"ValueError"})


@pytest.mark.parametrize(
    "coordinate",
    (
        "open",
        "builtins.open",
        "contextlib.closing",
        "numpy.errstate",
        "numpy.nditer",
        "pandas.HDFStore",
        "pandas._testing.assert_produces_warning",
        "pandas._testing.raises_chained_assignment_error",
        "pandas.option_context",
        "pytest.warns",
    ),
)
def test_exact_non_suppressing_manager_coordinates_construct_contract(
    coordinate: str,
) -> None:
    contract = _static_exit_suppression_contract(coordinate, ())

    assert contract == ExitSuppressionContract.never_suppresses()


@pytest.mark.parametrize(
    "coordinate",
    (
        "project.closing",
        "project.HDFStore",
        "project.assert_produces_warning",
        "project.open",
        "project.option_context",
        "project.raises_chained_assignment_error",
        "project.errstate",
        "project.nditer",
        "project.warns",
        "numpy.unknown",
    ),
)
def test_similar_non_manager_coordinates_do_not_gain_exit_contract(
    coordinate: str,
) -> None:
    assert _static_exit_suppression_contract(coordinate, ()) is None


def test_exact_builtin_open_proves_exception_propagation() -> None:
    block = compose_block(
        "    with open(path, 'rb'):\n" "        raise ValueError('boom')\n",
        binds={"path": SymbolicValue(ctor("path", []))},
    )

    assert isinstance(block.statements[0], RaiseValue)
    assert block.statements[0].effect.exception_name == "ValueError"


def test_shadowed_open_keeps_unknown_exit_loud() -> None:
    with pytest.raises(FactoryPanic) as raised:
        compose_block(
            "    with open(path, 'rb'):\n" "        raise ValueError('boom')\n",
            binds={
                "path": SymbolicValue(ctor("path", [])),
                "open": SymbolicValue(ctor("shadowed-open", [])),
            },
        )

    assert raised.value.info.owner == "WithSugar"
    assert "__exit__" in raised.value.info.requested


def test_symbolic_receiver_manager_exit_is_a_runtime_operand() -> None:
    receiver = SymbolicValue(make_var("pytest_fixture"))
    manager = CallSiteValue(
        target_name="context",
        arg_values=(receiver,),
        parameters=(),
        term=ctor("call:context", [receiver.to_term(owner="test")]),
        body=None,
        runtime_dispatch_receiver=receiver,
    )

    outcome = compose_block(
        "    with manager:\n" "        raise ValueError('boom')\n",
        binds={"manager": manager},
    )

    assert isinstance(outcome.statements[0], Incomplete)
    assert (
        type(outcome.statements[0].effect).__name__ == "ContextManagerExitRuntimeEffect"
    )
    assert outcome.statements[0].effect.witness.operand == receiver.to_term(
        owner="test"
    )


def test_source_backed_manager_propagates_its_genuine_runtime_effect() -> None:
    site = SourceFragment.from_source("manager()", "manager.py")
    receiver = SymbolicValue(make_var("runtime_manager_input"))
    effect = GetattrRuntimeEffect(
        "manager result depends on a genuine runtime operand",
        **runtime_effect_evidence("py.manager.result", receiver, site),
    )
    manager = CallSiteValue(
        target_name="manager",
        arg_values=(),
        parameters=(),
        term=ctor("call:manager", []),
        body=SugarBody(_EffectSugar(effect), SugarRole.TERM),
    )

    outcome = compose_block(
        "    with manager:\n" "        raise ValueError('boom')\n",
        binds={"manager": manager},
    )

    assert isinstance(outcome.statements[0], Incomplete)
    assert outcome.statements[0].effect is effect
    assert outcome.statements[0].effect.witness.operand == make_var(
        "runtime_manager_input"
    )


def test_testimony_report_accounts_for_runtime_manager_exit() -> None:
    payload = lift_file_payload(
        "def test_manager_exit(manager):\n"
        "    with manager.context():\n"
        "        raise ValueError('boom')\n",
        "test_manager_exit.py",
    )

    assert len(payload.effects) == 1
    assert type(payload.effects[0].effect).__name__ == (
        "ContextManagerExitRuntimeEffect"
    )
    assert (
        "runtime-selected context manager exit" in payload.effects[0].to_rpc()["reason"]
    )


def test_contextlib_suppress_does_not_hide_unlisted_exception() -> None:
    block = compose_block(
        "    with manager:\n" "        raise ValueError('boom')\n",
        binds={
            "manager": _opaque_manager_callsite(
                ExitSuppressionContract.suppresses(("TypeError",))
            )
        },
    )

    assert isinstance(block.statements[-1], RaiseValue)
    assert block.statements[-1].effect.exception_name == "ValueError"


def test_same_leaf_unrelated_exit_cannot_substitute_for_manager_method() -> None:
    unrelated = _manager_callsite(exit_expr="True", class_name="Unrelated")

    with pytest.raises(FactoryPanic) as raised:
        compose_block(
            "    with manager:\n" "        raise ValueError('boom')\n",
            binds={
                "manager": _manager_callsite(exit_expr=None),
                "__exit__": unrelated,
            },
        )

    assert raised.value.info.owner == "WithSugar"
    assert "__exit__" in raised.value.info.requested


def test_attached_manager_non_raising_body_still_rewrites_enter_value() -> None:
    block = compose_block(
        "    with manager as entered:\n" "        return entered\n",
        binds={"manager": _manager_callsite(exit_expr="False")},
    )

    assert block.statements == (ReturnValue(TermValue(1)),)


def test_multi_item_raise_demands_exact_exits_right_to_left() -> None:
    events: list[str] = []
    block = compose_block(
        "    with left, right:\n" "        raise ValueError('boom')\n",
        binds={
            "left": _manager_callsite(
                exit_expr="False", class_name="Left", events=events
            ),
            "right": _manager_callsite(
                exit_expr="False", class_name="Right", events=events
            ),
        },
    )

    assert isinstance(block.statements[0], RaiseValue)
    assert events == [
        "manager:Left",
        "enter:Left",
        "manager:Right",
        "enter:Right",
        "exit:Right",
        "exit:Left",
    ]


def _install_module(tmp_path, monkeypatch, name: str, source: str) -> str:
    import importlib

    (tmp_path / f"{name}.py").write_text(source, encoding="utf-8")
    monkeypatch.syspath_prepend(str(tmp_path))
    importlib.invalidate_caches()
    return name


def test_source_class_exit_contract_proves_non_suppression_from_exit_body(
    tmp_path, monkeypatch
) -> None:
    """Digged class ``__exit__`` (not the #4702 static coordinate table).

    Live shape from #4979: raise-carrying with-body over an install-source
    manager whose exact ``__exit__`` cannot return truthy (implicit None).
    """
    from sugar_lift_py_tests.sugar.install_source_dig import (
        resolve_class_exit_contract,
        resolve_source_exit_contract,
    )

    module = _install_module(
        tmp_path,
        monkeypatch,
        "exit_never_manager",
        "class Managed:\n"
        "    def __enter__(self):\n"
        "        return self\n"
        "    def __exit__(self, exc_type, exc, tb):\n"
        "        self.close()\n"
        "    def close(self):\n"
        "        pass\n",
    )
    target = f"{module}.Managed"

    contract = resolve_class_exit_contract(target)
    assert contract is not None
    assert contract.exception_names == frozenset()
    assert resolve_source_exit_contract(target) == contract

    payload = lift_file_payload(
        f"from {module} import Managed\n"
        "def test_raise_through_manager():\n"
        "    with Managed():\n"
        "        raise ValueError('boom')\n",
        "test_source_class_exit.py",
    )
    assert not payload.effects


def test_source_class_truthy_exit_stays_loud_without_static_hatch(
    tmp_path, monkeypatch
) -> None:
    """``return True`` is not a never-suppresses proof; keep the named gap."""
    from sugar_lift_py_tests.sugar.install_source_dig import resolve_class_exit_contract

    module = _install_module(
        tmp_path,
        monkeypatch,
        "exit_true_manager",
        "class Managed:\n"
        "    def __enter__(self):\n"
        "        return self\n"
        "    def __exit__(self, exc_type, exc, tb):\n"
        "        return True\n",
    )

    assert resolve_class_exit_contract(f"{module}.Managed") is None

    with pytest.raises(FactoryPanic) as raised:
        lift_file_payload(
            f"from {module} import Managed\n"
            "def test_raise_suppressed_unknown():\n"
            "    with Managed():\n"
            "        raise ValueError('boom')\n",
            "test_source_class_true_exit.py",
        )

    assert raised.value.info.owner == "WithSugar"
    assert raised.value.info.observed == "raise-carrying callsite with-body"
    assert "dig manager().__exit__" in raised.value.info.requested


def test_source_function_exit_contract_inherits_digged_manager_class(
    tmp_path, monkeypatch
) -> None:
    """Factory function returning a diggable manager class (deprecated_call shape)."""
    from sugar_lift_py_tests.sugar.install_source_dig import (
        resolve_source_exit_contract,
    )

    module = _install_module(
        tmp_path,
        monkeypatch,
        "exit_factory_manager",
        "class Managed:\n"
        "    def __enter__(self):\n"
        "        return self\n"
        "    def __exit__(self, exc_type, exc, tb):\n"
        "        return None\n"
        "\n"
        "def managed() -> Managed:\n"
        "    return Managed()\n",
    )

    assert resolve_source_exit_contract(f"{module}.managed") is not None
    assert resolve_source_exit_contract(f"{module}.managed").exception_names == (
        frozenset()
    )

    payload = lift_file_payload(
        f"from {module} import managed\n"
        "def test_raise_through_factory():\n"
        "    with managed():\n"
        "        raise ValueError('boom')\n",
        "test_source_function_exit.py",
    )
    assert not payload.effects
