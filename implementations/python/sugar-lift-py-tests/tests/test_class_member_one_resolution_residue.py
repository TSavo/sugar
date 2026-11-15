"""The residue of the one class-member resolution (#7757, residue of #8163).

1. ``Cls.m`` (``ClassDefinitionValue.call_method_value``) and ``super().m``
   (``BuiltinSuperValue``) read the one resolution
   (``ClassDefinitionValue.namespace_member``: ``namespace_owner``, then the
   binding the holding class's body left last), never a method of the roster
   found by its name.  A function class field is unbound read off its class
   and bound to the receiver through ``super()``.
2. A store through any name whose value may be a class -- a call's result, a
   ``for``/``with`` target, a lambda's or a comprehension's own variable --
   makes the name undecided on every class the module hands on.
3. The dataclass call asks the one ``__new__`` lookup
   (``ClassDef.dataclass_new_entry``): a ``__new__`` that is not a builtin's
   is never skipped.
"""

from __future__ import annotations

import pytest

from frame_fresh import FRAME_FRESH
from sugar_lift_py_tests.callable_application import CallableApplication
from sugar_lift_py_tests.context import ReduceContext
from sugar_lift_py_tests.context_manager_resolution import (
    SourceFragmentCoordinateV1,
    TreeConstructionContextV1,
)
from sugar_lift_py_tests.effect.raise_effect import UndeterminedRaiseEffect
from sugar_lift_py_tests.floor import BuiltinSuperValue, TermValue
from sugar_lift_py_tests.floor.class_definition_value import ClassDefinitionValue
from sugar_lift_py_tests.outcome import Halted
from sugar_lift_python_source.canonical import blake3_512_of
from sugar_source_tree.nodes import ClassDef, FunctionDef
from sugar_source_tree.panic import SugarNotWritten
from sugar_source_tree.tree import SourceFile


def _tree(source: str, name: str) -> SourceFile:
    return SourceFile(
        (source, name, blake3_512_of(source.encode())),
        construction_context=TreeConstructionContextV1.for_test_without_workspace(),
    )


def _statements(source: str, name: str = "residue.py") -> dict:
    """Every module ``class`` statement of ``source``, by name."""
    tree = _tree(source, name)
    return {node.name: node for node in tree.root.body if isinstance(node, ClassDef)}


def _values(source: str, name: str = "residue_values.py"):
    """The context and the class value each module ``class`` statement of
    ``source`` builds, each bound for the next to read as a base."""
    tree = _tree(source, name)
    context = ReduceContext.root(owner="test")
    values = {}
    for node in tree.root.body:
        if not isinstance(node, ClassDef):
            continue
        value = node.sugar().desugar(context).completed_value()
        context.temporal = context.temporal.bind_value(value.class_name, value)
        values[value.class_name] = value
    return context, values


def _bare_class_value(statement: ClassDef) -> ClassDefinitionValue:
    """A class value built from ``statement`` alone."""
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
        class_definition=statement,
    )


def _halt_names(outcome) -> list:
    return [
        face.effect.exception_name
        for face in getattr(outcome, "exits", ())
        if isinstance(face, Halted)
    ]


def _the_edge(outcome) -> None:
    """The call of the member the one resolution selected is its coordinate
    and edge (#7757 steps 5 and 6, #8705, #8738): one completion under the
    unanswered call's ``completes`` atom, whose value is the call with no body
    applied, and one halt no exception names here.  What the member's body
    raises is its contract's halt, joined at prove; before steps 5 and 6 the
    body was applied here and its own exception named."""
    from sugar_lift_py_tests.floor import CallSiteValue
    from sugar_lift_py_tests.outcome import Completed

    assert _halt_names(outcome) == [None]
    (completed,) = (face for face in outcome.exits if isinstance(face, Completed))
    assert "python:unknown_callee_call.completes" in repr(completed.guard)
    assert isinstance(completed.value, CallSiteValue)
    assert completed.value.body is None


def _unanswered(outcome, target: str) -> None:
    (halt,) = outcome.halts()
    assert isinstance(halt.effect, UndeterminedRaiseEffect)
    assert halt.effect.producer_node_owner == f"UnknownCallee:{target}"
    assert outcome.owed_items()


# --- 1. Cls.m and super().m read the one resolution ---------------------------


