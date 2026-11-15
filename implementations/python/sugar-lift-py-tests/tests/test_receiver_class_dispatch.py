"""#7757 step 8: a method call on an instance whose class the method does not
know is its coordinate plus an edge resolved at prove through the receiver's
class input (``receiver_dispatch``).

The class of the object a parameter binds is an input of the function's
contract, ``class:<param>``, exactly where nothing the frame does could change
what the object's ``__dict__`` holds before a method call on it unseen
(``nodes._receiver_class_parameters``).  ``self.m()`` on such a parameter is
``call:dispatch:m(self, ..., py.class("0", class:self))`` with the member
``python:dispatch:m``; prove binds the class from the caller and resolves
``m`` on the class's order (``consistency::dispatched_symbol``).  The twins
that read it through the solver are in ``test_method_call_application_twins``.
"""

from __future__ import annotations

import pytest

from sugar_lift_py_tests.context_manager_resolution import TreeConstructionContextV1
from sugar_lift_python_source.canonical import blake3_512_of
from sugar_source_tree.nodes import FunctionDef, _receiver_class_parameters
from sugar_source_tree.tree import SourceFile


def _tree(source: str) -> SourceFile:
    return SourceFile(
        (source, "test_witness.py", blake3_512_of(source.encode())),
        construction_context=TreeConstructionContextV1.for_test_without_workspace(),
    )


def _function(tree: SourceFile, name: str):
    (function,) = tuple(
        node
        for node in tree.nodes()
        if isinstance(node, FunctionDef) and node.name == name
    )
    return function


_CLASS = """\
class Box:
    def run(self, other):
{body}

    def check(self):
        return None
"""


@pytest.mark.parametrize(
    ("body", "inputs"),
    [
        # Method calls on both parameters, nothing else: both are inputs.
        ("        self.check()\n        return other.get()", ("self", "other")),
        # A field read beside the call keeps the input.
        ("        self.check()\n        return self.n", ("self",)),
        # The object handed to code: its ``__dict__`` may change unseen.
        ("        helper(self)\n        return self.check()", ()),
        # Bound to another name, the object is read bare.
        ("        alias = self\n        return self.check()", ()),
        # Code reached through a field of the object may reach the object.
        ("        self.items.append(1)\n        return self.check()", ()),
        # A closure that reads the object runs where the frame does not see.
        ("        f = lambda: self.check()\n        return self.check()", ()),
        # A base's method runs on the object.
        ("        super().check()\n        return self.check()", ()),
        # No method call on the parameter: no input.
        ("        return self.n", ()),
    ],
)
def test_a_parameter_s_class_is_an_input_where_nothing_unseen_may_change_it(
    body: str, inputs: tuple
) -> None:
    tree = _tree(_CLASS.format(body=body))
    assert _receiver_class_parameters(_function(tree, "run")) == inputs


def test_a_generator_states_no_class_input() -> None:
    """A generator's body runs after its call returned: the caller's class of
    the object says nothing about its ``__dict__`` then."""
    tree = _tree(
        "class Box:\n"
        "    def run(self):\n"
        "        yield self.check()\n"
        "\n"
        "    def check(self):\n"
        "        return None\n"
    )
    assert _receiver_class_parameters(_function(tree, "run")) == ()


def test_a_method_call_on_a_receiver_whose_class_is_an_input_is_dispatched() -> None:
    """``self.check()`` in ``run``'s own proof: the dispatched edge, owed as it
    stands (its member ``python:dispatch:check``); nothing here names which
    function runs."""
    from sugar_lift_py_tests.tree_enumerate import function_universe_outcome

    tree = _tree(
        "class Box:\n"
        "    def run(self):\n"
        "        return self.check()\n"
        "\n"
        "    def check(self):\n"
        "        return None\n"
    )
    outcome = function_universe_outcome(_function(tree, "run"))
    owners = {halt.effect.producer_node_owner for halt in outcome.halts()}
    assert "UnknownCallee:dispatch:check" in owners


def test_a_field_stored_under_the_method_s_name_keeps_the_call_undispatched() -> None:
    """The module stores a field named ``check``: on the formal it would
    shadow the method unseen (the formal stands as it was after a store), so
    the call is not dispatched."""
    from sugar_lift_py_tests.tree_enumerate import function_universe_outcome

    tree = _tree(
        "class Box:\n"
        "    def run(self):\n"
        "        return self.check()\n"
        "\n"
        "    def check(self):\n"
        "        return None\n"
        "\n"
        "\n"
        "def patch(box):\n"
        "    box.check = None\n"
    )
    outcome = function_universe_outcome(_function(tree, "run"))
    owners = {halt.effect.producer_node_owner for halt in outcome.halts()}
    assert "UnknownCallee:dispatch:check" not in owners


_INITIALIZER = """\
class Base:
    def __init__(self):
{body}

    def setup(self):
        return None


class Derived(Base):
    def __init__(self):
        super().__init__()

    def setup(self):
        raise ValueError('override')
"""


def _initializer(tree: SourceFile, class_name: str):
    from sugar_source_tree.nodes import ClassDef

    (owner,) = tuple(
        node
        for node in tree.nodes()
        if isinstance(node, ClassDef) and node.name == class_name
    )
    (initializer,) = tuple(
        node
        for node in owner.body
        if isinstance(node, FunctionDef) and node.name == "__init__"
    )
    return initializer


def test_self_m_in_an_init_s_own_contract_is_dispatched_over_its_class_input() -> None:
    """``self.setup()`` in ``Base.__init__``'s own contract: ``self`` is the
    instance a constructor made, and a subclass's ``super().__init__()``
    runs this ``__init__`` on an instance of the subclass.  So the class of
    ``self`` is the contract's ``class:self`` input and the call is the
    dispatched edge over it -- never an edge to ``Base.setup``, the class that
    wrote the ``__init__`` (#7757 step 8)."""
    from sugar_lift_py_tests.tree_enumerate import function_universe_outcome

    tree = _tree(_INITIALIZER.format(body="        self.setup()"))
    initializer = _initializer(tree, "Base")
    assert _receiver_class_parameters(initializer) == ("self",)
    outcome = function_universe_outcome(initializer)
    owners = {halt.effect.producer_node_owner for halt in outcome.halts()}
    assert "UnknownCallee:dispatch:setup" in owners
    assert not any("Base.setup" in str(owner) for owner in owners)


def test_an_init_that_hands_self_keeps_its_method_call_undispatched() -> None:
    """``register(self)`` hands the object to code the frame does not see:
    the class of ``self`` is no input, so nothing binds it and the call is
    not dispatched (it stays the unanswered call, owed)."""
    from sugar_lift_py_tests.tree_enumerate import function_universe_outcome

    tree = _tree(
        _INITIALIZER.format(body="        register(self)\n        self.setup()")
        + "\n\ndef register(item):\n    return None\n"
    )
    initializer = _initializer(tree, "Base")
    assert _receiver_class_parameters(initializer) == ()
    outcome = function_universe_outcome(initializer)
    owners = {halt.effect.producer_node_owner for halt in outcome.halts()}
    assert "UnknownCallee:dispatch:setup" not in owners
