"""f-strings: JoinedStr concatenates its parts; FormattedValue is format(value)."""

import tempfile

import pytest

from sugar_lift_py_tests.caller_parameter_contract import NativeOperationExitCarrierV1
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
    outcome = _fn(src).sugar().desugar()
    if not hasattr(outcome, "exits"):
        return outcome.value.post().args[1]
    # ``f"{x}"`` on a formal runs ``type(x).__format__`` (``!r``/``!s``/``!a``
    # its ``__repr__``/``__str__`` first), which may be user code: the return
    # is the one unanswered call, completing only under its atom and halting
    # undetermined under its complement. Read the term off that one completed
    # face.
    from sugar_lift_py_tests.effect.raise_effect import UndeterminedRaiseEffect
    from sugar_lift_py_tests.outcome.exit_set import Completed, Halted

    (completed,) = [e for e in outcome.exits if isinstance(e, Completed)]
    (halted,) = [e for e in outcome.exits if isinstance(e, Halted)]
    assert completed.guard.name == "python:unknown_callee_call.completes"
    assert isinstance(halted.effect, UndeterminedRaiseEffect)
    assert halted.effect.producer_node_owner == "UnknownCallee:format"
    return completed.value.post().args[1]


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


def test_fstring_concat_keeps_its_faces_and_its_operands():
    """``f"n={z}"`` is its faces, never a carrier that waits on no caller.

    The formatted part is ``format(z)``, not the parameter ``z``: no caller's
    actual fills it, so nothing defers.  Its raise face is the format call's
    own (``UnknownCallee:format``) and the join of two strings adds none.  The
    completed face keeps both operands, the literal and the formatted value,
    in ``python:fstring``; it does not fabricate the joined string (#7060).
    A carrier minted here with no coordinate held every face beside it, and
    no caller ever answered it (#7757).
    """
    outcome = _fn('def A(z):\n    return f"n={z}"\n').sugar().desugar()
    assert not isinstance(outcome, NativeOperationExitCarrierV1), outcome

    term = _post_term('def A(z):\n    return f"n={z}"\n')
    assert term.name == "python:fstring"
    left, right = term.args
    assert type(left).__name__ == "_ConstStr" and left.value == "n="
    assert right.name == "python:fstring_value"


def test_string_plus_an_undecided_value_is_the_undecided_binary_law():
    """``"n=" + z`` reduced with no context: ``z`` is an undecided value with
    no formal, so no caller answers the operation.  It is the one undecided
    binary law, a completed face and the ``UndecidedBinary:+`` halt, never a
    carrier with no coordinate (#7757)."""
    from sugar_lift_py_tests.outcome import Completed, ExitSet

    fn = _fn('def A(z):\n    return "n=" + z\n')
    outcome = fn.body[0].value.sugar().desugar(None)

    assert isinstance(outcome, ExitSet), type(outcome).__name__
    assert any(isinstance(face, Completed) for face in outcome.exits)
    assert [face.effect.producer_node_owner for face in outcome.halts()] == [
        "UndecidedBinary:+"
    ]


def test_string_plus_a_parameter_is_the_undecided_binary_law():
    """``"n=" + z`` with ``z`` the function's parameter waits on no caller
    (#7757, audit row NEW-1): ``z``'s ``__radd__`` may answer after
    ``str.__add__``'s ``NotImplemented``, which no one dispatched method
    states.  So the function states the one undecided binary law, a
    completed face and the ``UndecidedBinary:+`` halt, over the exact
    operands: the literal and the parameter."""
    from sugar_lift_py_tests.ir import _ConstStr, _Ctor, _Var
    from sugar_lift_py_tests.outcome import Completed, ExitSet

    outcome = _fn('def A(z):\n    return "n=" + z\n').sugar().desugar()

    assert not isinstance(outcome, NativeOperationExitCarrierV1), outcome
    assert isinstance(outcome, ExitSet), type(outcome).__name__
    assert [face.effect.producer_node_owner for face in outcome.halts()] == [
        "UndecidedBinary:+"
    ]
    (done,) = [face for face in outcome.exits if isinstance(face, Completed)]
    assert "python:binary_op.completes" in repr(done.guard)
    results = [
        node
        for node in _terms(done.guard)
        if isinstance(node, _Ctor) and node.name == "python:binary_result"
    ]
    assert results, done.guard
    operator, left, right, _key = results[0].args
    assert operator.value == "+"
    assert isinstance(left, _ConstStr) and left.value == "n="
    assert isinstance(right, _Var) and right.name == "z"


def _terms(root):
    """Every node of a formula or term, depth first."""
    import dataclasses

    stack = [root]
    while stack:
        node = stack.pop()
        yield node
        if isinstance(node, (tuple, list)):
            stack.extend(node)
        elif dataclasses.is_dataclass(node) and not isinstance(node, type):
            stack.extend(
                getattr(node, field.name, None) for field in dataclasses.fields(node)
            )


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
