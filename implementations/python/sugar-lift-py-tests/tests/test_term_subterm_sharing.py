from __future__ import annotations

from dataclasses import FrozenInstanceError

import pytest

from sugar_lift_py_tests.canonicalizer import blake3_512_of, encode_jcs
from sugar_lift_py_tests.floor import GuardedValue, SymbolicValue, TermValue
from sugar_lift_py_tests.ir import (
    Formula,
    _Atomic,
    _Connective,
    _ConstInt,
    _ConstStr,
    _Ctor,
    _Var,
    Int,
    String,
    Term,
    TermTableBuilder,
    atomic,
    ctor,
    constructor_symbol_kinds,
    formula_to_value,
    formula_term,
    implies,
    make_var,
    not_,
    str_const,
    term_to_value,
    term_intern_scope,
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

    def audit_lift_file(source, filename, *, hold_panic=False):
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


def _guard_formula_pair() -> tuple[Formula, Formula]:
    """Same adt.is_python_type guard constructed twice — the timedelta residual.

    Issue #4355: terms were hash-consed but formula wrappers around shared
    guards still minted distinct identities, so not(adt.is_python_type(...))
    repeated thousands of times as separate objects.
    """
    guard = atomic(
        "adt.is_python_type",
        [make_var("microseconds"), str_const("float")],
    )
    again = atomic(
        "adt.is_python_type",
        [make_var("microseconds"), str_const("float")],
    )
    return not_(guard), not_(again)


def test_equal_formulas_share_identity_per_lift() -> None:
    with term_intern_scope():
        left, right = _guard_formula_pair()
        implication = implies(left, atomic("=", [make_var("out"), make_var("out")]))
        implication_again = implies(
            right, atomic("=", [make_var("out"), make_var("out")])
        )

    offenders = [
        name
        for name, a, b in (
            ("not-guard", left, right),
            ("implies", implication, implication_again),
        )
        if a is not b
    ]
    assert not offenders, (
        f"R={len(offenders)} equal formulas have distinct identities ({offenders}); "
        "route formula constructors through request-scoped formula hash-consing"
    )

    # Byte-identical to an independently built unshared tree of the same shape.
    unshared = _Connective(
        "not",
        (
            _Atomic(
                "adt.is_python_type",
                (_Var("microseconds"), _ConstStr("float", String())),
            ),
        ),
    )
    assert encode_jcs(formula_to_value(left)) == encode_jcs(formula_to_value(unshared))


def test_formula_identity_does_not_cross_lift_requests() -> None:
    with term_intern_scope():
        first, _ = _guard_formula_pair()
    with term_intern_scope():
        second, _ = _guard_formula_pair()

    assert first == second
    assert first is not second


def test_term_identity_does_not_cross_lift_requests(monkeypatch) -> None:
    first = _lift_terms(monkeypatch)[0]
    second = _lift_terms(monkeypatch)[0]

    assert first == second
    assert first is not second


def test_interned_terms_are_immutable(monkeypatch) -> None:
    term = _lift_terms(monkeypatch)[0]

    with pytest.raises(FrozenInstanceError):
        term.name = "mutated"  # type: ignore[misc]


def test_constructor_symbol_kind_does_not_change_term_identity_or_wire() -> None:
    with term_intern_scope():
        coordinate = ctor("call:vendor_open_name", [], symbol_kind="method-coordinate")
    with term_intern_scope():
        builtin = ctor("call:vendor_open_name", [], symbol_kind="builtin")

    assert coordinate == builtin
    canonical = encode_jcs(term_to_value(coordinate))
    assert canonical == encode_jcs(term_to_value(builtin))
    assert canonical == '{"args":[],"kind":"ctor","name":"call:vendor_open_name"}'
    assert blake3_512_of(canonical.encode()) == blake3_512_of(
        b'{"args":[],"kind":"ctor","name":"call:vendor_open_name"}'
    )


def test_constructor_rejects_unknown_symbol_kind() -> None:
    with pytest.raises(ValueError, match="unknown constructor symbol kind"):
        ctor("call:anything", [], symbol_kind="guessed")


def test_symbol_kind_testimony_is_a_payload_sidecar() -> None:
    payload = LiftReportPayloadDto(
        source_ledger={},
        symbol_kinds={"call:vendor_open_name": "method-coordinate"},
    )

    assert payload.to_rpc()["symbolKinds"] == {
        "call:vendor_open_name": "method-coordinate"
    }


def test_lift_collects_constructor_testimony_once_per_spelling(monkeypatch) -> None:
    def audit_lift_file(source, filename, *, hold_panic=False):
        del source, filename, hold_panic
        ctor("call:vendor_open_name", [], symbol_kind="method-coordinate")
        ctor("call:vendor_open_name", [], symbol_kind="method-coordinate")
        return LiftReportPayloadDto(source_ledger={}), []

    monkeypatch.setattr("sugar_lift_py_tests.lift_rpc.audit_lift_file", audit_lift_file)

    payload = lift_file_payload("def f(): pass\n", "sidecar.py")

    assert payload.symbol_kinds == {"call:vendor_open_name": "method-coordinate"}


def test_contract_testimony_refines_coordinate_for_one_spelling() -> None:
    with term_intern_scope():
        coordinate = ctor("call:resolved_later", [], symbol_kind="method-coordinate")
        contract = ctor("call:resolved_later", [], symbol_kind="contract-target")

        assert coordinate is contract
        assert constructor_symbol_kinds() == {"call:resolved_later": "contract-target"}


def test_builtin_and_method_testimony_meet_at_coordinate() -> None:
    with term_intern_scope():
        builtin = ctor("call:type", [], symbol_kind="builtin")
        method = ctor("call:type", [], symbol_kind="method-coordinate")

        assert builtin is method
        assert constructor_symbol_kinds() == {"call:type": "coordinate"}


def test_builtin_and_contract_testimony_meet_at_coordinate() -> None:
    with term_intern_scope():
        builtin = ctor("call:map", [], symbol_kind="builtin")
        contract = ctor("call:map", [], symbol_kind="contract-target")

        assert builtin is contract
        assert constructor_symbol_kinds() == {"call:map": "coordinate"}


def test_reified_formula_constructor_testifies_as_coordinate() -> None:
    with term_intern_scope():
        formula_term(not_(atomic("guard", [])))

        assert constructor_symbol_kinds() == {
            "formula:guard": "coordinate",
            "formula:not": "coordinate",
        }


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
    wire = payload.to_rpc()
    assert wire["termTable"]
    assert "term-ref" in str(wire["ir"])
    assert '"kind": "ctor"' not in str(wire["ir"])


def test_term_table_emits_one_node_per_cid_and_formula_uses_refs() -> None:
    with term_intern_scope():
        leaf = ctor("call:leaf", [_Var("x")], symbol_kind="method-coordinate")
        rung = ctor("call:rung", [leaf, leaf], symbol_kind="method-coordinate")
        formula = atomic("=", [rung, rung])

        builder = TermTableBuilder()
        wire_formula = builder.formula(formula)

    assert wire_formula["args"][0]["kind"] == "term-ref"
    assert wire_formula["args"][0] == wire_formula["args"][1]
    assert len(builder.nodes) == 3
    assert all(cid.startswith("blake3-512:") for cid in builder.nodes)
    rung_node = builder.nodes[wire_formula["args"][0]["cid"]]
    assert rung_node["args"][0] == rung_node["args"][1]
    assert rung_node["args"][0]["kind"] == "term-ref"

    old_canonical = encode_jcs(term_to_value(rung))
    assert wire_formula["args"][0]["cid"] == blake3_512_of(old_canonical.encode())
