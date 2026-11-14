"""In ``floor/`` and ``sugar/``, a name the program spells never selects
behaviour; its binding does (#7757).

- A method call on a value no floor decides may change that value whatever
  the method is spelled (``_may_change``): a source ``o.set(3)`` as much as
  ``o.append(3)``.  The container law's method names are read only on a value
  the floor decides is a builtin container.
- A zero-argument ``super()`` binds the first positional formal its enclosing
  ``def`` declares (``zero_argument_super_receiver``), never a value some
  frame binds under the spelling ``self``/``cls``/``metacls``.
"""

from __future__ import annotations

from types import SimpleNamespace

from sugar_lift_py_tests.context import ReduceContext
from sugar_lift_py_tests.context_manager_resolution import TreeConstructionContextV1
from sugar_lift_py_tests.floor import CallSiteValue, SymbolicValue
from sugar_lift_py_tests.floor.builtin_semantic_callable import (
    zero_argument_super_receiver,
)
from sugar_lift_py_tests.floor.list_value import ListValue
from sugar_lift_py_tests.floor.string_value import StringValue
from sugar_lift_py_tests.floor.term_value import TermValue
from sugar_lift_py_tests.ir import make_var
from sugar_lift_py_tests.sugar.builtin_container_call_sugar import _may_change
from sugar_lift_python_source.canonical import blake3_512_of
from sugar_source_tree.nodes import ClassDef
from sugar_source_tree.tree import SourceFile


# --- _may_change: the method's spelling decides nothing on an undecided value --


def test_undecided_receiver_may_change_under_any_method_spelling() -> None:
    receiver = SymbolicValue(make_var("o"))

    # A source method spelled like no container mutator still may change it.
    assert _may_change(receiver, "set", False, False)
    assert _may_change(receiver, "compute", False, False)
    # One spelled like a container mutator is no different.
    assert _may_change(receiver, "append", False, False)


def test_undecided_operand_keeps_its_value() -> None:
    assert not _may_change(SymbolicValue(make_var("o")), "", False, False)


def test_decided_list_reads_the_container_law_by_method() -> None:
    # The floor decided the receiver is a builtin ``list``: only then does the
    # method name choose the container rule.
    receiver = ListValue((TermValue(1),))

    assert _may_change(receiver, "append", False, False)
    assert not _may_change(receiver, "count", False, False)


# --- zero-argument super(): the declared first formal, never ``self`` ---------


def _tree(source: str, name: str):
    return SourceFile(
        (source, name, blake3_512_of(source.encode())),
        construction_context=TreeConstructionContextV1.for_test_without_workspace(),
    )


def _super_call_site(tree):
    for node in tree.root.walk():
        callee = getattr(getattr(node, "func", None), "id", None)
        if getattr(node, "kind", None) == "Call" and callee == "super":
            return SimpleNamespace(unit=node.unit, node=node)
    raise AssertionError("no super() call in the source")


_DECLARED_THIS = (
    "class Base:\n"
    "    def m(this):\n"
    "        return 1\n"
    "\n"
    "class Derived(Base):\n"
    "    def m(this):\n"
    "        return super().m()\n"
)


def test_super_receiver_is_the_declared_first_formal() -> None:
    site = _super_call_site(_tree(_DECLARED_THIS, "super_this.py"))
    inner = StringValue("inner")
    outer = StringValue("outer")
    temporal = (
        ReduceContext.root(owner="test")
        .temporal.bind_value("self", outer)
        .bind_value("this", inner)
    )

    assert zero_argument_super_receiver(site, temporal) is inner


def test_super_receiver_never_reads_a_self_the_frame_did_not_declare() -> None:
    site = _super_call_site(_tree(_DECLARED_THIS, "super_this.py"))
    temporal = ReduceContext.root(owner="test").temporal.bind_value(
        "self", StringValue("outer")
    )

    assert zero_argument_super_receiver(site, temporal) is None


_NO_POSITIONAL = (
    "class Base:\n"
    "    def m(*args):\n"
    "        return 1\n"
    "\n"
    "class Derived(Base):\n"
    "    def m(*args):\n"
    "        return super().m()\n"
)


def test_super_without_a_positional_formal_has_no_receiver() -> None:
    site = _super_call_site(_tree(_NO_POSITIONAL, "super_varargs.py"))
    temporal = (
        ReduceContext.root(owner="test")
        .temporal.bind_value("self", StringValue("outer"))
        .bind_value("args", StringValue("args"))
    )

    assert zero_argument_super_receiver(site, temporal) is None


_INIT_THIS = (
    "class Base:\n"
    "    def __init__(this, x):\n"
    "        this.x = x\n"
    "\n"
    "class Derived(Base):\n"
    "    def __init__(this, x):\n"
    "        super().__init__(x)\n"
    "        this.y = x\n"
)


def test_super_init_dispatches_with_a_receiver_not_spelled_self() -> None:
    tree = _tree(_INIT_THIS, "super_init_this.py")
    context = ReduceContext.root(owner="test")
    values = []
    for node in tree.root.body:
        if not isinstance(node, ClassDef):
            continue
        value = node.sugar().desugar(context).completed_value()
        context.temporal = context.temporal.bind_value(value.class_name, value)
        values.append(value)
    _base, derived = values
    receiver = derived.construct_receiver_state_from_block(None, "receiver")

    call = receiver.call_method_value(
        "__init__",
        (StringValue("v"),),
        owner="test",
        blame="derived-init",
        ctx=context,
    ).completed_value()

    assert isinstance(call, CallSiteValue)
    reduced = call.retained_source_completion_outcome()
    assert any(type(face).__name__ == "Completed" for face in reduced.exits), reduced
