"""Population membrane: off-pin success cites, never rebuilds.

Advisor ruling (measurement integrity): the pin enrolls corpus files (pandas),
not CPython.  A terminal for a pandas file must not be decided by constructing
an unenrolled module.

The opaque/cite path already existed on FAILURE
(``_install_opaque_call_obligation``).  SUCCESS against authenticated stdlib
used to call ``resolve_source_visible_frame`` → full ``MaterializeModule`` of
the dependency (``enum.py`` 35× on one open of ``pandas/io/json/_json.py``).

Red instrument (one assertion):
  one open of pandas/io/json/_json.py → SourceFile constructions of enum.py == 0

Do not touch the dependency-seat memo — that is a separate campaign (white).
"""

from __future__ import annotations

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


def _count_enum_sourcefiles_during(open_fn) -> tuple[int, int, object]:
    """Patch SourceFile.__init__ to count constructions, run open_fn, restore."""
    counts = {"all": 0, "enum": 0}
    orig = SourceFile.__init__

    def counting_init(self, identity, *args, **kwargs):  # type: ignore[no-untyped-def]
        _source, filename, _cid = identity
        counts["all"] += 1
        if _enum_seat(filename):
            counts["enum"] += 1
        return orig(self, identity, *args, **kwargs)

    SourceFile.__init__ = counting_init  # type: ignore[method-assign]
    try:
        result = open_fn()
    finally:
        SourceFile.__init__ = orig  # type: ignore[method-assign]
    return counts["enum"], counts["all"], result


def _locus_root_for_corpus(corpus: Path) -> Path:
    """Install root that records seats as ``pandas/...`` (not package-relative)."""
    import importlib.util

    # tests/ -> sugar-lift-python-source -> python/ -> sugar-lift-py-tests/scripts
    cer_path = (
        Path(__file__).resolve().parents[2]
        / "sugar-lift-py-tests"
        / "scripts"
        / "control_effect_recensus.py"
    )
    # __file__ = .../sugar-lift-python-source/tests/test_....py
    # parents[0]=tests, [1]=sugar-lift-python-source, [2]=python
    assert cer_path.is_file(), f"missing recensus script at {cer_path}"
    spec = importlib.util.spec_from_file_location("cer_membrane", cer_path)
    assert spec is not None and spec.loader is not None
    cer = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(cer)
    return cer.locus_root_for_corpus(corpus)


def test_population_membrane_json_open_never_materializes_enum_py() -> None:
    """One open of pandas io/json/_json.py must construct SourceFile(enum.py) zero times.

    Pre-membrane this was 35.  Green is 0: success cites.
    Open may still SNW for unrelated in-population reasons; the instrument
    only measures off-population rebuild of enum.py.
    """
    corpus = authenticated_pandas_corpus().root
    locus = _locus_root_for_corpus(corpus)
    target = corpus / "io" / "json" / "_json.py"
    assert target.is_file(), f"missing planted corpus file {target}"

    ctx = tree_construction_context_for_workspace(corpus, contract_refs={})
    reporter = CollectingReporter()

    def open_once():
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
            # In-population SNW is not this instrument.  enum count still measured.
            return object()

    enum_n, total_n, _result = _count_enum_sourcefiles_during(open_once)
    assert enum_n == 0, (
        f"POPULATION MEMBRANE RED: SourceFile constructions of enum.py = {enum_n} "
        f"(want 0). Success against authenticated stdlib must cite, never "
        f"MaterializeModule. total SourceFile constructions this open={total_n}."
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
