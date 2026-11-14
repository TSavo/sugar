"""Every halt states the source fragment it left at on its effect's ``site``
(#7766, after #8185): the halts that still had none.

``tree_enumerate.halt_locus`` refuses by name a halt whose effect states no
fragment, so each producer below carries the real fragment from where it
builds the effect: the ``with`` item a formal-selected manager's steps halt at,
the ``with`` whose generator ``__exit__`` refuses, the ``break``/``continue``
statement, the ``warnings.warn`` call.
"""

from __future__ import annotations

import pytest

from sugar_lift_py_tests.context_manager_resolution import SourceFragmentCoordinateV1
from sugar_lift_py_tests.outcome.exit_set import Halted
from sugar_lift_py_tests.unanswered_calls import UnansweredCallV1

_SRC = "blake3-512:" + "ab" * 64
_COORDINATE = SourceFragmentCoordinateV1(_SRC, 3, 4, 3, 12)
_CID = "blake3-512:" + "ef" * 64


class _Fragment:
    """What a panic locus reads off a fragment: file, line, column."""

    filename = "pkg/mod.py"
    line = 3
    col = 4

    def __str__(self) -> str:
        return "pkg/mod.py:3:4"


@pytest.mark.parametrize("step", ["select", "construct", "__enter__", "__exit__"])
def test_a_formal_selected_manager_step_halts_at_the_with_item(step: str) -> None:
    from sugar_lift_py_tests.floor.entered_manager_state_value import (
        EnteredManagerStateValue,
    )
    from sugar_lift_py_tests.floor.formal_selected_manager import (
        FormalSelectedManagerProtocol,
        FormalSelectedManagerValue,
    )

    fragment = _Fragment()
    protocol = FormalSelectedManagerProtocol(
        "p.open", "with-key", _COORDINATE, fragment=fragment
    )
    manager = FormalSelectedManagerValue("p.open", "with-key")
    if step == "select":
        faces = protocol.step_faces("select", None)
    elif step == "construct":
        faces = protocol.construct_manager(manager)
    elif step == "__enter__":
        faces = protocol.enter_resource_outcome_for(manager)
    else:
        faces = protocol.exit_outcome_for(
            EnteredManagerStateValue(enter_value=None, receiver_state=manager)
        )
    (halt,) = [arm for arm in faces.exits if isinstance(arm, Halted)]
    # The halt states the item's fragment; the debt stays keyed on the
    # item's coordinate, as before.
    assert halt.effect.site is fragment
    assert halt.owed == (UnansweredCallV1(None, _COORDINATE),)


def test_the_head_sugar_carries_the_item_fragment() -> None:
    from sugar_lift_py_tests.floor.formal_selected_manager import (
        FormalSelectedManagerProtocol,
    )

    fragment = _Fragment()
    protocol = FormalSelectedManagerProtocol(
        "p.open", "with-key", _COORDINATE, fragment=fragment
    )
    assert protocol.head_sugar().fragment is fragment
    # Testimony, not identity: the fragment never splits two protocols.
    assert protocol == FormalSelectedManagerProtocol("p.open", "with-key", _COORDINATE)


def test_a_generator_manager_exit_refusal_halts_at_the_with() -> None:
    from sugar_lift_py_tests.generator_manager_exit import (
        _pep479,
        _refusal,
        observed_exit_refusals,
    )

    fragment = _Fragment()
    refusal = _refusal(observed_exit_refusals().did_not_stop, site=fragment)
    assert refusal.site is fragment
    assert refusal.blame == str(fragment)
    converted = _pep479(refusal, site=fragment)
    assert converted.site is fragment


def test_a_loop_control_halt_states_its_statement() -> None:
    from sugar_lift_py_tests.effect.loop_control_effect import LoopControlEffect

    fragment = _Fragment()
    effect = LoopControlEffect("break", _CID, _CID, site=fragment)
    assert effect.site is fragment
    # The occurrence is the identity; the site is testimony.
    assert effect == LoopControlEffect("break", _CID, _CID)


def test_a_warning_states_the_call_it_was_observed_at() -> None:
    from sugar_lift_py_tests.effect.warning_effect import WarningEffect

    fragment = _Fragment()
    effect = WarningEffect("UserWarning", site=fragment)
    assert effect.site is fragment
    assert "pkg/mod.py:3:4" in effect.reason
