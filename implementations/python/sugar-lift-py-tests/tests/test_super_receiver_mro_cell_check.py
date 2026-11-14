"""Zero-argument ``super()`` answers as CPython does (#7757, leftovers of #8128).

1. Every lookup walks ``type(obj).__mro__`` from the class after
   ``__class__`` (the receiver's class's one base walk,
   ``ClassDef.namespace_owner(name, after=...)``): with ``class D(B, C)``,
   ``B(A)``, ``C(A)``, ``super()`` in ``B.m`` on a ``D`` reaches ``C``, never
   ``B``'s own base ``A``.  A receiver whose MRO is not read is the one
   unanswered call.
2. A frame with no ``__class__`` cell of its own (its symtable block lists no
   free ``__class__``) is ``RuntimeError: super(): __class__ cell not
   found``, whatever ``__class__`` a caller bound; a cell's class is the one
   its own class statement makes, never a caller's.
3. ``supercheck``: ``obj`` not an instance of ``__class__`` is the
   ``TypeError``; a check not decided here is two-faced, owing the
   ``undecided`` member.
4. In a generator expression the frame's first argument is the ``.0``
   iterator.  Over a builtin iterable (a display, ``range(...)``, ...) it is
   decided no instance of ``__class__``: the ``TypeError``.  Over anything
   else it may be one (``__iter__`` returning ``self``): the check is
   undecided, two-faced and owed.
"""

from __future__ import annotations

import pytest

from sugar_lift_py_tests.context import ReduceContext
from sugar_lift_py_tests.context_manager_resolution import TreeConstructionContextV1
from sugar_lift_py_tests.effect.raise_effect import UndeterminedRaiseEffect
from sugar_lift_py_tests.floor import (
    BuiltinSuperValue,
    CallSiteValue,
    TermValue,
)
from sugar_lift_py_tests.floor.builtin_semantic_callable import (
    zero_argument_super,
    zero_argument_super_class_cell,
    zero_argument_super_generator_iterator_is_builtin,
)
from sugar_lift_py_tests.gap.panic import ConstructionPanic
from sugar_lift_py_tests.outcome import Halted
from sugar_lift_python_source.canonical import blake3_512_of
from sugar_source_tree.nodes import ClassDef
from sugar_source_tree.tree import SourceFile


def _parsed(source: str, name: str):
    tree = SourceFile(
        (source, name, blake3_512_of(source.encode())),
        construction_context=TreeConstructionContextV1.for_test_without_workspace(),
    )
    context = ReduceContext.root(owner="test")
    classes = {}
    for node in tree.root.body:
        if not isinstance(node, ClassDef):
            continue
        value = node.sugar().desugar(context).completed_value()
        context.temporal = context.temporal.bind_value(value.class_name, value)
        classes[value.class_name] = value
    return tree, context, classes


def _super_site(tree):
    """The source fragment of the one ``super()`` call in the tree."""
    for node in tree.root.walk():
        callee = getattr(getattr(node, "func", None), "id", None)
        if getattr(node, "kind", None) == "Call" and callee == "super":
            return node.fragment
    raise AssertionError("no super() call in the source")


def _frame(context, cell, receiver):
    """The context a method body runs in: its ``__class__`` and ``self``."""
    temporal = context.temporal.bind_value("__class__", cell).bind_value(
        "self", receiver
    )
    return context.with_temporal(temporal)


def _raised(outcome):
    assert outcome.halts() == outcome.exits
    return [halt.effect.exception_name for halt in outcome.halts()]


# --- (1) the lookup walks type(obj).__mro__ after __class__ -------------------

_DIAMOND = (
    "class A:\n"
    "    def m(self):\n"
    "        return 'A'\n"
    "\n"
    "class B(A):\n"
    "    def m(self):\n"
    "        return super().m()\n"
    "\n"
    "class C(A):\n"
    "    def m(self):\n"
    "        return 'C'\n"
    "\n"
    "class D(B, C):\n"
    "    pass\n"
)


def _super_m(classes, context, receiver):
    return (
        BuiltinSuperValue(classes["B"], receiver)
        .call_method_value("m", (), owner="test", blame="super-m", ctx=context)
        .completed_value()
    )


def test_super_in_b_on_a_d_reaches_c_not_bs_own_base() -> None:
    _tree, context, classes = _parsed(_DIAMOND, "diamond.py")
    receiver = classes["D"].construct_receiver_state_from_block(None, "receiver")

    call = _super_m(classes, context, receiver)

    # D's MRO is D, B, C, A, object: the class after B binding ``m`` is C.
    assert isinstance(call, CallSiteValue)
    assert call.lexical_defining_class is classes["C"]
    assert call.arg_values[0] is receiver


