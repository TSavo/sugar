"""A function-local ``import`` answers the roll where its row is minted.

Since #8983 an import replaces a binding the threading holds of its name in
every frame, as the one import table's row (``ImportBindingRef``).  A
function frame holds every local unbound until its body binds it
(``FunctionDef._body_scope``), so every function-local ``import`` mints the
row at its alias.  Every read the table rows with the import's target keeps
its own name (``Name.substitute``) and answers for itself, so nothing
constructed the row: the pandas board (main scorecard, #8416) went from 0 to
179 construction panics, 165 of them ``ImportBindingRef registered but never
answered the roll call`` at a function-local import's alias
(``pandas/conftest.py:114:11``, ``core/internals/__init__.py:21:11``,
``core/arrays/numeric.py:73:15``, ...).

The row is a value of the scope and answers where it is minted
(``_minted_binding_reference``); a read that is the row constructs it and
answers again, present or refused by name.  The roll-call check stays.
"""

from sugar_lift_python_source.source_oracle import path_source
from sugar_lift_py_tests.context_manager_resolution import TreeConstructionContextV1
from sugar_source_tree.reporter import CollectingReporter
from sugar_source_tree.roll_call import discharge
from sugar_source_tree.tree import SourceFile


def _report(tmp_path, source: str):
    path = tmp_path / "function_local_import.py"
    path.write_text(source)
    return discharge(
        SourceFile(
            path_source(str(path)),
            reporter=CollectingReporter(),
            construction_context=TreeConstructionContextV1.for_test_without_workspace(),
        )
    )


def _import_rows(entries):
    return [e for e in entries if e.kind == "ImportBindingRef"]


# The shape of ``pandas/conftest.py:112`` (``pytest_sessionstart``): two
# function-local imports, one read in the body, one only in a nested def.
CONFTEST_SHAPE = (
    "def session_start(session):\n"
    "    import doctest\n"
    "    import inspect\n"
    "    orig = doctest.DocTestFinder._from_module\n"
    "    def _from_module(self, module, object):\n"
    "        if inspect.isfunction(object):\n"
    "            return True\n"
    "        return orig(self, module, object)\n"
    "    doctest.DocTestFinder._from_module = _from_module\n"
)


def test_a_function_local_import_answers_the_roll(tmp_path):
    report = _report(tmp_path, CONFTEST_SHAPE)
    # The rows were minted: the test reads the path the board panicked on.
    assert _import_rows(report.roster), report.roster
    assert not _import_rows(report.minority), report.minority


# The shape of ``pandas/core/internals/__init__.py:19`` (module
# ``__getattr__``): the import read only in an ``if`` arm.
GETATTR_SHAPE = (
    "def __getattr__(name):\n"
    "    import warnings\n"
    "    from os import sep\n"
    "    if name == 'x':\n"
    "        warnings.warn(sep)\n"
    "        return 1\n"
    "    raise AttributeError(name)\n"
)


def test_an_import_read_in_one_arm_answers_the_roll(tmp_path):
    report = _report(tmp_path, GETATTR_SHAPE)
    assert _import_rows(report.roster), report.roster
    assert not _import_rows(report.minority), report.minority


def test_an_import_never_read_answers_the_roll(tmp_path):
    report = _report(tmp_path, "def f():\n    import os\n    return 1\n")
    assert _import_rows(report.roster), report.roster
    assert not _import_rows(report.minority), report.minority


def test_the_row_a_read_is_answers_the_roll(tmp_path):
    # After a loop whose items import the name, the read is the import's
    # row (#8983): it constructs it, and it is answered either way.
    report = _report(
        tmp_path,
        "def f():\n"
        "    m = None\n"
        "    for i in [1, 2]:\n"
        "        import os as m\n"
        "    return m\n",
    )
    assert _import_rows(report.roster), report.roster
    assert not _import_rows(report.minority), report.minority
