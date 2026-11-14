"""The could-not-parse contract (#5946).

``backend.py`` names the outcome: the backend that cannot parse a source
unit raises ``BackendCouldNotParse`` — never its native library exception
(CPython's ``SyntaxError``). This test drives one deliberately unparseable
file through the backend and asserts a recorded could-not-parse outcome row
from ``emit_corpus``, never an escaped exception.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from conftest import oracle_source_file
from sugar_source_tree.backend import BackendCouldNotParse
from sugar_source_tree.corpus import emit_corpus
from sugar_source_tree.cpython_adapter import CPythonAstBackend

UNPARSEABLE = "def f(:\n    pass\n"


def test_the_adapter_raises_the_membrane_error_not_its_native_exception():
    with pytest.raises(BackendCouldNotParse) as excinfo:
        oracle_source_file(UNPARSEABLE)
    could_not_parse = excinfo.value
    assert could_not_parse.backend == CPythonAstBackend().name
    assert could_not_parse.file.endswith(".py")
    assert could_not_parse.reason


def test_an_unparseable_file_produces_a_recorded_row_never_an_escaped_exception(
    tmp_path: Path,
):
    """The HARD LAW, driven end to end through the CLI-facing entry point:
    a could not parse file is a recorded failure in the corpus result, not a dead
    process."""
    bad = tmp_path / "unparseable.py"
    bad.write_text(UNPARSEABLE, encoding="utf-8")
    good = tmp_path / "fine.py"
    good.write_text("x = 1\n", encoding="utf-8")

    result = emit_corpus([tmp_path], out_path=None, base=tmp_path)

    assert result.files == 1  # only fine.py parsed
    could_not_parse = [f for f in result.failures if f[1] == "backend_could_not_parse"]
    assert len(could_not_parse) == 1
    assert could_not_parse[0][0] == "unparseable.py"
