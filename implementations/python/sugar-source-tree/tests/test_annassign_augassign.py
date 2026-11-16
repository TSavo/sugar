"""AnnAssign (`x: T = v` / bare `x: T`) and AugAssign (`x OP= e`) -- both are
INERT at the meaning layer for a plain Name target, because their binding (if
any) already threaded via substitute/substitution_binding before sugar runs;
an annotation states nothing at runtime either way. An attribute augmented
target is the one field store of the field's in-place result, a subscript one
the container-mutation door's read-modify-store; a valued annotation of an
attribute/subscript target is the plain store ``Assign`` (#7757), followed in
a module body by the annotation's evaluation; a bare attribute annotation
evaluates its receiver, and in a module body then its annotation; other bare
non-Name annotations remain loud gaps."""

import tempfile

import pytest

from sugar_lift_python_source.source_oracle import path_source
from sugar_lift_py_tests.effect import SubscriptStoreRuntimeEffect
from sugar_lift_py_tests.outcome import ExitSet
from sugar_lift_py_tests.sugar.expr_statement_sugar import ExprStatementSugar
from sugar_lift_py_tests.sugar.binop_sugar import BinOpSugar
from sugar_lift_py_tests.sugar.builtin_container_call_sugar import (
    ContainerMutationStatementSugar,
    PathContainerCallSugar,
)
from sugar_lift_py_tests.sugar.assign_sugar import KeyedStoreSugar
from sugar_lift_py_tests.sugar.augassign_sugar import AttributeAugAssignSugar
from sugar_lift_py_tests.sugar.receiver_field_store_sugar import (
    ReceiverFieldStoreSugar,
)
from sugar_source_tree.panic import SugarNotWritten
from sugar_lift_py_tests.context_manager_resolution import TreeConstructionContextV1
from sugar_source_tree.tree import SourceFile


def _write(src):
    with tempfile.NamedTemporaryFile("w", suffix=".py", delete=False, dir="/tmp") as f:
        f.write(src)
        return f.name


def _fn(src):
    return next(SourceFile(path_source(_write(src)), construction_context=TreeConstructionContextV1.for_test_without_workspace()).functions())


def test_annotated_assign_with_value_is_inert_and_threads():
    outcome = _fn("def A():\n    x: int = 5\n    return x\n").sugar().desugar()
    v = outcome.completed_value()
    assert v.invs() == ()
    assert v.post().args[1].value == 5


def test_bare_annotation_lifts_and_states_nothing():
    v = _fn("def A(z):\n    x: int\n    return z\n").sugar().desugar().completed_value()
    assert v.invs() == ()
    assert v.post().args[1].name == "z"


def test_aug_assign_rebinds_and_is_inert():
    outcome = _fn("def A():\n    t = 0\n    t += 2\n    return t\n").sugar().desugar()
    v = outcome.completed_value()
    assert v.invs() == ()
    assert v.post().args[1].value == 2


def _in_place_call(statement_sugar):
    """``x OP= e``'s in-place call: the one mutation door's statement
    (#7757), whose first evaluation is the call on ``x``'s prior read."""
    assert isinstance(statement_sugar, ContainerMutationStatementSugar)
    call = statement_sugar.evaluated[0]
    assert isinstance(call, PathContainerCallSugar)
    return call


def _is_in_place(statement) -> bool:
    return statement.kind == "ContainerMutationStatement" and isinstance(
        getattr(statement, "rebinds", None), str
    )


def test_name_augassign_constructs_inplace_owned_rebind():
    """Name OP=: project_inplace + name; not substitute-time BinOp rebind."""
    function = _fn("def arbitrary():\n    renamed = 1\n    renamed += 2\n")
    substituted = function.substitute({})
    assert _is_in_place(substituted.body[1])
    assert substituted.body[1].rebinds == "renamed"
    sugar = _in_place_call(substituted.body[1].sugar())
    assert sugar.label == "renamed"
    assert type(sugar.operator).inplace_operator == "iadd"
    from sugar_source_tree.operators import BinaryOperator

    assert sugar.operator.project_inplace.__func__ is BinaryOperator.project_inplace
    # Prior read is the assigned constant, not a BinOpSugar binding child.
    assert not isinstance(sugar.receiver, BinOpSugar)


