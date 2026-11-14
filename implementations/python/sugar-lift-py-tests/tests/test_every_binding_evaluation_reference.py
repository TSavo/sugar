"""Every binding reads its own statement's evaluation (temporal choice 1,
#7661; #7757 item 7, after #7941).

#7941 keyed ``y = x``.  The other bindings still read the wrong value once a
name they read was rebound:

1. ``y = x + 0`` (any right-hand side that is not a bare reference) was
   inlined at each read of ``y``, so the read evaluated ``x + 0`` again after
   ``x`` was rebound.  Every assignment now binds its target to the value
   under its own statement key (``Assign.target_evaluations``).
2. ``y: T = x`` read ``x``'s reference.  An annotated assignment with a value
   evaluates its right-hand side and is keyed like ``Assign``
   (``AnnAssign.target_evaluations``).
3. An unrolled ``for y in [x]`` bound ``y`` to the display member, read again
   wherever ``y`` was read.  Each iteration opens with its own keyed binding
   of its item (``For._iteration_unpacks``).
4. A nested ``def`` reading an enclosing local was refused (no captured
   coordinate), and a reference whose key never reached its frame read the
   name.  A call of the local ``def`` in its enclosing body now carries the
   binding its own scope holds for the name at the call
   (``Call._closure_cells``) and binds its value under the frame's captured
   coordinate (``FunctionDef._captured_bindings``): no name read.

An assignment's reference also carries what the name was given as the object
it denotes (``_evaluation_ref``, ``of``), so a store through one name still
reaches every name given the same object (``container_mutation._identity``).
"""

from __future__ import annotations

from pathlib import Path

from sugar_lift_py_tests.context_manager_resolution import TreeConstructionContextV1
from sugar_lift_py_tests.floor import TermValue
from sugar_lift_py_tests.floor.guarded_return import GuardedReturn
from sugar_lift_py_tests.floor.return_value import ReturnValue
from sugar_lift_py_tests.outcome import Completed, outcome_to_exitset
from sugar_lift_py_tests.sugar.assign_sugar import AssignSugar
from sugar_lift_py_tests.temporal.temporal_context import (
    EVALUATION_PREFIX,
    projection_key,
)
from sugar_lift_python_source.canonical import blake3_512_of
from sugar_lift_python_source.source_oracle import path_source
from sugar_source_tree.nodes import (
    AnnAssign,
    Assign,
    Call,
    EvaluationRef,
    FunctionDef,
    Return,
)
from sugar_source_tree.tree import SourceFile

ONE, TWO = TermValue(1), TermValue(2)

# 1. Any right-hand side.
EXPRESSION_REBOUND = (
    "def f():\n"
    "    x = 1\n"
    "    y = x + 0\n"
    "    x = 5\n"
    "    return y\n"
)
EXPRESSION_AUGMENTED = (
    "def f():\n"
    "    x = 1\n"
    "    x += 1\n"
    "    y = x + 0\n"
    "    x += 1\n"
    "    return y\n"
)
# 2. An annotated assignment.
ANNOTATED = (
    "def f():\n"
    "    x = 1\n"
    "    x += 1\n"
    "    y: int = x\n"
    "    x += 1\n"
    "    return y\n"
)
# 3. An unrolled for target.
FOR_TARGET_REBOUND = (
    "def f():\n"
    "    x = 1\n"
    "    for y in [x]:\n"
    "        x = 9\n"
    "        r = y\n"
    "    return r\n"
)
FOR_TARGET_AUGMENTED = (
    "def f():\n"
    "    x = 1\n"
    "    for y in [x]:\n"
    "        x += 8\n"
    "        r = y\n"
    "    return r\n"
)
# 4. A nested function reads the enclosing binding at the call.
NESTED = (
    "def f():\n"
    "    y = 1\n"
    "    def g():\n"
    "        return y\n"
    "    y = 2\n"
    "    return g()\n"
)
# The object a name denotes: a store through one name reaches the other.
ALIASED_LIST = (
    "def f():\n"
    "    r = []\n"
    "    a = r\n"
    "    r.append(1)\n"
    "    return a\n"
)


def _function(source: str, name: str = "f") -> FunctionDef:
    tree = SourceFile(
        (source, "every_binding_evaluation.py", blake3_512_of(source.encode())),
        construction_context=TreeConstructionContextV1.for_source_call_construction(),
    )
    return next(
        node
        for node in tree.nodes()
        if isinstance(node, FunctionDef) and node.name == name
    )


