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
        # A field read alone: the class is an input, the field's reads are
        # the ``field:`` input under the plain-read guard (#7757).
        ("        return self.n", ("self",)),
        # A field stored and read: the ``__dict__`` changes in the frame.
        ("        self.n = 1\n        return self.n", ()),
        # Neither a method call nor a field read: no input.
        ("        return other", ()),
        # An item store or delete is ``type(other).__setitem__`` /
        # ``__delitem__``, dispatched as a method call is (#7757 step 7).
        ("        other[0] = 1\n        return self.check()", ("self", "other")),
        ("        del other[0]\n        return self.check()", ("self", "other")),
        # An item read hands the object to code the frame does not see.
        ("        other.append(other[0])\n        return self.check()", ("self",)),
        # A field store on the parameter (#7757 step 7): the store is stated
        # under a guard over the class input.
        ("        self.n = 1\n        return other.get()", ("self", "other")),
        ("        self.n += 1\n        return None", ("self",)),
        # The stored value read bare is handed to the store, not the receiver.
        ("        self.n = other\n        return None", ("self",)),
        # Stored on, but also handed to code: no input.
        ("        self.n = 1\n        helper(self)", ()),
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


_CELL = """\
def test_append():
    xs = []

    def add():
{body}

    add()
"""


@pytest.mark.parametrize(
    ("body", "inputs"),
    [
        # A method call on the cell's object: its class is an input.
        ("        xs.append(1)", ("xs",)),
        # An item store is ``type(xs).__setitem__``, dispatched too.
        ("        xs[0] = 1", ("xs",)),
        # Handed to code: its contents may change unseen.
        ("        helper(xs)\n        xs.append(1)", ()),
        # Declared ``nonlocal``: the cell is rebound, never only mutated.
        ("        nonlocal xs\n        xs.append(1)", ()),
    ],
)
def test_a_cell_s_class_is_an_input_where_the_body_mutates_its_object(
    body: str, inputs: tuple
) -> None:
    """#7757 step 7: a captured cell the body mutates through a method or an
    item store takes ``class:cell:<name>``, under a parameter's rules."""
    from sugar_source_tree.nodes import _receiver_class_cells

    tree = _tree(_CELL.format(body=body))
    assert _receiver_class_cells(_function(tree, "add")) == inputs


def test_a_builtin_value_s_class_is_its_exact_builtin_class() -> None:
    """#7757 step 7: a caller supplies ``python:builtin("<name>")`` for a
    value whose builtin class the lifter decides; never for a ``bool``,
    whose class is not ``int``."""
    from sugar_lift_py_tests.floor.list_value import ListValue
    from sugar_lift_py_tests.floor.string_value import StringValue
    from sugar_lift_py_tests.floor.term_value import TermValue
    from sugar_lift_py_tests.ir import ctor, str_const
    from sugar_lift_py_tests.receiver_dispatch import class_value

    def builtin(name):
        return ctor("python:builtin", [str_const(name)])

    assert class_value(ListValue((), allocation="here")) == builtin("list")
    assert class_value(StringValue("a")) == builtin("str")
    assert class_value(TermValue(3)) == builtin("int")
    assert class_value(TermValue(True)) is None


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


@pytest.mark.parametrize(
    ("body", "fields"),
    [
        # Fields read of the receiver where its ``__dict__`` is the one it
        # arrived with: each is an input, in field order; a dunder never is,
        # nor a field of another parameter (no call binds its class).
        (
            "        return self.n + other.m + self.k + self.__class__",
            (("self", "k"), ("self", "n")),
        ),
        # A method call on the object may store any field: no field input.
        ("        self.check()\n        return self.n", ()),
        # A store or a delete on the object changes its ``__dict__``.
        ("        self.k = 1\n        return self.n", ()),
        ("        del self.k\n        return self.n", ()),
        # The object handed to code: no class input, so no field input.
        ("        helper(self)\n        return self.n", ()),
    ],
)
def test_a_field_read_of_a_parameter_is_an_input_where_its_dict_is_as_it_arrived(
    body: str, fields: tuple
) -> None:
    from sugar_source_tree.nodes import _receiver_field_inputs

    tree = _tree(_CLASS.format(body=body))
    assert _receiver_field_inputs(_function(tree, "run")) == fields


