"""The member a read of a class's name meets is the one resolution
(#7757, leftovers of #8155 and #8156).

1. Every reader of an instance's class member -- the attribute read, the
   explicit call ``o.m()``, an implicit special-method call -- reads the one
   class-namespace lookup once (``ObjectValue.class_member``) and carries the
   member it selected; the call binds that member, never one selected again
   by name.
2. The member is the binding the class body left last (``ClassDef.body_binder``):
   a ``def`` after a ``property`` of the same name, an assignment after a
   ``def``, a ``def`` after an assignment.
3. A function the class namespace holds as a field (``f = lambda self: 1``,
   ``m = some_def``), read off an instance, is a method bound to it.
4. The ``__new__`` a class call runs is read through the one lookup, with
   the MRO (``ClassDef.new_entry``).
5. ``delattr`` and the deferred-helper rebuild keep the receiver's class.
6. Stores through a parameter, ``exec``, an alias bound in a module compound
   statement and a tuple unpack are stores on the class.
"""

from __future__ import annotations

from sugar_lift_py_tests.callable_application import CallableApplication
from sugar_lift_py_tests.context_manager_resolution import (
    SourceFragmentCoordinateV1,
    TreeConstructionContextV1,
)
from sugar_lift_py_tests.floor import (
    LambdaCallable,
    MappingObjectValue,
    ObjectField,
    TermValue,
)
from sugar_lift_py_tests.floor.bound_method_value import BoundMethodValue
from sugar_lift_py_tests.floor.class_definition_value import ClassDefinitionValue
from sugar_lift_py_tests.floor.object_value import ObjectValue
from sugar_lift_py_tests.outcome import Halted
from sugar_lift_python_source.canonical import blake3_512_of
from sugar_source_tree.nodes import ClassDef, FunctionDef, SourceUnit
from sugar_source_tree.tree import SourceFile

from frame_fresh import FRAME_FRESH


def _tree(source: str, name: str) -> SourceFile:
    return SourceFile(
        (source, name, blake3_512_of(source.encode())),
        construction_context=TreeConstructionContextV1.for_test_without_workspace(),
    )


def _classes(source: str, name: str = "one_resolution.py") -> dict:
    """Every module ``class`` statement of ``source``, by name."""
    tree = _tree(source, name)
    return {node.name: node for node in tree.root.body if isinstance(node, ClassDef)}


def _built(source: str):
    """The class value the one ``class`` statement of ``source`` builds, a
    receiver its call made in the reading frame, and the context."""
    from sugar_lift_py_tests.context.reduce_context import ReduceContext

    tree = _tree(source, "one_resolution_built.py")
    (class_def,) = tuple(node for node in tree.nodes() if isinstance(node, ClassDef))
    ctx = ReduceContext.root(owner="test")
    value = class_def.sugar().desugar(ctx).completed_value()
    return value, value.fresh_receiver("receiver-cid", allocation=FRAME_FRESH), ctx


def _bare_class_value(statement: ClassDef, class_fields=()) -> ClassDefinitionValue:
    """A class value built from ``statement`` alone, with ``class_fields``."""
    span = statement.binding_target.line_col_span()
    return ClassDefinitionValue(
        class_name=statement.name,
        class_definition_cid=statement.fragment.seal().cid,
        methods=(),
        initializer=None,
        binding_target_occurrence=SourceFragmentCoordinateV1(
            statement.unit.source_cid,
            span.start_line,
            span.start_col,
            span.end_line,
            span.end_col,
        ),
        class_fields=tuple(class_fields),
        class_definition=statement,
    )


def _halt_names(outcome) -> list:
    return [
        face.effect.exception_name
        for face in getattr(outcome, "exits", ())
        if isinstance(face, Halted)
    ]


def _call(value, arguments, site, ctx):
    return value.callable_application_with(
        CallableApplication(tuple(arguments), (), site, owner="test"), ctx
    )


