from __future__ import annotations

import copy
from dataclasses import replace
import importlib
from pathlib import Path
import tempfile

import pytest

from sourcefile_construction_door_evidence import SourceFileConstructionDoorEvidence, assert_test_owned_evidence
from sourcefile_construction_door_fixture import _direct_source_file_entry, sourcefile_construction_door_evidence
from sugar_source_tree.backend import Backend
from sugar_source_tree.nodes import SourceUnit
from sugar_source_tree.panic import BackendDefect
from sugar_source_tree.reporter import CollectingReporter, NULL_REPORTER
from sugar_source_tree.spans import LineColSpan


def _file(
    source: str,
    filename: str = "constructed-module.py",
    *,
    backend=None,
    reporter=None,
):
    with tempfile.TemporaryDirectory() as directory:
        path = Path(directory, filename)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(source, encoding="utf-8")
        return _direct_source_file_entry(
            path,
            backend,
            NULL_REPORTER if reporter is None else reporter,
        )


def _constructed(source: str, filename: str = "constructed-module.py"):
    return _file(source, filename).constructed_module


def _authentic_foreign_backend_product(source: str):
    products = []
    for module_name, class_name in (
        ("sugar_source_tree.parso_adapter", "ParsoBackend"),
        ("sugar_source_tree.libcst_adapter", "LibCSTBackend"),
        ("sugar_source_tree.tree_sitter_python_adapter", "TreeSitterPythonBackend"),
    ):
        try:
            module = importlib.import_module(module_name)
        except ModuleNotFoundError:
            continue
        products.append(_file(source, backend=getattr(module, class_name)()).constructed_module)
    return products[0] if products else None


def test_missing_constructed_module_door_is_one_measured_red() -> None:
    assert hasattr(Backend, "materialize_module"), (
        "R_missing_constructed_module_door=1: Backend.materialize_module is the "
        "one final constructor event required before semantic laws can execute"
    )


_DORMANT_SEMANTIC_PROGRAMS = (
    "def outer(child):\n    return child(1)\n",
    "def outer():\n    child = 1\n    return child(1)\n",
    "def outer():\n    def child(value):\n        return value\n    del child\n    return child(1)\n",
    "def outer():\n    def child(value):\n        return value\n    child = 1\n    return child(1)\n",
    "def outer():\n    def child(value):\n        return value\n    def caller():\n        return child(1)\n    return caller()\n",
    "def first():\n    return child(1)\n    def child(value):\n        return value\n",
)


@pytest.fixture
def constructed_module_door():
    if not hasattr(Backend, "materialize_module"):
        pytest.skip("dormant until R_missing_constructed_module_door reaches zero")
    return Backend.materialize_module


@pytest.fixture
def authentic_same_preimage_axis_products(constructed_module_door):
    source = (
        "PROVIDER_VALUE = 3\n\n"
        "def outer():\n"
        "    def child():\n"
        "        return True\n"
        "    assert child()\n"
        "    return True\n"
    )
    first = _file(source).constructed_module
    same_preimage = _file(source).constructed_module
    foreign_source = _file(source + "\n# distinct authenticated source\n").constructed_module
    assert first.constructed_module_identity == same_preimage.constructed_module_identity
    assert first.constructed_module_identity != foreign_source.constructed_module_identity
    return first, {
        "source_cid": foreign_source,
        "constructed_module_identity": foreign_source,
        "root": same_preimage,
        "closed_roll_call": same_preimage,
        "lexical_call_rows": same_preimage,
        "provider_member_rows": same_preimage,
        "leaf_assertion_rows": same_preimage,
        "construction_event_receipt": same_preimage,
    }


@pytest.fixture
def authentic_relation_axis_products(constructed_module_door):
    first = _constructed(
        "def outer():\n    def child():\n        return 1\n    return child()\n"
    ).lexical_call_rows[0]
    foreign = _constructed(
        "def other():\n    def child():\n        return 2\n    return child()\n"
    ).lexical_call_rows[0]
    closure = _constructed(
        "def parent():\n"
        "    def child():\n"
        "        return 1\n"
        "    def caller():\n"
        "        return child()\n"
        "    return caller()\n"
    ).lexical_call_rows[0]
    return first, {
        "source_cid": foreign,
        "definition_occurrence": foreign,
        "lexical_parent": closure,
        "call_occurrence": foreign,
        "lexical_scope": closure,
    }


