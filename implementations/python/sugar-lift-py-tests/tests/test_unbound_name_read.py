"""A name nothing binds is a NameError halt, never a free variable (#7757 item 30).

Reading a name that is not local, not a parameter, not module-level, not
imported and not a builtin raises ``NameError``. The read is a halt with a
``NameErrorEffect``; a bound read still completes.
"""

from __future__ import annotations

from sugar_lift_py_tests.context_manager_resolution import TreeConstructionContextV1
from sugar_lift_py_tests.effect import NameErrorEffect
from sugar_lift_py_tests.outcome import Completed, Halted
from sugar_lift_py_tests.outcome.exit_set import outcome_to_exitset
from sugar_lift_python_source.canonical import blake3_512_of
from sugar_source_tree.nodes import FunctionDef
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
    return outcome_to_exitset(function.sugar().desugar(None)).exits


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