def _the_edge(outcome) -> None:
    """The call of the member the lookup selected is its coordinate and edge
    (#7757 step 6, #8738): one completion under the unanswered call's
    ``completes`` atom, whose value is the call with no body applied, and one
    halt no exception names here.  What the member's body raises is its
    contract's halt, joined at prove; before step 6 the body was applied here
    and its own exception named (the member selection itself is asserted on
    ``read.member`` and ``class_member``)."""
    from sugar_lift_py_tests.floor import CallSiteValue
    from sugar_lift_py_tests.outcome import Completed

    assert _halt_names(outcome) == [None]
    (completed,) = (face for face in outcome.exits if isinstance(face, Completed))
    assert "python:unknown_callee_call.completes" in repr(completed.guard)
    assert isinstance(completed.value, CallSiteValue)
    assert completed.value.body is None


# --- 1 and 2. one resolution, the last binding ------------------------------------


def test_a_def_after_a_property_is_the_member_every_reader_meets() -> None:
    _value, receiver, ctx = _built(
        "class Box:\n"
        "    @property\n"
        "    def m(self):\n"
        "        return 3\n"
        "    def m(self):\n"
        "        raise ValueError('the def')\n"
    )

    decided, method, value = receiver.class_member("m")
    assert decided and value is None
    assert method is not None and method.descriptor_kind is None

    # The read is the plain def bound to the receiver, never the property's
    # getter run at the read.
    read = receiver.attribute("m", "m-site", ctx).completed_value()
    assert isinstance(read, BoundMethodValue)
    assert read.member is method
    _the_edge(_call(read, (), "m-site", ctx))

    # The class-side call (an implicit special-method call's door) reads the
    # same member: the edge, never the property's getter run at the read.
    outcome = receiver.call_method_value(
        "m", (), owner="test", blame="call-site", ctx=ctx
    )
    _the_edge(outcome)


def test_an_assignment_after_a_def_is_the_member() -> None:
    _value, receiver, ctx = _built(
        "class Box:\n"
        "    def m(self):\n"
        "        raise ValueError('the def')\n"
        "    m = 5\n"
    )

    assert receiver.class_member("m") == (True, None, TermValue(5))
    assert receiver.attribute("m", "m-site", ctx).completed_value() == TermValue(5)


def test_a_def_after_an_assignment_is_the_member() -> None:
    _value, receiver, ctx = _built(
        "class Box:\n"
        "    m = 5\n"
        "    def m(self):\n"
        "        raise ValueError('the def')\n"
    )

    decided, method, value = receiver.class_member("m")
    assert decided and value is None and method is not None
    read = receiver.attribute("m", "m-site", ctx).completed_value()
    assert isinstance(read, BoundMethodValue) and read.member is method
    _the_edge(_call(read, (), "m-site", ctx))


# --- 3. a function in the class namespace, read off an instance ------------------


def test_a_lambda_class_field_read_off_an_instance_binds_self() -> None:
    _value, receiver, ctx = _built("class Box:\n    f = lambda self, n: n // 0\n")

    read = receiver.attribute("f", "f-site", ctx).completed_value()
    assert isinstance(read, BoundMethodValue)
    assert isinstance(read.member, LambdaCallable)
    assert read.receiver is receiver
    # ``self`` is bound to the receiver, so the one written actual is ``n``;
    # the lambda's call is its coordinate and edge (#7757 step 5, #8705), its
    # ``ZeroDivisionError`` the lambda's contract's halt, joined at prove.
    _the_edge(_call(read, (TermValue(3),), "f-site", ctx))


def test_a_def_held_as_a_class_field_read_off_an_instance_is_bound() -> None:
    box = _classes("def helper(self):\n    return 7\n\nclass Box:\n    m = helper\n")[
        "Box"
    ]
    # The function a ``def`` builds is a ``LambdaCallable``
    # (``decorator_application_sugar._function_value``).
    function = LambdaCallable(("self",), None, "helper")
    receiver = ObjectValue(
        "Box",
        (),
        identity="receiver",
        defining_class=_bare_class_value(box, (ObjectField("m", function),)),
        allocation=FRAME_FRESH,
    )

    assert receiver.class_member("m") == (True, None, function)
    read = receiver.attribute("m", "m-site", None).completed_value()
    assert isinstance(read, BoundMethodValue)
    assert read.member is function and read.receiver is receiver