@pytest.fixture
def authentic_leaf_axis_rows(constructed_module_door):
    source = (
        "def first():\n"
        "    assert left() and right()\n\n"
        "def second():\n"
        "    assert left()\n"
    )
    product = _constructed(source)
    first, second, foreign_frame = product.leaf_assertion_rows
    same_product = _constructed(source)
    same_event_row = same_product.leaf_assertion_rows[0]
    foreign_source = _constructed(
        "def first():\n"
        "    assert left() and changed()\n\n"
        "def second():\n"
        "    assert left()\n"
    ).leaf_assertion_rows[0]
    foreign_backend_product = _authentic_foreign_backend_product(source)
    foreign_backend = (
        None
        if foreign_backend_product is None
        else foreign_backend_product.leaf_assertion_rows[0]
    )
    assert first.constructed_module_identity == same_event_row.constructed_module_identity
    assert first.construction_event_identity is not same_event_row.construction_event_identity
    assert first.assert_occurrence is second.assert_occurrence
    assert first.call_occurrence is not second.call_occurrence
    assert first.assert_occurrence is not foreign_frame.assert_occurrence
    return first, second, {
        "source_cid": foreign_source,
        "constructed_module_identity": foreign_source,
        "backend_fingerprint": foreign_backend,
        "construction_event_identity": same_event_row,
        "function_occurrence": foreign_frame,
        "function_locus": foreign_frame,
        "assert_occurrence": foreign_frame,
        "assert_locus": foreign_frame,
        "call_occurrence": second,
        "call_locus": second,
        "translated_atom_identity": foreign_frame,
        "translated_atom_value": foreign_frame,
        "translated_term_identity": second,
        "translated_term_value": second,
    }


class _SealCountingReporter(CollectingReporter):
    def __init__(self) -> None:
        super().__init__()
        self.events = []

    def register(self, node):
        self.events.append(("register", node))
        return super().register(node)

    def present_fact(self, node):
        self.events.append(("present", node))
        return super().present_fact(node)

    def present_inert(self, node):
        self.events.append(("present", node))
        return super().present_inert(node)

    def present_construction(self, node, value):
        self.events.append(("construction", value))
        return super().present_construction(node, value)

    def report_gap(self, node, panic):
        self.events.append(("gap", panic))
        return super().report_gap(node, panic)


def test_source_file_constructs_and_seals_inside_one_reporter_event(
    constructed_module_door,
) -> None:
    reporter = _SealCountingReporter()
    source_file = _file(
        "PROVIDER_VALUE = 3\n\ndef outer():\n    assert external()\n",
        reporter=reporter,
    )

    assert source_file.root is source_file.constructed_module.root
    assert source_file.closed_roll_call is source_file.constructed_module.closed_roll_call
    assert (
        source_file.provider_member_rows
        is source_file.constructed_module.provider_member_rows
    )
    receipt = source_file.constructed_module.construction_event_receipt
    assert receipt.closed_roll_call is source_file.closed_roll_call
    assert receipt.provider_member_rows is source_file.provider_member_rows
    assert receipt.leaf_assertion_rows is (
        source_file.constructed_module.leaf_assertion_rows
    )
    assert receipt.provider_member_rows
    assert receipt.leaf_assertion_rows
    assert all(
        member.construction_event_identity is receipt.construction_event_identity
        for member in receipt.provider_member_rows
    )
    assert all(
        row.construction_event_identity is receipt.construction_event_identity
        for row in receipt.leaf_assertion_rows
    )
    assert len(receipt.registered_occurrences) == len(reporter.registered) > 0
    assert all(
        testified is observed
        for testified, observed in zip(
            receipt.registered_occurrences, reporter.registered, strict=True
        )
    )
    construction_values = [
        value for kind, value in reporter.events if kind == "construction"
    ]
    assert len(construction_values) == 1
    assert construction_values[0] is receipt


def test_independent_sourcefile_construction_door_evidence_closes_owner_privacy_and_zero_work(
    constructed_module_door,
    sourcefile_construction_door_evidence: SourceFileConstructionDoorEvidence,
) -> None:
    closed = assert_test_owned_evidence(sourcefile_construction_door_evidence)
    assert closed is sourcefile_construction_door_evidence
    assert closed.zero_work.closed_roll_call is (
        closed.zero_work.constructed_product.closed_roll_call
    )
    assert closed.privacy.leaf_assertion_type is type(
        closed.zero_work.constructed_product.leaf_assertion_rows[0]
    )


def test_construction_event_receipt_cross_wire_refuses(
    constructed_module_door,
) -> None:
    first = _constructed("PROVIDER_VALUE = 3\n")
    foreign = _constructed("PROVIDER_VALUE = 4\n")
    assert first.construction_event_receipt is not foreign.construction_event_receipt
    with pytest.raises(BackendDefect, match="sealed construction event receipt"):
        replace(
            first,
            construction_event_receipt=foreign.construction_event_receipt,
        )