def _outcome(tmp_path: Path, source: str, stem: str, name: str = "f"):
    path = tmp_path / f"{stem}.py"
    path.write_text(source, encoding="utf-8")
    functions = SourceFile(
        path_source(str(path)),
        construction_context=TreeConstructionContextV1.for_test_without_workspace(),
    ).functions()
    function = next(node for node in functions if node.name == name)
    return function.sugar().desugar(None)


def _returned(outcome) -> list:
    """Every value a completed face of ``outcome`` returns; a call's value is
    the body its producer already reduced."""
    found: list = []

    def visit(value) -> None:
        if isinstance(value, (ReturnValue, GuardedReturn)):
            found.append(_resolved(value.value))
            return
        for entry in getattr(value, "statements", ()) or ():
            visit(entry)
        record = getattr(value, "record", None)
        if record is not None:
            visit(record)

    for exit_ in outcome_to_exitset(outcome).exits:
        if isinstance(exit_, Completed):
            visit(exit_.value)
    return found


def _resolved(value):
    retained = getattr(value, "retained_source_completion_outcome", None)
    if not callable(retained):
        return value
    outcome = retained()
    if outcome is None:
        return value
    inner = _returned(outcome)
    if inner:
        return inner[-1]
    return outcome_to_exitset(outcome).completed_value()


# ---------------------------------------------------------------------------
# 1. ``y = x + 0``: the read is the assignment's key, never the expression.
# ---------------------------------------------------------------------------


def test_an_expression_assignment_is_read_through_its_key() -> None:
    body = _function(EXPRESSION_AUGMENTED).substitute({}).body
    assign = next(
        node
        for node in body
        if isinstance(node, Assign) and node.targets[0].id == "y"
    )
    ret = body[-1]
    assert isinstance(ret, Return)
    assert isinstance(assign.evaluation, str)
    assert isinstance(ret.value, EvaluationRef)
    assert ret.value.evaluation == projection_key(assign.evaluation, "y")
    assert ret.value.name == "y"


def test_an_expression_assignment_sugar_binds_its_key() -> None:
    statements = _function(EXPRESSION_AUGMENTED).sugar().statements
    assign = next(
        sugar
        for sugar in statements
        if isinstance(sugar, AssignSugar) and sugar.name == "y"
    )
    ((name, key),) = assign.evaluations
    assert name == "y"
    assert key.startswith(EVALUATION_PREFIX)
    assert key.endswith("/y")


def test_an_expression_read_after_a_plain_rebind_is_the_old_value(
    tmp_path: Path,
) -> None:
    returned = _returned(_outcome(tmp_path, EXPRESSION_REBOUND, "rebound"))
    assert returned == [ONE], returned


def test_an_expression_read_after_an_augmented_rebind_is_the_old_value(
    tmp_path: Path,
) -> None:
    returned = _returned(_outcome(tmp_path, EXPRESSION_AUGMENTED, "augmented"))
    assert returned == [TWO], returned


# ---------------------------------------------------------------------------
# 2. ``y: int = x``: keyed like ``Assign``.
# ---------------------------------------------------------------------------


def test_an_annotated_assignment_is_read_through_its_key() -> None:
    body = _function(ANNOTATED).substitute({}).body
    annotated = next(node for node in body if isinstance(node, AnnAssign))
    ret = body[-1]
    assert isinstance(annotated.evaluation, str)
    assert isinstance(ret.value, EvaluationRef)
    assert ret.value.evaluation == projection_key(annotated.evaluation, "y")


def test_an_annotated_assignment_evaluates_its_value() -> None:
    statements = _function(ANNOTATED).sugar().statements
    annotated = next(
        sugar
        for sugar in statements
        if isinstance(sugar, AssignSugar) and sugar.name == "y"
    )
    ((name, key),) = annotated.evaluations
    assert name == "y"
    assert key.endswith("/y")


def test_an_annotated_read_after_a_rebind_is_the_old_value(tmp_path: Path) -> None:
    returned = _returned(_outcome(tmp_path, ANNOTATED, "annotated"))
    assert returned == [TWO], returned


