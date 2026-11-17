"""An import-bound read inside a dict display or a store target has its row (#7757).

The lexical import pass walks every expression for import-bound references,
but it read only an expression's ``Expression`` children.  A Dict display's
``key: value`` item is a structural part (``DictItem``), not an Expression, so
``{"k": np.nan}`` was never walked: the read of ``np.nan`` got no row, its
Attribute was constructed over the free name ``np``, and ``ScopedFormula``
refused the whole function with ``illegal free var(s): np``.  The pandas
nine-step lane (main d5dcbab5c) refused 352 functions by that owner; about
240 of them read an import inside a dict display.  The same pass read only an
assignment's value, never what its targets evaluate before they store
(``os.environ["TZ"] = tz`` reads ``os.environ``; so does ``del
os.environ["TZ"]``), never a lambda's defaults, and never a ``def``'s
annotations, which Python evaluates where the ``def`` runs unless the module
postpones them (``def f(self, ser: pd.Series)`` in a class body refused the
class, and every method that reads the class, by ``pd``).

Each read now takes the one row every other import-bound read takes, so it is
the one two-faced undecided read (``ImportMemberValue.read_faces``): the
closed reference under its completes atom, an undetermined raise under the
complement, the ``undecided`` member owed under the import's target symbol.
Nothing is decided that was not, and no halt is dropped.

THE DISCRIMINATION: a head that is not uniquely import-bound (an optional
import, a name that is not imported) still gets no row, inside a dict or
not: the walk reaches more places, the law it applies there is unchanged.
An optional import's read is the join the threading carries past its
``try`` (the import, or a ``NameError`` halt), never the free name (#7757).
"""

from __future__ import annotations

from pathlib import Path

import pytest

from sugar_lift_py_tests.import_binding import (
    AuthenticatedImportUseV1,
    authenticated_import_value_use_receipts,
)
from sugar_lift_py_tests.outcome import Completed
from sugar_lift_py_tests.proofir.formulas import formula_from_ir
from sugar_lift_py_tests.proofir.scope import ScopedFormula
from sugar_lift_py_tests.proofir.sorts import UnknownSort
from sugar_lift_python_source.source_oracle import path_source

from test_import_bound_callee_is_closed import _function_outcome


def _receipts(tmp_path: Path, text: str) -> list[AuthenticatedImportUseV1]:
    path = tmp_path / "m.py"
    path.write_text(text, encoding="utf-8")
    source, _, source_cid = path_source(str(path))
    receipts, _ = authenticated_import_value_use_receipts(
        tmp_path, path, source, source_cid, module_identities={}
    )
    return receipts


def _targets(receipts) -> set[str]:
    return {receipt.target_symbol for receipt in receipts}


def _scoped_posts(source: str, formals: tuple[str, ...]) -> list[ScopedFormula]:
    """Every completed face's post, scoped over the formals and ``out``.

    Constructing the scope is the law that refused these functions: it
    panics on a free name no contract declares."""
    sort = UnknownSort(reason="lift is sort-silent; the compiler decides")
    allowed = {name: sort for name in (*formals, "out")}
    outcome = _function_outcome(source)
    completed = [face for face in outcome.exits if isinstance(face, Completed)]
    assert completed, outcome.exits
    return [
        ScopedFormula(
            formula_from_ir(face.value.post(), var_sorts=allowed),
            allowed_vars=allowed,
        )
        for face in completed
    ]


@pytest.mark.parametrize(
    ("text", "target"),
    [
        ("import idn\nd = {'k': idn.CONST}\n", "python:idn.CONST"),
        ("import idn\nd = {idn.KEY: 1}\n", "python:idn.KEY"),
        ("import idn\nd = {'k': [1, idn.CONST]}\n", "python:idn.CONST"),
        ("import idn\nd = {**{'k': idn.CONST}}\n", "python:idn.CONST"),
        ("import idn\nf = lambda x=idn.CONST: x\n", "python:idn.CONST"),
    ],
    ids=["dict-value", "dict-key", "dict-nested-list", "dict-spread", "lambda-default"],
)
def test_a_read_in_a_dict_item_or_lambda_default_has_its_row(
    tmp_path: Path, text: str, target: str
) -> None:
    assert target in _targets(_receipts(tmp_path, text))


@pytest.mark.parametrize(
    ("text", "target"),
    [
        ("import os\n\n\ndef f(tz):\n    os.environ['TZ'] = tz\n", "python:os.environ"),
        ("import os\n\n\ndef f():\n    del os.environ['TZ']\n", "python:os.environ"),
        ("import idn\n\n\ndef f(d):\n    d[idn.KEY] = 1\n", "python:idn.KEY"),
        ("import idn\n\n\ndef f(d):\n    d[idn.KEY] += 1\n", "python:idn.KEY"),
        ("import idn\n\n\ndef f():\n    idn.TABLE.x = 1\n", "python:idn.TABLE"),
        (
            "import idn\n\n\ndef f(v):\n    a, idn.TABLE['k'] = v\n",
            "python:idn.TABLE",
        ),
        (
            "import idn\n\n\ndef f(v):\n    for idn.TABLE['k'] in v:\n        pass\n",
            "python:idn.TABLE",
        ),
    ],
    ids=[
        "subscript-store-receiver",
        "subscript-delete-receiver",
        "subscript-store-key",
        "augmented-store-key",
        "attribute-store-receiver",
        "unpack-element",
        "for-target",
    ],
)
def test_what_a_store_target_reads_has_its_row(
    tmp_path: Path, text: str, target: str
) -> None:
    assert target in _targets(_receipts(tmp_path, text))


