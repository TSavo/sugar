"""An import-bound read in an evaluated annotated-assignment annotation has
its row (#7757).

Python evaluates the annotation of ``x: T`` / ``x: T = v`` when the
statement runs in a module or class body (never in a function body), and of
``o.f: T [= v]`` / ``o[k]: T = v`` in a module body, unless the module
postpones its annotations (``from __future__ import annotations``).  The
meaning layer splices exactly those annotations into the block as
evaluations (``AnnAssign._evaluates_annotation``).  The lexical import pass
never walked them: ``class UniqueAllResult(NamedTuple): values: np.ndarray``
(numpy ``lib/_arraysetops_impl.py``) and ``eigenvalues: NDArray[Any]``
(numpy ``linalg/_linalg.py``) reached the meaning layer over the free names
``np``, ``NDArray`` and ``Any``, and ``ScopedFormula`` refused the class and
every function that reads it (``illegal free var(s): np``; 12 numpy
functions, 30 more naming ``Any, NDArray`` beside two other names, on the
nine-step lane at main 13e3413ad).

The pass now walks such an annotation, after the store, by the one law the
meaning layer splices it by (``annotated_assignment_annotation_evaluated``),
and each read takes the one row every other import-bound read takes: the
two-faced undecided import read.

THE DISCRIMINATION: an annotation Python does not evaluate (a function
body's, a postponed module's, a bare subscript target's) is never walked; a
string annotation reads no name; a head no unique import binds still gets no
row.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from sugar_source_tree.nodes import annotated_assignment_annotation_evaluated

from test_import_reads_in_dict_items_and_store_targets import (
    _receipts,
    _scoped_posts,
    _targets,
)


@pytest.mark.parametrize(
    ("text", "target"),
    [
        ("import idn\n\n\nclass C:\n    v: idn.T\n", "python:idn.T"),
        ("import idn\n\n\nclass C:\n    v: idn.T = 1\n", "python:idn.T"),
        (
            "from idn import Arr, Elem\n\n\nclass C:\n    v: Arr[Elem]\n",
            "python:idn.Elem",
        ),
        ("import idn\n\nx: idn.T\n", "python:idn.T"),
        ("import idn\n\nx: idn.T = 1\n", "python:idn.T"),
        (
            "import idn\n\n\nclass O:\n    pass\n\n\nO.f: idn.T = 1\n",
            "python:idn.T",
        ),
        (
            "import idn\n\n\ndef f():\n    class C:\n        v: idn.T\n    return C\n",
            "python:idn.T",
        ),
    ],
    ids=[
        "class-body-bare",
        "class-body-valued",
        "class-body-subscript-from-import",
        "module-bare",
        "module-valued",
        "module-attribute-target",
        "local-class-body",
    ],
)
def test_an_evaluated_annotated_assignment_annotation_has_its_row(
    tmp_path: Path, text: str, target: str
) -> None:
    assert target in _targets(_receipts(tmp_path, text))


@pytest.mark.parametrize(
    "text",
    [
        "from __future__ import annotations\n\nimport idn\n\n\n"
        "class C:\n    v: idn.T\n",
        "import idn\n\n\nclass C:\n    v: 'idn.T'\n",
        "import idn\n\n\ndef f():\n    x: idn.T = 1\n    return x\n",
        "import idn\n\nd = {}\nd['k']: idn.T\n",
        "zz = object()\n\n\nclass C:\n    v: zz.T\n",
    ],
    ids=[
        "postponed-module",
        "string-annotation",
        "function-body",
        "bare-subscript-target",
        "not-imported",
    ],
)
def test_an_annotation_python_does_not_evaluate_or_no_import_binds_has_no_row(
    tmp_path: Path, text: str
) -> None:
    # THE DISCRIMINATION: the walk reads an annotation exactly where the
    # meaning layer evaluates it, and the strict law decides each head.
    assert _receipts(tmp_path, text) == []


def test_the_pass_and_the_meaning_layer_read_one_law() -> None:
    """``annotated_assignment_annotation_evaluated`` is the one predicate:
    a Name target evaluates in a module or class body, an attribute target
    and a valued subscript target in a module body only, nothing in a
    postponed module."""
    law = annotated_assignment_annotation_evaluated
    assert law("Name", False, None, postponed_module=False)
    assert law("Name", True, "ClassDef", postponed_module=False)
    assert not law("Name", True, "FunctionDef", postponed_module=False)
    assert not law("Name", True, "AsyncFunctionDef", postponed_module=False)
    assert law("Attribute", False, None, postponed_module=False)
    assert law("Subscript", True, None, postponed_module=False)
    assert not law("Subscript", False, None, postponed_module=False)
    assert not law("Attribute", True, "ClassDef", postponed_module=False)
    assert not law("Name", True, None, postponed_module=True)
    assert not law("Name", True, "ClassDef", postponed_module=True)


def test_a_local_class_reading_an_import_in_an_annotation_is_scoped() -> None:
    """The scope law refused this function by ``idn``; its class body's
    annotation is now the import read, and nothing is free."""
    for scoped in _scoped_posts(
        "import idn\n\n\ndef f():\n    class C:\n        v: idn.T\n    return 1\n",
        (),
    ):
        assert scoped.formula.free_vars <= {"out"}
