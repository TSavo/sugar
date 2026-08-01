"""factoryPrefixCids seal is a transaction: every face mints or the door refuses.

SIN CLUSTER 4 / coord 1 — ``except ConstructionPanic: continue`` under
``never panic the door`` dropped unprojectable prefix faces, then sealed the
survivors into ``factoryPrefixCids`` inside the manager construction preimage.
A term-projection defect silently mutated identity: structurally different
factories could share a construction CID.

Replacement: ``_content_cids_for_factory_prefix`` — all faces project, or a
named ``ManagerConstructionGapV1`` carries the blame. Silence is not zero.
"""

from __future__ import annotations

from dataclasses import dataclass

from sugar_lift_py_tests.floor.floor_value import FloorValue
from sugar_lift_py_tests.floor.none_value import NoneValue
from sugar_lift_py_tests.gap.info import ConstructionGap, GapKind, GapLocus
from sugar_lift_py_tests.gap.panic import ConstructionPanic
from sugar_lift_py_tests.ir import _term_content_cid
from sugar_lift_python_source.manager_construction import (
    ManagerConstructionGapV1,
    _content_cids_for_factory_prefix,
)


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


def _lying_swallow_cids(
    factory_prefix: tuple[FloorValue, ...], *, resolved_cid: str
) -> tuple[str, ...]:
    """Banned shape: catch ConstructionPanic, keep survivors, seal shorter list.

    This is the old door. Tests keep it only as the LYING twin that must fail
    the content-address law.
    """
    cids: list[str] = []
    for item in factory_prefix:
        try:
            cids.append(_term_content_cid(item.to_term(owner=resolved_cid)))
        except ConstructionPanic:
            continue
    return tuple(cids)


def test_truthful_prefix_seal_projects_every_face():
    """Truthful twin: projectable prefix faces mint one CID each, in order."""
    resolved = "blake3-512:" + "a" * 128
    prefix = (NoneValue(), NoneValue())
    sealed = _content_cids_for_factory_prefix(prefix, resolved_cid=resolved)
    assert isinstance(sealed, tuple)
    assert len(sealed) == 2
    assert sealed[0] == _term_content_cid(NoneValue().to_term(owner=resolved))
    assert sealed[1] == sealed[0]


def test_truthful_prefix_seal_refuses_unprojectable_face_by_name():
    """Truthful twin: ConstructionPanic becomes a named force-floor residual."""
    resolved = "blake3-512:" + "b" * 128
    prefix = (NoneValue(), _PanickingPrefixFace("drop-me"))
    result = _content_cids_for_factory_prefix(prefix, resolved_cid=resolved)
    assert isinstance(result, ManagerConstructionGapV1)
    assert result.kind == "force-floor"
    assert result.resolved_object_cid == resolved
    assert "factory-prefix" in result.detail
    assert "_PanickingPrefixFace" in result.detail
    assert "test.factory-prefix" in result.detail


def test_lying_swallow_collides_identity_for_structurally_different_prefixes():
    """Lying twin MUST FAIL the content-address rule.

    Under the banned swallow, a prefix with an unprojectable face seals to the
    same CID list as the same prefix without that face — identity mutation.
    The truthful seal refuses the panicking prefix instead.
    """
    resolved = "blake3-512:" + "c" * 128
    alone = (NoneValue(),)
    with_panic = (NoneValue(), _PanickingPrefixFace("hidden-defect"))

    lying_alone = _lying_swallow_cids(alone, resolved_cid=resolved)
    lying_with = _lying_swallow_cids(with_panic, resolved_cid=resolved)
    # The crime: structurally different prefixes mint the same survivor CIDs.
    assert lying_alone == lying_with

    truthful_alone = _content_cids_for_factory_prefix(alone, resolved_cid=resolved)
    truthful_with = _content_cids_for_factory_prefix(with_panic, resolved_cid=resolved)
    assert truthful_alone == lying_alone
    assert isinstance(truthful_with, ManagerConstructionGapV1), (
        "truthful seal must refuse the unprojectable face; "
        f"got survivor CIDs {truthful_with!r} that collide with {truthful_alone!r}"
    )
    # Transaction: no partial survivor list is returned alongside a success.
    assert not isinstance(truthful_with, tuple)
