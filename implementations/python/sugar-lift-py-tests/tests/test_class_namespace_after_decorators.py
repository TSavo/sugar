"""The one class-namespace lookup reads the class VALUE's namespace (#7757,
found by #8138).

``ClassDef.namespace_owner`` -- every implicit dunder read and every
zero-argument ``super()`` lookup -- asks each class of the MRO whether its
namespace holds the name (``ClassDef.namespace_binds``): the class body's
bindings, what creation and its decorators write, and the module's stores on
the class object.  A bare ``@dataclasses.dataclass`` writes ``__init__``,
``__repr__``, ``__eq__``, ... whatever its fields; an identity decorator its
flag; type creation ``__hash__`` beside a body ``__eq__``.  An unmodelled
decorator, a metaclass, a base's ``__init_subclass__``, or a store
``C.m = f`` / ``setattr(C, ...)`` the module makes leaves the name undecided
-- never "missing", never a later class's binding.
"""

from __future__ import annotations

from sugar_lift_py_tests.context_manager_resolution import (
    SourceFragmentCoordinateV1,
    TreeConstructionContextV1,
)
from sugar_lift_py_tests.effect.raise_effect import UndeterminedRaiseEffect
from sugar_lift_py_tests.floor import BuiltinSuperValue
from sugar_lift_py_tests.floor.class_definition_value import ClassDefinitionValue
from sugar_lift_py_tests.floor.object_value import ObjectValue
from sugar_lift_python_source.canonical import blake3_512_of
from sugar_source_tree.nodes import ClassDef
from sugar_source_tree.tree import SourceFile

from frame_fresh import FRAME_FRESH


def _classes(source: str, name: str = "namespace.py") -> dict:
    """Every module ``class`` statement of ``source``, by name."""
    tree = SourceFile(
        (source, name, blake3_512_of(source.encode())),
        construction_context=TreeConstructionContextV1.for_test_without_workspace(),
    )
    return {node.name: node for node in tree.root.body if isinstance(node, ClassDef)}


def _class_value(statement: ClassDef) -> ClassDefinitionValue:
    """A class value built from ``statement`` alone (no methods carried)."""
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


# --- a dataclass's generated methods are its own ------------------------------

_DATACLASS_SUBCLASS = (
    "from dataclasses import dataclass\n"
    "\n"
    "class A:\n"
    "    def __init__(self):\n"
    "        self.a = 1\n"
    "\n"
    "@dataclass\n"
    "class B(A):\n"
    "    x: int\n"
    "\n"
    "class C(B):\n"
    "    def __init__(self):\n"
    "        super().__init__(1)\n"
)


def test_super_in_a_subclass_reaches_the_dataclass_generated_init() -> None:
    classes = _classes(_DATACLASS_SUBCLASS)
    b, c = classes["B"], classes["C"]

    decided, owner = c.namespace_owner("__init__", after=c)

    # C, B, A, object: B's ``@dataclass`` wrote ``__init__``; A's is never
    # reached.
    assert decided
    assert isinstance(owner, ClassDef) and owner.name == "B"
    assert b.namespace_binds("__init__") is True
    # Its value is the decorator's, not one B's body bound.
    assert b.namespace_value_is_body("__init__") is False


def test_super_init_selecting_a_generated_init_is_the_unanswered_call() -> None:
    classes = _classes(_DATACLASS_SUBCLASS)
    c_value = _class_value(classes["C"])
    receiver = ObjectValue(
        "C",
        (),
        identity="receiver",
        defining_class=c_value,
        allocation=FRAME_FRESH,
    )

    outcome = BuiltinSuperValue(c_value, receiver).call_method_value(
        "__init__", (), owner="test", blame="super-init"
    )

    (halt,) = outcome.halts()
    assert isinstance(halt.effect, UndeterminedRaiseEffect)
    assert halt.effect.producer_node_owner == "UnknownCallee:super.__init__"
    assert outcome.owed_items()


def test_a_bare_dataclass_writes_its_methods_whatever_its_fields() -> None:
    p = _classes(
        "from dataclasses import dataclass\n"
        "\n"
        "@dataclass\n"
        "class P:\n"
        "    x: int\n"
    )["P"]

    for name in ("__init__", "__repr__", "__eq__", "__hash__", "__match_args__"):
        assert p.namespace_owner(name) == (True, p), name
    # Written by version (3.13): undecided.
    assert p.namespace_owner("__replace__") == (False, None)
    # An annotation alone binds nothing, and the decorator writes nothing
    # under a field with no ``Field`` default.
    assert p.namespace_binds("x") is False


def test_an_identity_decorator_writes_its_flag() -> None:
    p = _classes(
        "from typing import final\n"
        "\n"
        "@final\n"
        "class P:\n"
        "    def m(self):\n"
        "        return 1\n"
    )["P"]

    assert p.namespace_binds("__final__") is True
    assert p.namespace_value_is_body("m") is True


# --- an unmodelled decorator, a metaclass, __init_subclass__ ------------------


