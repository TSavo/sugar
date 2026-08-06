"""The module-prefix door must thread its block before it sugars it.

``FunctionDef.source_visible_call_frame`` substitutes a body and only then
sugars each statement (``nodes.py``: ``_substitute_body`` -> per-statement
sugar). ``manager_construction._module_prefix_outcome`` used to sugar each
prefix statement where it stood, with nothing threaded. Two doors onto the same
construct, one of which could not reach it.

The cost, measured on the sealed board: ``pandas/__init__.py:9`` is
``for _dependency in _hard_dependencies:`` over a tuple bound two lines above.
Unthreaded, the iterable is symbolic, ``For.substitute`` cannot unroll, and the
statement falls to ``For.sugar`` -- deliberately unwritten, because a SURVIVING
``For`` IS the symbolic fold. ``prefix_has_completed_fallthrough`` then reports
``construction-refusal``, and ``dependency_export_adapter`` fuses that into
``dynamic-export``. Every ``with pd.option_context(...)`` in the corpus panics
with a manager the board describes as *dynamically exported* -- which
``pandas/__init__.py:34`` plainly is not.

TWO ARMS, and both are needed:

* CLEAR -- ``tests/indexes/datetimes/test_formats.py`` carries exactly two
  ``With._construct_sugar`` panics, both ``option_context`` dynamic-export.
  Threading the prefix must kill that label and carry construction across the
  export boundary into ``pandas/_config/config.py``. It does NOT make the seat
  clean: behind the export is a constructed-value canonicalization gap, owned
  elsewhere. Clearing a first terminal reveals what it masked; that is
  discovery, and this tooth stops exactly where threading's authority stops.
* HOLD -- ``core/arrays/_ranges.py`` carries exactly two, both
  ``numpy.errstate`` dynamic-export, and those reach the SAME label by a
  DIFFERENT route: ``numpy/__init__.py``'s prefix already reports ``completed``
  and the export is declined further down, at an ``If``-block binding locus.
  Threading must not admit them. A repair that clears this arm too has
  over-admitted, and the fused label would hide it.

Measured through the census entrance (``measure_file_via_enumerate``) on the
real authenticated seats, never ``SourceFile.from_path`` -- a different door
proves nothing about this one.
"""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path
from types import ModuleType

import pytest

from sugar_lift_py_tests.repo_root import sugar_lift_py_tests_package_root

_SCRIPTS = sugar_lift_py_tests_package_root() / "scripts"

CLEAR_SEAT = "tests/indexes/datetimes/test_formats.py"
HOLD_SEAT = "core/arrays/_ranges.py"


def _load(name: str) -> ModuleType:
    if str(_SCRIPTS) not in sys.path:
        sys.path.insert(0, str(_SCRIPTS))
    path = _SCRIPTS / f"{name}.py"
    spec = importlib.util.spec_from_file_location(name, path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


CONSUMER = _load("recensus_enumerate_consumer")


def _measure(seat: str) -> dict:
    from sugar_lift_py_tests.authenticated_pytest import authenticated_pandas_corpus
    from sugar_lift_python_source.source_oracle import install_root_for

    corpus = authenticated_pandas_corpus().root
    target = corpus.joinpath(*seat.split("/"))
    installed = install_root_for(str(target))
    locus_root = corpus if installed is None else Path(installed)
    return CONSUMER.measure_file_via_enumerate(
        workspace_root=corpus,
        file_rel=seat,
        distribution="pandas",
        source_workspace_root=locus_root,
    )


def _manager_gaps(row: dict, manager: str) -> list[str]:
    """Every construction panic naming this manager, as its observed text."""
    return [
        str(panic.get("observed"))
        for panic in (row.get("constructionPanics") or [])
        if isinstance(panic, dict) and manager in str(panic.get("observed"))
    ]


def _instrument_failure(row: dict) -> str | None:
    message = (row.get("instrumentFailure") or {}).get("message")
    return str(message) if message else None


@pytest.mark.slow
def test_option_context_construction_crosses_the_export_boundary() -> None:
    """CLEAR arm: the prefix threads, the For dissolves, the export RESOLVES.

    This asserts what threading owns and nothing further. The ``with`` still
    refuses -- but at a coordinate INSIDE the manager's own module
    (``pandas/_config/config.py``), which is only reachable once export
    resolution succeeded. Unthreaded, construction never got past
    ``pandas/__init__.py`` and no inner coordinate could appear.

    Deliberately NOT asserted: that the seat goes clean. What is behind the
    export is a constructed-value canonicalization gap owned elsewhere, and a
    tooth that waited on it would be asserting someone else's target.
    """
    row = _measure(CLEAR_SEAT)

    assert _instrument_failure(row) is None, _instrument_failure(row)
    observed = _manager_gaps(row, "python:pandas.option_context")
    assert observed, (
        "the option_context seats must still be measurable; an empty roster "
        "here means the measurement stopped reaching them"
    )
    assert all("pandas/_config/config.py" in text for text in observed), (
        "construction must reach INSIDE the resolved manager's module; a "
        f"refusal naming no inner coordinate means the export never resolved: {observed}"
    )


@pytest.mark.slow
def test_option_context_refusal_named_dynamic_export_is_gone() -> None:
    """The SPECIFIC false label must be gone, not merely some panic count.

    Asserted on the refusal TEXT: a repair that swapped one wrong word for
    another wrong word would keep this red.
    """
    row = _measure(CLEAR_SEAT)

    # An absence assertion is worthless if the measurement never happened: a
    # seat that died at source-identity reports no panics at all and would let
    # this pass while proving nothing.
    assert _instrument_failure(row) is None, _instrument_failure(row)
    fused = [
        text
        for text in _manager_gaps(row, "python:pandas.option_context")
        if "dynamic-export" in text
    ]
    assert fused == [], (
        "pandas/__init__.py:34 is a plain static ImportFrom; no resolution may "
        f"call option_context a dynamic export: {fused}"
    )


@pytest.mark.slow
def test_numpy_errstate_with_still_refuses() -> None:
    """HOLD arm: same label, different route -- threading must not admit it.

    ``numpy/__init__.py``'s prefix already reports ``completed``; its export is
    declined at an ``If``-block binding locus. Nothing about threading a module
    prefix touches that, so this refusal must survive intact. If it clears, the
    repair admitted an export it never proved.
    """
    row = _measure(HOLD_SEAT)

    assert _instrument_failure(row) is None, _instrument_failure(row)
    observed = _manager_gaps(row, "python:numpy.errstate")
    assert len(observed) == 2, (
        "core/arrays/_ranges.py holds exactly two numpy.errstate refusals and "
        f"threading the module prefix must not change that; observed {observed}"
    )
    assert all("dynamic-export" in text for text in observed), observed
