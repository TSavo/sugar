"""Population membrane: off-pin *distributions* cite, never rebuild.

stdlib was closed by #7057.  The residual hole: test-only distributions
(``pytest``) authenticated as ``artifact_kind=distribution`` still fully
projected frames during open of enrolled pandas *test* files.

Measured on tip after #7057 family: one open of
``pandas/tests/io/json/test_pandas.py`` spent ~3.8s / 40 frames inside
``_pytest.*`` while stdlib was already 0.001s (113 off-pop cites).  Median
open in a 29-file sample was 0.586s; this file was 5.725s — 10×.

Law: the pin enrolls corpus files (``pandas``), not CPython and not
test-only deps.  Session ``enrolled_distributions`` names the pin;
``populate_source_derived_resource_refs`` sets it from the consumer path.
"""

from __future__ import annotations

from collections import Counter
from pathlib import Path

from sugar_lift_py_tests.authenticated_pytest import authenticated_pandas_corpus
from sugar_lift_py_tests.lift_rpc import open_source_file_for_construction
from sugar_lift_py_tests.context_manager_resolution import TreeConstructionContextV1
from sugar_source_tree.tree import SourceFile


def _locus_root_for_corpus(corpus: Path) -> Path:
    import importlib.util

    cer_path = (
        Path(__file__).resolve().parents[2]
        / "sugar-lift-py-tests"
        / "scripts"
        / "control_effect_recensus.py"
    )
    spec = importlib.util.spec_from_file_location("cer_offpin", cer_path)
    assert spec is not None and spec.loader is not None
    cer = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(cer)
    return cer.locus_root_for_corpus(corpus)


def test_pandas_test_open_never_materializes_pytest() -> None:
    """One open of tests/io/json/test_pandas.py must not SourceFile pytest seats.

    Pre-membrane residual: 40 frame projections into _pytest (distribution).
    Green: zero SourceFile constructions whose seat is under pytest/_pytest.
    """
    corpus = authenticated_pandas_corpus().root
    address_root = _locus_root_for_corpus(corpus)
    path = corpus / "tests" / "io" / "json" / "test_pandas.py"
    if not path.is_file():
        import pytest

        pytest.skip(f"missing {path}")

    seats: Counter[str] = Counter()
    orig = SourceFile.__init__

    def counting_init(self, identity, *args, **kwargs):  # type: ignore[no-untyped-def]
        _source, filename, _cid = identity
        seats[str(filename).replace("\\", "/")] += 1
        return orig(self, identity, *args, **kwargs)

    SourceFile.__init__ = counting_init  # type: ignore[method-assign]
    try:
        open_source_file_for_construction(
            path,
            root=address_root,
            construction_context=TreeConstructionContextV1.for_source_call_construction(),
            populate_derived=True,
            distribution="pandas",
            source_workspace_root=corpus,
        )
    finally:
        SourceFile.__init__ = orig  # type: ignore[method-assign]

    offenders = {
        seat: n
        for seat, n in seats.items()
        if "_pytest" in seat
        or seat.startswith("pytest/")
        or "/site-packages/pytest/" in seat
        or "/site-packages/_pytest/" in seat
        or seat.endswith("pytest/__init__.py")
    }
    assert not offenders, (
        f"population membrane: off-pin pytest must never MaterializeModule; "
        f"offenders={offenders} (all seats sample={seats.most_common(20)})"
    )
