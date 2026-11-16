"""Zero-argument ``super()``: the cell, the frame, and dict's own methods (#7757,
leftovers of #8118).

- The ``__class__`` cell is the class whose body defines the function the
  call runs, at every application: a method (its own frame), a source
  store through a mapping (``MappingObjectValue._source_store``).  A class
  call dispatches ``__init__`` (#7757 B3), whose own frame seats its cell.
  ``class A: def m(self): return super().m()`` / ``class B(A): pass`` /
  ``B().m()`` searches after ``A``, never after ``B``.
- A generator expression is a frame of its own whose first argument is the
  ``.0`` iterator; a list, set or dict comprehension is inlined into the
  frame around it (PEP 709, CPython 3.12+); a generator's outermost iterable
  runs in the frame around it.
- ``super().__getitem__``/``__delitem__``/``__contains__``/``get`` that select
  ``dict`` are the one dispatched call after ``__class__``, as through any
  source class (#7757 L5): the lift never answers them by dict's own method.
"""

from __future__ import annotations

from types import SimpleNamespace

import pytest

from frame_fresh import FRAME_FRESH
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
    from sugar_lift_py_tests.floor import SymbolicValue
    from sugar_lift_py_tests.outcome.exit_set import Completed

    receiver = classes["B"].fresh_receiver("receiver", allocation=FRAME_FRESH)

    stored = receiver.setitem(StringValue("k"), TermValue(7), "caller", context)

    # The store selects ``A.__setitem__`` (B inherits it) and is that
    # method's coordinate and edge (#7757 step 6, #8738): its body, whose
    # ``super()`` searches after A, is A's contract, joined at prove.  It is
    # never applied here (the application was deleted by #8751), so what it
    # leaves of the receiver is not read at lift: the completed face states
    # the receiver after the call as unknown, and the store's entries are
    # joined from the method's contract at prove (step 7).
    (done,) = [arm for arm in stored.exits if isinstance(arm, Completed)]
    assert stored.halts(), stored
    assert isinstance(done.value, SymbolicValue)
    assert not isinstance(done.value, MappingObjectValue)


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


# --- (3) super() into dict: the one dispatched call, never dict answered here ---

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
    receiver = definition.fresh_receiver("receiver", allocation=FRAME_FRESH).mapping_with_entries(
        ((StringValue("k"), TermValue(7)),)
    )
    return context, definition, receiver


def _super_call(name: str, *arguments):
    _context, definition, receiver = _override()
    return BuiltinSuperValue(definition, receiver).call_method_value(
        name, arguments, owner="test", blame=f"super-{name}"
    )


@pytest.mark.parametrize(
    "name, arguments",
    [
        ("__getitem__", (StringValue("k"),)),
        ("__contains__", (StringValue("k"),)),
        ("get", (StringValue("k"), NoneValue())),
        ("get", (StringValue("absent"), NoneValue())),
        ("__delitem__", (StringValue("k"),)),
    ],
)
def test_super_into_the_dict_base_is_the_one_call(name, arguments) -> None:
    """``super().<name>(...)`` whose order after ``__class__`` is ``dict``,
    ``object``: the one dispatched call after ``__class__`` (#7757 L5), as
    the same lookup through any source class is.  With no workspace root it
    is the one unanswered call ``super.<name>``, owed, both faces standing:
    never dict's own read, test or deletion answered here (no member it
    holds, no default, no receiver transition)."""
    from sugar_lift_py_tests.effect import UndeterminedRaiseEffect
    from sugar_lift_py_tests.floor.named_expression_value import peel_walrus_binds
    from sugar_lift_py_tests.outcome.exit_set import Completed

    outcome = _super_call(name, *arguments)

    (done,) = [arm for arm in outcome.exits if isinstance(arm, Completed)]
    (halt,) = outcome.halts()
    assert len(outcome.exits) == 2
    assert isinstance(halt.effect, UndeterminedRaiseEffect)
    assert halt.effect.producer_node_owner == f"UnknownCallee:super.{name}"
    _binds, call = peel_walrus_binds(done.value)
    assert isinstance(call, CallSiteValue), type(call)
    assert not isinstance(call, ReceiverOwnedMutationResult)
    assert call != TermValue(7)
    assert not isinstance(call, (NoneValue, TrueBoolLiteralSugar))
    assert outcome.owed_items()


def _undecided_deletion_arms(outcome):
    """``del`` on the dict base: whether the key is held is read off storage
    that is not current (``MappingObjectValue._builtin_dict``), so the
    deletion is the undecided item mutation
    (``list_value.stale_item_mutation``): it completes under its own
    site-keyed atom, leaving the receiver after it unknown, and halts with an
    undetermined raise under the complement.  Neither ``KeyError`` nor the
    key's removal is decided from contents the object may no longer hold, and
    neither face is dropped."""
    from sugar_lift_py_tests.effect import UndeterminedRaiseEffect
    from sugar_lift_py_tests.outcome.exit_set import Completed, Halted

    (done,) = [arm for arm in outcome.exits if isinstance(arm, Completed)]
    (halt,) = [arm for arm in outcome.exits if isinstance(arm, Halted)]
    assert len(outcome.exits) == 2
    assert isinstance(halt.effect, UndeterminedRaiseEffect)
    return done


def test_del_through_the_source_override_leaves_the_dict_base_undecided() -> None:
    from sugar_lift_py_tests.floor import SymbolicValue

    context, _definition, receiver = _override()

    done = _undecided_deletion_arms(
        receiver.delitem(StringValue("k"), "caller", context)
    )

    # The override's ``super().__delitem__(key)`` leaves the receiver its one
    # mutation states: unknown, never ``entries == ()``.
    assert isinstance(done.value, SymbolicValue)
    assert not isinstance(done.value, MappingObjectValue)
