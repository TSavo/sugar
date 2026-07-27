"""Authenticated producer law for pandas' no-call BinOp assertion body."""

from __future__ import annotations

import hashlib
from pathlib import Path

import pytest

from sugar_lift_python_source.canonical import blake3_512_of
from sugar_lift_py_tests.authenticated_pytest import authenticated_pandas_corpus
from sugar_lift_py_tests.context_manager_resolution import TreeConstructionContextV1
from sugar_lift_py_tests.gap.panic import ConstructionPanic
from sugar_source_tree.nodes import BinOp
from sugar_source_tree.tree import SourceFile

# Content manifest (relative path + per-file BLAKE3-512). Path-shape
# sha256:a223… is historical negative testimony only — never identity.
PANDAS_MANIFEST_CID = (
    "blake3-512:6f317a5a489eb7e730064d79792f0d1656723130603309e2f2ed9cbedb604eda"
    "1c4b77a26dc90c980411292ea3994af9015da4cd850b5a307af5a4998b563530"
)
HISTORICAL_PATH_SHAPE_DIGEST = (
    "sha256:a223a4499d0909f22190748b4aca9144e35a58fec31e84cb924e2c25fd3c03d0"
)
FILE_SHA256 = "14698f3356d531b1cb87761c57be48737cb547b7ac97f7a6406c16336d5e2f5f"


def _corpus_file() -> Path:
    corpus = authenticated_pandas_corpus()
    assert (corpus.version, corpus.manifest_cid, corpus.file_count) == (
        "3.0.3",
        PANDAS_MANIFEST_CID,
        1421,
    )
    assert corpus.manifest_cid != HISTORICAL_PATH_SHAPE_DIGEST
    return corpus.root / "tests/series/test_logical_ops.py"


def _line_96_bitand(source: str, path: Path):
    source_cid = blake3_512_of(source.encode("utf-8"))
    tree = SourceFile(
        (source, str(path), source_cid),
        construction_context=TreeConstructionContextV1.for_source_call_construction(),
    )
    matches = tuple(
        node
        for node in tree.nodes()
        if isinstance(node, BinOp)
        and node.op.kind == "BitAnd"
        and node.line_col_span().start_line == 96
    )
    assert len(matches) == 1
    return matches[0]


def _assert_named_panic(
    node,
    *,
    owner: str,
    observed: str,
    requested_contains: str,
) -> None:
    with pytest.raises(ConstructionPanic) as raised:
        node.sugar().desugar(None)
    info = raised.value.info
    assert info.owner == owner
    assert info.observed == observed
    assert requested_contains in info.requested
    # Never invent a runtime TypeError / RuntimeEffect for undecided source.
    assert "TypeError" not in str(info)
    assert "RuntimeEffect" not in str(info)


def _binop_at(source: str, path: Path, *, line: int, kind: str):
    source_cid = blake3_512_of(source.encode("utf-8"))
    tree = SourceFile(
        (source, str(path), source_cid),
        construction_context=TreeConstructionContextV1.for_source_call_construction(),
    )
    matches = tuple(
        node
        for node in tree.nodes()
        if isinstance(node, BinOp)
        and node.op.kind == kind
        and node.line_col_span().start_line == line
    )
    assert len(matches) == 1
    return matches[0]


def _assert_named_refusal(node, *, owner: str, observed_contains: str) -> None:
    from sugar_source_tree.panic import SugarNotWritten

    with pytest.raises(SugarNotWritten) as raised:
        node.sugar().desugar(None)
    refusal = raised.value
    assert refusal.owner == owner
    assert observed_contains in refusal.observed
    assert "AttributeError" not in refusal.observed
    assert "AttributeError" not in refusal.requested
    assert "RuntimeEffect" not in refusal.observed
    assert "RuntimeEffect" not in refusal.requested


def test_pandas_series_nan_bitand_stays_source_undecided_in_the_producer() -> None:
    """Truthful/lying runtime twins cannot license invented source testimony.

    Site: ``pandas/tests/series/test_logical_ops.py:96`` ``s_0123 & np.nan``.

    Operand evaluation runs before the BinOp floor. On the truthful site the
    right operand is ``np.nan`` — Attribute on an unresolved name — so the
    named coordinate is ``SymbolicValue.attribute``. Replacing the right
    operand with a term (``0``) removes that child gap and the panic lands on
    ``binary_operation_exception_floor`` as ``SymbolicValue & TermValue``.
    Neither arm invents TypeError.
    """
    path = _corpus_file()
    truthful = path.read_text(encoding="utf-8")
    assert hashlib.sha256(truthful.encode("utf-8")).hexdigest() == FILE_SHA256
    assert truthful.count("s_0123 & np.nan") == 1

    import pandas

    series = pandas.Series(range(4), dtype="int64")
    with pytest.raises(TypeError):
        series & float("nan")
    assert (series & 0).tolist() == [0, 0, 0, 0]

    lying = truthful.replace("s_0123 & np.nan", "s_0123 & 0")
    _assert_named_refusal(
        _line_96_bitand(truthful, path),
        owner="SymbolicValue.attribute",
        observed_contains=(
            "undecided receiver runtime type or member semantics: SymbolicValue.nan"
        ),
    )
    _assert_named_panic(
        _line_96_bitand(lying, path),
        owner="binary_operation_exception_floor",
        observed="SymbolicValue & TermValue",
        requested_contains="authenticated exceptional exit",
    )


@pytest.mark.parametrize(
    ("line", "kind", "snippet", "observed", "runtime_right"),
    (
        # Same function as :96; ground float right still cannot type the left.
        (98, "BitAnd", "s_0123 & 3.14", "SymbolicValue & TermValue", 3.14),
        # List right is decided as a sequence; left Series type is not.
        (
            101,
            "BitAnd",
            "s_0123 & [0.1, 4, 3.14, 2]",
            "SymbolicValue & ListValue",
            [0.1, 4, 3.14, 2],
        ),
        # String right is decided; left Series type is not.
        (117, "BitAnd", 's_1111 & "a"', "SymbolicValue & StringValue", "a"),
    ),
)
def test_pandas_series_bitand_mixed_rights_stay_named_refusals(
    line: int, kind: str, snippet: str, observed: str, runtime_right
) -> None:
    """Additional vertical slices: one operator law, mixed decided rights.

    Each site raises TypeError at CPython on a concrete Series, but the
    producer only sees a SymbolicValue left.  The shared undecided-binary law
    must refuse every one without inventing TypeError.
    """
    path = _corpus_file()
    source = path.read_text(encoding="utf-8")
    assert hashlib.sha256(source.encode("utf-8")).hexdigest() == FILE_SHA256
    assert source.count(snippet) == 1

    import pandas

    series = pandas.Series(range(4), dtype="int64")
    with pytest.raises(TypeError):
        series & runtime_right

    _assert_named_panic(
        _binop_at(source, path, line=line, kind=kind),
        owner="binary_operation_exception_floor",
        observed=observed,
        requested_contains="authenticated exceptional exit",
    )