def test_name_augassign_reads_the_guarded_join_not_a_last_writer():
    function = _fn(
        "def arbitrary(condition):\n"
        "    renamed = 1\n"
        "    if condition:\n"
        "        renamed = 2\n"
        "    renamed += 3\n"
        "    return renamed\n"
    )
    substituted = function.substitute({})
    sugar = _in_place_call(
        next(
            statement.sugar()
            for statement in substituted.body
            if _is_in_place(statement)
        )
    )
    # Prior load is the if-join (IfExpSugar), not a last-writer Constant alone.
    assert type(sugar.receiver).__name__ == "IfExpSugar"


def _red_effects(source):
    # A store partitions the block into a completed and a halted arm (stores are
    # not infallible), so a body containing one reduces to an ExitSet. These
    # assertions are about the store the COMPLETED arm records; the halt face
    # and the composition laws live in
    # sugar-lift-py-tests/tests/test_store_outcome_composition.py.
    from sugar_lift_py_tests.outcome.exit_set import sole_completed_value

    entries = sole_completed_value(_fn(source).sugar().desugar()).record.statements
    return [
        halt.effect
        for entry in entries
        if isinstance(entry, ExitSet) and entry.halts() == entry.exits
        for halt in entry.halts()
    ]


def test_attribute_aug_assign_formal_get_is_the_undecided_read():
    """Attribute OP= on formals: the get leg is the one two-faced undecided
    read (``SymbolicValue.attribute``, its halt kept), never an
    ``attribute_named`` carrier waiting on a caller's actual (#7757 audit 2
    row NEW-1).  The in-place operator over the formal ``y`` is another
    family's operation; where it still defers, its carrier discharged with
    no actual keeps every arm composed beside it (#7825)."""
    from sugar_lift_py_tests.caller_parameter_contract import (
        NativeOperationExitCarrierV1,
    )

    outcome = _fn("def A(obj, y):\n    obj.a += y\n    return y\n").sugar().desugar()
    assert getattr(getattr(outcome, "demand", None), "operator", None) != (
        "attribute_named"
    )
    if isinstance(outcome, NativeOperationExitCarrierV1):
        outcome = outcome.discharge(None, {})
    assert isinstance(outcome, ExitSet)
    assert "SymbolicValue.attribute" in [
        face.effect.producer_node_owner for face in outcome.halts()
    ]


def test_subscript_aug_assign_formal_get_is_the_undecided_read():
    """Subscript OP= on formals: the get leg ``d[k]`` is the one undecided
    read (``SymbolicValue.subscript``), never a ``subscript`` carrier waiting
    on a caller's actual (#7757, audit 2 row NEW-1, #9016).  Its value is
    keyed per evaluation, ``python:subscript_result(d, k, <key>)``, it
    completes only under its ``python:subscript_op.completes`` atom, and its
    halt is kept beside the store's undecided mutation."""
    outcome = _fn("def A(d, k, y):\n    d[k] += y\n    return y\n").sugar().desugar()
    assert isinstance(outcome, ExitSet), type(outcome)
    owners = [face.effect.producer_node_owner for face in outcome.halts()]
    assert "SymbolicValue.subscript" in owners, owners
    assert "UndecidedSetitem" in owners, owners
    text = repr(outcome)
    assert "python:subscript_result" in text
    assert "python:subscript_op.completes" in text
    assert "python:subscript.completes" not in text


def test_annotated_attribute_with_value_builds_store_effect():
    """``obj.a: int = y`` is the one attribute store
    (``store_effect_sugar.attribute_mutation``): on a receiver nothing
    decides it is the one undecided mutation (#7757 NEW-4), completing under
    its ``python:setattr`` atom and halting, undetermined, under the
    complement."""
    outcome = _fn(
        "def A(obj, y):\n    obj.a: int = y\n    return y\n"
    ).sugar().desugar()

    assert isinstance(outcome, ExitSet)
    completed = [arm for arm in outcome.exits if arm not in outcome.halts()]
    assert completed and all(
        "python:setattr.completes" in repr(arm.guard) for arm in completed
    )
    assert "UndecidedSetattr" in [
        face.effect.producer_node_owner for face in outcome.halts()
    ]


def test_annotated_subscript_store_is_the_one_item_mutation():
    """A formal's annotated subscript store is the one item mutation
    (``store_effect_sugar.item_mutation``, #7757 step 7), never a carrier
    and never a free SugarNotWritten: the dispatched ``__setitem__`` or the
    undecided mutation, its halt kept either way."""
    from sugar_lift_py_tests.caller_parameter_contract import (
        NativeOperationExitCarrierV1,
    )

    outcome = (
        _fn("def A(d, k, y):\n    d[k]: int = y\n    return y\n").sugar().desugar()
    )
    assert not isinstance(outcome, NativeOperationExitCarrierV1)
    text = repr(outcome)
    assert "UnknownCallee:dispatch:__setitem__" in text or "UndecidedSetitem" in text