def test_super_in_b_on_a_b_reaches_a() -> None:
    _tree, context, classes = _parsed(_DIAMOND, "diamond.py")
    receiver = classes["B"].construct_receiver_state_from_block(None, "receiver")

    call = _super_m(classes, context, receiver)

    assert isinstance(call, CallSiteValue)
    assert call.lexical_defining_class is classes["A"]


def test_the_one_lookup_starts_after_the_cell_in_the_receivers_order() -> None:
    _tree, _context, classes = _parsed(_DIAMOND, "diamond.py")
    d = classes["D"].class_definition
    b = classes["B"].class_definition

    decided, owner = d.namespace_owner("m", after=b)

    assert decided
    assert isinstance(owner, ClassDef) and owner.name == "C"
    assert d.mro_holds(b) is True
    assert b.mro_holds(classes["C"].class_definition) is False


def test_a_receiver_whose_mro_is_not_read_is_the_unanswered_call() -> None:
    _tree, context, classes = _parsed(_DIAMOND, "diamond.py")

    outcome = BuiltinSuperValue(classes["B"], TermValue("opaque")).call_method_value(
        "m", (), owner="test", blame="super-m", ctx=context
    )

    (halt,) = outcome.halts()
    assert isinstance(halt.effect, UndeterminedRaiseEffect)
    assert halt.effect.producer_node_owner == "UnknownCallee:super.m"
    assert outcome.owed_items()


# --- (2) the cell is the frame's own ------------------------------------------

_FREE_FUNCTION = (
    "def helper(self):\n"
    "    return super().m()\n"
    "\n"
    "class A:\n"
    "    def m(self):\n"
    "        return 1\n"
    "\n"
    "class B(A):\n"
    "    def m(self):\n"
    "        return helper(self)\n"
)


def test_a_function_with_no_cell_of_its_own_is_the_runtime_error() -> None:
    tree, context, classes = _parsed(_FREE_FUNCTION, "free_function.py")
    site = _super_site(tree)
    receiver = classes["B"].construct_receiver_state_from_block(None, "receiver")

    # ``helper`` reads ``super`` outside any class body: no free ``__class__``.
    assert zero_argument_super_class_cell(site) == (True, None)
    # The caller's (B.m's) ``__class__`` is never read in its place.
    outcome = zero_argument_super(site, _frame(context, classes["B"], receiver))

    assert _raised(outcome) == ["RuntimeError"]


def test_a_methods_cell_is_its_class_statement() -> None:
    tree, _context, _classes = _parsed(_DIAMOND, "diamond.py")

    decided, cell = zero_argument_super_class_cell(_super_site(tree))

    assert decided
    assert isinstance(cell, ClassDef) and cell.name == "B"


def test_a_lambda_in_a_method_carries_the_methods_class_cell() -> None:
    source = (
        "class A:\n"
        "    def m(self):\n"
        "        return 1\n"
        "\n"
        "class B(A):\n"
        "    def m(self):\n"
        "        return (lambda x: super().m())(self)\n"
    )
    tree, _context, _classes = _parsed(source, "lambda_cell.py")

    decided, cell = zero_argument_super_class_cell(_super_site(tree))

    assert decided
    assert isinstance(cell, ClassDef) and cell.name == "B"


def test_a_callers_class_binding_is_never_the_frames_cell() -> None:
    tree, context, classes = _parsed(_DIAMOND, "diamond.py")
    receiver = classes["D"].construct_receiver_state_from_block(None, "receiver")

    # ``super()`` in B.m with ``__class__`` bound to C: some caller's binding,
    # not the cell B's class statement makes.
    with pytest.raises(ConstructionPanic):
        zero_argument_super(
            _super_site(tree), _frame(context, classes["C"], receiver)
        )


# --- (3) supercheck: isinstance(obj, __class__) ----------------------------------

_UNRELATED = (
    "class A:\n"
    "    def m(self):\n"
    "        return super().m()\n"
    "\n"
    "class Other:\n"
    "    pass\n"
)


def test_super_on_an_instance_of_the_class_completes() -> None:
    tree, context, classes = _parsed(_UNRELATED, "unrelated.py")
    receiver = classes["A"].construct_receiver_state_from_block(None, "receiver")

    outcome = zero_argument_super(
        _super_site(tree), _frame(context, classes["A"], receiver)
    )

    made = outcome.completed_value()
    assert isinstance(made, BuiltinSuperValue)
    assert made.receiver is receiver


