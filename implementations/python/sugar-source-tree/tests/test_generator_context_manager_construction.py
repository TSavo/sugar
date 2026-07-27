import pytest

from sugar_lift_py_tests.context_manager_resolution import (
    SourceFragmentCoordinateV1,
    TreeConstructionContextV1,
)
from sugar_lift_py_tests.outcome import Complete
from sugar_lift_py_tests.ir import ctor, eq, num, str_const
from sugar_source_tree.nodes import Call, FunctionDef, With
from sugar_source_tree.panic import SugarNotWritten
from sugar_source_tree.tree import SourceFile


def _source_file(source: str, context) -> SourceFile:
    from sugar_lift_python_source.canonical import blake3_512_of

    return SourceFile(
        (source, "renamed_generator_manager.py", blake3_512_of(source.encode())),
        construction_context=context,
    )


def _coordinate(node) -> SourceFragmentCoordinateV1:
    span = node.line_col_span()
    return SourceFragmentCoordinateV1(
        node.unit.source_cid,
        span.start_line,
        span.start_col,
        span.end_line,
        span.end_col,
    )


def _with_sugar(
    manager_body: str,
    with_body: str = "    assert entered == 7",
    *,
    bind_entered: bool = True,
):
    context = TreeConstructionContextV1.for_source_call_construction()
    source = _source_file(
        "def arbitrarily_renamed():\n"
        f"{manager_body}\n\n"
        f"with arbitrarily_renamed(){' as entered' if bind_entered else ''}:\n"
        f"{with_body}\n",
        context,
    )
    function = next(node for node in source.nodes() if isinstance(node, FunctionDef))
    with_node = next(node for node in source.nodes() if isinstance(node, With))
    manager_call = with_node.items[0].context_expr
    assert isinstance(manager_call, Call)
    context.source_call_frames[_coordinate(manager_call)] = (
        function.source_visible_call_frame()
    )
    return with_node.substitute({}).sugar()


def test_renamed_generator_manager_enters_at_first_yield_without_name_authority():
    sugar = _with_sugar("    yield 7")

    assert type(sugar).__name__ == "GeneratorWithSugar"
    outcome = sugar.desugar()
    assert isinstance(outcome, Complete)
    assert outcome.value.statements[0].formula == eq(
        ctor("enter_result_value", [str_const(sugar.enter_slot_id)]), num(7)
    )


def test_second_yield_stays_typed_loud_on_normal_exit():
    sugar = _with_sugar("    yield 7\n    yield 8")

    with pytest.raises(SugarNotWritten, match="second yield"):
        sugar.desugar()


def test_premature_return_on_enter_is_the_observed_manager_raise():
    """Return-before-yield at enter is RuntimeError("generator didn't yield").

    Not a SugarNotWritten refusal of a real Python outcome: the consumer
    routes GeneratorTerminationV1 through the observed entry refusal into
    a Halted RaiseEffect arm that exitset_to_outcome projects as Incomplete
    inside the block.
    """
    from sugar_lift_py_tests.effect.raise_effect import RaiseEffect
    from sugar_lift_py_tests.generator_entry_refusal import observed_entry_refusal
    from sugar_lift_py_tests.outcome import Incomplete

    sugar = _with_sugar("    return 7\n    yield 8", bind_entered=False)
    outcome = sugar.desugar()
    assert isinstance(outcome, Complete)
    raises = [
        entry
        for entry in outcome.value.statements
        if isinstance(entry, Incomplete) and isinstance(entry.effect, RaiseEffect)
    ]
    assert len(raises) == 1, outcome.value.statements
    refusal = observed_entry_refusal()
    assert raises[0].effect.exception_name == refusal.exception_name
    assert raises[0].effect.raised_value == refusal.message


def test_never_yield_on_enter_is_the_observed_manager_raise():
    """``if False: yield`` never suspends — same enter raise as premature return."""
    from sugar_lift_py_tests.effect.raise_effect import RaiseEffect
    from sugar_lift_py_tests.generator_entry_refusal import observed_entry_refusal
    from sugar_lift_py_tests.outcome import Incomplete

    sugar = _with_sugar("    if False:\n        yield 1", bind_entered=False)
    outcome = sugar.desugar()
    assert isinstance(outcome, Complete)
    raises = [
        entry
        for entry in outcome.value.statements
        if isinstance(entry, Incomplete) and isinstance(entry.effect, RaiseEffect)
    ]
    assert len(raises) == 1
    refusal = observed_entry_refusal()
    assert raises[0].effect.exception_name == refusal.exception_name
    assert raises[0].effect.raised_value == refusal.message


def test_opaque_transition_stays_typed_loud():
    sugar = _with_sugar("    if opaque:\n        yield 7")

    with pytest.raises(SugarNotWritten, match="opaque generator transition"):
        sugar.desugar()


def test_exceptional_exit_throws_into_machine_and_preserves_both_body_faces():
    sugar = _with_sugar(
        "    yield 7",
        "    if condition:\n        raise RenamedError",
        bind_entered=False,
    )

    outcome = sugar.desugar()

    assert isinstance(outcome, Complete)
    contributions = outcome.value.statements
    assert any(type(item).__name__ == "Incomplete" for item in contributions)
    assert outcome.value.can_fall_through


def test_contextmanager_style_try_finally_resumes_cleanup_before_termination():
    sugar = _with_sugar("    try:\n        yield 7\n    finally:\n        pass")

    outcome = sugar.desugar()

    assert isinstance(outcome, Complete)
    assert outcome.value.statements[0].formula == eq(
        ctor("enter_result_value", [str_const(sugar.enter_slot_id)]), num(7)
    )


def test_docstring_is_stepped_and_is_never_the_blocker():
    """TRUTHFUL TWIN. A leading docstring owes nothing, so it is stepped.

    The generator enters at its `yield` exactly as it does with no docstring
    at all -- the `InertStepV1` row is the whole difference. Without it the
    machine refuses at statement zero and names `Expr`, which is a blocker
    that asks for nothing.
    """
    sugar = _with_sugar("    '''Real work happens below.'''\n    yield 7")

    outcome = sugar.desugar()
    assert isinstance(outcome, Complete)
    assert outcome.value.statements[0].formula == eq(
        ctor("enter_result_value", [str_const(sugar.enter_slot_id)]), num(7)
    )


def test_inert_step_does_not_swallow_a_call_expression():
    """LYING TWIN. An `Expr` that is not a `Constant` still owes execution.

    `record()` is spelled like the docstring -- a bare expression statement --
    and is exactly what a spelling-based admission would step past. It owes a
    call, so it stays opaque and loud. If this node goes green the inert row
    has been widened past what it can prove.
    """
    sugar = _with_sugar("    record()\n    yield 7")

    with pytest.raises(SugarNotWritten, match="opaque generator transition: Expr"):
        sugar.desugar()


def test_inert_step_does_not_swallow_a_binding():
    """LYING TWIN. A binding is real work and must remain the named blocker.

    This is the pandas `__tracebackhide__ = True` shape, and it is what the
    machine must report once the docstring ahead of it is stepped.
    """
    sugar = _with_sugar("    '''Doc.'''\n    hidden = True\n    yield 7")

    with pytest.raises(SugarNotWritten, match="opaque generator transition: Assign"):
        sugar.desugar()