# --- 4. __new__ through the one lookup ------------------------------------------


_NEW = (
    "class Base:\n"
    "    def __init__(self):\n"
    "        self.k = 1\n"
    "\n"
    "class Own:\n"
    "    def __new__(cls, value):\n"
    "        self = super(Own, cls).__new__(cls)\n"
    "        self.value = value\n"
    "        return self\n"
    "\n"
    "class Heir(Own):\n"
    "    pass\n"
    "\n"
    "class Inited(Base):\n"
    "    def __new__(cls, value):\n"
    "        self = super(Inited, cls).__new__(cls)\n"
    "        self.value = value\n"
    "        return self\n"
    "\n"
    "class Stored:\n"
    "    pass\n"
    "\n"
    "def make(cls):\n"
    "    return object.__new__(cls)\n"
    "\n"
    "Stored.__new__ = make\n"
)


def test_new_is_read_through_the_one_lookup() -> None:
    classes = _classes(_NEW)

    decided, own = classes["Own"].new_entry()
    assert decided and isinstance(own, FunctionDef) and own.name == "__new__"
    assert classes["Own"]._authenticated_new_constructor_shape() is not None
    # ``object.__new__`` runs: no source ``__new__``.
    assert classes["Base"].new_entry() == (True, None)


def test_an_inherited_new_is_never_skipped() -> None:
    classes = _classes(_NEW)

    # Heir's call runs Own's ``__new__``: its frame cannot seat a base's, so
    # the call is the unanswered call, never a frame that skips it.
    assert classes["Heir"].new_entry() == (False, None)
    assert not SourceUnit.source_class_admits_source_constructor_frame(
        classes["Heir"]
    )


def test_a_stored_new_is_undecided() -> None:
    classes = _classes(_NEW)

    assert classes["Stored"].new_entry() == (False, None)
    assert classes["Stored"]._authenticated_new_constructor_shape() is None
    assert not SourceUnit.source_class_admits_source_constructor_frame(
        classes["Stored"]
    )


def test_a_new_shape_whose_call_runs_a_source_init_is_not_the_shape() -> None:
    # Base's ``__init__`` runs on what ``__new__`` returns: the shape does
    # not read it.
    assert _classes(_NEW)["Inited"]._authenticated_new_constructor_shape() is None


# --- 5. the receiver keeps its class ----------------------------------------------


def test_delattr_and_the_helper_rebuild_keep_the_class() -> None:
    box = _bare_class_value(_classes("class Box:\n    pass\n")["Box"])
    receiver = ObjectValue(
        "Box",
        (ObjectField("x", TermValue(1)),),
        identity="receiver",
        defining_class=box,
        allocation=FRAME_FRESH,
    )

    after = receiver.delattr("x", "del-site", None).completed_value()
    assert after.defining_class is box
    assert after.fields == () and "x" in after.deleted_instance_fields
    assert after.allocation is receiver.allocation

    assert receiver.with_deferred_helper_fields().defining_class is box


def _delete_site():
    """The fragment of a real ``del o.__class__`` statement: a ground exit
    cites source it can re-read (``ground_exit.ground_raise_effect``), never
    a prose locus."""
    tree = _tree("def f(o):\n    del o.__class__\n", "delete_class.py")
    return next(tree.functions()).body[0].fragment


def test_deleting_the_class_is_the_type_error_halt() -> None:
    """``del o.__class__`` is ``object.__class__``'s setter with no value
    (``object_set_class``): ``TypeError``, never the instance-field delete
    and never ``AttributeError`` (#7757, surfaced in #8803).  The halt is a
    ground exit, which cites the statement's fragment."""
    box = _bare_class_value(_classes("class Box:\n    pass\n")["Box"])
    receiver = ObjectValue(
        "Box",
        (ObjectField("x", TermValue(1)),),
        identity="receiver",
        defining_class=box,
        allocation=FRAME_FRESH,
    )

    outcome = receiver.delattr("__class__", _delete_site(), None)
    assert _halt_names(outcome) == ["TypeError"]
    assert len(outcome.exits) == 1