def test_super_on_an_instance_of_an_unrelated_class_is_the_type_error() -> None:
    # ``A.m(Other())``: Other's MRO (Other, object) holds no A, and
    # ``obj.__class__`` is object's own: CPython's TypeError.
    tree, context, classes = _parsed(_UNRELATED, "unrelated.py")
    receiver = classes["Other"].construct_receiver_state_from_block(None, "receiver")

    outcome = zero_argument_super(
        _super_site(tree), _frame(context, classes["A"], receiver)
    )

    assert _raised(outcome) == ["TypeError"]


def test_an_undecided_check_is_two_faced_and_owed() -> None:
    tree, context, classes = _parsed(_UNRELATED, "unrelated.py")

    outcome = zero_argument_super(
        _super_site(tree), _frame(context, classes["A"], TermValue("opaque"))
    )

    (halt,) = outcome.halts()
    assert isinstance(halt.effect, UndeterminedRaiseEffect)
    assert halt.effect.producer_node_owner == "BuiltinSuperValue.supercheck"
    completed = [face for face in outcome.exits if not isinstance(face, Halted)]
    assert len(completed) == 1
    assert isinstance(completed[0].value, BuiltinSuperValue)
    assert outcome.owed_items()


# --- (4) a generator expression's .0 fails the check -----------------------------


def test_super_in_a_generator_expression_is_the_type_error() -> None:
    source = (
        "class Base:\n"
        "    def m(self):\n"
        "        return [1]\n"
        "\n"
        "class Derived(Base):\n"
        "    def m(self):\n"
        "        return list(super().m() for _ in [1])\n"
    )
    tree, context, classes = _parsed(source, "generator_check.py")
    receiver = classes["Derived"].construct_receiver_state_from_block(None, "receiver")

    outcome = zero_argument_super(
        _super_site(tree), _frame(context, classes["Derived"], receiver)
    )

    assert _raised(outcome) == ["TypeError"]


@pytest.mark.parametrize(
    "iterable",
    ["(1, 2)", "{1: 2}", "'ab'", "range(2)", "[x for x in [1]]", "zip([1], [2])"],
)
def test_a_builtin_iterator_is_decided_no_instance(iterable: str) -> None:
    source = (
        "class Base:\n"
        "    def m(self):\n"
        "        return [1]\n"
        "\n"
        "class Derived(Base):\n"
        "    def m(self):\n"
        f"        return list(super().m() for _ in {iterable})\n"
    )
    tree, _context, _classes = _parsed(source, "generator_builtin.py")

    assert zero_argument_super_generator_iterator_is_builtin(_super_site(tree))


def test_an_iterator_that_may_be_an_instance_leaves_the_check_undecided() -> None:
    # ``iter(self)`` is ``self`` when ``__iter__`` returns it: CPython's check
    # passes, so the TypeError is never assumed.
    source = (
        "class Base:\n"
        "    def m(self):\n"
        "        return [1]\n"
        "\n"
        "class Walker(Base):\n"
        "    def __iter__(self):\n"
        "        return self\n"
        "\n"
        "    def m(self):\n"
        "        return list(super().m() for _ in self)\n"
    )
    tree, context, classes = _parsed(source, "generator_self_iterator.py")
    site = _super_site(tree)
    receiver = classes["Walker"].construct_receiver_state_from_block(None, "receiver")

    assert not zero_argument_super_generator_iterator_is_builtin(site)
    outcome = zero_argument_super(site, _frame(context, classes["Walker"], receiver))

    (halt,) = outcome.halts()
    assert isinstance(halt.effect, UndeterminedRaiseEffect)
    assert halt.effect.producer_node_owner == "BuiltinSuperValue.supercheck"
    completed = [face for face in outcome.exits if not isinstance(face, Halted)]
    assert len(completed) == 1
    assert isinstance(completed[0].value, BuiltinSuperValue)
    # The ``.0`` iterator is no value here; the enclosing ``self`` is never
    # read in its place.
    assert completed[0].value.receiver is None
    assert outcome.owed_items()


def test_super_in_a_generator_outside_any_class_is_the_runtime_error() -> None:
    source = "def f(self):\n    return list(super().m() for _ in [1])\n"
    tree, context, _classes = _parsed(source, "generator_no_cell.py")

    outcome = zero_argument_super(_super_site(tree), context)

    assert _raised(outcome) == ["RuntimeError"]
