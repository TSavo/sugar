"""``None.<name>``: Python's ``AttributeError`` off ``NoneType``'s members, the
getattr coordinate on them.

Four ``attribute x NoneValue`` rows on the pinned pandas tree
(``arrays/boolean.py``, ``arrays/numeric.py``, ``indexes/accessors.py``,
``plotting/_matplotlib/core.py``) construction_panicked with
``owner=attribute observed=NoneValue``: ``NoneValue`` had no ``attribute``
arm.

``NoneType``'s member set is closed (``NoneValue._NONETYPE_MEMBERS``,
CPython's ``dir(None)``). A name outside it -- ``None.foo`` -- definitely
raises ``AttributeError``: a raise is a halt, never a completion, so it is the
ground exceptional exit, cited at its source fragment. A name inside it --
``None.__class__`` -- is a real member and does not raise; its value stays the
``getattr_coordinate``, which claims nothing about what the member is.

A ground exit cites source it can re-read, so its locus must be
workspace-relative (``ground_exit.ground_raise_effect``): through the
workspace door the whole function halts with the ``AttributeError``; through
the absolute-locus door the citation is refused by name. Both doors are
asserted, so neither stops being true silently.
"""

from __future__ import annotations

import pytest

from sugar_lift_py_tests.floor.none_value import NoneValue
from sugar_lift_py_tests.floor.symbolic_value import SymbolicValue
from sugar_lift_py_tests.gap.panic import ConstructionPanic
from sugar_lift_py_tests.ir import str_const
from sugar_lift_py_tests.effect import RaiseEffect

SITE = "none-attribute-site"


class _Fragment:
    """A workspace-relative source fragment, as a ground exit cites it."""

    filename = "none_attribute.py"
    line = 2
    col = 11

    class unit:
        source = "def f():\n    return None.foo\n"

    def __str__(self) -> str:
        return "<none_attribute.py [20, 28)>"


def _coordinate(outcome):
    value = outcome.completed_value()
    assert value is not None, outcome
    assert type(value) is SymbolicValue
    term = value.term
    assert term.name == "py.getattr"
    return term


def _attribute_error(outcome):
    """The one halt ``outcome`` is: Python's ground ``AttributeError``."""
    assert outcome.halts() == outcome.exits, outcome
    (halt,) = outcome.halts()
    assert type(halt.effect) is RaiseEffect
    assert halt.effect.exception_name == "AttributeError"
    assert halt.effect.raised_value.exception_name == "AttributeError"
    return halt


# -- a name off the member set: the AttributeError ---------------------------


def test_none_attribute_off_the_member_set_is_the_attribute_error() -> None:
    _attribute_error(NoneValue().attribute("foo", _Fragment(), None))


# -- a real member: the getattr coordinate -----------------------------------


@pytest.mark.parametrize(
    "name",
    (
        # REAL members of NoneType. Python does not raise for these, which is
        # why the arm is not a blanket ground AttributeError.
        "__class__",
        "__doc__",
        "__bool__",
    ),
)
def test_the_coordinate_makes_no_claim_about_a_real_member(name) -> None:
    """``None.__class__`` does not raise. The coordinate is an opaque symbol
    over the receiver's term and the name: it states no value for the
    member."""
    term = _coordinate(NoneValue().attribute(name, SITE, None))

    assert term.args[0] == NoneValue().to_term(owner="NoneValue.attribute")
    assert term.args[1] == str_const(name)


# -- the real reproducer, through BOTH source doors --------------------------


@pytest.mark.parametrize("workspace_relative", (False, True))
def test_the_whole_function_lifts_through_either_source_door(
    tmp_path, workspace_relative
) -> None:
    """The workspace door halts with the cited ``AttributeError``; the
    absolute-locus door refuses the citation by name, never a completion."""
    from sugar_lift_python_source.source_oracle import (
        path_source,
        workspace_path_source,
    )
    from sugar_lift_py_tests.context_manager_resolution import TreeConstructionContextV1
    from sugar_lift_py_tests.lift_rpc import tree_construction_context_for_workspace
    from sugar_source_tree.tree import SourceFile

    path = tmp_path / "none_attribute.py"
    path.write_text("def f():\n    return None.foo\n", encoding="utf-8")

    # THE CONTEXT IS PARAMETRIZED ALONGSIDE THE DOOR, because the two arms make
    # different claims about the same line. The rooted arm holds a workspace
    # (``root`` is required, so its presence proves one) and must honour it; the
    # absolute arm genuinely has none, and asserting so is true there.
    if workspace_relative:
        source = workspace_path_source(str(path), root=str(tmp_path))
        context = tree_construction_context_for_workspace(tmp_path)
    else:
        source = path_source(str(path))
        context = TreeConstructionContextV1.for_test_without_workspace()

    fn = next(SourceFile(source, construction_context=context).functions())

    if not workspace_relative:
        with pytest.raises(ConstructionPanic) as refused:
            fn.sugar().desugar(None)
        assert refused.value.info.owner == "NoneValue.attribute"
        assert refused.value.info.observed == "absolute source locus"
        return

    halt = _attribute_error(fn.sugar().desugar(None))
    assert halt.effect.occurrence.value == "none_attribute.py:2:11"


# -- discriminating arm ------------------------------------------------------


def test_the_sibling_ground_exit_is_not_stolen() -> None:
    """``None[...]`` is still Python's exact ground ``TypeError``.

    The attribute arm sits beside that exit and took nothing from it.
    """

    class _SubscriptFragment:
        filename = "none_subscript.py"
        line = 1
        col = 0

        class unit:
            source = "def f():\n    return None[0]\n"

        def __str__(self) -> str:
            return "<none_subscript.py [0, 1)>"

    outcome = NoneValue().subscript(None, _SubscriptFragment())

    assert outcome.halts() == outcome.exits
    (halt,) = outcome.halts()
    assert type(halt.effect) is RaiseEffect
    assert halt.effect.raised_value.exception_name == "TypeError"


def test_the_arm_invents_no_field_and_no_completion() -> None:
    """Nothing is fabricated for ``None.foo``: not a field value, not a
    sentinel, not a completion -- only the halt Python takes."""

    outcome = NoneValue().attribute("foo", _Fragment(), None)

    assert outcome.completed_value() is None
    _attribute_error(outcome)