def test_a_field_read_of_an_arrived_receiver_is_its_input_under_the_plain_read_guard() -> (
    None
):
    """``return self.n`` in ``read``'s own proof: one completed face returns
    the ``field:self.n`` input under ``python:plain_read(class:self, "n")``,
    and the undecided read stands under its complement (owed, its halt
    kept).  Before, the read was the formal's waiting operation, owed on
    every face."""
    from sugar_lift_py_tests.effect.raise_effect import UndeterminedRaiseEffect
    from sugar_lift_py_tests.outcome import Completed, Halted
    from sugar_lift_py_tests.tree_enumerate import function_universe_outcome

    tree = _tree(
        "class Gauge:\n"
        "    def __init__(self, n):\n"
        "        self.n = n\n"
        "\n"
        "    def read(self):\n"
        "        return self.n\n"
    )
    function = _function(tree, "read")
    assert "field:self.n" in tuple(
        item.formal for item in function.contract_inputs()
    )
    outcome = function_universe_outcome(function)
    completed = [face for face in outcome.exits if isinstance(face, Completed)]
    halted = [face for face in outcome.exits if isinstance(face, Halted)]
    assert len(completed) >= 2, outcome
    assert "field:self.n" in str(outcome), outcome
    assert "python:plain_read" in str(outcome), outcome
    assert halted and all(
        isinstance(face.effect, UndeterminedRaiseEffect) for face in halted
    ), outcome


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


_CLASS_STORE = """\
class Box:
    def run(self):
        return self.check()

    def check(self):
        return None


class Other:
    def check(self):
        raise ValueError('other')


def patch(box):
{store}
"""


@pytest.mark.parametrize(
    "store",
    [
        "    box.__class__ = Other",
        "    box.__class__, n = Other, 1",
        "    [*box.__class__] = [Other]",
        "    del box.__class__",
        "    for box.__class__ in (Other,):\n        pass",
        "    object.__setattr__(box, '__class__', Other)",
        "    setattr(box, '__class__', Other)",
    ],
)
def test_a_class_store_anywhere_keeps_the_call_undispatched(store: str) -> None:
    """The module may give an object another class (``x.__class__ = C``,
    ``setattr(x, "__class__", C)``, ``object.__setattr__``): the class a
    caller binds ``class:self`` to may not be the object's class at the
    call, so the call is not dispatched (owed, #7757 step 8)."""
    from sugar_lift_py_tests.tree_enumerate import function_universe_outcome

    tree = _tree(_CLASS_STORE.format(store=store))
    outcome = function_universe_outcome(_function(tree, "run"))
    owners = {halt.effect.producer_node_owner for halt in outcome.halts()}
    assert "UnknownCallee:dispatch:check" not in owners


def test_a_class_read_keeps_the_call_dispatched() -> None:
    """A read of ``__class__`` changes no object's class: the call is
    dispatched as before."""
    from sugar_lift_py_tests.tree_enumerate import function_universe_outcome

    tree = _tree(_CLASS_STORE.format(store="    return box.__class__.__name__"))
    outcome = function_universe_outcome(_function(tree, "run"))
    owners = {halt.effect.producer_node_owner for halt in outcome.halts()}
    assert "UnknownCallee:dispatch:check" in owners


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


_KINDS = """\
def helper(self):
    return 0


class Box:
    def get(self):
        return 1

    @staticmethod
    def make(n):
        return n

    @classmethod
    def build(cls, n):
        return n

    @property
    def size(self):
        return 2

    pick = lambda self: 3

    alias = helper

    def counted(self):
        yield 1
"""


def test_a_namespace_row_states_each_binding_s_kind(tmp_path) -> None:
    """The class's namespace row states each binding's kind with its
    function's join symbol (#7757 step 8): a plain ``def``, a
    ``staticmethod``, a ``classmethod``, a ``property`` getter and a lambda
    field, each bound at prove as its descriptor binds it.  A field holding
    a name, and a generator, are ``other``: a dispatched call of them stays
    owed.  A ``classmethod`` brings the class object's term."""
    from sugar_lift_py_tests.lift_rpc import open_source_file_for_construction
    from sugar_lift_py_tests.tree_enumerate import _class_namespace_facts
    from sugar_source_tree.nodes import ClassDef

    path = tmp_path / "subject.py"
    path.write_text(_KINDS)
    tree = open_source_file_for_construction(path, root=tmp_path)
    (box,) = tuple(node for node in tree.nodes() if isinstance(node, ClassDef))
    symbol, mro, binds, class_object = _class_namespace_facts(box)
    assert symbol == "python:subject.Box"
    assert mro == ("python:subject.Box", "builtins.object")
    kinds = {name: (kind, target) for name, kind, target in binds}
    assert kinds["get"] == ("function", "python:subject.Box.get")
    assert kinds["make"] == ("staticmethod", "python:subject.Box.make")
    assert kinds["build"] == ("classmethod", "python:subject.Box.build")
    assert kinds["size"] == ("property", "python:subject.Box.size")
    assert kinds["pick"][0] == "field"
    assert "<lambda>" in kinds["pick"][1]
    assert kinds["alias"] == ("other", "")
    assert kinds["counted"] == ("other", "")
    assert class_object is not None
    assert class_object.name == "python:class-definition"


