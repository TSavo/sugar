"""A read of a name no one statement binds on every route is the join the
threading builds, never the free name (#7757, carry undecided).

The pandas nine-step lane (run 43960179946) refused about 39 functions by
``proofir.scope.ScopedFormula`` (``illegal free var(s): <name>``) where the
name is bound, but not by one import on every route:

- ``if HAS_PYARROW: import pyarrow as pa`` (``pa``, ``pc``, ``ne``,
  ``groupby`` under ``if TYPE_CHECKING``), read in a function: the name was
  not threaded (an ``import`` binds no key), the lexical table rows no read of
  it (the import meets unbound at the ``if``'s join), so the read stayed the
  free name;
- ``if TYPE_CHECKING: import numba`` / ``else: numba =
  import_optional_dependency("numba")`` in a function, and every ``try:
  import m`` / ``except ...``: the threading joins the routes, but the
  import's arm (``ImportBindingRef``) had no receipt at its alias and was the
  free name;
- a ``def`` bound on one route of a module ``if``, and a name only a function
  binds through ``global`` (``global QApplication`` then an import).

Each read is now the binding under the guard of the route that bound it, and
a ``NameError`` halt under its complement (``GuardedBinding``, the one join an
``if`` or ``try`` carries a name out by; the module run starts such a name
unbound, as a function frame starts each local), or, for a name a function
rebinds through ``global``, the module global undecided.  The halt is kept;
nothing is decided that was not.

THE DISCRIMINATION: a unique, unconditional import is untouched -- its read
takes its row at its own coordinate, and no receipt is enrolled at its alias.
"""

from __future__ import annotations

from pathlib import Path

from sugar_lift_python_source.source_oracle import path_source
from sugar_source_tree.nodes import GuardedBindingRead

from sugar_lift_py_tests.effect import NameErrorEffect
from sugar_lift_py_tests.import_binding import authenticated_import_value_use_receipts
from sugar_lift_py_tests.outcome import Completed
from sugar_lift_py_tests.proofir.formulas import formula_from_ir
from sugar_lift_py_tests.proofir.scope import ScopedFormula
from sugar_lift_py_tests.proofir.sorts import UnknownSort

from test_import_bound_callee_is_closed import _function_outcome
from test_module_global_evaluation_reference import (
    _assert_undecided,
    _function,
    _returned,
    _source,
)

CONDITIONAL_IMPORT = (
    "import idn\n\n"
    "if idn.FLAG:\n"
    "    import pyarrow as pa\n\n\n"
    "def f():\n"
    "    return pa\n"
)

OPTIONAL_DEPENDENCY = (
    "from typing import TYPE_CHECKING\n\n"
    "from idn import import_optional_dependency\n\n\n"
    "def f():\n"
    "    if TYPE_CHECKING:\n"
    "        import numba\n"
    "    else:\n"
    "        numba = import_optional_dependency('numba')\n"
    "    return numba\n"
)

DEF_IN_ONE_BRANCH = (
    "import idn\n\n\n"
    "def f():\n"
    "    return helper\n\n\n"
    "if idn.FLAG:\n\n"
    "    def helper():\n"
    "        return 1\n"
)


def _receipts(tmp_path: Path, text: str):
    path = tmp_path / "m.py"
    path.write_text(text, encoding="utf-8")
    source, _, source_cid = path_source(str(path))
    receipts, _ = authenticated_import_value_use_receipts(
        tmp_path, path, source, source_cid, module_identities={}
    )
    return receipts


def _completed_posts_are_scoped(outcome) -> list:
    """Every completed face's post, scoped over ``out`` alone: constructing
    the scope is the law that refused these functions by the free name."""
    sort = UnknownSort(reason="lift is sort-silent; the compiler decides")
    allowed = {"out": sort}
    completed = [face for face in outcome.exits if isinstance(face, Completed)]
    assert completed, outcome.exits
    posts = []
    for face in completed:
        post = face.value.post()
        scoped = ScopedFormula(
            formula_from_ir(post, var_sorts=allowed), allowed_vars=allowed
        )
        assert scoped.formula.free_vars <= {"out"}, post
        posts.append(post)
    return posts


def _name_errors(outcome) -> set[str]:
    return {
        halt.effect.name
        for halt in outcome.halts()
        if isinstance(halt.effect, NameErrorEffect)
    }


def test_a_conditional_import_read_is_the_import_or_a_name_error() -> None:
    # The read is the join over the module ``if``: the import on the route
    # that ran it, ``NameError`` on the route that did not.
    read = _returned(_function(_source(CONDITIONAL_IMPORT)))
    assert isinstance(read, GuardedBindingRead), read
    outcome = _function_outcome(CONDITIONAL_IMPORT)
    assert "pa" in _name_errors(outcome), outcome.exits
    posts = _completed_posts_are_scoped(outcome)
    assert any("pyarrow" in repr(post) for post in posts), posts


def test_a_local_import_or_optional_dependency_read_is_never_the_free_name() -> None:
    # ``if TYPE_CHECKING: import numba`` / ``else: numba = <call>``: the
    # threading joins the two routes; the import's arm is the module, read at
    # its alias, never the free name ``numba``.
    _completed_posts_are_scoped(_function_outcome(OPTIONAL_DEPENDENCY))


def test_a_def_bound_in_one_branch_is_the_function_or_a_name_error() -> None:
    read = _returned(_function(_source(DEF_IN_ONE_BRANCH)))
    assert isinstance(read, GuardedBindingRead), read
    outcome = _function_outcome(DEF_IN_ONE_BRANCH)
    assert "helper" in _name_errors(outcome), outcome.exits
    _completed_posts_are_scoped(outcome)


def test_a_global_only_a_function_imports_is_undecided_never_the_free_name() -> None:
    # ``global QApplication`` then an import in a function body: the body
    # rebinds the module global whenever it runs, so every reader reads it
    # undecided -- the free ``global:`` input with no stated value -- never
    # the name read in its place.
    tree = _source(
        "def f():\n"
        "    return QApplication\n\n\n"
        "def init():\n"
        "    global QApplication\n"
        "    from qtpy.QtWidgets import QApplication\n"
    )
    unit = _function(tree).unit
    assert "QApplication" in unit.module_unthreaded_names()
    _assert_undecided(_returned(_function(tree)), "QApplication")


def test_the_binding_read_is_enrolled_at_the_alias_a_join_meets(
    tmp_path: Path,
) -> None:
    # The import meets unbound at the ``if``'s join: its own read is enrolled
    # at its alias (line 4), so the threading's arm of it is the import.  The
    # read in ``f`` (line 8) takes no row: no one import binds it there.
    receipts = [
        receipt
        for receipt in _receipts(tmp_path, CONDITIONAL_IMPORT)
        if receipt.target_symbol == "python:pyarrow"
    ]
    assert [receipt.use["useSite"]["startLine"] for receipt in receipts] == [4]
    assert receipts[0].use["exportedMemberPath"] == []


def test_a_unique_import_enrolls_nothing_at_its_alias(tmp_path: Path) -> None:
    # THE DISCRIMINATION: one import on every route; its read takes its own
    # row where it is read (line 5), and nothing is enrolled at the alias.
    receipts = _receipts(tmp_path, "import idn\n\n\ndef f():\n    return idn\n")
    assert [receipt.use["useSite"]["startLine"] for receipt in receipts] == [5]