def test_a_receiver_with_no_class_statement_stores_and_deletes_its_class_by_the_owed_call() -> (
    None
):
    """A receiver built with no class statement has no lookup of its
    type's MRO: ``object.__class__`` (or a class between that overrides it)
    answers ``o.__class__ = C`` and ``del o.__class__``, never the instance
    field.  The store is the owed ``type(o).__setattr__`` call
    (``field_store_route`` undecided: it runs code, so the object after it
    has arrived and no method call on it is dispatched); the delete is the
    owed ``type(o).__delattr__`` call, two faces, never the certain
    ``TypeError`` that only a decided lookup gives (#7757, surfaced in
    #8817)."""
    receiver = ObjectValue(
        "Box",
        (ObjectField("x", TermValue(1)),),
        identity="receiver",
        allocation=FRAME_FRESH,
    )

    assert receiver.field_store_route("__class__") == ("undecided", None)
    assert receiver.field_store_runs_code("__class__")
    # Any other name stays the instance-field store.
    assert receiver.field_store_route("x") == ("plain", None)

    outcome = receiver.delattr("__class__", "del-site", None)
    halted = [face for face in outcome.exits if isinstance(face, Halted)]
    completed = [face for face in outcome.exits if not isinstance(face, Halted)]
    assert len(halted) == 1 and len(completed) == 1
    assert getattr(halted[0].effect, "exception_name", None) != "TypeError"


def test_delattr_keeps_a_mapping_receiver_a_mapping() -> None:
    box = _bare_class_value(_classes("class Box(dict):\n    pass\n")["Box"])
    receiver = MappingObjectValue(
        "Box",
        (ObjectField("x", TermValue(1)),),
        identity="receiver",
        defining_class=box,
        allocation=FRAME_FRESH,
        entries=((TermValue(1), TermValue(2)),),
    )

    after = receiver.delattr("x", "del-site", None).completed_value()
    assert type(after) is MappingObjectValue
    assert after.entries == receiver.entries
    assert after.defining_class is box


# --- 6. stores through other references -------------------------------------------


def test_a_store_through_a_parameter_reaches_every_class_handed_to_one() -> None:
    classes = _classes(
        "class A:\n"
        "    pass\n"
        "\n"
        "class Kept:\n"
        "    pass\n"
        "\n"
        "def patch(K):\n"
        "    K.x = 1\n"
        "\n"
        "patch(A)\n"
        "Kept()\n"
    )

    assert classes["A"].namespace_binds("x") is None
    # A class only called, never handed on, is no parameter's.
    assert classes["Kept"].namespace_binds("x") is False


def test_exec_may_store_any_name_on_any_class() -> None:
    classes = _classes(
        "class A:\n"
        "    def m(self):\n"
        "        return 1\n"
        "\n"
        "exec('A.m = None')\n"
    )

    assert classes["A"].namespace_binds("m") is None
    assert classes["A"].namespace_binds("anything") is None


def test_an_alias_bound_in_a_module_compound_statement_is_the_class() -> None:
    classes = _classes(
        "flag = input()\n"
        "\n"
        "class A:\n"
        "    pass\n"
        "\n"
        "class Other:\n"
        "    pass\n"
        "\n"
        "if flag:\n"
        "    K = A\n"
        "K.z = 1\n"
    )

    assert classes["A"].namespace_binds("z") is None
    assert classes["Other"].namespace_binds("z") is False


def test_a_tuple_unpack_alias_is_the_class() -> None:
    classes = _classes(
        "class A:\n"
        "    pass\n"
        "\n"
        "class B:\n"
        "    pass\n"
        "\n"
        "class Other:\n"
        "    pass\n"
        "\n"
        "K, _ = A, 0\n"
        "K.w = 1\n"
        "\n"
        "pair = (B, 0)\n"
        "J, _ = pair\n"
        "J.v = 1\n"
    )

    assert classes["A"].namespace_binds("w") is None
    # ``J`` may be any class the module handed on: B, a member of ``pair``.
    assert classes["B"].namespace_binds("v") is None
    assert classes["Other"].namespace_binds("w") is False
    assert classes["Other"].namespace_binds("v") is False