_STORED = """\
class Box:
    pass


def fill(b, v):
    b.n = v
    b.m = 2
"""


def _atom_names(formula) -> set:
    """The names of the atoms ``formula`` states under its connectives."""
    names = set()
    pending = [formula]
    while pending:
        node = pending.pop()
        operands = getattr(node, "operands", None)
        if operands is not None:
            pending.extend(operands)
        elif hasattr(node, "args"):
            names.add(node.name)
    return names


def test_a_field_stored_on_a_parameter_is_stated_under_its_guard() -> None:
    """``fill(b, v)``: the class of ``b`` is the contract's ``class:b``
    input, and each completed arm states the fields the body stores last on
    ``b`` over ``python:after(out, "b")`` under
    ``python:plain_store(class:b, "<f>")`` for each such store and every
    store after it.  Each store's own completion is guarded by its atom
    too, so its halt is the store that is not plain (#7757 step 7)."""
    from sugar_lift_py_tests.outcome import Completed
    from sugar_lift_py_tests.tree_enumerate import function_universe_outcome

    fill = _function(_tree(_STORED), "fill")
    assert _receiver_class_parameters(fill) == ("b",)
    outcome = function_universe_outcome(fill)
    completed = [face.value for face in outcome.exits if isinstance(face, Completed)]
    assert completed, outcome
    for universe in completed:
        assert universe.plain_stores == (("b", "n"), ("b", "m"))
        assert [(param, attr) for param, attr, _value in universe.fields] == [
            ("b", "n"),
            ("b", "m"),
        ]
        stated = universe.field_facts()
        assert stated is not None and stated.kind == "implies"
        assert _atom_names(stated.operands[0]) == {"python:plain_store"}
    halts = outcome.halts()
    assert halts
    assert all("python:plain_store" in _atom_names(face.guard) for face in halts)


_STORED_BEFORE_CODE = """\
class Box:
    pass


def note():
    return 1


def fill(b, v):
    if v > 9:
        return None
    held = v
    b.n = held
    note()
"""


def _stated_fields(source: str, name: str = "fill") -> list:
    """``(plain_stores, fields)`` of each completed arm of ``name``'s own
    reduction that states a field."""
    from sugar_lift_py_tests.outcome import Completed
    from sugar_lift_py_tests.tree_enumerate import function_universe_outcome

    outcome = function_universe_outcome(_function(_tree(source), name))
    return [
        (face.value.plain_stores, face.value.fields)
        for face in outcome.exits
        if isinstance(face, Completed) and face.value.fields
    ]


def test_a_field_stored_before_code_that_reaches_no_object_is_read_per_arm() -> None:
    """``b.n = held`` after an early ``return`` and before ``note()``, a
    source function that runs no code: the store is the last of ``n`` at
    the top level and nothing after it may change it, so each arm that ran
    to the end reads what the store put there, through its key, in the
    context it left (#7757 step 7).  The arm the early ``return`` ended
    states nothing.  The quiet tail stated nothing here (a call follows the
    store, and ``held`` is a local, no parameter)."""
    stated = _stated_fields(_STORED_BEFORE_CODE)
    assert stated
    for plain_stores, fields in stated:
        assert plain_stores == (("b", "n"),)
        assert [(param, attr) for param, attr, _value in fields] == [("b", "n")]


@pytest.mark.parametrize(
    "after",
    [
        "    other.poke()",
        "    print(v)",
        "    if v:\n        b.n = 0",
        "    other.n = 3",
    ],
    ids=[
        "method-call",
        "builtin-over-a-formal",
        "store-under-a-branch",
        "alias-store",
    ],
)
def test_a_field_code_after_it_may_change_is_never_stated(after: str) -> None:
    """``b.n = v`` followed by code that may change ``b.n``: a method call
    on another parameter (it may be the same object), a builtin over a
    formal (its dunders run), a later store of ``n`` under a branch, a store
    of ``n`` on another parameter -- nothing is stated, and a caller's read
    of ``n`` stays undecided (#7757 step 7)."""
    source = (
        "class Box:\n"
        "    pass\n"
        "\n"
        "\n"
        "def fill(b, v, other):\n"
        "    b.n = v\n"
        f"{after}\n"
    )
    assert _stated_fields(source) == []
