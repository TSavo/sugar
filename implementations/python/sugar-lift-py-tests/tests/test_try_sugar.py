"""TrySugar: try/except threads body + guarded handlers with py.except(type).

Owned: Try with one+ single-type except handlers, no else/finally.
Loud: bare except, else, finally. Multi-type except (A, B) is owned.
"""

from __future__ import annotations

import ast
from pathlib import Path

import pytest

from factory_reduce import compose_block

from sugar_lift_py_tests.claim import SugarRole
from sugar_lift_py_tests.context.factory_build_context import FactoryBuildContext
from sugar_lift_py_tests.factory.build import build_node, default_catalog
from sugar_lift_py_tests.factory.factory_gap import FactoryPanic
from sugar_lift_py_tests.factory.source_fragment import SourceFragment
from sugar_lift_py_tests.floor import (
    BlockValue,
    CallSiteValue,
    ReturnValue,
    TermValue,
)
from sugar_lift_py_tests.ir import ctor, str_const
from sugar_lift_py_tests.idd.sugar_witness_instruments import evaluate_seed_witnesses
from sugar_lift_py_tests.lift_rpc import audit_lift_file
from sugar_lift_py_tests.sugar.try_sugar import TrySugar
from sugar_lift_py_tests.sugar.witnesses import SugarRedEffectWitnessPair
from sugar_lift_py_tests.witness_harness import run_source_through_real_solver


def _site(source: str):
    node = ast.parse(source).body[0]
    return SourceFragment.from_node(node, "t.py")


def test_try_body_and_except_thread_with_caught_type() -> None:
    """(1) Try-body return contributes; except as-name is py.except(Type)."""
    block = compose_block(
        "    try:\n"
        "        return 1\n"
        "    except ValueError as e:\n"
        "        return e\n"
    )
    assert isinstance(block, BlockValue)
    # Try body return + handler return both splice into the record.
    assert len(block.statements) == 2
    first = block.statements[0]
    assert isinstance(first, ReturnValue)
    assert first.value == TermValue(1)
    second = block.statements[1]
    from sugar_lift_py_tests.floor.guarded_return import GuardedReturn

    # Except-arm return is GuardedReturn so outer tail after try still reduces.
    assert isinstance(second, GuardedReturn)
    value = second.value
    assert isinstance(value, CallSiteValue)
    assert value.target_name == "except"
    assert value.term == ctor("py.except", [str_const("ValueError")])


def test_handler_type_discriminates_the_except_coordinate() -> None:
    """(2) Different caught type produces a different py.except coordinate."""
    ve = compose_block(
        "    try:\n"
        "        return 1\n"
        "    except ValueError as e:\n"
        "        return e\n"
    )
    te = compose_block(
        "    try:\n"
        "        return 1\n"
        "    except TypeError as e:\n"
        "        return e\n"
    )
    term_ve = ve.statements[1].value.term
    term_te = te.statements[1].value.term
    assert term_ve == ctor("py.except", [str_const("ValueError")])
    assert term_te == ctor("py.except", [str_const("TypeError")])
    assert term_ve != term_te


def test_owns_every_try_parent_shape() -> None:
    assert (
        TrySugar.owns(_site("try:\n    pass\nexcept ValueError:\n    pass\n")) is True
    )
    assert (
        TrySugar.owns(_site("try:\n    pass\nexcept ValueError as e:\n    pass\n"))
        is True
    )
    assert TrySugar.owns(_site("try:\n    pass\nexcept:\n    pass\n")) is True
    assert (
        TrySugar.owns(
            _site("try:\n    pass\nexcept (ValueError, TypeError):\n    pass\n")
        )
        is True
    )
    assert (
        TrySugar.owns(
            _site("try:\n    pass\nexcept ValueError:\n    pass\nelse:\n    pass\n")
        )
        is True
    )
    assert (
        TrySugar.owns(
            _site("try:\n    pass\nexcept ValueError:\n    pass\nfinally:\n    pass\n")
        )
        is True
    )
    assert TrySugar.owns(_site("x = 1\n")) is False

    catalog = default_catalog()
    simple = _site("try:\n    pass\nexcept ValueError:\n    pass\n")
    bare = _site("try:\n    pass\nexcept:\n    pass\n")
    assert any(
        c.name == "TrySugar"
        for c in catalog.candidates_for(SugarRole.STATEMENT, simple)
    )
    assert [c.name for c in catalog.candidates_for(SugarRole.STATEMENT, bare)] == [
        "TrySugar"
    ]


def test_bare_except_uses_cited_catch_all_guard() -> None:
    block = compose_block("    try:\n        return 1\n    except:\n        return 2\n")

    from sugar_lift_py_tests.floor import GuardedReturn
    from sugar_lift_py_tests.ir import atomic

    assert isinstance(block.statements[1], GuardedReturn)
    assert block.statements[1].guards == (atomic("py.except", []),)


def test_try_finally_sequences_final_body_unconditionally() -> None:
    from sugar_lift_py_tests.floor import InvValue, SymbolicValue
    from sugar_lift_py_tests.ir import make_var

    block = compose_block(
        "    try:\n        return 1\n    finally:\n        assert cleanup\n",
        {"cleanup": SymbolicValue(make_var("cleanup"))},
    )

    assert isinstance(block.statements[0], ReturnValue)
    assert isinstance(block.statements[1], InvValue)


