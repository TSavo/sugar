"""The producer of authenticated warning testimony, from real source.

``dd3d1b5ca`` (#6458) shipped the CONSUMER of ``WarningObservationValue`` and
no producer: ``git grep -c "WarningObservationValue(" 964dbf95d`` hit exactly
three files, the definition and two test modules, and nothing in any ``src``
tree.  Every warning boundary therefore reached its "unresolved warning
producers" refusal by construction.  These twins own the other half.

Two real pandas 3.0 sites, one on each side of the cut, are the reproducers:

* ``pandas/core/accessor.py:285`` -- ``warnings.warn(msg, UserWarning,
  stacklevel=find_stack_level())`` under ``if hasattr(cls, name)``;
* ``pandas/core/algorithms.py:1033`` -- ``warnings.warn(f"Unable to sort modes:
  {err}", stacklevel=find_stack_level())``, with NO explicit category.

The second one is why explicit-category-only is the cut: ``UserWarning`` there
is a defaulting rule living in CPython, not in the source text.

Nothing below supplies the value it then asserts.  The distinctive value is the
category SPELLED IN THE SOURCE, and each twin requires that same category out
the far side of a lift that never saw the expected term; the lying arm writes a
different category in the source and requires the projection to move with it.
No tooth here reads a wall clock.
"""

from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

import pytest

from sugar_lift_py_tests.context_manager_contract import (
    CallParameterV1,
    EffectBoundarySemanticsV1,
    ExpectsModeV1,
    FormalArgumentProjectionV1,
    ImportSignatureV2,
    NoDefaultV1,
    NoMessagePatternV1,
    PositionalOrKeywordV1,
    WarningEffectKindV1,
    WarningObservationBindingV1,
)
from sugar_lift_py_tests.effect import ExpectationNotMetEffect
from sugar_lift_py_tests.floor import CallSiteValue, TermValue
from sugar_lift_py_tests.floor.warning_observation_value import WarningObservationValue
from sugar_lift_py_tests.ir import PrimitiveSort, ctor, str_const
from sugar_lift_py_tests.outcome import Complete
from sugar_lift_py_tests.outcome.exit_set import Completed, Halted
from sugar_lift_py_tests.sugar.function_universe_sugar import reduce_block_to_exitset
from sugar_lift_py_tests.sugar.sugar_base import Sugar
from sugar_lift_py_tests.sugar.with_effect_boundary_sugar import WithEffectBoundarySugar
from sugar_lift_python_source.source_oracle import path_source
from sugar_source_tree.panic import SugarNotWritten
from sugar_source_tree.tree import SourceFile


def _entries(tmp_path: Path, source: str, stem: str = "warn_case"):
    """Every record entry of every completed face, from real lifted source."""
    path = tmp_path / f"{stem}.py"
    path.write_text(source, encoding="utf-8")
    function = next(SourceFile(path_source(str(path))).functions())
    exits = reduce_block_to_exitset(function.sugar().statements, None)
    return tuple(
        entry for face in exits.exits for entry in getattr(face.value, "entries", ())
    )


def _observations(tmp_path: Path, source: str, stem: str = "warn_case"):
    return tuple(
        entry
        for entry in _entries(tmp_path, source, stem)
        if isinstance(entry, WarningObservationValue)
    )


def _builtin_category_identity(name: str):
    return ctor(
        "python:exception_type_identity",
        [str_const("builtins"), str_const(name)],
    )


# The pandas ``accessor.py:285`` occurrence, hoisted out of its ``if`` so the
# occurrence is unconditional.  The guarded spelling is its own twin below.
PANDAS_ACCESSOR_WARN = """import warnings


def register(cls, name, accessor):
    warnings.warn(
        "registration of accessor is overriding a preexisting attribute",
        {category},
        stacklevel=2,
    )
"""

# The pandas ``algorithms.py:1033`` occurrence, verbatim in shape: no category.
PANDAS_ALGORITHMS_WARN = """import warnings


def mode(err):
    warnings.warn(
        "Unable to sort modes",
        stacklevel=2,
    )
"""


@pytest.mark.parametrize(
    "category",
    ["UserWarning", "FutureWarning", "DeprecationWarning", "RuntimeWarning"],
)
def test_real_warn_site_produces_its_own_source_category(tmp_path, category):
    """The category WRITTEN IN THE SOURCE is the one that comes out.

    Parametrised because a producer that hard-coded any single category — or
    that read the category off a table rather than off this file — would pass
    exactly one arm.  The expected term is built from ``category`` here, but
    the lift is handed only the source text.
    """
    observations = _observations(
        tmp_path, PANDAS_ACCESSOR_WARN.format(category=category)
    )
    assert len(observations) == 1
    effect = observations[0].effect
    assert effect.category_identity == _builtin_category_identity(category)
    assert effect.category_name == category
    assert observations[0].guards == ()


