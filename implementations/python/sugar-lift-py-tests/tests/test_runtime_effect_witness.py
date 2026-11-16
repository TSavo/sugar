from __future__ import annotations

import inspect
import tempfile

import pytest

import sugar_lift_py_tests.effect as effects
from sugar_lift_py_tests.effect import (
    RuntimeEffect,
    RuntimeEffectWitness,
    AppendRuntimeEffect,
    genuine_runtime_operand,
    is_lift_time_decidable,
    runtime_effect_evidence,
)
from sugar_lift_py_tests.gap.panic import ConstructionPanic
from sugar_lift_py_tests.ir import ctor, make_var, str_const
from sugar_lift_python_source.source_oracle import path_source
from sugar_source_tree.tree import SourceFile


def _site(src: str = "x = 1\n"):
    """One SourceFragment via SourceOracle + enumeration."""
    with tempfile.NamedTemporaryFile("w", suffix=".py", delete=False, dir="/tmp") as f:
        f.write(f"def _w():\n    {src}")
        path = f.name
    fn = next(SourceFile(path_source(path)).functions())
    return fn.fragment


def test_runtime_effect_requires_operation_operand_and_site_witness() -> None:
    site = _site("x[i] = 1\n")
    witness = RuntimeEffectWitness(
        operation=ctor("py.setitem", [make_var("runtime_index")]),
        runtime_operand=genuine_runtime_operand(
            "py.setitem", make_var("runtime_index")
        ),
        site=site,
    )
    assert witness.locus == f"{site.filename}:{site.line}:{site.col}"

    effect = AppendRuntimeEffect(
        "runtime store",
        runtime_operand=witness.runtime_operand,
        witness=witness,
    )
    assert effect.witness == witness


def test_no_runtime_effect_subclass_is_instantiable_without_a_witness() -> None:
    subclasses = {
        value
        for _name, value in inspect.getmembers(effects, inspect.isclass)
        if issubclass(value, RuntimeEffect) and value is not RuntimeEffect
    }
    assert subclasses
    for effect_type in subclasses:
        with pytest.raises(TypeError, match="runtime_operand.*witness"):
            effect_type("unwitnessed runtime claim")  # type: ignore[call-arg]


def test_statically_known_global_scope_cannot_mint_a_runtime_witness() -> None:
    assert not hasattr(effects, "GlobalScopeRuntimeEffect")


def test_tree_fragment_answers_locus_via_oracle_filename() -> None:
    site = _site("x = 1\n")
    witness = RuntimeEffectWitness(
        operation=ctor("py.runtime", [make_var("operand")]),
        runtime_operand=genuine_runtime_operand("py.runtime", make_var("operand")),
        site=site,
    )
    assert witness.locus == f"{site.filename}:{site.line}:{site.col}"
    assert site.filename  # oracle-backed path


def test_string_locus_cannot_mint_a_runtime_effect_witness() -> None:
    from sugar_lift_py_tests.effect import runtime_effect_witness

    with pytest.raises(TypeError, match="filename/"):
        runtime_effect_witness(
            "py.divide",
            genuine_runtime_operand("py.divide", make_var("x")),
            "t.py:1:0",
        )


def test_arbitrary_object_operand_cannot_fabricate_a_witness_term() -> None:
    site = _site("x = 1\n")
    with pytest.raises(ConstructionPanic, match="cannot mint a RuntimeEffect"):
        runtime_effect_evidence("py.runtime", object(), site)


def test_operation_carrying_fragment_blame_resolves_as_site() -> None:
    from sugar_lift_py_tests.effect import runtime_effect_witness

    site = _site("x.y\n")

    class _Op:
        blame = site
        name = "y"

    witness = runtime_effect_witness(
        "py.getattr",
        genuine_runtime_operand("py.getattr", make_var("y")),
        _Op(),
    )
    assert witness.site is site
    assert witness.locus == f"{site.filename}:{site.line}:{site.col}"


def test_import_exception_predicate_is_a_genuine_runtime_operand() -> None:
    condition = ctor("py.except", [str_const("ImportError")])
    operand = genuine_runtime_operand("py.ifexp.select", condition)
    assert operand.term == condition


def test_ground_boolean_constructor_still_cannot_mint_runtime_authority() -> None:
    site = _site("x = True\n")
    with pytest.raises(ConstructionPanic, match="ground/decidable"):
        runtime_effect_evidence(
            "py.ifexp.select",
            ctor("py.not", [ctor("py.and", [])]),
            site,
        )


def test_deep_runtime_operand_decision_is_construction_closed() -> None:
    ground = str_const("ground")
    runtime = ctor("call:opaque", [])
    for _ in range(2_000):
        ground = ctor("wrapper", [ground])
        runtime = ctor("wrapper", [runtime])
    assert is_lift_time_decidable(ground)
    assert not is_lift_time_decidable(runtime)


def test_a_store_on_a_receiver_after_an_undecided_call_is_runtime_dependent() -> None:
    """``python:receiver_after_call(<occurrence>, <label>)`` -- the receiver
    after an undecided call or store (#7757 step 7's undecided after-call
    value) -- carries only ground strings, but they name the operation, not
    the value: the store over it is runtime-dependent, never refused as
    ground (``live_loop_evaluation.py:4:8``)."""
    after = ctor(
        "python:receiver_after_call",
        [str_const("blake3-512:occurrence@loop#1"), str_const(".n")],
    )
    store = ctor("python:attribute_store", [after, str_const("n"), str_const("2")])
    assert not is_lift_time_decidable(after)
    assert not is_lift_time_decidable(store)
    assert genuine_runtime_operand("RuntimeEffect", store).term == store
    with pytest.raises(TypeError, match="ground/decidable"):
        genuine_runtime_operand(
            "RuntimeEffect",
            ctor("python:attribute_store", [str_const("o"), str_const("n")]),
        )


def test_dynamic_type_operand_effect_names_its_operation() -> None:
    """A constructor partition can identity-hash a dynamic isinstance halt."""
    from sugar_lift_py_tests.effect import (
        DynamicTypeOperandRuntimeEffect,
        runtime_effect_evidence_from_terms,
    )
    from sugar_lift_py_tests.floor.receiver_state_partition_value import (
        ReceiverStatePartitionValue,
    )
    from sugar_lift_py_tests.outcome import ExitSet, Halted
    from sugar_lift_py_tests.outcome.exit_set import true_guard

    site = _site("isinstance(x, T)\n")
    operation = ctor("adt.is_python_type", (make_var("x"), make_var("T")))
    effect = DynamicTypeOperandRuntimeEffect(
        "dynamic isinstance type operand",
        **runtime_effect_evidence_from_terms(operation, make_var("T"), site),
    )
    term = effect.to_term(owner="DynamicTypeOperandRuntimeEffect.to_term")
    assert term.name == "python:dynamic-type-operand"
    assert term.args == (operation,)

    partition = ReceiverStatePartitionValue(
        exits=ExitSet((Halted(true_guard(), effect, None, frozenset()),))
    )
    identity = partition.identity
    assert isinstance(identity, str) and identity