def test_an_unmodelled_decorator_leaves_every_unbound_name_undecided() -> None:
    classes = _classes(
        "def deco(cls):\n"
        "    cls.m = lambda self: 'deco'\n"
        "    return cls\n"
        "\n"
        "class A:\n"
        "    def m(self):\n"
        "        return 'A'\n"
        "\n"
        "@deco\n"
        "class B(A):\n"
        "    def n(self):\n"
        "        return 'B'\n"
        "\n"
        "class C(B):\n"
        "    def m(self):\n"
        "        return super().m()\n"
    )
    b, c = classes["B"], classes["C"]

    # Never A's ``m``: B's decorator may have written one.
    assert c.namespace_owner("m", after=c) == (False, None)
    assert b.namespace_binds("m") is None
    # A name the body binds is B's, but its value may be the decorator's.
    assert b.namespace_binds("n") is True
    assert b.namespace_value_is_body("n") is False


def test_an_imported_class_decorator_is_never_answered_by_object() -> None:
    b = _classes(
        "import functools\n"
        "\n"
        "@functools.total_ordering\n"
        "class B:\n"
        "    def __eq__(self, other):\n"
        "        return True\n"
        "\n"
        "    def __lt__(self, other):\n"
        "        return True\n"
    )["B"]

    # ``total_ordering`` writes ``__le__``; ``object.__le__`` is not the answer.
    assert b.namespace_owner("__le__") == (False, None)
    assert b.namespace_owner("__lt__") == (True, b)


def test_a_metaclass_leaves_the_class_and_its_subclasses_undecided() -> None:
    classes = _classes(
        "class Meta(type):\n"
        "    pass\n"
        "\n"
        "class K(metaclass=Meta):\n"
        "    def m(self):\n"
        "        return 1\n"
        "\n"
        "class L(K):\n"
        "    pass\n"
    )

    assert classes["K"].namespace_binds("extra") is None
    assert classes["L"].namespace_binds("extra") is None
    assert classes["L"].namespace_owner("m") == (False, None)


def test_a_bases_init_subclass_leaves_its_subclasses_undecided() -> None:
    classes = _classes(
        "class Base:\n"
        "    def __init_subclass__(cls):\n"
        "        cls.extra = 1\n"
        "\n"
        "class Sub(Base):\n"
        "    pass\n"
    )

    assert classes["Base"].namespace_binds("extra") is False
    assert classes["Sub"].namespace_binds("extra") is None


# --- stores the module makes on the class object -------------------------------

_STORED = (
    "class A:\n"
    "    def m(self):\n"
    "        return 'A'\n"
    "\n"
    "class B(A):\n"
    "    def n(self):\n"
    "        return 'B'\n"
    "\n"
    "def f(self):\n"
    "    return 'f'\n"
    "\n"
)


def test_an_attribute_store_on_the_class_is_undecided_not_the_base() -> None:
    b = _classes(_STORED + "B.m = f\n")["B"]

    assert b.namespace_owner("m") == (False, None)


def test_a_store_over_a_body_binding_is_undecided() -> None:
    b = _classes(_STORED + "B.n = f\n")["B"]

    assert b.namespace_binds("n") is None
    assert b.namespace_value_is_body("n") is False


def test_setattr_and_delattr_by_binding_are_stores() -> None:
    assert _classes(_STORED + "setattr(B, 'm', f)\n")["B"].namespace_binds("m") is None
    assert _classes(_STORED + "delattr(B, 'n')\n")["B"].namespace_binds("n") is None
    # A name not spelled as a constant may be any name.
    any_name = _classes(_STORED + "name = 'm'\nsetattr(B, name, f)\n")["B"]
    assert any_name.namespace_binds("anything") is None


def test_a_store_on_a_parameter_of_the_same_spelling_is_not_the_class() -> None:
    b = _classes(_STORED + "def g(B):\n    B.m = f\n")["B"]

    decided, owner = b.namespace_owner("m")

    assert decided
    assert isinstance(owner, ClassDef) and owner.name == "A"


# --- type creation and the body --------------------------------------------------


def test_eq_without_hash_holds_hash() -> None:
    e = _classes(
        "class E:\n"
        "    def __eq__(self, other):\n"
        "        return True\n"
    )["E"]

    # Type creation sets ``__hash__ = None``: never ``object.__hash__``.
    assert e.namespace_owner("__hash__") == (True, e)


def test_an_annotation_alone_binds_nothing_and_creation_names_are_undecided() -> None:
    p = _classes("class P:\n    x: int\n    y: int = 0\n")["P"]

    # The body's own statements tell ``x: int`` from ``y: int = 0``.
    assert p.namespace_binds("x") is False
    assert p.namespace_binds("y") is True
    assert p.namespace_owner("__doc__") == (False, None)


def test_a_plain_class_answers_as_before() -> None:
    p = _classes("class P:\n    def m(self):\n        return 1\n")["P"]

    assert p.namespace_owner("m") == (True, p)
    assert p.namespace_owner("zz") == (True, None)
    assert p.namespace_owner("__getattribute__") == (True, "object")
    assert p.namespace_value_is_body("m") is True
