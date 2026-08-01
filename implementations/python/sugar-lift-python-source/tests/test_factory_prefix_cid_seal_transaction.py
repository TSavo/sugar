"""factoryPrefixCids: project every face or panic — no second mechanism.

SIN CLUSTER 4 / coord 1 — ``except ConstructionPanic: continue`` under
``never panic the door`` dropped unprojectable prefix faces, then sealed the
survivors into ``factoryPrefixCids`` inside the manager construction preimage.
A missing Sugar law was replaced by ad-hoc survival; identity mutated.

LAW OF ONE: AST shadows → Sugar → meaning. Catch-and-continue is a second
mechanism. DELETE the handler. If a face has no term, ConstructionPanic rises.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import pytest

from sugar_lift_py_tests.floor.floor_value import FloorValue
from sugar_lift_py_tests.floor.none_value import NoneValue
from sugar_lift_py_tests.gap.info import ConstructionGap, GapKind, GapLocus
from sugar_lift_py_tests.gap.panic import ConstructionPanic
from sugar_lift_py_tests.ir import _term_content_cid


@dataclass(frozen=True)
class _PanickingPrefixFace(FloorValue):
    """Honorable unfinished Floor: to_term raises ConstructionPanic."""

    label: str = "unwritten-prefix-face"

    def to_term(self, *, owner: str):
        del owner
        raise ConstructionPanic(
            ConstructionGap(
                owner="test.factory-prefix",
                blame=self.label,
                observed=type(self).__name__,
                requested="project this floor value to a term",
                fix=f"write more Floor: implement {type(self).__name__}.to_term",
                gap_kind=GapKind.FLOOR,
                gap_locus=GapLocus.PROJECTION,
            )
        )


def _project_prefix_cids(
    factory_prefix: tuple[FloorValue, ...], *, resolved_cid: str
) -> tuple[str, ...]:
    """Production shape after the fix: no try/except — panics rise."""
    return tuple(
        _term_content_cid(item.to_term(owner=resolved_cid)) for item in factory_prefix
    )


def _lying_swallow_cids(
    factory_prefix: tuple[FloorValue, ...], *, resolved_cid: str
) -> tuple[str, ...]:
    """Banned shape: catch ConstructionPanic, keep survivors, seal shorter list."""
    cids: list[str] = []
    for item in factory_prefix:
        try:
            cids.append(_term_content_cid(item.to_term(owner=resolved_cid)))
        except ConstructionPanic:
            continue
    return tuple(cids)


def test_truthful_prefix_projects_every_face():
    """Truthful twin: projectable faces mint one CID each, in order."""
    resolved = "blake3-512:" + "a" * 128
    prefix = (NoneValue(), NoneValue())
    sealed = _project_prefix_cids(prefix, resolved_cid=resolved)
    assert len(sealed) == 2
    assert sealed[0] == _term_content_cid(NoneValue().to_term(owner=resolved))
    assert sealed[1] == sealed[0]


def test_truthful_unprojectable_face_panics_the_door():
    """Truthful twin: ConstructionPanic propagates — the door panics."""
    resolved = "blake3-512:" + "b" * 128
    prefix = (NoneValue(), _PanickingPrefixFace("drop-me"))
    with pytest.raises(ConstructionPanic) as raised:
        _project_prefix_cids(prefix, resolved_cid=resolved)
    assert raised.value.info.owner == "test.factory-prefix"


def test_lying_swallow_collides_identity_for_structurally_different_prefixes():
    """Lying twin MUST FAIL the content-address rule under the banned swallow.

    Under catch-and-continue, a prefix with an unprojectable face seals to the
    same CID list as the same prefix without that face — identity mutation via
    a second mechanism. Truthful projection raises instead.
    """
    resolved = "blake3-512:" + "c" * 128
    alone = (NoneValue(),)
    with_panic = (NoneValue(), _PanickingPrefixFace("hidden-defect"))

    lying_alone = _lying_swallow_cids(alone, resolved_cid=resolved)
    lying_with = _lying_swallow_cids(with_panic, resolved_cid=resolved)
    assert lying_alone == lying_with  # the crime: collision

    truthful_alone = _project_prefix_cids(alone, resolved_cid=resolved)
    assert truthful_alone == lying_alone
    with pytest.raises(ConstructionPanic):
        _project_prefix_cids(with_panic, resolved_cid=resolved)


def test_production_source_has_no_factory_prefix_catch_continue():
    """Static twin: the catch-continue and "never panic the door" are gone."""
    source = (
        Path(__file__).resolve().parents[1]
        / "src"
        / "sugar_lift_python_source"
        / "manager_construction.py"
    ).read_text(encoding="utf-8")
    assert "never panic the door" not in source
    assert "kept_prefix" not in source
    # The seal is a bare projection loop — no ConstructionPanic handler on it.
    marker = "_term_content_cid(item.to_term(owner=resolved.cid))"
    assert marker in source
    # No _content_cids helper that catches panic into a gap (prior soft fix).
    assert "_content_cids_for_factory_prefix" not in source