def test_cls_m_is_the_def_after_a_property_never_a_count_of_names() -> None:
    context, classes = _values(
        "class Box:\n"
        "    @property\n"
        "    def m(self):\n"
        "        return 3\n"
        "    def m(self):\n"
        "        raise ValueError('the def')\n"
    )
    box = classes["Box"]
    receiver = box.fresh_receiver("receiver", allocation=FRAME_FRESH)

    # Two roster functions are named ``m``; the body's last binding is the
    # member, read off the class unbound: the receiver is written.  Its call
    # is the edge; ``raise ValueError`` is the def's contract, joined at prove.
    outcome = box.call_method_value(
        "m", (receiver,), owner="test", blame="cls-m", ctx=context
    )

    _the_edge(outcome)


def test_cls_m_of_a_lambda_class_field_is_the_function_unbound() -> None:
    context, classes = _values("class Box:\n    f = lambda n: n // 0\n")

    outcome = classes["Box"].call_method_value(
        "f", (TermValue(3),), owner="test", blame="cls-f", ctx=context
    )

    # No receiver is bound: the one written actual is ``n``.  The lambda's
    # call is the edge; its ``ZeroDivisionError`` is joined at prove.
    _the_edge(outcome)


def test_cls_m_after_an_assignment_never_runs_the_earlier_def() -> None:
    context, classes = _values(
        "class Box:\n"
        "    def m(self):\n"
        "        raise ValueError('the def')\n"
        "    m = 5\n"
    )
    box = classes["Box"]
    receiver = box.fresh_receiver("receiver", allocation=FRAME_FRESH)

    # ``Box.m`` is ``5``: not callable here, refused by name -- never the
    # roster's ``def`` of the same name.
    with pytest.raises(SugarNotWritten):
        box.call_method_value(
            "m", (receiver,), owner="test", blame="cls-m", ctx=context
        )


def test_super_m_is_the_last_binding_a_lambda_bound_to_the_receiver() -> None:
    context, classes = _values(
        "class Base:\n"
        "    def m(self):\n"
        "        raise ValueError('the def')\n"
        "    m = lambda self, n: n // 0\n"
        "\n"
        "class A(Base):\n"
        "    pass\n"
    )
    receiver = classes["A"].fresh_receiver("receiver", allocation=FRAME_FRESH)

    outcome = BuiltinSuperValue(classes["A"], receiver).call_method_value(
        "m", (TermValue(3),), owner="test", blame="super-m", ctx=context
    )

    # Base's namespace holds the lambda, bound to the receiver: ``n`` is 3.
    # The lambda's call is the edge; its ``ZeroDivisionError`` is joined at
    # prove, never the earlier ``def``'s ``ValueError``.
    _the_edge(outcome)


def test_super_m_of_a_rewritten_def_is_the_unanswered_call() -> None:
    context, classes = _values(
        "import functools\n"
        "\n"
        "class Base:\n"
        "    @functools.cache\n"
        "    def m(self):\n"
        "        raise ValueError('the body')\n"
        "\n"
        "class A(Base):\n"
        "    pass\n"
    )
    receiver = classes["A"].fresh_receiver("receiver", allocation=FRAME_FRESH)

    # Base holds the decorator's result, not the function its body wrote.
    _unanswered(
        BuiltinSuperValue(classes["A"], receiver).call_method_value(
            "m", (), owner="test", blame="super-m", ctx=context
        ),
        "super.m",
    )


# --- 2. stores through every name whose value may be a class -------------------


def test_a_store_through_a_calls_result_reaches_every_class_handed_on() -> None:
    classes = _statements(
        "class A:\n"
        "    pass\n"
        "\n"
        "class Other:\n"
        "    pass\n"
        "\n"
        "def make():\n"
        "    return A\n"
        "\n"
        "K = make()\n"
        "K.x = 1\n"
    )

    assert classes["A"].namespace_binds("x") is None
    assert classes["Other"].namespace_binds("x") is False


