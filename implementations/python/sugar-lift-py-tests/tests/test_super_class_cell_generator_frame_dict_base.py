"""Zero-argument ``super()``: the cell, the frame, and dict's own methods (#7757,
leftovers of #8118).

- The ``__class__`` cell is the class whose body defines the function the
  call runs, at every application: a method (``bind_method_call``), a source
  store through a mapping (``MappingObjectValue._source_store``) and a class
  call running an inherited ``__init__`` (``ClassConstructorBodySugar``).
  ``class A: def m(self): return super().m()`` / ``class B(A): pass`` /
  ``B().m()`` searches after ``A``, never after ``B``.
- A generator expression is a frame of its own whose first argument is the
  ``.0`` iterator; a list, set or dict comprehension is inlined into the
  frame around it (PEP 709, CPython 3.12+); a generator's outermost iterable
  runs in the frame around it.
- ``super().__getitem__``/``__delitem__``/``__contains__``/``get`` that select
  ``dict`` are dict's own method through the mapping's one door per
  operation (``MappingObjectValue.dict_base_call``).
"""

from __future__ import annotations

from types import SimpleNamespace

import pytest

from sugar_lift_py_tests.context import ReduceContext
from sugar_lift_py_tests.context_manager_resolution import TreeConstructionContextV1
from sugar_lift_py_tests.floor import (
    BuiltinSuperValue,
    CallSiteValue,
    MappingObjectValue,
    NoneValue,
    ReceiverOwnedMutationResult,
    StringValue,
    TermValue,
)
from sugar_lift_py_tests.floor.builtin_semantic_callable import (
    zero_argument_super_has_no_arguments,
    zero_argument_super_in_generator_frame,
    zero_argument_super_receiver,
)
from sugar_lift_py_tests.outcome import ExitSet
from sugar_lift_py_tests.sugar.true_bool_literal_sugar import TrueBoolLiteralSugar
from sugar_lift_python_source.canonical import blake3_512_of
from sugar_source_tree.nodes import ClassDef
from sugar_source_tree.tree import SourceFile


def _tree(source: str, name: str):
    return SourceFile(
        (source, name, blake3_512_of(source.encode())),
        construction_context=TreeConstructionContextV1.for_test_without_workspace(),
    )


def _classes(source: str, name: str):
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


# --- (1) the __class__ cell is the defining class ----------------------------

_INHERITED_METHOD = (
    "class Base:\n"
    "    def m(self):\n"
    "        return 1\n"
    "\n"
    "class A(Base):\n"
    "    def m(self):\n"
    "        return super().m()\n"
    "\n"
    "class B(A):\n"
    "    pass\n"
)


def test_an_inherited_method_runs_with_its_defining_class_cell() -> None:
    context, classes = _classes(_INHERITED_METHOD, "inherited_method.py")
    receiver = classes["B"].construct_receiver_state_from_block(None, "receiver")

    call = receiver.call_method_value(
        "m", (), owner="test", blame="b-m", ctx=context
    ).completed_value()

    assert isinstance(call, CallSiteValue)
    # ``super()`` in A.m searches after A (into Base.m), never after B.
    assert call.lexical_defining_class is classes["A"]
    assert call.retained_source_completion_outcome().completed_value() is not None


_INHERITED_SETITEM = (
    "class A(dict):\n"
    "    def __setitem__(self, key, value):\n"
    "        super().__setitem__(key, value)\n"
    "\n"
    "class B(A):\n"
    "    pass\n"
)


def test_a_source_store_runs_an_inherited_override_with_its_defining_class() -> None:
    context, classes = _classes(_INHERITED_SETITEM, "inherited_setitem.py")
    receiver = classes["B"].construct_receiver_state_from_block(None, "receiver")

    stored = receiver.setitem(StringValue("k"), TermValue(7), "caller", context)

    after = stored.completed_value()
    assert isinstance(after, MappingObjectValue)
    assert after.identity == receiver.identity
    assert after.entries == ((StringValue("k"), TermValue(7)),)


_INHERITED_INIT = (
    "class Base:\n"
    "    def __init__(self):\n"
    "        self.x = 1\n"
    "\n"
    "class A(Base):\n"
    "    def __init__(self):\n"
    "        super().__init__()\n"
    "\n"
    "class B(A):\n"
    "    pass\n"
)


@pytest.mark.parametrize("called", ["A", "B"])
def test_a_class_call_seats_the_cell_of_the_class_that_wrote_init(
    called: str,
) -> None:
    context, classes = _classes(_INHERITED_INIT, "inherited_init.py")
    body = classes[called].class_definition.source_visible_constructor_frame().body
    assert body.cell_class_definition.name == "A"
    seen = []

    def initialize(value, ctx):
        seen.append(ctx.temporal.value_if_bound("__class__"))
        return ExitSet.completed(value)

    body.enter_initializer(context, initialize)

    # ``B()`` runs A's ``__init__``: its ``super()`` searches after A.
    assert [cell.class_name for cell in seen] == ["A"]


# --- (2) the frame a zero-argument super() runs in ---------------------------