def test_multiple_handlers_and_else_are_guarded_coordinates() -> None:
    block = compose_block(
        "    try:\n"
        "        value = 1\n"
        "    except ValueError:\n"
        "        return 2\n"
        "    except TypeError:\n"
        "        return 3\n"
        "    else:\n"
        "        return value\n"
    )

    from sugar_lift_py_tests.floor import GuardedReturn

    assert len(block.statements) == 3
    assert all(isinstance(entry, GuardedReturn) for entry in block.statements)


def test_runtime_selected_handler_type_is_a_named_effect() -> None:
    from sugar_lift_py_tests.effect import TryHandlerDispatchRuntimeEffect
    from sugar_lift_py_tests.outcome import Incomplete

    outcome = compose_block(
        "    try:\n        return 1\n    except choose_error():\n        return 2\n"
    )

    assert isinstance(outcome, BlockValue)
    assert len(outcome.statements) == 1
    assert isinstance(outcome.statements[0], Incomplete)
    assert isinstance(outcome.statements[0].effect, TryHandlerDispatchRuntimeEffect)


def test_runtime_selected_handler_effect_has_a_refuting_bad_twin(tmp_path) -> None:
    witness = next(
        row
        for row in TrySugar.witnesses()
        if row.name == "try_runtime_handler_dispatch"
    )

    assert isinstance(witness, SugarRedEffectWitnessPair)
    assert witness.truthful.expected_match is True
    assert witness.lying.expected_match is False
    assert (
        witness.truthful.expectation.effect_class == "TryHandlerDispatchRuntimeEffect"
    )
    assert evaluate_seed_witnesses((witness,), tmp_path).is_zero


def test_try_threads_binding_from_only_reduced_continuing_path() -> None:
    block = compose_block(
        "    try:\n"
        "        result = 5\n"
        "    except ValueError:\n"
        "        return 0\n"
        "    return result\n"
    )

    assert isinstance(block, BlockValue)
    assert isinstance(block.statements[-1], ReturnValue)
    assert block.statements[-1].value == TermValue(5)


def test_try_terminal_pytest_fail_handler_stays_loud_without_kit_contract() -> None:
    """#5603: fail logo deleted — handler is not a constructed exceptional exit."""
    with pytest.raises(FactoryPanic):
        compose_block(
            "    try:\n"
            "        result = 5\n"
            "    except ValueError:\n"
            "        pytest.fail('missing signature')\n"
            "    return result\n"
        )


def test_try_terminal_pytest_skip_handler_stays_loud_without_kit_contract() -> None:
    """#5603: skip logo deleted — handler is not a constructed exceptional exit."""
    with pytest.raises(FactoryPanic):
        compose_block(
            "    try:\n"
            "        result = 5\n"
            "    except ValueError:\n"
            "        pytest.skip('unsupported input')\n"
            "    return result\n"
        )


def test_nonterminal_pytest_method_does_not_grant_body_binding() -> None:
    with pytest.raises(FactoryPanic) as raised:
        compose_block(
            "    try:\n"
            "        result = 5\n"
            "    except ValueError:\n"
            "        pytest.warns(UserWarning)\n"
            "    return result\n"
        )

    # Loud residual: either the unbound pytest name or the body binding past a
    # non-terminal handler — never a silent success path.
    assert raised.value.info.owner in {"TemporalContext", "python.factory"}
    assert raised.value.info.observed in {"result", "pytest", "Call"}


TRY_SUCCESS_SENTINEL = (
    "def A(op, value):\n"
    "    exc = None\n"
    "    try:\n"
    "        result = op(value)\n"
    "    except Exception as err:\n"
    "        exc = err\n"
)


def test_try_success_sentinel_activates_body_only_binding() -> None:
    source = (
        TRY_SUCCESS_SENTINEL
        + "    if exc is None:\n"
        + "        return result\n"
        + "    return 0\n"
    )

    payload, gaps = audit_lift_file(source, "try_success_result.py")

    assert gaps == []
    assert any(row.post is not None for row in payload.ir)


def test_try_exception_sentinel_does_not_activate_body_only_binding() -> None:
    source = (
        TRY_SUCCESS_SENTINEL
        + "    if exc is not None:\n"
        + "        return result\n"
        + "    return 0\n"
    )

    with pytest.raises(FactoryPanic, match="observed=result requested=value"):
        audit_lift_file(source, "try_exception_result.py", hold_panic=False)


def test_try_unrelated_guard_does_not_activate_body_only_binding() -> None:
    source = (
        TRY_SUCCESS_SENTINEL
        + "    if value:\n"
        + "        return result\n"
        + "    return 0\n"
    )

    with pytest.raises(FactoryPanic, match="observed=result requested=value"):
        audit_lift_file(source, "try_open_guard_result.py", hold_panic=False)


def test_try_success_sentinel_witness_truthful_sat_wrong_twin_unsat(
    tmp_path: Path,
) -> None:
    witnesses = TrySugar.witnesses()
    pair = next(
        witness
        for witness in witnesses
        if witness.name == "try_success_sentinel_result"
    )

    truthful = run_source_through_real_solver(
        tmp_path / "try-success-truthful", pair.truthful.source
    )
    lying = run_source_through_real_solver(
        tmp_path / "try-success-lying", pair.lying.source
    )

    assert truthful.verdict == pair.truthful.expected == "sat"
    assert lying.verdict == pair.lying.expected == "unsat"


def test_try_does_not_bind_name_missing_from_a_continuing_handler_path() -> None:
    with pytest.raises(FactoryPanic) as raised:
        compose_block(
            "    try:\n"
            "        result = 5\n"
            "    except ValueError:\n"
            "        pass\n"
            "    return result\n"
        )

    assert raised.value.info.owner == "TemporalContext"
    assert raised.value.info.observed == "result"
    assert raised.value.info.requested == "value"