def test_a_store_through_a_for_or_with_target_reaches_every_class_handed_on() -> None:
    classes = _statements(
        "class A:\n"
        "    pass\n"
        "\n"
        "class B:\n"
        "    pass\n"
        "\n"
        "class Other:\n"
        "    pass\n"
        "\n"
        "for K in (A,):\n"
        "    K.y = 1\n"
        "\n"
        "registry = [B]\n"
        "with registry[0] as J:\n"
        "    J.z = 1\n"
    )

    for name in ("y", "z"):
        assert classes["A"].namespace_binds(name) is None, name
        assert classes["B"].namespace_binds(name) is None, name
        assert classes["Other"].namespace_binds(name) is False, name


def test_a_store_through_a_lambdas_own_parameter_reaches_the_class() -> None:
    classes = _statements(
        "class A:\n"
        "    pass\n"
        "\n"
        "class Other:\n"
        "    pass\n"
        "\n"
        "mark = lambda K: setattr(K, 'v', 1)\n"
        "mark(A)\n"
    )

    assert classes["A"].namespace_binds("v") is None
    assert classes["Other"].namespace_binds("v") is False


def test_a_store_through_a_comprehensions_own_variable_reaches_the_class() -> None:
    classes = _statements(
        "class A:\n"
        "    pass\n"
        "\n"
        "class Other:\n"
        "    pass\n"
        "\n"
        "def patch():\n"
        "    [setattr(K, 'u', 1) for K in (A,)]\n"
    )

    assert classes["A"].namespace_binds("u") is None
    assert classes["Other"].namespace_binds("u") is False


def test_a_name_bound_to_a_display_is_no_class() -> None:
    classes = _statements(
        "class A:\n"
        "    pass\n"
        "\n"
        "def f(o):\n"
        "    return o\n"
        "\n"
        "f(A)\n"
        "names = ['a']\n"
        "names.t = 1\n"
    )

    # A list display is never a class: no store on A.
    assert classes["A"].namespace_binds("t") is False


# --- 3. the dataclass call asks the one __new__ lookup ------------------------

_DATACLASSES = (
    "from dataclasses import dataclass\n"
    "from typing import Generic, TypeVar\n"
    "\n"
    "T = TypeVar('T')\n"
    "\n"
    "@dataclass\n"
    "class Plain:\n"
    "    x: int\n"
    "\n"
    "@dataclass\n"
    "class Own:\n"
    "    x: int\n"
    "    def __new__(cls, x):\n"
    "        return object.__new__(cls)\n"
    "\n"
    "@dataclass\n"
    "class Stored:\n"
    "    x: int\n"
    "\n"
    "def make(cls, x):\n"
    "    return object.__new__(cls)\n"
    "\n"
    "Stored.__new__ = make\n"
    "\n"
    "@dataclass\n"
    "class Boxed(Generic[T]):\n"
    "    x: int\n"
    "\n"
    "@dataclass\n"
    "class NewBoxed(Generic[T]):\n"
    "    x: int\n"
    "    def __new__(cls, x):\n"
    "        return object.__new__(cls)\n"
)


def test_the_dataclass_new_is_the_one_lookups() -> None:
    classes = _statements(_DATACLASSES, "dataclass_new.py")

    for name in ("Plain", "Own", "Stored", "Boxed", "NewBoxed"):
        assert classes[name]._dataclass_generated_init_fields() is not None, name
    # ``object.__new__`` runs: the generated ``__init__`` is the frame.
    assert classes["Plain"].dataclass_new_entry() == (True, None)
    assert classes["Boxed"].dataclass_new_entry() == (True, None)
    decided, own = classes["Own"].dataclass_new_entry()
    assert decided and isinstance(own, FunctionDef) and own.name == "__new__"
    assert classes["Stored"].dataclass_new_entry() == (False, None)
    assert classes["NewBoxed"].dataclass_new_entry() == (False, None)


@pytest.mark.parametrize("name", ["Own", "Stored", "NewBoxed"])
def test_a_dataclass_whose_new_is_not_a_builtins_is_the_unanswered_call(
    name: str,
) -> None:
    statement = _statements(_DATACLASSES, "dataclass_new_call.py")[name]
    context = ReduceContext.root(owner="test")

    outcome = _bare_class_value(statement).callable_application_with(
        CallableApplication((TermValue(1),), (), "call-site", owner="test"),
        context,
    )

    _unanswered(outcome, name)
    # No frame skips the ``__new__`` the call runs.
    with pytest.raises(SugarNotWritten):
        statement.source_visible_constructor_frame()