def test_a_bare_annotation_binds_nothing() -> None:
    body = _function("def f():\n    y: int\n    return 0\n").substitute({}).body
    annotated = next(node for node in body if isinstance(node, AnnAssign))
    assert getattr(annotated, "evaluation", None) is None
    assert annotated.substitution_binding({}) is None


# ---------------------------------------------------------------------------
# 3. ``for y in [x]``: the iteration's own key.
# ---------------------------------------------------------------------------


def test_an_unrolled_name_target_is_keyed_per_iteration() -> None:
    body = _function(FOR_TARGET_AUGMENTED).substitute({}).body
    stores = [
        node
        for node in body
        if isinstance(node, Assign)
        and node.targets[0].id == "y"
        and isinstance(getattr(node, "evaluation", None), str)
    ]
    assert len(stores) == 1
    read = next(
        node.value
        for node in body
        if isinstance(node, Assign) and node.targets[0].id == "r"
    )
    assert isinstance(read, EvaluationRef)
    assert read.evaluation == projection_key(stores[0].evaluation, "y")


def test_two_iterations_have_two_keys() -> None:
    source = "def f(p, q):\n    for y in [p, q]:\n        r = y\n    return r\n"
    body = _function(source).substitute({}).body
    stores = [
        node
        for node in body
        if isinstance(node, Assign)
        and node.targets[0].id == "y"
        and isinstance(getattr(node, "evaluation", None), str)
    ]
    assert len(stores) == 2
    assert stores[0].evaluation != stores[1].evaluation


def test_an_unrolled_target_after_a_plain_rebind_is_the_old_value(
    tmp_path: Path,
) -> None:
    returned = _returned(_outcome(tmp_path, FOR_TARGET_REBOUND, "for_rebound"))
    assert returned == [ONE], returned


def test_an_unrolled_target_after_an_augmented_rebind_is_the_old_value(
    tmp_path: Path,
) -> None:
    returned = _returned(_outcome(tmp_path, FOR_TARGET_AUGMENTED, "for_augmented"))
    assert returned == [ONE], returned


# ---------------------------------------------------------------------------
# 4. A nested ``def``: the enclosing binding at the call, carried.
# ---------------------------------------------------------------------------


def test_the_call_carries_the_enclosing_binding_at_the_call() -> None:
    body = _function(NESTED).substitute({}).body
    rebind = [
        node
        for node in body
        if isinstance(node, Assign) and node.targets[0].id == "y"
    ][-1]
    ret = body[-1]
    assert isinstance(ret, Return)
    call = ret.value
    assert isinstance(call, Call)
    ((name, cell),) = call.closure_cells
    assert name == "y"
    assert isinstance(cell, EvaluationRef)
    assert cell.evaluation == projection_key(rebind.evaluation, "y")


def test_the_nested_frame_reads_the_name_through_a_captured_coordinate() -> None:
    nested = _function(NESTED, name="g")
    names, coordinates = nested._captured_bindings()
    assert names == ("y",)
    frame = nested.source_visible_call_frame()
    assert frame.captured_names == ("y",)
    assert tuple(item.cid for item in frame.captured_coordinates) == tuple(
        item.cid for item in coordinates
    )


def test_a_nonlocal_closure_carries_no_cells() -> None:
    source = (
        "def f():\n"
        "    y = 1\n"
        "    def g():\n"
        "        nonlocal y\n"
        "        y = 3\n"
        "        return y\n"
        "    return g()\n"
    )
    ret = _function(source).substitute({}).body[-1]
    assert isinstance(ret.value, Call)
    assert not getattr(ret.value, "closure_cells", ())


def test_a_nested_call_reads_the_binding_at_the_call(tmp_path: Path) -> None:
    returned = _returned(_outcome(tmp_path, NESTED, "nested"))
    assert TWO in returned, returned
    assert ONE not in returned, returned


# ---------------------------------------------------------------------------
# The object a name denotes.
# ---------------------------------------------------------------------------


def test_a_store_through_one_name_reaches_the_name_given_the_same_object() -> None:
    body = _function(ALIASED_LIST).substitute({}).body
    ret = body[-1]
    assert isinstance(ret, Return)
    # ``a`` was given ``r``'s list; ``r.append(1)`` rebinds both to the list
    # after the append, so ``a`` is never read as the list before it.
    assert not isinstance(ret.value, EvaluationRef)
    assert ret.value.kind == "BuiltinContainerProjection"
