"""Population membrane: off-pin success cites, never rebuilds.

Advisor ruling (measurement integrity): the pin enrolls corpus files (pandas),
not CPython.  A terminal for a pandas file must not be decided by constructing
an unenrolled module.

The opaque/cite path already existed on FAILURE
(``_install_opaque_call_obligation``).  SUCCESS against authenticated stdlib
used to call ``resolve_source_visible_frame`` → full ``MaterializeModule`` of
the dependency (``enum.py`` 35×, ``re/*`` 71× on one open of
``pandas/io/json/_json.py``).

Red instruments:
  one open of pandas/io/json/_json.py → SourceFile of enum.py == 0
  one open of pandas/io/json/_json.py → SourceFile of ANY stdlib seat == 0

In-population redundancy (e.g. pandas/_config/config.py ×18) is white's
dependency-seat memo campaign — not this instrument.
"""

from __future__ import annotations

import sysconfig
from collections import Counter
from pathlib import Path

from sugar_lift_py_tests.authenticated_pytest import authenticated_pandas_corpus
from sugar_lift_py_tests.lift_rpc import (
    open_source_file_for_construction,
    tree_construction_context_for_workspace,
)
from sugar_source_tree.reporter import CollectingReporter
from sugar_source_tree.tree import SourceFile


def _enum_seat(filename: str) -> bool:
    seat = str(filename).replace("\\", "/")
    return seat.endswith("enum.py") or seat == "enum.py"


def _stdlib_seat(filename: str, *, stdlib_root: Path) -> bool:
    """True when the SourceFile identity is an off-population stdlib seat."""
    seat = str(filename).replace("\\", "/")
    if seat.startswith("pandas/") or "/site-packages/pandas/" in seat:
        return False
    if seat.startswith("numpy/") or "/site-packages/numpy/" in seat:
        return False
    # Relative seats minted by authenticate_stdlib_path (enum.py, re/__init__.py, …)
    candidate = (stdlib_root / seat).resolve()
    try:
        candidate.relative_to(stdlib_root)
    except ValueError:
        pass
    else:
        if candidate.is_file() or seat.endswith(".py") or "/" in seat:
            # Prefer existence, but also match known relative seats even if
            # this interpreter layout differs slightly from the seat spelling.
            if candidate.is_file():
                return True
    # Absolute path inside stdlib root
    try:
        p = Path(seat).resolve()
        p.relative_to(stdlib_root)
        return True
    except (ValueError, OSError):
        pass
    # Common relative stdlib spellings used as source_seat
    if seat in {"enum.py", "re.py", "abc.py", "typing.py", "types.py"}:
        return True
    if seat.startswith("re/") or seat.startswith("collections/") or seat.startswith(
        "importlib/"
    ):
        return True
    if seat.endswith("/enum.py") or seat.endswith("/re.py"):
        return True
    return False


def _count_sourcefiles_during(open_fn) -> tuple[Counter[str], object]:
    """Patch SourceFile.__init__, run open_fn, restore. Returns seat counter."""
    seats: Counter[str] = Counter()
    orig = SourceFile.__init__

    def counting_init(self, identity, *args, **kwargs):  # type: ignore[no-untyped-def]
        _source, filename, _cid = identity
        seats[str(filename).replace("\\", "/")] += 1
        return orig(self, identity, *args, **kwargs)

    SourceFile.__init__ = counting_init  # type: ignore[method-assign]
    try:
        result = open_fn()
    finally:
        SourceFile.__init__ = orig  # type: ignore[method-assign]
    return seats, result


