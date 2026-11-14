"""Every reader of a class's members asks the one class-namespace lookup
(#7757, leftovers of #8148).

``ClassDef.namespace_owner`` / ``namespace_binds`` decide what a class value
holds.  Three things follow, each tested here:

1. Every reader of a class's methods and attributes -- an instance's member
   read, call, comparison and store (``ObjectValue.class_member``), a mapping
   receiver's protocol owner, ``Cls.m(...)``, the ``__init__`` a class call
   runs (``ClassDef.initializer_entry``) -- reads that lookup; a name it does
   not decide is the one unanswered form, never the body's ``def``.
2. A class body's binding stands only when its own control flow decides it:
   a ``def`` under ``if c:``, an assignment in a ``try`` whose handler passes,
   a ``del`` under ``if c:`` leave the name undecided; an unconditional
   ``del`` unbinds it; a constant ``if`` and a ``finally`` decide.
3. A store through the class a method runs on (``cls.x`` in a classmethod,
   ``type(self).x``, ``self.__class__.x``) or through an alias (``K = C;
   K.x``) is a store on the class -- and on every subclass the method may
   run on.
"""

from __future__ import annotations

from sugar_lift_py_tests.context_manager_resolution import (
    SourceFragmentCoordinateV1,
    TreeConstructionContextV1,
)
from sugar_lift_py_tests.effect.raise_effect import UndeterminedRaiseEffect
from sugar_lift_py_tests.floor import MappingObjectValue, StringValue
from sugar_lift_py_tests.floor.class_definition_value import ClassDefinitionValue
from sugar_lift_py_tests.floor.object_value import ObjectValue
from sugar_lift_python_source.canonical import blake3_512_of
from sugar_source_tree.nodes import ClassDef, SourceUnit
from sugar_source_tree.tree import SourceFile

from frame_fresh import FRAME_FRESH


def _classes(source: str, name: str = "one_lookup.py") -> dict:
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


def _instance(class_value: ClassDefinitionValue, identity: str = "receiver"):
    """An instance of ``class_value`` made in the reading frame."""
    return ObjectValue(
        class_value.class_name,
        (),
        identity=identity,
        defining_class=class_value,
        allocation=FRAME_FRESH,
    )


def _unanswered(outcome, target: str) -> None:
    """``outcome`` is the one unanswered call of ``target``: owed, and its
    halt the undetermined raise of that callee."""
    (halt,) = outcome.halts()
    assert isinstance(halt.effect, UndeterminedRaiseEffect)
    assert halt.effect.producer_node_owner == f"UnknownCallee:{target}"
    assert outcome.owed_items()


# --- 1. the readers ------------------------------------------------------------

_DATACLASS = (
    "from dataclasses import dataclass\n"
    "\n"
    "@dataclass\n"
    "class P:\n"
    "    x: int\n"
)


def test_a_generated_eq_is_the_unanswered_call_never_identity() -> None:
    p_value = _class_value(_classes(_DATACLASS)["P"])
    left = _instance(p_value, "left")
    right = _instance(p_value, "right")

    # The dataclass wrote ``__eq__``: not the body's, so not decided here --
    # never "no method", which would compare identities.
    assert left.class_member("__eq__") == (False, None, None)
    assert left.has_method("__eq__") is None

    _unanswered(left.equals(right, "eq-site", None), "P.__eq__")


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
    "B.m = f\n"
)


def test_an_instance_call_of_a_stored_name_is_the_unanswered_call() -> None:
    receiver = _instance(_class_value(_classes(_STORED)["B"]))

    # Never A's ``m``: ``B.m = f`` may have run before the call.
    assert receiver.class_member("m") == (False, None, None)
    _unanswered(
        receiver.call_method_value("m", (), owner="test", blame="call-site"),
        "B.m",
    )


