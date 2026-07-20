"""The refusal contract twin (#5946): both backends refuse identically.

``backend.py`` names the outcome: a backend that cannot parse a source
unit raises ``BackendRefused`` — never its native library exception
(CPython's ``SyntaxError``, LibCST's ``ParserSyntaxError``, which does NOT
subclass ``SyntaxError``). Before the fix, ``corpus.py`` caught only
``SyntaxError``: CPython's refusal was recorded as a row, LibCST's escaped
and killed the run. This test drives one deliberately unparseable file
through BOTH adapters and asserts identical handling — a recorded refusal
row from ``emit_corpus``, never an escaped exception.
"""

from __future__ import annotations

from pathlib import Path

import pytest

libcst = pytest.importorskip("libcst", reason="LibCST backend not installed")

from sugar_source_tree.backend import BackendRefused  # noqa: E402
from sugar_source_tree.tree import SourceFile  # noqa: E402
from sugar_source_tree.corpus import emit_corpus  # noqa: E402
from sugar_source_tree.cpython_adapter import CPythonAstBackend  # noqa: E402
from sugar_source_tree.libcst_adapter import LibCSTBackend  # noqa: E402

UNPARSEABLE = "def f(:\n    pass\n"


def test_libcst_raises_a_type_that_does_not_subclass_syntaxerror():
    """The defect's root cause, pinned: LibCST's own refusal exception is
    not a SyntaxError, so ``except SyntaxError`` never catches it."""
    assert not issubclass(libcst.ParserSyntaxError, SyntaxError)


@pytest.mark.parametrize(
    "provider_cls", [CPythonAstBackend, LibCSTBackend], ids=["cpython", "libcst"]
)
def test_both_adapters_raise_the_membrane_refusal_not_their_native_exception(
    provider_cls,
):
    with pytest.raises(BackendRefused) as excinfo:
        SourceFile(filename="<unparseable>", source=UNPARSEABLE, backend=provider_cls())
    refusal = excinfo.value
    assert refusal.backend == provider_cls().name
    assert refusal.file == "<unparseable>"
    assert refusal.reason


@pytest.mark.parametrize(
    "provider_cls", [CPythonAstBackend, LibCSTBackend], ids=["cpython", "libcst"]
)
def test_a_refused_file_produces_a_recorded_row_never_an_escaped_exception(
    provider_cls, tmp_path: Path
):
    """The HARD LAW, driven end to end through the CLI-facing entry point:
    a refused file is a recorded failure in the corpus result, not a dead
    process. This is the assertion that failed before the fix for LibCST
    (the exception escaped ``emit_corpus`` and killed the run) and passes
    identically for both backends after it."""
    bad = tmp_path / "unparseable.py"
    bad.write_text(UNPARSEABLE, encoding="utf-8")
    good = tmp_path / "fine.py"
    good.write_text("x = 1\n", encoding="utf-8")

    # The backend is a parameter of emit_corpus, not a source edit or a
    # monkeypatch of the tree (#5946/#5948's own workaround) —
    # this is the fix the corpus.emit_corpus backend parameter exists for.
    result = emit_corpus(
        [tmp_path], out_path=None, base=tmp_path, backend=provider_cls()
    )

    assert result.files == 1  # only fine.py parsed
    refused = [f for f in result.failures if f[1] == "backend_refused"]
    assert len(refused) == 1
    assert refused[0][0] == "unparseable.py"
