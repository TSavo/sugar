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

The consumer (``WithEffectBoundarySugar``) had no producer of its own and is
deleted (#7757); the twins through it went with it.

Nothing below supplies the value it then asserts.  The distinctive value is the
category SPELLED IN THE SOURCE, and each twin requires that same category out
the far side of a lift that never saw the expected term; the lying arm writes a
different category in the source and requires the projection to move with it.
No tooth here reads a wall clock.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from sugar_lift_py_tests.floor import CallSiteValue
from sugar_lift_py_tests.floor.warning_observation_value import WarningObservationValue
from sugar_lift_py_tests.ir import ctor, str_const
from sugar_lift_py_tests.outcome.exit_set import Completed
from sugar_lift_py_tests.sugar.function_universe_sugar import reduce_block_to_exitset
from sugar_lift_python_source.source_oracle import path_source
from sugar_source_tree.tree import SourceFile
from sugar_lift_py_tests.context_manager_resolution import TreeConstructionContextV1


def _entries(tmp_path: Path, source: str, stem: str = "warn_case"):
    """Every record entry of every completed face, from real lifted source."""
    path = tmp_path / f"{stem}.py"
    path.write_text(source, encoding="utf-8")
    function = next(
        SourceFile(
            path_source(str(path)),
            construction_context=TreeConstructionContextV1.for_test_without_workspace(),
        ).functions()
    )
    exits = reduce_block_to_exitset(function.sugar().statements, None)
    return tuple(
        entry
        for face in exits.exits
        if isinstance(face, Completed)
        for entry in getattr(face.value, "entries", ())
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
    # The formal receiver's class is ``f``'s ``class:warnings`` input: the
    # call is the dispatched edge (#7757 step 8), resolved at prove where a
    # caller binds the class, never a warning observation.
    path = tmp_path / "warn_case.py"
    path.write_text(source, encoding="utf-8")
    function = next(
        SourceFile(
            path_source(str(path)),
            construction_context=TreeConstructionContextV1.for_test_without_workspace(),
        ).functions()
    )
    outcome = function.sugar().desugar(None)
    owners = {halt.effect.producer_node_owner for halt in outcome.halts()}
    assert "UnknownCallee:dispatch:warn" in owners
    assert not any(
        isinstance(getattr(exit_, "value", None), WarningObservationValue)
        for exit_ in outcome.exits
    )


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