def test_an_instance_read_of_a_stored_name_is_the_unanswered_read() -> None:
    receiver = _instance(_class_value(_classes(_STORED)["B"]))

    outcome = receiver.attribute("m", "read-site", None)

    (halt,) = outcome.halts()
    assert isinstance(halt.effect, UndeterminedRaiseEffect)
    assert halt.effect.producer_node_owner == "ObjectValue.attribute"


def test_a_store_of_an_undecided_member_is_not_an_instance_field() -> None:
    receiver = _instance(_class_value(_classes(_STORED)["B"]))

    assert receiver.authenticates_plain_attribute_store("m") is False
    # A name no class binds is an ordinary instance field.
    assert receiver.authenticates_plain_attribute_store("fresh") is True


def test_a_class_call_of_a_stored_name_is_the_unanswered_call() -> None:
    b_value = _class_value(_classes(_STORED)["B"])

    _unanswered(
        b_value.call_method_value("m", (), owner="test", blame="class-call-site"),
        "B.m",
    )


def test_a_mapping_protocol_name_a_store_writes_is_undecided() -> None:
    m = _classes(
        "class M(dict):\n"
        "    def __getitem__(self, key):\n"
        "        return 7\n"
        "\n"
        "def g(self, key, default=None):\n"
        "    return default\n"
        "\n"
        "M.get = g\n"
        "M.__getitem__ = g\n"
    )["M"]
    receiver = MappingObjectValue(
        "M",
        (),
        identity="receiver",
        defining_class=_class_value(m),
        allocation=FRAME_FRESH,
    )

    # Neither the body's ``__getitem__`` nor dict's ``get`` is assumed.
    assert receiver._protocol_owner("__getitem__") == "undecided"
    assert receiver._protocol_owner("get") == "undecided"
    assert receiver._protocol_owner("__len__") == "dict"
    _unanswered(
        receiver.call_method_value(
            "get", (StringValue("k"),), owner="test", blame="get-site"
        ),
        "M.get",
    )


def test_the_initializer_is_the_one_lookups() -> None:
    classes = _classes(
        "from dataclasses import dataclass\n"
        "\n"
        "class A:\n"
        "    def __init__(self, x):\n"
        "        self.x = x\n"
        "\n"
        "def g(self):\n"
        "    pass\n"
        "\n"
        "A.__init__ = g\n"
        "\n"
        "@dataclass\n"
        "class D:\n"
        "    x: int\n"
        "\n"
        "class E(D):\n"
        "    pass\n"
        "\n"
        "class Plain:\n"
        "    def __init__(self, y):\n"
        "        self.y = y\n"
    )

    # A store to ``A.__init__``: neither A's ``def`` nor ``object``'s.
    assert classes["A"].initializer_entry() is None
    assert not SourceUnit.source_class_admits_source_constructor_frame(classes["A"])
    # E inherits D's generated ``__init__``: never ``object``'s zero formals.
    assert classes["E"].initializer_entry() is None
    assert not SourceUnit.source_class_admits_source_constructor_frame(classes["E"])
    plain = classes["Plain"].initializer_entry()
    assert isinstance(plain, ClassDef) and plain.name == "Plain"
    assert SourceUnit.source_class_admits_source_constructor_frame(classes["Plain"])


# --- 2. the class body's own control flow ----------------------------------------


def test_a_conditional_def_is_undecided_and_never_the_base() -> None:
    classes = _classes(
        "flag = input()\n"
        "\n"
        "class A:\n"
        "    def m(self):\n"
        "        return 'A'\n"
        "\n"
        "class B(A):\n"
        "    if flag:\n"
        "        def m(self):\n"
        "            return 'B'\n"
    )

    assert classes["B"].namespace_binds("m") is None
    assert classes["B"].namespace_owner("m") == (False, None)


def test_a_try_whose_handler_passes_is_undecided() -> None:
    b = _classes(
        "def make():\n"
        "    return 1\n"
        "\n"
        "class B:\n"
        "    try:\n"
        "        m = make()\n"
        "    except Exception:\n"
        "        pass\n"
    )["B"]

    assert b.namespace_binds("m") is None