def test_a_different_source_category_projects_a_different_identity(tmp_path):
    """The lying arm: change only the category, the coordinate must move."""
    truthful = _observations(
        tmp_path, PANDAS_ACCESSOR_WARN.format(category="FutureWarning"), "truthful"
    )
    lying = _observations(
        tmp_path, PANDAS_ACCESSOR_WARN.format(category="UserWarning"), "lying"
    )
    assert truthful[0].effect.category_identity != lying[0].effect.category_identity
    assert truthful[0].effect.category_identity == _builtin_category_identity(
        "FutureWarning"
    )


def test_keyword_spelled_category_is_the_same_occurrence(tmp_path):
    """``category=`` binds the same CPython formal that position 1 does."""
    source = """import warnings


def f():
    warnings.warn("m", category=FutureWarning, stacklevel=2)
"""
    observations = _observations(tmp_path, source)
    assert len(observations) == 1
    assert observations[0].effect.category_identity == _builtin_category_identity(
        "FutureWarning"
    )


def test_pandas_default_category_site_produces_no_testimony(tmp_path):
    """``warnings.warn(msg)`` is NOT evidence of a ``UserWarning`` occurrence.

    The default lives in CPython, not in the source text.  The occurrence keeps
    its ordinary call coordinate, and the boundary names it unresolved.
    """
    entries = _entries(tmp_path, PANDAS_ALGORITHMS_WARN)
    assert not any(isinstance(entry, WarningObservationValue) for entry in entries)
    assert any(isinstance(entry, CallSiteValue) for entry in entries)


def test_a_shadowed_head_is_not_a_warning_occurrence(tmp_path):
    """The door is lexical import binding, never the dotted spelling.

    A parameter named ``warnings`` spells ``warnings.warn`` exactly, and mints
    nothing.  This is the discrimination the existing With census lacks.
    """
    source = """def f(warnings):
    warnings.warn("m", UserWarning, stacklevel=2)
"""
    entries = _entries(tmp_path, source)
    assert not any(isinstance(entry, WarningObservationValue) for entry in entries)
    assert any(isinstance(entry, CallSiteValue) for entry in entries)


def test_a_computed_category_carries_no_identity(tmp_path):
    """A category that is not a closed class coordinate stays undecided."""
    source = """import warnings


def f(pick):
    warnings.warn("m", pick(), stacklevel=2)
"""
    entries = _entries(tmp_path, source)
    assert not any(isinstance(entry, WarningObservationValue) for entry in entries)


def test_the_guarded_pandas_site_records_its_guard(tmp_path):
    """``accessor.py:285`` as pandas actually writes it: under ``if hasattr``.

    The occurrence is conditional, so the testimony carries the branch guard.
    Dropping it would restate "warns when the guard holds" as "warns".
    """
    source = """import warnings


def register(cls, name):
    if hasattr(cls, name):
        warnings.warn("m", UserWarning, stacklevel=2)
"""
    observations = _observations(tmp_path, source)
    assert len(observations) == 1
    assert observations[0].guards != ()


# --- the producer through the shipped consumer ------------------------------


class _Fixed(Sugar):
    def __init__(self, outcome):
        self.outcome = outcome

    def desugar(self, ctx=None):
        del ctx
        return self.outcome

    @classmethod
    def witnesses(cls):
        return ()


class _ExpectedCategory(TermValue):
    def exception_type_identity(self):
        return self.value


class _Record(Sugar):
    """A completed face whose entries are the ones the PRODUCER built."""

    def __init__(self, entries):
        self.entries = entries

    def desugar(self, ctx=None):
        del ctx
        from sugar_lift_py_tests.floor import BlockValue

        return Complete(BlockValue(self.entries))

    @classmethod
    def witnesses(cls):
        return ()


SEMANTICS = EffectBoundarySemanticsV1(
    ExpectsModeV1(),
    WarningEffectKindV1(),
    FormalArgumentProjectionV1(0),
    NoMessagePatternV1(),
    WarningObservationBindingV1(),
)


