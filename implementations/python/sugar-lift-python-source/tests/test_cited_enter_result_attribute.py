"""``with urlopen(...) as req: req.headers`` -- a read on a cited enter result.

``pandas.io.common.get_handle`` reads ``req.headers`` on the value a cited
(off-population) manager's ``__enter__`` returned.  When a dependency frame is
projected, the body reads ``req`` through its ``#enter_result`` slot
(``EffectCoordinate``), which had no attribute floor: "implement
EffectCoordinate.attribute".

Law (#7585, the same as ``opaque().name``): nothing testified to the runtime
type ``__enter__`` returned, so the read completes as ``attr:<name>(<slot>)``
only under ``python:attribute.completes(python:attribute(<slot>, <name>,
<site>))`` and halts with an ``UndeterminedRaiseEffect`` under the
complement.  No member value and no exception identity are invented.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from sugar_lift_py_tests.floor.effect_coordinate import EffectCoordinate
from sugar_lift_py_tests.effect.raise_effect import UndeterminedRaiseEffect
from sugar_lift_py_tests.outcome.exit_set import Completed, Halted

from test_contextmanager_generator_protocol import _function_rows, _imported


def test_enter_result_slot_attribute_is_two_faced() -> None:
    slot = EffectCoordinate(slot_id="with@1:4#0#enter_result")
    faces = slot.attribute("headers", "site.py:3:8", None).exits
    completed = [face for face in faces if isinstance(face, Completed)]
    halted = [face for face in faces if isinstance(face, Halted)]
    assert len(completed) == 1 and len(halted) == 1
    assert "python:attribute.completes" in repr(completed[0].guard)
    assert "attr:headers" in repr(completed[0].value.to_term(owner="test"))
    assert isinstance(halted[0].effect, UndeterminedRaiseEffect)


def test_other_effect_slots_keep_their_floor() -> None:
    # Lying twin: only an enter-result slot is a value ``__enter__`` returned;
    # an exception slot's attribute floor is unchanged.
    slot = EffectCoordinate(slot_id="try@1:4#handler0")
    from sugar_lift_py_tests.gap.panic import ConstructionPanic

    with pytest.raises(ConstructionPanic):
        slot.attribute("headers", "site.py:3:8", None)


def test_dependency_frame_reads_cited_enter_result(tmp_path: Path) -> None:
    implementation = (
        "def opener(*args, **kwargs):\n"
        "    import contextlib\n"
        "    return contextlib.nullcontext(*args, **kwargs)\n"
        "import contextlib\n"
        "@contextlib.contextmanager\n"
        "def cm():\n"
        "    with opener(1) as req:\n"
        "        encoding = req.headers\n"
        "    yield 1\n"
    )
    tree, with_node = _imported(tmp_path, implementation, "pass", contextlib_enrolled=False)
    _consumer, rows = _function_rows(tree, with_node)
    assert ("return", 7) in rows
    assert ("halt", None) in rows

