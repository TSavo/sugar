"""Whether a name may hold a class is read off its value (#7757, follow-up
to #8166).

1. A name bound to a call holds what the callee's value decides: a call of a
   source class whose own ``__new__`` lookup decides an instance
   (``ClassDef.call_yields_an_instance``), a builtin whose result type the
   language fixes, an ``async def``'s coroutine -- none of them a class.  A
   call of a module ``def`` is its contract's, never read off its body, and
   like any call the tree cannot decide stays any class the module hands on
   (#8166's answer).
2. A name a class body binds is that class body's, never the module's.

(A constructor frame is no longer rebuilt at a call: the per-call rebuild,
``SourceVisibleCallFrameV1.bind_node_actuals``, is deleted, #7757 N4.)
"""

from __future__ import annotations

from sugar_lift_py_tests.context_manager_resolution import TreeConstructionContextV1
from sugar_lift_python_source.canonical import blake3_512_of
from sugar_source_tree.nodes import ClassDef
from sugar_source_tree.tree import SourceFile


def _tree(source: str, name: str) -> SourceFile:
    return SourceFile(
        (source, name, blake3_512_of(source.encode())),
        construction_context=TreeConstructionContextV1.for_test_without_workspace(),
    )


def _statements(source: str, name: str = "by_value.py") -> dict:
    """Every module ``class`` statement of ``source``, by name."""
    tree = _tree(source, name)
    return {node.name: node for node in tree.root.body if isinstance(node, ClassDef)}


# Box is handed on (an actual of ``keep``): a store through any name that may
# be any class the module hands on lands on it.
_HANDED = (
    "class Box:\n"
    "    pass\n"
    "\n"
    "def keep(c):\n"
    "    return c\n"
    "\n"
    "keep(Box)\n"
)


# --- 1. a call holds what its callee's value decides ---------------------------


def test_an_instance_of_a_source_class_is_no_class() -> None:
    classes = _statements(
        _HANDED
        + "o = Box()\n"
        "o.x = 1\n"
        "\n"
        "def f():\n"
        "    p = Box()\n"
        "    p.y = 1\n"
    )

    # ``object.__new__`` runs: ``o`` and ``p`` hold instances, never a class.
    box = classes["Box"]
    assert box.call_yields_an_instance(box.unit.class_namespace_stores)
    assert classes["Box"].namespace_binds("x") is False
    assert classes["Box"].namespace_binds("y") is False


def test_a_builtin_is_no_class_and_a_def_s_call_is_its_contract_s() -> None:
    classes = _statements(
        _HANDED
        + "d = dict()\n"
        "d.x = 1\n"
        "\n"
        "def new():\n"
        "    return Box()\n"
        "\n"
        "q = new()\n"
        "q.y = 1\n"
        "\n"
        "def items():\n"
        "    yield Box\n"
        "\n"
        "g = items()\n"
        "g.z = 1\n"
        "\n"
        "async def fetch():\n"
        "    return Box\n"
        "\n"
        "c = fetch()\n"
        "c.w = 1\n"
    )

    assert classes["Box"].namespace_binds("x") is False
    # A module ``def``'s call is a call like any other (#7757, the owner's
    # ruling of 2026-11-15): what it returns is its contract's to state,
    # never read here off its body, so it may be any class handed on.
    assert classes["Box"].namespace_binds("y") is None
    assert classes["Box"].namespace_binds("z") is None
    # An ``async def``'s call is a coroutine, by its header.
    assert classes["Box"].namespace_binds("w") is False


def test_a_def_returning_a_class_holds_that_class() -> None:
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


def test_a_call_that_may_return_a_class_stays_undecided() -> None:
    classes = _statements(
        _HANDED
        + "def make(c):\n"
        "    return c\n"
        "\n"
        "K = make(Box)\n"
        "K.x = 1\n"
        "\n"
        "class Meta(type):\n"
        "    pass\n"
        "\n"
        "class Made(metaclass=Meta):\n"
        "    pass\n"
        "\n"
        "m = Made()\n"
        "m.y = 1\n"
        "\n"
        "class Odd:\n"
        "    def __new__(cls):\n"
        "        return Box\n"
        "\n"
        "n = Odd()\n"
        "n.z = 1\n"
    )

    # ``make`` returns its parameter: any class the module hands on.
    assert classes["Box"].namespace_binds("x") is None
    # A metaclass's ``__call__`` and an own ``__new__`` may return a class.
    stores = classes["Box"].unit.class_namespace_stores
    assert not classes["Made"].call_yields_an_instance(stores)
    assert classes["Box"].namespace_binds("y") is None
    assert not classes["Odd"].call_yields_an_instance(stores)
    assert classes["Box"].namespace_binds("z") is None


def test_a_builtin_is_known_by_its_binding_never_its_spelling() -> None:
    classes = _statements(
        _HANDED
        + "def list():\n"
        "    return Box\n"
        "\n"
        "o = list()\n"
        "o.x = 1\n"
    )

    # The module's ``list`` shadows the builtin: its call returns ``Box``.
    assert classes["Box"].namespace_binds("x") is None


def test_a_store_through_an_instance_does_not_decide_its_own_class_new() -> None:
    classes = _statements(
        _HANDED
        + "o = Box()\n"
        "o.__new__ = 1\n"
        "o.x = 1\n"
    )

    # Read with every call a class, ``o.__new__ = 1`` may write ``Box``'s
    # ``__new__``: the call is not decided an instance, ``o`` stays any
    # class handed on.
    assert classes["Box"].namespace_binds("x") is None


# --- 2. a class-body name is the class body's -----------------------------------


def test_a_class_body_name_never_leaks_to_module_scope() -> None:
    classes = _statements(
        "class Box:\n"
        "    pass\n"
        "\n"
        "class Holder:\n"
        "    K = Box\n"
        "    K.y = 1\n"
        "\n"
        "K = []\n"
        "K.x = 1\n"
    )

    # The module's ``K`` is a list: ``Holder.K`` is no binding of it.
    assert classes["Box"].namespace_binds("x") is False
    # The class body's own ``K`` is ``Box``.
    assert classes["Box"].namespace_binds("y") is None


def test_a_class_body_read_falls_back_to_the_module_binding() -> None:
    classes = _statements(
        "class Box:\n"
        "    pass\n"
        "\n"
        "K = Box\n"
        "\n"
        "class Holder:\n"
        "    K.x = 1\n"
        "    K = []\n"
    )

    # ``LOAD_NAME``: before the body binds ``K`` it reads the module's.
    assert classes["Box"].namespace_binds("x") is None