_CONSTRUCTED_RECEIVER_SOURCE = (
    "class C:\n"
    "    def __init__(self, a):\n"
    "        self.a = a\n"
    "        self.rows{annotation} = []\n"
    "\n"
    "\n"
    "def make(a):\n"
    "    c = C(a)\n"
    "    return c\n"
)


def _constructed_object(annotation):
    source = _CONSTRUCTED_RECEIVER_SOURCE.format(annotation=annotation)
    function = next(
        item
        for item in SourceFile(path_source(_write(source)), construction_context=TreeConstructionContextV1.for_test_without_workspace()).functions()
        if item.name == "make"
    )
    return function.sugar().desugar().completed_value().record.statements[-1].value


def test_annotated_store_on_constructed_receiver_matches_plain_store():
    """`self.rows: list = []` is the SAME store as `self.rows = []`.

    The annotation states nothing at runtime, so it may not demote a
    constructed-receiver field store to an opaque runtime store effect. Before
    this parity the annotated arm partitioned the constructor body into a
    halted store arm, and ClassConstructorBodySugar could not project one
    completed floor value out of the resulting ExitSet.
    """
    plain = _constructed_object("")
    annotated = _constructed_object(": list")

    # Field coordinates carry each fixture's own source cid, so the parity
    # claim is the constructed SHAPE: same fields, same constructed value kinds.
    assert [field.name for field in plain.fields] == ["a", "rows"]
    assert [field.name for field in annotated.fields] == ["a", "rows"]
    assert [type(field.value).__name__ for field in annotated.fields] == [
        type(field.value).__name__ for field in plain.fields
    ]


def test_bare_attribute_annotation_evaluates_only_renamed_receiver():
    function = _fn(
        "def record_shape(receiver):\n"
        "    receiver.payload: MissingType\n"
        "    return receiver\n"
    )
    substituted = function.substitute({})
    declaration = substituted.body[0]
    sugar = declaration.sugar()
    assert isinstance(sugar, ExprStatementSugar)
    assert sugar.value == declaration.target.value.sugar()

    value = function.sugar().desugar().completed_value()
    assert value.post().args[1].name == "receiver"


def test_valued_attribute_annotation_does_not_enter_bare_declaration_arm():
    function = _fn(
        "def record_shape(receiver, supplied):\n"
        "    receiver.payload: MissingType = supplied\n"
        "    return supplied\n"
    ).substitute({})
    sugar = function.body[0].sugar()
    # The one field store, keyed, whatever the receiver is.
    assert isinstance(sugar, KeyedStoreSugar)
    assert isinstance(sugar.store, ReceiverFieldStoreSugar)
    assert not isinstance(sugar, ExprStatementSugar)


def test_attribute_aug_assign_is_the_one_field_store():
    """``o.x += v`` is the one field store of the field's in-place result
    (#7757): the same statement ``o.x = v`` makes, its receiver evaluated
    once, first, and bound under its key."""
    body = _fn("def A(o, v):\n    o.x += v\n    return o\n").substitute({}).body
    store = body[0]
    assert store.kind == "ReceiverFieldStoreStatement"
    assert store.read_modifies()
    assert store.receiver_value is not None
    plain = _fn("def A(o, v):\n    o.x = v\n    return o\n").substitute({}).body
    assert plain[0].kind == store.kind
    assert not plain[0].read_modifies()
    sugar = store.sugar()
    assert isinstance(sugar, KeyedStoreSugar)
    assert isinstance(sugar.value, AttributeAugAssignSugar)
    assert isinstance(sugar.store, ReceiverFieldStoreSugar)
    assert sugar.receiver_evaluation == store.receiver_evaluation
    # Every later read of ``o`` reads the post-state over the receiver's key.
    returned = body[-1].value
    assert returned.kind == "ReceiverFieldStoreState"
    assert returned.receiver.kind == "EvaluationRef"
    assert returned.receiver.evaluation == store.receiver_evaluation


def _outcome_shape(outcome):
    """What an outcome is, without the source coordinates two spellings of
    one store cannot share: its kind, the operation a carrier demands, and
    the kind of each exit."""
    demand = getattr(outcome, "demand", None)
    exits = getattr(outcome, "exits", ())
    return (
        type(outcome).__name__,
        getattr(demand, "operator", None),
        tuple(type(exit_).__name__ for exit_ in exits),
    )


