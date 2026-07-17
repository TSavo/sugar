from __future__ import annotations

from dataclasses import dataclass, replace

from factory_reduce import compose_block
import pytest

from sugar_lift_py_tests.claim import SugarRole
from sugar_lift_py_tests.context import FactoryBuildContext
from sugar_lift_py_tests.factory import FactoryPanic, SourceFragment
from sugar_lift_py_tests.factory.build import default_catalog
from sugar_lift_py_tests.floor import (
    BlockValue,
    BuiltinExceptionClassValue,
    CallSiteValue,
    FloorValue,
    ObjectMethodValue,
    ObjectValue,
    RaiseValue,
    ReturnValue,
    SymbolicValue,
    TermValue,
)
from sugar_lift_py_tests.floor.call_site_value import ExitSuppressionContract
from sugar_lift_py_tests.ir import ctor, make_var
from sugar_lift_py_tests.lift_rpc import lift_file_payload
from sugar_lift_py_tests.outcome import Complete, Incomplete
from sugar_lift_py_tests.sugar_body import SugarBody
from sugar_lift_py_tests.sugar.method_call_sugar import (
    _static_exit_suppression_contract,
)


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


def _expr_body(expr: str) -> SugarBody:
    ctx = FactoryBuildContext(filename="manager.py", catalog=default_catalog())
    suite = SourceFragment.from_source(expr, "manager.py").statements()[0]
    return ctx.build_body(suite.statements()[0].expr_value(), SugarRole.TERM)


def _manager_callsite(
    *,
    exit_expr: str | None,
    exit_value: FloorValue | None = None,
    class_name: str = "Manager",
    events: list[str] | None = None,
    exit_contract: ExitSuppressionContract | None = None,
) -> CallSiteValue:
    enter_body = _expr_body("1")
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