def test_construction_event_receipt_constructor_and_copy_are_closed(
    constructed_module_door,
) -> None:
    product = _constructed("PROVIDER_VALUE = 3\n")
    receipt = product.construction_event_receipt
    receipt_type = type(receipt)

    with pytest.raises(TypeError, match="backend construction owner"):
        receipt_type(
            construction_event_identity=receipt.construction_event_identity,
            closed_roll_call=receipt.closed_roll_call,
            provider_member_rows=receipt.provider_member_rows,
            leaf_assertion_rows=receipt.leaf_assertion_rows,
            registered_occurrences=receipt.registered_occurrences,
            source_cid=receipt.source_cid,
            constructed_module_identity=receipt.constructed_module_identity,
            root_identity=receipt.root_identity,
            backend_fingerprint=receipt.backend_fingerprint,
        )
    with pytest.raises(BackendDefect, match="copied sealed construction event"):
        replace(receipt)
    with pytest.raises(BackendDefect, match="copied sealed construction event"):
        replace(
            receipt,
            construction_event_identity=receipt.construction_event_identity,
            closed_roll_call=receipt.closed_roll_call,
            provider_member_rows=receipt.provider_member_rows,
            leaf_assertion_rows=receipt.leaf_assertion_rows,
            registered_occurrences=receipt.registered_occurrences,
            source_cid=receipt.source_cid,
            constructed_module_identity=receipt.constructed_module_identity,
            root_identity=receipt.root_identity,
            backend_fingerprint=receipt.backend_fingerprint,
        )
    assert not any(
        callable(getattr(receipt_type, name, None))
        for name in ("decode", "deserialize", "from_dict", "from_json", "load")
    )


@pytest.mark.parametrize(
    "field_name",
    (
        "construction_event_identity",
        "closed_roll_call",
        "provider_member_rows",
        "leaf_assertion_rows",
        "registered_occurrences",
        "source_cid",
        "constructed_module_identity",
        "root_identity",
        "backend_fingerprint",
    ),
)
def test_construction_event_receipt_cross_wire_refuses_one_axis(
    field_name, constructed_module_door,
) -> None:
    source = (
        "PROVIDER_VALUE = 3\n"
        "def outer():\n"
        "    def child():\n"
        "        return True\n"
        "    assert child()\n"
    )
    first_product = _constructed(source)
    same_product = _constructed(source)
    foreign_source_product = _constructed(source + "# foreign source\n")
    assert (
        first_product.construction_event_receipt.constructed_module_identity
        == same_product.construction_event_receipt.constructed_module_identity
    )
    assert (
        first_product.construction_event_receipt.root_identity
        == same_product.construction_event_receipt.root_identity
    )
    foreign_backend_product = _authentic_foreign_backend_product(source)
    if field_name == "backend_fingerprint" and foreign_backend_product is None:
        pytest.skip("unmeasured: authentic_generic_backend_denominator=0")
    first = first_product.construction_event_receipt
    foreign = (
        foreign_source_product.construction_event_receipt
        if field_name in ("source_cid", "constructed_module_identity", "root_identity")
        else (
            foreign_backend_product.construction_event_receipt
            if field_name == "backend_fingerprint"
            else same_product.construction_event_receipt
        )
    )
    leaves = (
        "construction_event_identity",
        "closed_roll_call",
        "provider_member_rows",
        "leaf_assertion_rows",
        "registered_occurrences",
        "source_cid",
        "constructed_module_identity",
        "root_identity",
        "backend_fingerprint",
    )
    if field_name in (
        "construction_event_identity",
        "closed_roll_call",
        "provider_member_rows",
        "leaf_assertion_rows",
        "registered_occurrences",
    ):
        assert getattr(first, field_name) is not getattr(foreign, field_name)
    else:
        assert getattr(first, field_name) != getattr(foreign, field_name)
    proposed = {
        name: getattr(foreign, name) if name == field_name else getattr(first, name)
        for name in leaves
    }
    assert all(
        proposed[name] is getattr(first, name)
        for name in leaves
        if name != field_name
        and name
        in (
            "construction_event_identity",
            "closed_roll_call",
            "provider_member_rows",
            "leaf_assertion_rows",
            "registered_occurrences",
        )
    )
    assert all(
        proposed[name] == getattr(first, name)
        for name in leaves
        if name != field_name
        and name
        in (
            "source_cid",
            "constructed_module_identity",
            "root_identity",
            "backend_fingerprint",
        )
    )
    with pytest.raises(BackendDefect, match="sealed construction event receipt"):
        replace(first, **{field_name: proposed[field_name]})


def test_filename_is_not_construction_identity_authority(
    constructed_module_door,
) -> None:
    source = "PROVIDER_VALUE = 3\n"
    first = _constructed(source, "first-name.py")
    renamed = _constructed(source, "unrelated-name.py")
    foreign_source = _constructed(source + "# changed authenticated bytes\n", "first-name.py")

    assert first.source_cid == renamed.source_cid
    assert first.backend_fingerprint == renamed.backend_fingerprint
    assert first.constructed_module_identity == renamed.constructed_module_identity
    assert (
        first.construction_event_receipt.root_identity
        == renamed.construction_event_receipt.root_identity
    )
    assert first.source_cid != foreign_source.source_cid
    assert (
        first.constructed_module_identity
        != foreign_source.constructed_module_identity
    )
    assert (
        first.construction_event_receipt.root_identity
        != foreign_source.construction_event_receipt.root_identity
    )