@pytest.mark.parametrize(
    ("annotated", "plain"),
    [
        (
            "def A(o, k, v):\n    o[k]: int = v\n    return v\n",
            "def A(o, k, v):\n    o[k] = v\n    return v\n",
        ),
        (
            "def A(o, v):\n    o.f: int = v\n    return v\n",
            "def A(o, v):\n    o.f = v\n    return v\n",
        ),
        (
            "def A(v):\n    o = {}\n    o['k']: int = v\n    return o\n",
            "def A(v):\n    o = {}\n    o['k'] = v\n    return o\n",
        ),
    ],
    ids=["item-on-formal", "field-on-formal", "item-on-local-dict"],
)
def test_annotated_store_is_the_assign_store(annotated, plain):
    """``o[k]: int = v`` / ``o.f: int = v`` is the store ``o[k] = v`` /
    ``o.f = v`` (#7757): substitution makes it that statement, through the
    one door each store target takes, so the two spellings give the same
    statements, the same sugar and the same outcome."""
    annotated_body = _fn(annotated).substitute({}).body
    plain_body = _fn(plain).substitute({}).body
    assert not any(statement.kind == "AnnAssign" for statement in annotated_body)
    assert [statement.kind for statement in annotated_body] == [
        statement.kind for statement in plain_body
    ]
    assert [type(sugar).__name__ for sugar in _fn(annotated).sugar().statements] == [
        type(sugar).__name__ for sugar in _fn(plain).sugar().statements
    ]
    assert _outcome_shape(_fn(annotated).sugar().desugar()) == _outcome_shape(
        _fn(plain).sugar().desugar()
    )


def _module(src):
    return SourceFile(
        path_source(_write(src)),
        construction_context=TreeConstructionContextV1.for_test_without_workspace(),
    ).root


_MODULE_PRELUDE = "d = {}\nclass C:\n    pass\no = C()\n"


@pytest.mark.parametrize(
    ("annotated", "plain"),
    [
        ("d['k']: int = 1\n", "d['k'] = 1\n"),
        ("o.f: int = 1\n", "o.f = 1\n"),
    ],
    ids=["item", "field"],
)
def test_module_annotated_store_evaluates_its_annotation_after_the_store(
    annotated, plain
):
    """In a module body Python evaluates a non-simple target's annotation
    after the store, and discards it (#7757): the statement is the store
    ``<target> = <value>``, then the annotation as an expression statement,
    spliced into the module block.  The annotation may run code; it is
    evaluated, never stored."""
    annotated_body = _module(_MODULE_PRELUDE + annotated).substitute({}).body
    plain_body = _module(_MODULE_PRELUDE + plain).substitute({}).body
    assert not any(statement.kind == "AnnAssign" for statement in annotated_body)
    assert len(annotated_body) == len(plain_body) + 1
    # The store first, the same statement the plain spelling makes ...
    assert annotated_body[-2].kind == plain_body[-1].kind
    # ... then the annotation, evaluated as an expression.
    evaluated = annotated_body[-1]
    assert evaluated.kind == "Expr"
    assert evaluated.value.kind == "Name"
    assert evaluated.value.id == "int"


def test_module_annotated_store_under_postponed_annotations_is_the_store():
    """``from __future__ import annotations`` postpones every annotation:
    the module-body annotated store is the store alone, as in a function."""
    future = "from __future__ import annotations\n"
    annotated_body = _module(future + "d = {}\nd['k']: int = 1\n").substitute({}).body
    plain_body = _module(future + "d = {}\nd['k'] = 1\n").substitute({}).body
    assert [statement.kind for statement in annotated_body] == [
        statement.kind for statement in plain_body
    ]


def test_module_annotated_store_never_substituted_refuses_by_name():
    """Only the module block's substitution splices the store and the
    annotation's evaluation; never substituted, the statement refuses by
    name rather than drop the annotation's evaluation."""
    statement = _module("d = {}\nd['k']: int = 1\n").body[-1]
    assert statement.kind == "AnnAssign"
    with pytest.raises(SugarNotWritten) as refused:
        statement.sugar()
    assert refused.value.owner == "AnnAssign._construct_sugar"


