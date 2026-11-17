"""A read the module's own run makes of a name a module ``def`` or ``class``
binds is the value its statement bound, never the free name (#7757).

The 13e3413ad nine-step lane refused about 200 functions and classes by
``proofir.scope.ScopedFormula`` (``illegal free var(s): <name>``) where the
name is a module ``def`` or ``class`` read by the module's own run as a
value, and by nothing outside it:

- ``get_resampler.__doc__ = Resampler.__doc__`` (pandas ``core/resample.py``),
  ``tensordot.__doc__ = ...`` (numpy ``linalg/_linalg.py``): a plain ``def``;
- ``Rolling.__doc__ = Window.__doc__`` (pandas ``core/window/rolling.py``),
  ``@doc(IndexingMixin.loc)``, ``_cParserHighMemory = CParserHighMemory``,
  ``params=[None, MockEngineDecorator]``: a class;
- ``_in_ops_funcs = (_in, _not_in)``, ``f=_compose(_replace_locals, ...)``
  in a default, ``rules = [Holiday(..., observance=nearest_workday)]`` and
  ``_add = staticmethod(chebadd)`` in a class body.

The module run threaded a ``def``/``class`` name only for a reader outside
the module block (``module_threaded_names``), so the statement bound nothing
for its own run's reads, and each stayed the bare name.  Such a statement now
binds its value for the statements after it (``_local_definition_binding``):
a class or decorated ``def`` its value under its key, a plain ``def`` its
function value under its key, as a local ``def`` does.

THE DISCRIMINATION: a name the run reads only by name -- a call's callee, a
bare-name decorator or base, a raised or handled class -- is no value read
(``module_run_value_reads``), and binds nothing new; nor does a method a class
body binds under a module-read spelling.
"""

from __future__ import annotations

from sugar_source_tree.nodes import Assign, DecoratedDefinitionRef

from test_module_global_evaluation_reference import _function, _source

PLAIN_DEF_ALIAS = "def helper():\n    return 1\n\n\nALIAS = helper\n"

PLAIN_DEF_DOC_STORE = (
    "def helper():\n    return 1\n\n\nhelper.__doc__ = 'one'\n\n\ndef f():\n"
    "    return 0\n"
)

CLASS_ATTRIBUTE = "class Box:\n    size = 1\n\n\nSIZE = Box.size\n"

CLASS_BODY_READ = (
    "def double(x):\n    return 2 * x\n\n\n"
    "class Rule:\n    observance = double\n"
)

CALL_ONLY = "def helper():\n    return 1\n\n\nX = helper()\n"

BY_NAME_ONLY = (
    "def deco(f):\n    return f\n\n\n"
    "class Base(Exception):\n    pass\n\n\n"
    "@deco\nclass Box(Base):\n    pass\n\n\n"
    "try:\n    raise Base()\nexcept Base:\n    pass\n"
)

METHOD_SPELLING = (
    "def size():\n    return 1\n\n\n"
    "class Box:\n    def size(self):\n        return 2\n\n\n"
    "S = size\n"
)


def _unit(text: str):
    return _function(_source(text + "\n\ndef zz():\n    return 0\n"), "zz").unit


def _run_statements(text: str):
    unit = _unit(text)
    statements, _states = unit.module_run(unit.typed_module)
    return unit, statements


def _assigned(statements, name: str):
    for statement in statements:
        if isinstance(statement, Assign) and any(
            getattr(target, "id", None) == name for target in statement.targets
        ):
            return statement.value
    raise AssertionError(f"no module assignment of {name}: {statements}")


def _definition_value(read, name: str) -> None:
    assert isinstance(read, DecoratedDefinitionRef), read
    assert read.definition_name == name
    assert isinstance(getattr(read, "evaluation", None), str), read


def test_the_value_reads_are_the_module_runs_own() -> None:
    assert "helper" in _unit(PLAIN_DEF_ALIAS).module_run_value_reads()
    assert "ALIAS" not in _unit(PLAIN_DEF_ALIAS).module_run_value_reads()
    assert "helper" in _unit(PLAIN_DEF_DOC_STORE).module_run_value_reads()
    assert "Box" in _unit(CLASS_ATTRIBUTE).module_run_value_reads()
    # A class body runs with the module: its read of a module ``def``.
    assert "double" in _unit(CLASS_BODY_READ).module_run_value_reads()


def test_a_plain_def_read_by_the_module_run_is_its_function_value() -> None:
    _unit_, statements = _run_statements(PLAIN_DEF_ALIAS)
    _definition_value(_assigned(statements, "ALIAS"), "helper")


def test_a_class_read_by_the_module_run_is_its_statements_value() -> None:
    _unit_, statements = _run_statements(CLASS_ATTRIBUTE)
    read = _assigned(statements, "SIZE")
    assert type(read).__name__ == "Attribute", read
    _definition_value(read.value, "Box")


def test_a_call_by_name_alone_binds_nothing_new() -> None:
    # THE DISCRIMINATION: a call's callee resolves by name, as it did.
    unit, statements = _run_statements(CALL_ONLY)
    assert "helper" not in unit.module_run_value_reads()
    call = _assigned(statements, "X")
    assert type(call.func).__name__ == "Name", call.func


def test_a_decorator_a_base_and_a_handled_class_are_no_value_read() -> None:
    reads = _unit(BY_NAME_ONLY).module_run_value_reads()
    assert "deco" not in reads, reads
    assert "Base" not in reads, reads


def test_a_method_of_a_module_read_spelling_is_the_class_bodys_own() -> None:
    # The module ``def size`` binds its value for ``S = size``; the method
    # ``size`` binds nothing in the module's run.
    unit, statements = _run_statements(METHOD_SPELLING)
    assert "size" in unit.module_run_value_reads()
    read = _assigned(statements, "S")
    _definition_value(read, "size")
    assert read.definition.line_col_span().start_line == 1, read.definition
