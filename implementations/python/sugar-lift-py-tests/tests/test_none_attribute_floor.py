"""``None.foo`` stands on the getattr coordinate, like every constructed value.

Four ``attribute x NoneValue`` rows on the pinned pandas tree
(``arrays/boolean.py``, ``arrays/numeric.py``, ``indexes/accessors.py``,
``plotting/_matplotlib/core.py``) construction_panicked with
``owner=attribute observed=NoneValue``.

These were reported as blocked on the installed-corpus locus-addressing
question. They were not. Measured through BOTH source doors -- ``path_source``
(absolute locus) and ``workspace_path_source`` (workspace-relative) -- the
refusal was byte-identical: ``observed=NoneValue``, never
``observed="absolute source locus"``. The rows never reached
``ground_raise_effect`` at all, because ``NoneValue`` had no ``attribute`` arm.
A plain missing floor arm, unblocked by addressing. Both doors are asserted
below so that stays true.

The arm is the established ``getattr_coordinate`` law, not a new one, and
deliberately NOT a ground ``AttributeError``.
"""

from __future__ import annotations

import pytest

from sugar_lift_py_tests.floor.none_value import NoneValue
from sugar_lift_py_tests.floor.symbolic_value import SymbolicValue
from sugar_lift_py_tests.ir import str_const
from sugar_lift_py_tests.outcome import Complete

SITE = "none-attribute-site"


def _coordinate(outcome):
    assert isinstance(outcome, Complete), outcome
    assert type(outcome.value) is SymbolicValue
    term = outcome.value.term
    assert term.name == "py.getattr"
    return term


# -- positive arm ------------------------------------------------------------


def test_none_attribute_is_the_getattr_coordinate() -> None:
    term = _coordinate(NoneValue().attribute("foo", SITE))

    assert term.args[0] == NoneValue().to_term(owner="NoneValue.attribute")
    assert term.args[1] == str_const("foo")


@pytest.mark.parametrize(
    "name",
    (
        "foo",
        # A REAL member of NoneType. Python does not raise for these, which is
        # why the arm must not be a blanket ground AttributeError.
        "__class__",
        "__doc__",
        "__bool__",
    ),
)
def test_the_coordinate_makes_no_claim_that_the_attribute_exists(name) -> None:
    """One arm for both cases.

    ``None.foo`` raises and ``None.__class__`` does not. The coordinate is an
    opaque symbol over the receiver's term and the name -- it asserts neither
    outcome, so it is exact for both without a NoneType member table. Deciding
    between them would mean reading a name off its spelling.
    """
    term = _coordinate(NoneValue().attribute(name, SITE))

    assert term.args[1] == str_const(name)


# -- the real reproducer, through BOTH source doors --------------------------


@pytest.mark.parametrize("workspace_relative", (False, True))
def test_the_whole_function_lifts_through_either_source_door(
    tmp_path, workspace_relative
) -> None:
    """The row was reported as addressing-blocked. It is not.

    The absolute-locus door is asserted alongside the workspace-relative one:
    if this arm ever starts depending on locus addressing, the ``False`` case
    is what says so.
    """
    from sugar_lift_python_source.source_oracle import (
        path_source,
        workspace_path_source,
    )
    from sugar_lift_py_tests.floor.universe_value import UniverseValue
    from sugar_source_tree.tree import SourceFile

    path = tmp_path / "none_attribute.py"
    path.write_text("def f():\n    return None.foo\n", encoding="utf-8")

    source = (
        workspace_path_source(str(path), root=str(tmp_path))
        if workspace_relative
        else path_source(str(path))
    )

    fn = next(SourceFile(source).functions())
    outcome = fn.sugar().desugar(None)

    assert isinstance(outcome, Complete)
    assert type(outcome.value) is UniverseValue


# -- discriminating arm ------------------------------------------------------


def test_the_sibling_ground_exit_is_not_stolen() -> None:
    """``None[...]`` is still Python's exact ground ``TypeError``.

    The getattr arm sits beside that exit and took nothing from it: subscript
    is decided for every index, attribute is not decided for every name.
    """
    from sugar_lift_py_tests.floor import RaiseValue

    class _Fragment:
        filename = "none_subscript.py"
        line = 1
        col = 0

        class unit:
            source = "def f():\n    return None[0]\n"

        def __str__(self) -> str:
            return "<none_subscript.py [0, 1)>"

    outcome = NoneValue().subscript(None, _Fragment())

    assert isinstance(outcome, Complete)
    assert type(outcome.value) is RaiseValue
    assert outcome.value.exception.exception_name == "TypeError"


def test_the_arm_invents_no_field_and_no_exit() -> None:
    """Nothing is fabricated: not a field value, not a sentinel, not an exit."""
    from sugar_lift_py_tests.floor import RaiseValue

    outcome = NoneValue().attribute("foo", SITE)

    assert type(outcome.value) is not RaiseValue
    assert type(outcome.value) is SymbolicValue
