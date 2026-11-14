"""A name nothing binds is a NameError halt, never a free variable (#7757 item 30).

Reading a name that is not local, not a parameter, not module-level, not
imported and not a builtin raises ``NameError``. The read is a halt with a
``NameErrorEffect``; a bound read still completes.
"""

from __future__ import annotations

from sugar_lift_py_tests.context_manager_resolution import TreeConstructionContextV1
from sugar_lift_py_tests.effect import NameErrorEffect
from sugar_lift_py_tests.outcome import Completed, Halted
from sugar_lift_python_source.canonical import blake3_512_of
from sugar_source_tree.nodes import FunctionDef, LanguageCallee, Name
from sugar_source_tree.tree import SourceFile


def _function_exits(source: str, *, fname: str = "f"):
    tree = SourceFile(
        (source, "unbound_name.py", blake3_512_of(source.encode())),
        construction_context=TreeConstructionContextV1.for_source_call_construction(),
    )
    function = next(
        node
        for node in tree.nodes()
        if isinstance(node, FunctionDef) and node.name == fname
    )
    return function.sugar().desugar(None).exits


def test_bound_parameter_read_completes() -> None:
    exits = _function_exits("def f(z):\n    return z\n")
    assert not [e for e in exits if isinstance(e, Halted)], exits
    assert len([e for e in exits if isinstance(e, Completed)]) == 1, exits


def test_unbound_read_halts_with_name_error() -> None:
    exits = _function_exits("def f():\n    return nowhere_bound\n")
    assert not [e for e in exits if isinstance(e, Completed)], exits
    halted = [e for e in exits if isinstance(e, Halted)]
    assert len(halted) == 1, exits
    effect = halted[0].effect
    assert isinstance(effect, NameErrorEffect)
    assert effect.exception_name == "NameError"
    assert effect.name == "nowhere_bound"


def _name_bound_nowhere(source: str, name: str) -> bool:
    unit = SourceFile(
        (source, "unbound_name.py", blake3_512_of(source.encode())),
        construction_context=TreeConstructionContextV1.for_source_call_construction(),
    ).unit
    return unit.name_bound_nowhere(name)


def test_only_a_name_nothing_binds_is_unbound() -> None:
    assert _name_bound_nowhere("def f():\n    return y\n", "y")
    # module-level, import, parameter, builtin, implicit module name
    assert not _name_bound_nowhere("y = 1\ndef f():\n    return y\n", "y")
    assert not _name_bound_nowhere("import y\ndef f():\n    return y\n", "y")
    assert not _name_bound_nowhere("def f(y):\n    return y\n", "y")
    assert not _name_bound_nowhere("def f():\n    return len\n", "len")
    assert not _name_bound_nowhere("def f():\n    return __name__\n", "__name__")
    # bound in another scope, by a loop, a with target or an except name
    assert not _name_bound_nowhere(
        "def g():\n    y = 1\ndef f():\n    return y\n", "y"
    )
    assert not _name_bound_nowhere("for y in ():\n    pass\n", "y")
    assert not _name_bound_nowhere("with m() as (x, y):\n    pass\n", "y")
    # an attribute target binds no name
    assert _name_bound_nowhere("def f(o):\n    o.y = 1\n    return y\n", "y")
    # a star import or a dynamic global writer may bind it unseen
    assert not _name_bound_nowhere("from m import *\ndef f():\n    return y\n", "y")
    assert not _name_bound_nowhere(
        "globals()['y'] = 1\ndef f():\n    return y\n", "y"
    )


def test_a_dynamic_global_writer_is_known_by_its_binding() -> None:
    """``globals``, ``exec``, ... are writers by the binding the read
    reaches (``SourceUnit.language_callee_of``), never by the spelling
    (#7757)."""
    # A ``globals`` the module binds itself is no builtin: it writes no global.
    assert _name_bound_nowhere(
        "def globals():\n    return {}\n"
        "globals()['y'] = 1\ndef f():\n    return y\n",
        "y",
    )
    # A parameter named ``exec`` is no builtin either.
    assert _name_bound_nowhere(
        "def g(exec):\n    exec('y = 1')\ndef f():\n    return y\n", "y"
    )
    # The builtin under another name is still the writer.
    assert not _name_bound_nowhere(
        "from builtins import exec as run\nrun('y = 1')\n"
        "def f():\n    return y\n",
        "y",
    )
    # The builtin namespace: imported (a store through it binds no name the
    # source spells), or the module attribute the interpreter sets.
    assert not _name_bound_nowhere(
        "import builtins\nbuiltins.y = 1\ndef f():\n    return y\n", "y"
    )
    assert not _name_bound_nowhere(
        "__builtins__['y'] = 1\ndef f():\n    return y\n", "y"
    )


def test_a_shadowed_globals_is_not_a_dynamic_writer() -> None:
    source = "def f(globals):\n    return globals()\n"
    unit = SourceFile(
        (source, "unbound_name.py", blake3_512_of(source.encode())),
        construction_context=TreeConstructionContextV1.for_source_call_construction(),
    ).unit
    reads = [
        node
        for node in unit.typed_module.walk()
        if isinstance(node, Name) and node.id == "globals"
    ]
    assert reads
    assert not any(unit.reads_dynamic_global_writer(node) for node in reads)
    builtin = "def f():\n    return globals()\n"
    unit = SourceFile(
        (builtin, "unbound_name.py", blake3_512_of(builtin.encode())),
        construction_context=TreeConstructionContextV1.for_source_call_construction(),
    ).unit
    (read,) = [
        node
        for node in unit.typed_module.walk()
        if isinstance(node, Name) and node.id == "globals"
    ]
    assert unit.language_callee_of(read) is LanguageCallee.BUILTIN_GLOBALS
    assert unit.reads_dynamic_global_writer(read)
