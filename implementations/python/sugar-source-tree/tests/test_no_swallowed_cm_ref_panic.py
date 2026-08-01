"""Narrow CM door panics must rise — never soft dual-mode as False.

SIN CLUSTER 4 / coord 2 — ``except Exception`` around ``_require_narrow_cm_ref``
under "soft dual-mode projection" turned a SourceTreePanic (named refusal)
into ``resolved_ref = None``, which the substitution path treated as "not an
effect boundary" and exported enter-result instead. UNDECIDED rendered as
False.

Replacement: call the door; None means absent arm; SourceTreePanic propagates.
"""

from __future__ import annotations

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
    """Lying twin: catching Exception and setting resolved_ref=None is the crime.

    Document the banned shape. If production re-grows the soft dual-mode
    catch, this twin fails because the panic is no longer raised.
    """
    panic = _panic(owner="test.lying-soft")
    site = _DuckWith(panic=panic, frame_projection=True)

    # Banned soft dual-mode (the old code):
    resolved_ref = None
    try:
        resolved_ref = site._require_narrow_cm_ref(site.items[0])
    except Exception:  # noqa: BLE001 — the sin under test
        resolved_ref = None
    assert resolved_ref is None, "lying twin: panic was reclassified as absence"

    # Truthful production path must still raise, not soft-None.
    with pytest.raises(UnsupportedContextManagerSemantics):
        site.substitution_binding(scope=None)


def test_truthful_frame_projection_no_longer_swallows_in_source():
    """Static twin: the soft dual-mode Exception catch is gone from With doors."""
    import inspect
    from pathlib import Path

    binding_src = inspect.getsource(With.substitution_binding)
    assert "soft dual-mode" not in binding_src
    assert "except Exception" not in binding_src
    assert "_require_narrow_cm_ref" in binding_src

    nodes_src = (
        Path(__file__).resolve().parents[1]
        / "src"
        / "sugar_source_tree"
        / "nodes.py"
    ).read_text(encoding="utf-8")
    assert "soft dual-mode factory projection" not in nodes_src
    assert "soft dual-mode projection" not in nodes_src
    # Import / return of the soft incomplete is gone (comment may still name it).
    assert "from sugar_lift_py_tests.sugar.soft_unresolved_with_sugar import" not in nodes_src
    assert "return SoftUnresolvedWithSugar" not in nodes_src