def test_construction_identity_is_bound_to_authenticated_backend_product(
    constructed_module_door,
) -> None:
    source = "PROVIDER_VALUE = 3\n"
    ordinary = _constructed(source)
    foreign_backend = _authentic_foreign_backend_product(source)
    if foreign_backend is None:
        pytest.skip("unmeasured: authentic_generic_backend_denominator=0")

    assert ordinary.source_cid == foreign_backend.source_cid
    assert ordinary.backend_fingerprint != foreign_backend.backend_fingerprint
    assert (
        ordinary.constructed_module_identity
        != foreign_backend.constructed_module_identity
    )
    assert (
        ordinary.construction_event_receipt.root_identity
        != foreign_backend.construction_event_receipt.root_identity
    )


def test_constructed_module_and_relation_constructors_are_closed(
    constructed_module_door,
) -> None:
    authentic = _constructed(
        "def outer():\n"
        "    def child():\n"
        "        return 1\n"
        "    return child()\n"
    )

    with pytest.raises(TypeError, match="backend construction owner"):
        type(authentic)(
            backend_fingerprint=authentic.backend_fingerprint,
            source_cid=authentic.source_cid,
            constructed_module_identity=authentic.constructed_module_identity,
            root=authentic.root,
            closed_roll_call=authentic.closed_roll_call,
            lexical_call_rows=authentic.lexical_call_rows,
            provider_member_rows=authentic.provider_member_rows,
            leaf_assertion_rows=authentic.leaf_assertion_rows,
            construction_event_receipt=authentic.construction_event_receipt,
        )
    with pytest.raises(BackendDefect, match="copied sealed constructed module"):
        replace(authentic)
    assert len(authentic.lexical_call_rows) == 1
    relation = authentic.lexical_call_rows[0]
    relation_type = type(relation)
    with pytest.raises(TypeError, match="backend construction owner"):
        relation_type(
            source_cid=relation.source_cid,
            definition_occurrence=relation.definition_occurrence,
            definition_locus=relation.definition_locus,
            lexical_parent=relation.lexical_parent,
            call_occurrence=relation.call_occurrence,
            call_locus=relation.call_locus,
            lexical_scope=relation.lexical_scope,
        )
    with pytest.raises(BackendDefect, match="copied sealed lexical relation"):
        replace(relation)
    assert not any(
        callable(getattr(relation_type, name, None))
        for name in ("decode", "deserialize", "from_dict", "from_json", "load")
    )


@pytest.mark.parametrize(
    "field_name",
    (
        "source_cid",
        "constructed_module_identity",
        "root",
        "closed_roll_call",
        "lexical_call_rows",
        "provider_member_rows",
        "leaf_assertion_rows",
        "construction_event_receipt",
    ),
)
def test_constructed_module_cross_wires_one_axis_only(
    field_name, authentic_same_preimage_axis_products
) -> None:
    first, twins = authentic_same_preimage_axis_products
    foreign = twins[field_name]
    leaves = (
        "backend_fingerprint",
        "source_cid",
        "constructed_module_identity",
        "root",
        "closed_roll_call",
        "lexical_call_rows",
        "provider_member_rows",
        "leaf_assertion_rows",
        "construction_event_receipt",
    )
    if field_name in ("source_cid", "constructed_module_identity"):
        assert getattr(first, field_name) != getattr(foreign, field_name)
    else:
        assert getattr(first, field_name) is not getattr(foreign, field_name)
    proposed = {
        name: (
            getattr(foreign, name) if name == field_name else getattr(first, name)
        )
        for name in leaves
    }
    assert all(
        proposed[other] is getattr(first, other)
        for other in leaves
        if other != field_name
        and other
        in (
            "root",
            "closed_roll_call",
            "lexical_call_rows",
            "provider_member_rows",
            "leaf_assertion_rows",
            "construction_event_receipt",
        )
    )
    assert all(
        proposed[other] == getattr(first, other)
        for other in leaves
        if other != field_name
        and other
        in ("backend_fingerprint", "source_cid", "constructed_module_identity")
    )
    with pytest.raises(BackendDefect, match="sealed constructed module preimage"):
        replace(first, **{field_name: proposed[field_name]})


def test_adapter_cannot_override_final_materialize_module(constructed_module_door) -> None:
    with pytest.raises(TypeError, match="final Backend.materialize_module"):

        class _LyingBackend(Backend):
            def materialize_module(self, unit, reporter):
                raise AssertionError("adapter-owned lexical policy")


