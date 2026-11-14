"""A name is resolved by the binding its read reaches, never by its spelling
(#7757).

``source_allocation_definition_for_call``, ``exception_type_identity`` and
``ClassDef._inherits_default_exception_constructor`` each read a name through
``SourceUnit.module_definition_at`` (a module ``def``/``class``), the builtin
namespace nothing rebinds (``builtin_reference_at``) or the one import table,
never through a raw lookup of the module's bindings of that spelling.  A name
a function shadows is that function's binding at every site.
"""

from __future__ import annotations

from sugar_lift_py_tests.context_manager_resolution import TreeConstructionContextV1
from sugar_lift_py_tests.ir import ctor, str_const
from sugar_source_tree.nodes import Call, ClassDef, Name
from sugar_source_tree.tree import SourceFile


def _source_file(source: str) -> SourceFile:
    from sugar_lift_python_source.canonical import blake3_512_of

    return SourceFile(
        (source, "binding_at_read.py", blake3_512_of(source.encode("utf-8"))),
        construction_context=TreeConstructionContextV1.for_test_without_workspace(),
    )


def _read(source_file, name, line):
    return next(
        node
        for node in source_file.nodes()
        if isinstance(node, Name)
        and node.id == name
        and node.line_col_span().start_line == line
    )


def _class(source_file, name, line):
    return next(
        node
        for node in source_file.nodes()
        if isinstance(node, ClassDef)
        and node.name == name
        and node.line_col_span().start_line == line
    )


def _call_of(source_file, name, line):
    return next(
        node
        for node in source_file.nodes()
        if isinstance(node, Call)
        and isinstance(node.func, Name)
        and node.func.id == name
        and node.line_col_span().start_line == line
    )


def test_an_allocation_callee_shadowed_by_a_parameter_is_the_parameter():
    source_file = _source_file(
        "class C:\n"  # 1
        "    pass\n"  # 2
        "def f(C):\n"  # 3
        "    return C()\n"  # 4
        "def g():\n"  # 5
        "    return C()\n"  # 6
        "def h():\n"  # 7
        "    class C:\n"  # 8
        "        pass\n"  # 9
        "    return C()\n"  # 10
    )
    def allocation(line):
        call = _call_of(source_file, "C", line)
        return call.unit.source_allocation_definition_for_call(call)

    assert allocation(4) is None
    assert allocation(10) is None
    module_class = allocation(6)
    assert isinstance(module_class, ClassDef)
    assert module_class.line_col_span().start_line == 1


def _builtin(name):
    return ctor("python:exception_type_identity", [str_const("builtins"), str_const(name)])


def test_an_exception_type_shadowed_by_a_parameter_is_the_parameter():
    source_file = _source_file(
        "from builtins import KeyError as VE\n"  # 1
        "class E(Exception):\n"  # 2
        "    pass\n"  # 3
        "def f(E):\n"  # 4
        "    raise E\n"  # 5
        "def g():\n"  # 6
        "    raise E\n"  # 7
        "def h(ValueError):\n"  # 8
        "    raise ValueError\n"  # 9
        "def k():\n"  # 10
        "    raise ValueError\n"  # 11
        "def m():\n"  # 12
        "    raise VE\n"  # 13
        "def n(VE):\n"  # 14
        "    raise VE\n"  # 15
    )
    def identity(name, line):
        read = _read(source_file, name, line)
        return read.unit.exception_type_identity(read)

    assert identity("E", 5) is None
    assert identity("ValueError", 9) is None
    assert identity("VE", 15) is None
    assert identity("ValueError", 11) == _builtin("ValueError")
    # The one import table's row, never the alias spelling.
    assert identity("VE", 13) == _builtin("KeyError")
    module_class = _class(source_file, "E", 2)
    lc = module_class.line_col_span()
    coordinate = (
        f"{module_class.unit.source_cid}:"
        f"{lc.start_line}:{lc.start_col}:{lc.end_line}:{lc.end_col}"
    )
    assert identity("E", 7) == ctor(
        "python:exception_type_identity",
        [str_const("source-class"), str_const(coordinate)],
    )


def test_an_exception_base_shadowed_by_a_parameter_is_the_parameter():
    source_file = _source_file(
        "class E(Exception):\n"  # 1
        "    pass\n"  # 2
        "class D(E):\n"  # 3
        "    pass\n"  # 4
        "def f(D):\n"  # 5
        "    class M(D):\n"  # 6
        "        pass\n"  # 7
        "    return M\n"  # 8
        "def g():\n"  # 9
        "    class N(D):\n"  # 10
        "        pass\n"  # 11
        "    return N\n"  # 12
    )
    shadowed = _class(source_file, "M", 6)
    module_base = _class(source_file, "N", 10)
    assert shadowed._inherits_default_exception_constructor() is False
    assert module_base._inherits_default_exception_constructor() is True
