"""f-strings: JoinedStr concatenates its parts; FormattedValue is format(value)."""

import tempfile

import pytest

from sugar_lift_py_tests.caller_parameter_contract import NativeOperationExitCarrierV1
from sugar_lift_py_tests.floor.string_value import StringValue
from sugar_lift_py_tests.floor.symbolic_value import SymbolicValue
from sugar_lift_python_source.source_oracle import path_source
from sugar_source_tree.backend import Leaf, MaybeChild, materialize
from sugar_source_tree.panic import BackendDefect
from sugar_source_tree.shadow import ShadowNode
from sugar_lift_py_tests.context_manager_resolution import TreeConstructionContextV1
from sugar_source_tree.tree import SourceFile


def _fn(src):
    with tempfile.NamedTemporaryFile("w", suffix=".py", delete=False, dir="/tmp") as f:
        f.write(src)
        path = f.name
    return next(SourceFile(path_source(path), construction_context=TreeConstructionContextV1.for_test_without_workspace()).functions())


def _post_term(src):
    return _fn(src).sugar().desugar().value.post().args[1]


def _formatted_value(src):
    fn = _fn(src)
    joined = fn.body[0].value
    return next(value for value in joined.values if value.kind == "FormattedValue")


def _with_conversion(node, conversion):
    desc = node.ref.describe()
    slots = tuple(
        (name, Leaf(conversion) if name == "conversion" else slot)
        for name, slot in desc.slots
    )
    return materialize(
        node.unit,
        ShadowNode("FormattedValue", desc.raw_span or node.span, slots),
        node.reporter,
    )


def _with_bare_format_spec(node):
    desc = node.ref.describe()
    slots = tuple(
        (name, MaybeChild(node.value.ref) if name == "format_spec" else slot)
        for name, slot in desc.slots
    )
    return materialize(
        node.unit,
        ShadowNode("FormattedValue", desc.raw_span or node.span, slots),
        node.reporter,
    )


def test_fstring_concat_preserves_operands_in_native_operation_carrier():
    """Do not restore the deleted ``.value`` false-completion expectation.

    ``str + SymbolicValue`` deliberately stays pending until native-operation
    discharge.  The carrier must retain the exact f-string operands instead of
    fabricating the completed ``+`` term this test asserted before #7060.
    """
    outcome = _fn('def A(z):\n    return f"n={z}"\n').sugar().desugar()

    assert isinstance(outcome, NativeOperationExitCarrierV1)
    with pytest.raises(AttributeError, match="value"):
        _ = outcome.value

    assert outcome.demand.operator == "add"
    left, right = outcome.operands
    assert isinstance(left, StringValue) and left.value == "n="
    assert isinstance(right, SymbolicValue)
    assert right.to_term(owner="f-string carrier tooth").name == "python:fstring_value"


def test_fstring_with_only_a_literal_is_the_string():
    term = _post_term('def A():\n    return f"hello"\n')
    assert type(term).__name__ == "_ConstStr" and term.value == "hello"


def test_conversion_and_format_spec_survive_in_reference_operand_order():
    """`value, conversion, format_spec` is the Python-reference order."""
    term = _post_term('def A(x):\n    return f"{x!r:>10}"\n')

    assert term.name == "python:fstring_value"
    assert term.args[0].name == "x"
    assert term.args[1].value == "r"
    assert term.args[2].name == "python:fstring"
    assert len(term.args[2].args) == 1
    assert term.args[2].args[0].value == ">10"


def test_fstring_conversions_are_distinct_typed_string_operands():
    conversions = {
        marker: _post_term(f'def A(x):\n    return f"{{x!{marker}}}"\n').args[1]
        for marker in ("r", "s", "a")
    }

    assert {marker: term.value for marker, term in conversions.items()} == {
        "r": "r",
        "s": "s",
        "a": "a",
    }
    assert {type(term).__name__ for term in conversions.values()} == {"_ConstStr"}


def test_absent_conversion_and_format_spec_are_explicit_none_operands():
    term = _post_term('def A(x):\n    return f"{x}"\n')

    assert term.name == "python:fstring_value"
    assert len(term.args) == 3
    assert term.args[1].name == "None" and term.args[1].args == ()
    assert term.args[2].name == "None" and term.args[2].args == ()


def test_malformed_conversion_slot_is_a_backend_defect():
    """Discrimination twin: a backend cannot claim an invented ``!q`` slot."""
    formatted = _formatted_value('def A(z):\n    return f"{z!r}"\n')
    lying = _with_conversion(formatted, ord("q"))

    with pytest.raises(BackendDefect):
        lying.sugar()


def test_bare_format_spec_slot_is_a_backend_defect():
    formatted = _formatted_value('def A(z):\n    return f"{z}"\n')
    lying = _with_bare_format_spec(formatted)

    with pytest.raises(BackendDefect):
        lying.sugar()


if __name__ == "__main__":
    test_fstring_concatenates_literal_and_interpolation()
    test_fstring_with_only_a_literal_is_the_string()
    test_conversion_and_format_spec_survive_in_reference_operand_order()
    test_fstring_conversions_are_distinct_typed_string_operands()
    test_absent_conversion_and_format_spec_are_explicit_none_operands()
    test_malformed_conversion_slot_is_a_backend_defect()
    test_bare_format_spec_slot_is_a_backend_defect()
    print("ok: f-strings concatenate; modifiers build; malformed slots loud")