def test_producer_never_ran_is_loud(constructed_module_door) -> None:
    source = "def outer():\n    return 1\n"
    authentic = _constructed(source)
    unit = SourceUnit("never-ran.py", source, authentic.source_cid)

    with pytest.raises(BackendDefect, match="module producer never ran"):
        unit.constructed_module


def test_nested_rows_are_in_producer_order_and_module_calls_are_absent(
    constructed_module_door,
) -> None:
    product = _constructed(
        "def module_child(value):\n"
        "    return value\n\n"
        "module_child(0)\n\n"
        "def outer():\n"
        "    def first(value):\n"
        "        return value\n"
        "    a = first(1)\n"
        "    def second(value):\n"
        "        return value\n"
        "    return second(a)\n"
    )
    first, second = product.lexical_call_rows

    assert first.call_locus == LineColSpan(9, 8, 9, 16)
    assert second.call_locus == LineColSpan(12, 11, 12, 20)
    assert first.source_cid == second.source_cid
    assert first.call_occurrence_identity != second.call_occurrence_identity


def test_parameter_assignment_delete_and_rebind_do_not_authorize_nested_call(
    constructed_module_door,
) -> None:
    for program in _DORMANT_SEMANTIC_PROGRAMS[:4]:
        assert _constructed(program).lexical_call_rows == ()


def test_closure_row_keeps_definition_parent_distinct_from_call_scope(
    constructed_module_door,
) -> None:
    product = _constructed(
        "def outer():\n"
        "    def child(value):\n"
        "        return value\n"
        "    def caller():\n"
        "        return child(1)\n"
        "    return caller()\n"
    )
    closure, local = product.lexical_call_rows

    assert closure.lexical_parent_identity != closure.lexical_scope_identity
    assert local.lexical_parent_identity == local.lexical_scope_identity


def test_later_definition_and_same_name_other_scope_do_not_authorize(
    constructed_module_door,
) -> None:
    product = _constructed(
        "def first():\n"
        "    return child(1)\n"
        "    def child(value):\n"
        "        return value\n\n"
        "def second():\n"
        "    def child(value):\n"
        "        return value\n"
        "    return child(2)\n"
    )
    (second_scope_row,) = product.lexical_call_rows

    assert second_scope_row.call_locus == LineColSpan(9, 11, 9, 19)


@pytest.mark.parametrize(
    ("field_name", "message"),
    (
        ("source_cid", "sealed lexical relation preimage"),
        ("definition_occurrence", "exact definition occurrence"),
        ("lexical_parent", "lexical parent capability"),
        ("call_occurrence", "exact call occurrence"),
        ("lexical_scope", "lexical scope capability"),
    ),
)
def test_forged_relation_one_axis_refuses(
    field_name, message, authentic_relation_axis_products,
) -> None:
    row, twins = authentic_relation_axis_products
    foreign = twins[field_name]
    assert getattr(row, field_name) is not getattr(foreign, field_name)
    with pytest.raises(BackendDefect, match=message):
        replace(row, **{field_name: getattr(foreign, field_name)})
    with pytest.raises(TypeError, match="backend construction owner"):
        type(row)(
            source_cid=row.source_cid,
            definition_occurrence=row.definition_occurrence,
            definition_locus=row.definition_locus,
            lexical_parent=row.lexical_parent,
            call_occurrence=row.call_occurrence,
            call_locus=row.call_locus,
            lexical_scope=row.lexical_scope,
        )


def test_closed_product_refuses_deserialization_and_empty_default(
    constructed_module_door,
) -> None:
    authentic = _constructed("def outer():\n    return 1\n")
    assert not any(
        callable(getattr(type(authentic), name, None))
        for name in ("decode", "deserialize", "from_dict", "from_json", "load")
    )
    with pytest.raises(
        BackendDefect,
        match="closed constructor requires backend-owned capability",
    ):
        type(authentic)()


def test_backend_fingerprint_and_product_substitution_refuse(
    constructed_module_door,
) -> None:
    source = "def outer():\n    return 1\n"
    ordinary = _constructed(source)
    foreign = _authentic_foreign_backend_product(source)
    if foreign is None:
        pytest.skip("unmeasured: authentic_generic_backend_denominator=0")
    assert ordinary.backend_fingerprint != foreign.backend_fingerprint
    with pytest.raises(BackendDefect, match="backend fingerprint"):
        replace(ordinary, backend_fingerprint=foreign.backend_fingerprint)


def test_constructed_provider_member_carries_exact_term_testimony(
    constructed_module_door,
) -> None:
    product = _constructed("PROVIDER_VALUE = 3\n")
    (member,) = product.provider_member_rows

    assert member.definition_locus == LineColSpan(1, 0, 1, 18)
    assert member.definition_occurrence is not None
    assert member.constructed_term_value.value == 3
    assert (
        member.constructed_term_value_identity
        == member.constructed_term_value.identity
    )
    assert member.constructed_term_sort == member.constructed_term_value.sort
    assert member.constructed_module_identity == product.constructed_module_identity
    assert member.construction_event_identity is (
        product.construction_event_receipt.construction_event_identity
    )