def _super_call_site(tree):
    for node in tree.root.walk():
        callee = getattr(getattr(node, "func", None), "id", None)
        if getattr(node, "kind", None) == "Call" and callee == "super":
            return SimpleNamespace(unit=node.unit, node=node)
    raise AssertionError("no super() call in the source")


def _method_with(body: str, name: str):
    source = (
        "class Base:\n"
        "    def m(self):\n"
        "        return [1]\n"
        "\n"
        "class Derived(Base):\n"
        "    def m(self):\n"
        f"        return {body}\n"
    )
    return _super_call_site(_tree(source, name))


def _temporal(**bound):
    temporal = ReduceContext.root(owner="test").temporal
    for name, value in bound.items():
        temporal = temporal.bind_value(name, value)
    return temporal


@pytest.mark.parametrize(
    "body",
    [
        "list(super().m() for _ in [1])",
        # A later clause's iterable runs in the generator's own code.
        "list(x for _ in [1] for x in super().m())",
        # A generator inside a lambda with no formal: the generator's frame
        # takes ``.0``, so it is not the lambda's RuntimeError.
        "(lambda: list(super().m() for _ in [1]))()",
    ],
)
def test_super_in_a_generator_expression_binds_its_own_iterator(body: str) -> None:
    site = _method_with(body, "generator_frame.py")

    assert zero_argument_super_in_generator_frame(site)
    assert not zero_argument_super_has_no_arguments(site)
    # The enclosing method's ``self`` is never read in place of ``.0``.
    assert (
        zero_argument_super_receiver(site, _temporal(self=StringValue("self")))
        is None
    )


@pytest.mark.parametrize(
    "body",
    [
        # Inlined into the method's frame (PEP 709).
        "[super().m() for _ in [1]]",
        "{super().m() for _ in [1]}",
        "{0: super().m() for _ in [1]}",
        # A generator's outermost iterable runs in the frame around it.
        "list(x for x in super().m())",
    ],
)
def test_super_in_the_methods_own_code_reads_the_method_formal(body: str) -> None:
    site = _method_with(body, "inlined_frame.py")
    receiver = StringValue("self")

    assert not zero_argument_super_in_generator_frame(site)
    assert zero_argument_super_receiver(site, _temporal(self=receiver)) is receiver


def test_a_lambda_in_a_generator_is_its_own_frame() -> None:
    site = _method_with(
        "list((lambda y: super().m())(0) for _ in [1])", "lambda_in_generator.py"
    )
    inner = StringValue("lambda formal")

    assert not zero_argument_super_in_generator_frame(site)
    assert (
        zero_argument_super_receiver(
            site, _temporal(self=StringValue("self"), y=inner)
        )
        is inner
    )


# --- (3) super() into dict: dict's own method, one door per operation ---------

_DICT_OVERRIDES = (
    "class Override(dict):\n"
    "    def __getitem__(self, key):\n"
    "        return super().__getitem__(key)\n"
    "    def __delitem__(self, key):\n"
    "        super().__delitem__(key)\n"
    "    def __contains__(self, key):\n"
    "        return super().__contains__(key)\n"
    "    def get(self, key, default=None):\n"
    "        return super().get(key, default)\n"
)


def _override():
    context, classes = _classes(_DICT_OVERRIDES, "dict_overrides.py")
    definition = classes["Override"]
    receiver = definition.construct_receiver_state_from_block(
        None, "receiver"
    ).mapping_with_entries(((StringValue("k"), TermValue(7)),))
    return context, definition, receiver


def _super_call(name: str, *arguments):
    _context, definition, receiver = _override()
    return BuiltinSuperValue(definition, receiver).call_method_value(
        name, arguments, owner="test", blame=f"super-{name}"
    )


def test_super_getitem_reads_the_dict_base() -> None:
    assert _super_call("__getitem__", StringValue("k")).completed_value() == (
        TermValue(7)
    )


def test_super_contains_tests_the_dict_base() -> None:
    assert isinstance(
        _super_call("__contains__", StringValue("k")).completed_value(),
        TrueBoolLiteralSugar,
    )


def test_super_get_reads_the_dict_base_with_its_default() -> None:
    assert _super_call("get", StringValue("k"), NoneValue()).completed_value() == (
        TermValue(7)
    )
    assert isinstance(
        _super_call("get", StringValue("absent"), NoneValue()).completed_value(),
        NoneValue,
    )


def test_super_delitem_is_the_receivers_transition() -> None:
    _context, definition, receiver = _override()

    deleted = (
        BuiltinSuperValue(definition, receiver)
        .call_method_value(
            "__delitem__", (StringValue("k"),), owner="test", blame="super-del"
        )
        .completed_value()
    )

    assert isinstance(deleted, ReceiverOwnedMutationResult)
    assert deleted.receiver_before is receiver
    assert deleted.receiver_after.identity == receiver.identity
    assert deleted.receiver_after.entries == ()


def test_del_through_the_source_override_leaves_the_dict_base_without_the_key() -> (
    None
):
    context, _definition, receiver = _override()

    after = receiver.delitem(StringValue("k"), "caller", context).completed_value()

    assert isinstance(after, MappingObjectValue)
    assert after.identity == receiver.identity
    assert after.entries == ()