def _locus_root_for_corpus(corpus: Path) -> Path:
    """Install root that records seats as ``pandas/...`` (not package-relative)."""
    import importlib.util

    # __file__ = .../sugar-lift-python-source/tests/test_....py
    # parents[0]=tests, [1]=sugar-lift-python-source, [2]=python
    cer_path = (
        Path(__file__).resolve().parents[2]
        / "sugar-lift-py-tests"
        / "scripts"
        / "control_effect_recensus.py"
    )
    assert cer_path.is_file(), f"missing recensus script at {cer_path}"
    spec = importlib.util.spec_from_file_location("cer_membrane", cer_path)
    assert spec is not None and spec.loader is not None
    cer = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(cer)
    return cer.locus_root_for_corpus(corpus)


def _open_json_once():
    corpus = authenticated_pandas_corpus().root
    locus = _locus_root_for_corpus(corpus)
    target = corpus / "io" / "json" / "_json.py"
    assert target.is_file(), f"missing planted corpus file {target}"
    ctx = tree_construction_context_for_workspace(corpus, contract_refs={})
    reporter = CollectingReporter()
    from sugar_source_tree.panic import SugarNotWritten

    try:
        return open_source_file_for_construction(
            target,
            root=locus,
            reporter=reporter,
            construction_context=ctx,
            populate_derived=True,
        )
    except SugarNotWritten:
        # In-population SNW is not this instrument; seat counts still measured.
        return object()


def test_population_membrane_json_open_never_materializes_enum_py() -> None:
    """One open of pandas io/json/_json.py must construct SourceFile(enum.py) zero times.

    Pre-membrane this was 35.  Green is 0: success cites.
    """
    seats, _ = _count_sourcefiles_during(_open_json_once)
    enum_n = sum(n for s, n in seats.items() if _enum_seat(s))
    total_n = sum(seats.values())
    assert enum_n == 0, (
        f"POPULATION MEMBRANE RED: SourceFile constructions of enum.py = {enum_n} "
        f"(want 0). Success against authenticated stdlib must cite, never "
        f"MaterializeModule. total SourceFile constructions this open={total_n}."
    )


def test_population_membrane_json_open_never_materializes_any_stdlib() -> None:
    """Off-population stdlib seats must be zero — not just enum.

    Pre-membrane: re/* was 71 constructions (~6.4s).  Membrane must kill all
    stdlib MaterializeModule, not only the enum tooth.
    """
    stdlib_root = Path(sysconfig.get_path("stdlib")).resolve()
    seats, _ = _count_sourcefiles_during(_open_json_once)
    stdlib_seats = {
        s: n for s, n in seats.items() if _stdlib_seat(s, stdlib_root=stdlib_root)
    }
    stdlib_n = sum(stdlib_seats.values())
    assert stdlib_n == 0, (
        f"POPULATION MEMBRANE RED: stdlib SourceFile constructions = {stdlib_n} "
        f"(want 0). Offenders: {dict(sorted(stdlib_seats.items(), key=lambda kv: -kv[1])[:20])}. "
        f"In-population residual is white's memo; stdlib is the membrane."
    )


def test_off_population_gap_helper_names_stdlib() -> None:
    """Unit tooth: stdlib graphs return the off-population gap; distributions do not."""
    from sugar_lift_python_source.dependency_artifact import (
        DependencyArtifactGraph,
    )
    from sugar_lift_python_source.manager_construction import (
        _off_population_materialize_gap,
    )

    # Minimal resolved stand-in: only cid + module_name are read by the helper.
    class _Resolved:
        cid = "test-resolved-cid"
        module_name = "enum"

    stdlib = DependencyArtifactGraph.authenticate_stdlib_module("enum")
    gap = _off_population_materialize_gap(_Resolved(), graph=stdlib)  # type: ignore[arg-type]
    assert gap is not None
    assert gap.kind == "call-target-off-population"
    assert "enum" in gap.detail

    re_graph = DependencyArtifactGraph.authenticate_stdlib_module("re")
    gap_re = _off_population_materialize_gap(
        type("R", (), {"cid": "r", "module_name": "re"})(),
        graph=re_graph,
    )
    assert gap_re is not None
    assert gap_re.kind == "call-target-off-population"