@pytest.mark.parametrize(
    ("field_name", "message"),
    (
        ("definition_occurrence", "exact member definition occurrence"),
        ("definition_locus", "exact member definition locus"),
        ("constructed_term_value_identity", "constructed TermValue identity"),
        ("constructed_term_value", "constructed TermValue value"),
        ("constructed_term_sort", "constructed TermValue sort"),
    ),
)
def test_constructed_provider_member_cross_wire_refuses_one_axis(
    field_name, message, constructed_module_door,
) -> None:
    product = _constructed("FIRST_VALUE = 3\nSECOND_VALUE = 'three'\n")
    first, second = product.provider_member_rows
    if field_name in ("definition_occurrence", "constructed_term_value"):
        assert getattr(first, field_name) is not getattr(second, field_name)
    else:
        assert getattr(first, field_name) != getattr(second, field_name)
    leaves = (
        "source_cid",
        "constructed_module_identity",
        "backend_fingerprint",
        "construction_event_identity",
        "definition_occurrence",
        "definition_locus",
        "constructed_term_value_identity",
        "constructed_term_value",
        "constructed_term_sort",
    )
    proposed = {
        name: getattr(second, name) if name == field_name else getattr(first, name)
        for name in leaves
    }
    assert all(
        proposed[name] is getattr(first, name)
        for name in leaves
        if name != field_name
        and name
        in (
            "construction_event_identity",
            "definition_occurrence",
            "constructed_term_value",
        )
    )
    assert all(
        proposed[name] == getattr(first, name)
        for name in leaves
        if name != field_name
        and name
        in (
            "source_cid",
            "constructed_module_identity",
            "backend_fingerprint",
            "definition_locus",
            "constructed_term_value_identity",
            "constructed_term_sort",
        )
    )
    with pytest.raises(BackendDefect, match=message):
        replace(first, **{field_name: proposed[field_name]})


@pytest.mark.parametrize(
    ("product_kind", "field_name", "message"),
    (
        ("foreign-source", "source_cid", "provider source CID"),
        (
            "foreign-source",
            "constructed_module_identity",
            "enclosing ConstructedModule identity",
        ),
        (
            "foreign-source",
            "construction_event_identity",
            "provider construction event identity",
        ),
        (
            "foreign-backend",
            "backend_fingerprint",
            "provider backend fingerprint",
        ),
    ),
)
def test_constructed_provider_member_refuses_product_migration_one_axis(
    product_kind, field_name, message, constructed_module_door,
) -> None:
    source = "PROVIDER_VALUE = 3\n"
    first_product = _constructed(source)
    foreign_products = {
        "foreign-source": _constructed(source + "# foreign source bytes\n"),
    }
    foreign_backend = _authentic_foreign_backend_product(source)
    if product_kind == "foreign-backend" and foreign_backend is None:
        pytest.skip("unmeasured: authentic_generic_backend_denominator=0")
    if foreign_backend is not None:
        foreign_products["foreign-backend"] = foreign_backend
    (first,) = first_product.provider_member_rows
    (foreign,) = foreign_products[product_kind].provider_member_rows

    if field_name == "construction_event_identity":
        assert getattr(first, field_name) is not getattr(foreign, field_name)
    else:
        assert getattr(first, field_name) != getattr(foreign, field_name)
    leaves = (
        "source_cid",
        "constructed_module_identity",
        "backend_fingerprint",
        "construction_event_identity",
        "definition_occurrence",
        "definition_locus",
        "constructed_term_value_identity",
        "constructed_term_value",
        "constructed_term_sort",
    )
    proposed = {
        name: getattr(foreign, name) if name == field_name else getattr(first, name)
        for name in leaves
    }
    assert all(
        proposed[name] is getattr(first, name)
        for name in leaves
        if name != field_name
        and name
        in (
            "construction_event_identity",
            "definition_occurrence",
            "constructed_term_value",
        )
    )
    assert all(
        proposed[name] == getattr(first, name)
        for name in leaves
        if name != field_name
        and name
        not in (
            "construction_event_identity",
            "definition_occurrence",
            "constructed_term_value",
        )
    )
    with pytest.raises(BackendDefect, match=message):
        replace(first, **{field_name: proposed[field_name]})