def test_an_unconditional_del_unbinds_and_the_base_answers() -> None:
    classes = _classes(
        "class A:\n"
        "    def m(self):\n"
        "        return 'A'\n"
        "\n"
        "class B(A):\n"
        "    def m(self):\n"
        "        return 'B'\n"
        "    del m\n"
    )

    assert classes["B"].namespace_binds("m") is False
    decided, owner = classes["B"].namespace_owner("m")
    assert decided
    assert isinstance(owner, ClassDef) and owner.name == "A"


def test_a_conditional_del_is_undecided() -> None:
    b = _classes(
        "flag = input()\n"
        "\n"
        "class B:\n"
        "    def m(self):\n"
        "        return 'B'\n"
        "    if flag:\n"
        "        del m\n"
    )["B"]

    assert b.namespace_binds("m") is None
    assert b.namespace_value_is_body("m") is False


def test_the_bodys_own_control_flow_decides_where_it_can() -> None:
    b = _classes(
        "class B:\n"
        "    if True:\n"
        "        def taken(self):\n"
        "            return 1\n"
        "    if False:\n"
        "        def skipped(self):\n"
        "            return 2\n"
        "    try:\n"
        "        pass\n"
        "    finally:\n"
        "        last = 3\n"
    )["B"]

    assert b.namespace_binds("taken") is True
    assert b.namespace_binds("skipped") is False
    assert b.namespace_binds("last") is True


def test_a_dataclass_field_default_may_be_rewritten() -> None:
    p = _classes(
        "from dataclasses import dataclass, field\n"
        "\n"
        "@dataclass\n"
        "class P:\n"
        "    x: int = 0\n"
        "    xs: list = field(default_factory=list)\n"
    )["P"]

    # A constant default stays; a ``Field`` default is replaced or deleted.
    assert p.namespace_binds("x") is True
    assert p.namespace_binds("xs") is None


# --- 3. stores through the class a method runs on, and through an alias ----------


def test_a_classmethod_store_reaches_the_class_and_its_subclasses() -> None:
    classes = _classes(
        "class A:\n"
        "    @classmethod\n"
        "    def setup(cls):\n"
        "        cls.x = 1\n"
        "\n"
        "class B(A):\n"
        "    pass\n"
        "\n"
        "class C:\n"
        "    pass\n"
    )

    assert classes["A"].namespace_binds("x") is None
    assert classes["B"].namespace_binds("x") is None
    # A class the method never runs on is untouched.
    assert classes["C"].namespace_binds("x") is False


def test_type_of_self_and_dunder_class_stores_reach_the_class() -> None:
    classes = _classes(
        "class A:\n"
        "    def bump(self):\n"
        "        type(self).count = 1\n"
        "        self.__class__.seen = True\n"
        "        setattr(type(self), 'named', 2)\n"
        "        self.mine = 3\n"
        "\n"
        "class B(A):\n"
        "    pass\n"
    )

    for name in ("count", "seen", "named"):
        assert classes["A"].namespace_binds(name) is None, name
        assert classes["B"].namespace_binds(name) is None, name
    # ``self.mine`` is the instance's, never the class's.
    assert classes["A"].namespace_binds("mine") is False


def test_a_staticmethod_formal_is_not_the_class() -> None:
    a = _classes(
        "class A:\n"
        "    @staticmethod\n"
        "    def put(cls):\n"
        "        cls.x = 1\n"
    )["A"]

    assert a.namespace_binds("x") is False


def test_a_store_through_an_alias_is_a_store_on_the_class() -> None:
    classes = _classes(
        "class A:\n"
        "    pass\n"
        "\n"
        "class Other:\n"
        "    pass\n"
        "\n"
        "K = A\n"
        "L = K\n"
        "K.w = 1\n"
        "L.v = 2\n"
        "\n"
        "def f():\n"
        "    M = A\n"
        "    M.u = 3\n"
    )

    for name in ("w", "v", "u"):
        assert classes["A"].namespace_binds(name) is None, name
        assert classes["Other"].namespace_binds(name) is False, name