def test_an_evaluated_annotation_has_its_row(tmp_path: Path) -> None:
    """``def f(s: idn.T) -> idn.R`` evaluates both annotations where the
    ``def`` runs (the module does not postpone them): each read takes its
    row, as a default does."""
    receipts = _receipts(
        tmp_path, "import idn\n\n\ndef f(s: idn.T) -> idn.R:\n    return s\n"
    )
    assert {"python:idn.T", "python:idn.R"} <= _targets(receipts)


@pytest.mark.parametrize(
    "text",
    [
        "from __future__ import annotations\n\nimport idn\n\n\n"
        "def f(s: idn.T) -> idn.R:\n    return s\n",
        "import idn\n\n\ndef f(s: 'idn.T') -> 'idn.R':\n    return s\n",
    ],
    ids=["postponed-module", "string-annotation"],
)
def test_an_annotation_python_does_not_evaluate_has_no_row(
    tmp_path: Path, text: str
) -> None:
    # THE DISCRIMINATION: the walk reads an annotation exactly where the
    # meaning layer evaluates it (``annotation_evaluated``), never elsewhere.
    assert _receipts(tmp_path, text) == []


def test_a_bound_name_in_a_target_is_never_a_use(tmp_path: Path) -> None:
    """``np = 1`` binds ``np``; it reads nothing, and nothing after it reads
    the import."""
    receipts = _receipts(
        tmp_path, "import idn\n\n\ndef f():\n    idn = 1\n    return {'k': idn}\n"
    )
    assert receipts == []


def test_a_name_that_is_not_imported_gets_no_row_in_a_dict(tmp_path: Path) -> None:
    # THE DISCRIMINATION: the walk reaches the item, the strict law decides.
    receipts = _receipts(tmp_path, "zz = object()\nd = {'k': zz.CONST, 'j': zz}\n")
    assert receipts == []


def test_an_optional_import_gets_no_row_in_a_dict(tmp_path: Path) -> None:
    # The read in the dict takes no row: ``pa`` is no unique import there.
    # The one receipt is the binding's own read at its alias (line 2), which
    # the join past the ``try`` enrolls so that the import's arm of the
    # threading's join is the import, never the free name (#7757).
    receipts = _receipts(
        tmp_path,
        "try:\n    import pa\nexcept ImportError:\n    pass\n\n"
        "d = {'k': pa.array}\n",
    )
    assert [receipt.use["useSite"]["startLine"] for receipt in receipts] == [2]
    (receipt,) = receipts
    assert receipt.target_symbol == "python:pa"
    assert receipt.use["exportedMemberPath"] == []


@pytest.mark.parametrize(
    ("source", "formals", "reference"),
    [
        (
            "import idn\n\n\ndef f():\n    return {'k': idn.CONST}\n",
            (),
            "ref:idn.CONST",
        ),
        (
            "import idn\n\n\ndef f():\n    return {'k': [1, idn.CONST]}\n",
            (),
            "ref:idn.CONST",
        ),
        (
            "import idn\n\n\ndef f():\n    return {idn.KEY: 1}\n",
            (),
            "ref:idn.KEY",
        ),
    ],
    ids=["dict-value", "dict-nested-list", "dict-key"],
)
def test_a_function_reading_an_import_in_a_dict_is_scoped(
    source: str, formals: tuple[str, ...], reference: str
) -> None:
    posts = _scoped_posts(source, formals)
    for scoped in posts:
        assert scoped.formula.free_vars <= {*formals, "out"}
    assert any(reference in repr(scoped.formula.ir_formula) for scoped in posts)


def test_a_store_through_an_import_member_is_scoped() -> None:
    for scoped in _scoped_posts(
        "import os\n\n\ndef f(tz):\n    os.environ['TZ'] = tz\n    return 1\n",
        ("tz",),
    ):
        assert scoped.formula.free_vars <= {"tz", "out"}


def test_an_optional_import_in_a_dict_is_the_join_never_the_free_name() -> None:
    # THE DISCRIMINATION is unchanged: ``pa`` binds nothing the strict law
    # accepts (the import may have failed), so its read takes no row.  It is
    # no longer the free name either: the read is the join the threading
    # carries past the ``try`` (#7757, carry undecided), the import on the
    # route that bound it and a ``NameError`` halt on the route that did not,
    # so the scope law has nothing to refuse.
    for scoped in _scoped_posts(
        "try:\n    import pyarrow as pa\nexcept ImportError:\n    pass\n\n\n"
        "def f():\n    return {'k': pa.array}\n",
        (),
    ):
        assert scoped.formula.free_vars <= {"out"}