def test_constructed_provider_member_constructor_and_deserialization_are_closed(
    constructed_module_door,
) -> None:
    product = _constructed("PROVIDER_VALUE = 3\n")
    (member,) = product.provider_member_rows
    member_type = type(member)

    with pytest.raises(TypeError, match="backend construction owner"):
        member_type(
            source_cid=member.source_cid,
            constructed_module_identity=member.constructed_module_identity,
            backend_fingerprint=member.backend_fingerprint,
            construction_event_identity=member.construction_event_identity,
            definition_occurrence=member.definition_occurrence,
            definition_locus=member.definition_locus,
            constructed_term_value_identity=member.constructed_term_value_identity,
            constructed_term_value=member.constructed_term_value,
            constructed_term_sort=member.constructed_term_sort,
        )
    with pytest.raises(BackendDefect, match="copied sealed provider member"):
        replace(member)
    assert not any(
        callable(getattr(member_type, name, None))
        for name in ("decode", "deserialize", "from_dict", "from_json", "load")
    )


def test_leaf_assertion_roster_is_distinct_ordered_same_event_testimony(
    constructed_module_door,
) -> None:
    product = _constructed(
        "def outer():\n"
        "    def child():\n"
        "        return True\n"
        "    assert child() and external()\n"
    )
    lexical, = product.lexical_call_rows
    child, external = product.leaf_assertion_rows

    assert product.leaf_assertion_rows is not product.lexical_call_rows
    assert type(child) is not type(lexical)
    assert child.source_cid == product.source_cid
    assert external.source_cid == product.source_cid
    assert child.function_locus == LineColSpan(1, 0, 4, 33)
    assert child.assert_locus == LineColSpan(4, 4, 4, 33)
    assert [row.call_locus for row in product.leaf_assertion_rows] == [
        LineColSpan(4, 11, 4, 18),
        LineColSpan(4, 23, 4, 33),
    ]
    assert child.function_occurrence is external.function_occurrence
    assert child.assert_occurrence is external.assert_occurrence
    assert child.call_occurrence is lexical.call_occurrence
    assert child.construction_event_identity is (
        product.construction_event_receipt.construction_event_identity
    )
    assert external.construction_event_identity is child.construction_event_identity
    receipt = product.construction_event_receipt
    assert receipt.leaf_assertion_rows is product.leaf_assertion_rows
    assert receipt.leaf_assertion_rows[0] is child
    assert receipt.leaf_assertion_rows[1] is external
    assert any(
        occurrence is child.call_occurrence
        for occurrence in receipt.registered_occurrences
    )
    assert any(
        occurrence is external.call_occurrence
        for occurrence in receipt.registered_occurrences
    )


def test_module_external_leaf_has_no_nested_definition_authority(
    constructed_module_door,
) -> None:
    product = _constructed("assert external()\n")
    (row,) = product.leaf_assertion_rows

    assert product.lexical_call_rows == ()
    assert row.function_occurrence is None
    assert row.function_locus is None
    for forbidden in (
        "definition_occurrence",
        "definition_locus",
        "lexical_parent",
        "lexical_scope",
        "reaching_definition",
        "nested_function_lookup",
    ):
        assert not hasattr(row, forbidden)


def test_leaf_roster_filename_is_output_only(constructed_module_door) -> None:
    source = "def outer():\n    assert external()\n"
    first = _constructed(source, "first.py").leaf_assertion_rows[0]
    renamed = _constructed(source, "renamed.py").leaf_assertion_rows[0]

    assert Path(first.filename).name == "first.py"
    assert Path(renamed.filename).name == "renamed.py"
    assert first.source_cid == renamed.source_cid
    assert first.function_occurrence_identity == renamed.function_occurrence_identity
    assert first.assert_occurrence_identity == renamed.assert_occurrence_identity
    assert first.call_occurrence_identity == renamed.call_occurrence_identity
    assert first.call_locus == renamed.call_locus
    assert first.translated_term_identity == renamed.translated_term_identity


