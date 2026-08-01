"""Narrow CM door panics must rise — no soft dual-mode second mechanism.

SIN CLUSTER 4 / coord 2 — ``except Exception`` around ``_require_narrow_cm_ref``
turned a SourceTreePanic into ``resolved_ref = None`` / SoftUnresolvedWithSugar.
UNDECIDED rendered as False: a missing Sugar law replaced by ad-hoc survival.

DELETE the handler. None from the door is the only absent arm; panics rise.
"""

from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

import pytest

from sugar_source_tree.nodes import With
from sugar_source_tree.panic import UnsupportedContextManagerSemantics


def _fragment():
    return SimpleNamespace(filename="twin.py", line=1, col=0, source_cid="cid:frag")


def _panic(*, owner: str) -> UnsupportedContextManagerSemantics:
    return UnsupportedContextManagerSemantics(
        blame=_fragment(),
        demand_cid="demand",
        member_cid="member",
        owner=owner,
        observed="unsupported semantics face",
        requested="typed EffectBoundarySemanticsV1",
        fix="leave unsupported faces loud",
    )


class _DuckWith:
    """Duck-typed self for With.substitution_binding — avoids frozen Node layout."""

    def __init__(self, *, panic: UnsupportedContextManagerSemantics, frame_projection: bool):
        self.unit = SimpleNamespace(
            construction_context=SimpleNamespace(frame_projection=frame_projection)
        )
        self.fragment = _fragment()
        self.items = (
            SimpleNamespace(optional_vars=SimpleNamespace(kind="Name", id="e")),
        )
        self._panic = panic

    def _generator_manager_frame(self, item):
        del item
        return None

    def _require_narrow_cm_ref(self, item):
        del item
        raise self._panic

    def substitution_binding(self, scope):
        return With.substitution_binding(self, scope)


def test_truthful_substitution_binding_propagates_narrow_cm_panic():
    """Truthful twin: SourceTreePanic from the narrow door is not soft-None."""
    panic = _panic(owner="test.narrow-cm")
    site = _DuckWith(panic=panic, frame_projection=True)

    with pytest.raises(UnsupportedContextManagerSemantics) as raised:
        site.substitution_binding(scope=None)
    assert raised.value is panic
    assert raised.value.owner == "test.narrow-cm"


def test_lying_soft_none_would_hide_named_refusal_as_enter_result_path():
    """Lying twin: catching Exception and setting resolved_ref=None is the crime."""
    panic = _panic(owner="test.lying-soft")
    site = _DuckWith(panic=panic, frame_projection=True)

    resolved_ref = None
    try:
        resolved_ref = site._require_narrow_cm_ref(site.items[0])
    except Exception:  # noqa: BLE001 — the sin under test
        resolved_ref = None
    assert resolved_ref is None, "lying twin: panic was reclassified as absence"

    with pytest.raises(UnsupportedContextManagerSemantics):
        site.substitution_binding(scope=None)


def test_production_source_has_no_soft_dual_mode_catch():
    """Static twin: soft dual-mode Exception catch is deleted from With doors."""
    import inspect

    binding_src = inspect.getsource(With.substitution_binding)
    assert "except Exception" not in binding_src
    assert "_require_narrow_cm_ref" in binding_src

    nodes_src = (
        Path(__file__).resolve().parents[1]
        / "src"
        / "sugar_source_tree"
        / "nodes.py"
    ).read_text(encoding="utf-8")
    assert "from sugar_lift_py_tests.sugar.soft_unresolved_with_sugar import" not in nodes_src
    assert "return SoftUnresolvedWithSugar" not in nodes_src
    assert "noqa: BLE001" not in nodes_src
