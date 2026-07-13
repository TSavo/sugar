from __future__ import annotations

from dataclasses import FrozenInstanceError

import pytest

from sugar_lift_py_tests.canonicalizer import encode_jcs
from sugar_lift_py_tests.floor import GuardedValue, SymbolicValue, TermValue
from sugar_lift_py_tests.ir import (
    _ConstInt,
    _Ctor,
    _Var,
    Int,
    Term,
    atomic,
    term_to_value,
)
from sugar_lift_py_tests.kit_rpc import LiftReportPayloadDto
from sugar_lift_py_tests.lift_rpc import lift_file_payload


def _distributed_terms() -> tuple[Term, ...]:
    inner = GuardedValue(
        atomic("inner", []),
        SymbolicValue(_Var("value")),
        SymbolicValue(_Var("value")),
    )
    nested = GuardedValue(atomic("outer", []), inner, inner)
    outcome = nested.add(TermValue(2), "nested-guards.py:1")

    outer = outcome.value
    assert isinstance(outer, GuardedValue)
    terms: list[Term] = []
    for face in (outer.when_true, outer.when_false):
        assert isinstance(face, GuardedValue)
        for leaf in (face.when_true, face.when_false):
            assert isinstance(leaf, SymbolicValue)
            terms.append(leaf.term)
    return tuple(terms)


def _lift_terms(monkeypatch) -> tuple[Term, ...]:
    captured: list[tuple[Term, ...]] = []

    def audit_lift_file(source, filename, *, hold_panic):
        del source, filename, hold_panic
        captured.append(_distributed_terms())
        return LiftReportPayloadDto(source_ledger={}), []

    monkeypatch.setattr("sugar_lift_py_tests.lift_rpc.audit_lift_file", audit_lift_file)
    lift_file_payload("def f(): pass\n", "nested-guards.py")
    return captured[0]


def test_nested_guard_distribution_shares_equal_term_nodes_per_lift(
    monkeypatch,
) -> None:
    terms = _lift_terms(monkeypatch)
    offenders = [term for term in terms[1:] if term is not terms[0]]

    assert not offenders, (
        f"R={len(offenders)} equal nested-guard terms have distinct identities; "
        "replace per-face copies with request-scoped term hash-consing"
    )

    unshared = _Ctor(
        "+",
        (
            _Var("value"),
            _ConstInt(2, Int()),
        ),
    )
    assert encode_jcs(term_to_value(terms[0])) == encode_jcs(term_to_value(unshared))


def test_term_identity_does_not_cross_lift_requests(monkeypatch) -> None:
    first = _lift_terms(monkeypatch)[0]
    second = _lift_terms(monkeypatch)[0]

    assert first == second
    assert first is not second


def test_interned_terms_are_immutable(monkeypatch) -> None:
    term = _lift_terms(monkeypatch)[0]

    with pytest.raises(FrozenInstanceError):
        term.name = "mutated"  # type: ignore[misc]


def test_lift_construction_does_not_expand_the_term_dag_to_wire(monkeypatch) -> None:
    def premature_wire_expansion(formula):
        del formula
        raise AssertionError(
            "lift construction expanded the term DAG before wire serialization"
        )

    monkeypatch.setattr(
        "sugar_lift_py_tests.proofir.scope.formula_to_rpc",
        premature_wire_expansion,
    )

    payload = lift_file_payload("def f(value):\n    return value + 1\n", "term-dag.py")

    assert payload.ir
