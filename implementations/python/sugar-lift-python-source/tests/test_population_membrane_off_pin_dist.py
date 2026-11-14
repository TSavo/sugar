"""Population membrane: off-pin *distributions* cite, never rebuild.

stdlib was closed by #7057.  The residual hole: test-only distributions
(``pytest``) authenticated as ``artifact_kind=distribution`` still fully
projected frames during open of enrolled pandas *test* files.

Measured on tip after #7057 family: one open of
``pandas/tests/io/json/test_pandas.py`` spent ~3.8s / 40 frames inside
``_pytest.*`` while stdlib was already 0.001s (113 off-pop cites).  Median
open in a 29-file sample was 0.586s; this file was 5.725s — 10×.

Law: the population is the lift's own file list (step 2), not CPython and
not test-only deps. The opener's walk session carries it as
``project_file_roster(root)`` (#7796).
"""

from __future__ import annotations

from collections import Counter
from pathlib import Path

from sugar_lift_py_tests.authenticated_pytest import authenticated_pandas_corpus
from sugar_lift_py_tests.lift_rpc import open_source_file_for_construction
from sugar_lift_py_tests.context_manager_resolution import TreeConstructionContextV1
import sugar_source_tree.process_resident_file as residency


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

    # Every open walks the one entry (``_open_at_seat``) into the residency
    # door; count the seats it is asked for there.
    seats: Counter[str] = Counter()
    orig = residency._source_file_from_identity

    def counting_open(identity, *args, **kwargs):  # type: ignore[no-untyped-def]
        _source, filename, _cid = identity
        seats[str(filename).replace("\\", "/")] += 1
        return orig(identity, *args, **kwargs)

    residency._source_file_from_identity = counting_open
    try:
        open_source_file_for_construction(
            path,
            root=address_root,
            construction_context=TreeConstructionContextV1.for_source_call_construction(),
            source_workspace_root=corpus,
        )
    finally:
        residency._source_file_from_identity = orig

    # The counter sits on the path the open walks: the target itself is one
    # count. A move of the entry turns this red instead of a vacuous green.
    assert sum(seats.values()) > 0, "the residency door never fired on this open"

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