@pytest.mark.parametrize(
    ("field_name", "message"),
    (
        ("source_cid", "leaf source CID"),
        ("constructed_module_identity", "enclosing ConstructedModule identity"),
        ("backend_fingerprint", "leaf backend fingerprint"),
        ("construction_event_identity", "leaf construction event identity"),
        ("function_occurrence", "exact leaf FunctionDef occurrence"),
        ("function_locus", "exact leaf FunctionDef locus"),
        ("assert_occurrence", "exact leaf Assert occurrence"),
        ("assert_locus", "exact leaf Assert locus"),
        ("call_occurrence", "exact leaf Call occurrence"),
        ("call_locus", "exact leaf Call locus"),
        ("translated_atom_identity", "translated atom identity"),
        ("translated_atom_value", "translated atom value"),
        ("translated_term_identity", "translated term identity"),
        ("translated_term_value", "translated term value"),
    ),
)
def test_leaf_assertion_row_cross_wire_refuses_one_axis(
    field_name,
    message,
    authentic_leaf_axis_rows,
) -> None:
    first, _, twins = authentic_leaf_axis_rows
    foreign = twins[field_name]
    if field_name == "backend_fingerprint" and foreign is None:
        pytest.skip("unmeasured: authentic_generic_backend_denominator=0")
    if field_name in ("translated_atom_identity", "translated_atom_value"):
        assert foreign.assert_occurrence is not first.assert_occurrence
    if field_name in ("translated_term_identity", "translated_term_value"):
        assert foreign.assert_occurrence is first.assert_occurrence
        assert foreign.call_occurrence is not first.call_occurrence
    object_leaves = {
        "construction_event_identity",
        "function_occurrence",
        "assert_occurrence",
        "call_occurrence",
        "translated_atom_value",
        "translated_term_value",
    }
    leaves = (
        "source_cid",
        "constructed_module_identity",
        "backend_fingerprint",
        "construction_event_identity",
        "function_occurrence",
        "function_locus",
        "assert_occurrence",
        "assert_locus",
        "call_occurrence",
        "call_locus",
        "translated_atom_identity",
        "translated_atom_value",
        "translated_term_identity",
        "translated_term_value",
    )
    if field_name in object_leaves:
        assert getattr(first, field_name) is not getattr(foreign, field_name)
    else:
        assert getattr(first, field_name) != getattr(foreign, field_name)
    proposed = {
        name: getattr(foreign, name) if name == field_name else getattr(first, name)
        for name in leaves
    }
    assert all(
        proposed[name] is getattr(first, name)
        for name in object_leaves
        if name != field_name
    )
    assert all(
        proposed[name] == getattr(first, name)
        for name in leaves
        if name != field_name and name not in object_leaves
    )
    with pytest.raises(BackendDefect, match=message):
        replace(first, **{field_name: proposed[field_name]})


@pytest.mark.parametrize("mutation", ("reordered", "dropped", "duplicated"))
def test_leaf_assertion_roster_shape_tamper_refuses(
    mutation,
    constructed_module_door,
) -> None:
    product = _constructed("def outer():\n    assert left() and right()\n")
    first, second = product.leaf_assertion_rows
    lying = {
        "reordered": (second, first),
        "dropped": (first,),
        "duplicated": (first, first, second),
    }[mutation]

    with pytest.raises(BackendDefect, match="ordered physical leaf assertion roster"):
        replace(product, leaf_assertion_rows=lying)


def test_leaf_assertion_relation_constructor_copy_mutation_and_decoder_are_closed(
    constructed_module_door,
) -> None:
    product = _constructed("def outer():\n    assert external()\n")
    (row,) = product.leaf_assertion_rows
    row_type = type(row)

    with pytest.raises(TypeError, match="backend construction owner"):
        row_type(
            source_cid=row.source_cid,
            constructed_module_identity=row.constructed_module_identity,
            backend_fingerprint=row.backend_fingerprint,
            construction_event_identity=row.construction_event_identity,
            filename=row.filename,
            function_occurrence=row.function_occurrence,
            function_locus=row.function_locus,
            assert_occurrence=row.assert_occurrence,
            assert_locus=row.assert_locus,
            call_occurrence=row.call_occurrence,
            call_locus=row.call_locus,
            translated_atom_identity=row.translated_atom_identity,
            translated_atom_value=row.translated_atom_value,
            translated_term_identity=row.translated_term_identity,
            translated_term_value=row.translated_term_value,
        )
    with pytest.raises(BackendDefect, match="copied sealed leaf assertion relation"):
        replace(row)
    with pytest.raises(BackendDefect, match="copied sealed leaf assertion relation"):
        copy.copy(row)
    with pytest.raises(BackendDefect, match="copied sealed leaf assertion relation"):
        copy.deepcopy(row)
    with pytest.raises(BackendDefect, match="sealed leaf assertion relation"):
        row.call_locus = LineColSpan(1, 0, 1, 1)
    assert not any(
        callable(getattr(row_type, name, None))
        for name in ("decode", "deserialize", "from_dict", "from_json", "load")
    )


def test_authentically_empty_leaf_roster_is_not_producer_never_ran(
    constructed_module_door,
) -> None:
    product = _constructed("VALUE = 3\n")

    assert product.leaf_assertion_rows == ()
    assert product.construction_event_receipt.leaf_assertion_rows is (
        product.leaf_assertion_rows
    )


def test_repeated_leaf_views_are_identity_projection_with_zero_later_work(
    constructed_module_door,
    sourcefile_construction_door_evidence: SourceFileConstructionDoorEvidence,
) -> None:
    evidence = assert_test_owned_evidence(sourcefile_construction_door_evidence)
    product = evidence.zero_work.constructed_product
    rows = product.leaf_assertion_rows

    assert rows
    assert product.reporting_projection is evidence.zero_work.reporting_projection
    assert product.leaf_assertion_rows is rows
    assert all(
        result is evidence.zero_work.reporting_projection
        for result in evidence.zero_work.repeated_projection_results
    )
    assert evidence.zero_work.reporter_after == evidence.zero_work.reporter_before
    assert evidence.zero_work.protocol_after == evidence.zero_work.protocol_before