def test_module_bare_attribute_annotation_evaluates_its_annotation():
    """``o.f: T`` in a module body: Python evaluates the receiver, then the
    annotation, and stores nothing (#7757).  The statement is the receiver's
    evaluation, then the annotation as an expression statement."""
    body = _module(_MODULE_PRELUDE + "o.f: int\n").substitute({}).body
    receiver, evaluated = body[-2], body[-1]
    assert receiver.kind == "AnnAssign"
    assert receiver.value is None
    assert isinstance(receiver.sugar(), ExprStatementSugar)
    assert evaluated.kind == "Expr"
    assert evaluated.value.kind == "Name"
    assert evaluated.value.id == "int"


def test_module_bare_attribute_annotation_under_postponed_annotations():
    """``from __future__ import annotations``: the receiver only."""
    future = "from __future__ import annotations\n"
    body = _module(future + _MODULE_PRELUDE + "o.f: int\n").substitute({}).body
    assert body[-1].kind == "AnnAssign"
    assert not any(
        statement.kind == "Expr"
        and statement.value.kind == "Name"
        and statement.value.id == "int"
        for statement in body
    )


def test_module_bare_attribute_annotation_never_substituted_refuses_by_name():
    statement = _module(_MODULE_PRELUDE + "o.f: int\n").body[-1]
    assert statement.kind == "AnnAssign"
    with pytest.raises(SugarNotWritten) as refused:
        statement.sugar()
    assert refused.value.owner == "AnnAssign._construct_sugar"


def test_module_annotated_name_evaluates_its_annotation_after_the_store():
    """``x: T = v`` and ``x: T`` in a module body: Python stores the value
    (if any), then evaluates the annotation (#7757).  The statement is the
    assignment (or nothing, bare), then the annotation as an expression
    statement, spliced into the module block."""
    body = _module("x: int = 1\ny: int\n").substitute({}).body
    assert [statement.kind for statement in body] == [
        "AnnAssign",
        "Expr",
        "AnnAssign",
        "Expr",
    ]
    assert all(body[index].value.id == "int" for index in (1, 3))


def test_module_annotated_name_under_postponed_annotations_is_the_assignment():
    future = "from __future__ import annotations\n"
    body = _module(future + "x: int = 1\n").substitute({}).body
    assert [statement.kind for statement in body] == ["ImportFrom", "AnnAssign"]


def test_module_annotated_name_never_substituted_refuses_by_name():
    statement = _module("x: int = 1\n").body[-1]
    assert statement.kind == "AnnAssign"
    with pytest.raises(SugarNotWritten) as refused:
        statement.sugar()
    assert refused.value.owner == "AnnAssign._construct_sugar"


def test_bare_annotated_store_target_stores_nothing():
    """``o[k]: int`` with no value stores nothing: it never becomes a
    store."""
    function = _fn("def A(o, k):\n    o[k]: int\n    return k\n").substitute({})
    assert function.body[0].kind == "AnnAssign"


def test_aug_assign_with_no_prior_binding_is_sound():
    # x += 1 as the FIRST statement: substitution_binding cannot see a prior
    # x in scope, so it falls back to the target itself as the "old" value
    # (scope.get(name, self.target)) -- the binding still threads, just with
    # x left free/symbolic. Not a panic and not a silent drop.
    function = _fn("def A(x):\n    x += 1\n    return x\n")
    sugar = function.sugar()
    outcome = sugar.desugar()
    # The ``+=`` on the formal waits on no caller (#7757, audit row NEW-1):
    # the undecided binary law's two faces, never a carrier, a construction
    # panic or a silent drop of the binding.
    assert type(outcome).__name__ == "ExitSet"
    assert outcome.halts(), outcome
    assert outcome.completed_value() is None
    # The in-place statement is present — the binding was not dropped.
    assert any(
        isinstance(s, ContainerMutationStatementSugar)
        and s.result_evaluations
        for s in sugar.statements
    )


def test_discrimination_annassign_value_changes_the_post():
    a_outcome = _fn("def A():\n    x: int = 5\n    return x\n").sugar().desugar()
    b_outcome = _fn("def A():\n    x: int = 6\n    return x\n").sugar().desugar()
    a = a_outcome.completed_value().post()
    b = b_outcome.completed_value().post()
    assert a.args[1].value == 5
    assert b.args[1].value == 6
    assert a.args[1].value != b.args[1].value


if __name__ == "__main__":
    test_annotated_assign_with_value_is_inert_and_threads()
    test_bare_annotation_lifts_and_states_nothing()
    test_aug_assign_rebinds_and_is_inert()
    test_annotated_attribute_with_value_builds_store_effect()
    test_aug_assign_with_no_prior_binding_is_sound()
    test_discrimination_annassign_value_changes_the_post()
    print("ok: AnnAssign/AugAssign target roles build or stay loud by shape")