def _boundary(expected_category: str, entries):
    expected = _ExpectedCategory(_builtin_category_identity(expected_category))
    manager_value = CallSiteValue(
        target_name="scope",
        arg_values=(expected,),
        parameters=("expected",),
        term=ctor("call", []),
        body=None,
    )
    signature = ImportSignatureV2(
        (
            CallParameterV1(
                "expected",
                PrimitiveSort("Value"),
                PositionalOrKeywordV1(),
                True,
                NoDefaultV1(),
            ),
        )
    )
    return WithEffectBoundarySugar(
        manager=_Fixed(Complete(manager_value)),
        body=(_Record(entries),),
        semantics=SEMANTICS,
        contract_ref=SimpleNamespace(import_signature=signature),
        context_manager_edge=None,
        site=None,
    )


def test_produced_testimony_satisfies_a_matching_boundary(tmp_path):
    """The truthful twin, end to end: real source in, completed face out."""
    entries = _observations(
        tmp_path, PANDAS_ACCESSOR_WARN.format(category="FutureWarning")
    )
    routed = _boundary("FutureWarning", entries).desugar()
    assert len(routed.exits) == 1
    face = routed.exits[0]
    assert isinstance(face, Completed)
    assert not any(
        isinstance(entry, WarningObservationValue) for entry in face.value.entries
    )


def test_produced_testimony_fails_a_mismatched_boundary(tmp_path):
    """The lying twin: the source warns ``UserWarning``, the boundary expects
    ``FutureWarning``.  It must go red, and it is the PRODUCER's coordinate
    that decides — the boundary is spelled identically in both twins."""
    entries = _observations(
        tmp_path, PANDAS_ACCESSOR_WARN.format(category="UserWarning")
    )
    routed = _boundary("FutureWarning", entries).desugar()
    assert len(routed.exits) == 1
    face = routed.exits[0]
    assert isinstance(face, Halted)
    assert isinstance(face.effect, ExpectationNotMetEffect)


def _refusal_members(tmp_path, source, stem):
    """Route real lifted source into the boundary; return the named bucket."""
    path = tmp_path / f"{stem}.py"
    path.write_text(source, encoding="utf-8")
    function = next(SourceFile(path_source(str(path))).functions())
    exits = reduce_block_to_exitset(function.sugar().statements, None)
    entries = tuple(
        entry for face in exits.exits for entry in getattr(face.value, "entries", ())
    )
    with pytest.raises(SugarNotWritten) as raised:
        _boundary("FutureWarning", entries).desugar()
    assert raised.value.observed == "completed face has unresolved warning producers"
    return str(path), raised.value.unresolved_warning_producers


def _line_of(source: str, needle: str) -> int:
    """The 1-based line of ``needle``, computed from the text, not the lift."""
    return source[: source.index(needle)].count("\n") + 1


# All three producer refusal shapes, each asserted PRESENT in the named bucket.
# Presence, never absence: a producer that was never wired at all leaves the
# produced set empty too, so an absence assertion is satisfied by the mechanism
# not running.  The expected line is computed from the source text here and the
# lift is handed only the text, so the coordinate is not supplied by the test.
@pytest.mark.parametrize(
    "stem,source",
    [
        # pandas ``core/algorithms.py:1033`` -- no explicit category.
        ("no_category", PANDAS_ALGORITHMS_WARN),
        # A category that is not a closed class coordinate.
        (
            "computed_category",
            'import warnings\n\n\ndef f(pick):\n    warnings.warn("m", pick(), stacklevel=2)\n',
        ),
        # A shadowed head: spells ``warnings.warn`` exactly, binds nothing.
        (
            "shadowed_head",
            'def f(warnings):\n    warnings.warn("m", UserWarning, stacklevel=2)\n',
        ),
    ],
)
def test_a_refused_producer_appears_in_the_unresolved_bucket(tmp_path, stem, source):
    filename, members = _refusal_members(tmp_path, source, stem)
    assert f"{filename}:{_line_of(source, 'warnings.warn')}" in members


def test_a_guarded_occurrence_is_refused_not_consumed(tmp_path):
    """A conditional occurrence is undecided at the boundary: not present, not
    absent.  Consuming it would be a strictly stronger claim than the source."""
    source = """import warnings


def register(cls, name):
    if hasattr(cls, name):
        warnings.warn("m", FutureWarning, stacklevel=2)
"""
    entries = _observations(tmp_path, source)
    with pytest.raises(SugarNotWritten) as raised:
        _boundary("FutureWarning", entries).desugar()
    assert raised.value.owner == "WithEffectBoundarySugar.warning_observation"
    assert "branch guard" in raised.value.observed
