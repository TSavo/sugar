# SPDX-License-Identifier: MIT OR Apache-2.0
"""Teeth for the test-boundary residency reset (#7364).

The process-resident file cache is keyed by (content CID, workspace-RELATIVE
filename). Two tests writing byte-identical source under the same relative name
collide, and ``_prepare_uncached`` -- MaterializeModule plus the unit's relation
tables -- runs only on a MISS. So without a reset at the test boundary, the
second test inherits the first test's mutated unit and can pass without ever
exercising its own mechanism.

These teeth are deliberately ORDER-INDEPENDENT: each one asserts a clean unit on
entry and then mutates it. Whichever runs second bites when isolation is absent,
so ``pytest-randomly`` cannot shuffle the trap out of the run.

Discrimination: ``test_residency_still_shares_within_one_test`` runs the OTHER
arm -- residency must still amortise inside a single test body. A reset that
also broke within-test sharing would satisfy the isolation teeth while silently
repealing protocol §4, and this arm refuses that.
"""

from __future__ import annotations

from sugar_lift_python_source.canonical import blake3_512_of
from sugar_source_tree.process_resident_file import prepare_count_for, resident_size
from sugar_source_tree.tree import SourceFile

# ONE body, ONE relative name, shared by both isolation teeth on purpose: this
# is exactly the colliding key. Do not make these unique -- uniqueness is the
# local workaround the autouse reset exists to make unnecessary.
_SHARED_BODY = "def collide(value):\n    return value\n"
_SHARED_SEAT = "shared/collide.py"
_SENTINEL = "_cross_test_residency_sentinel_7364"


def _identity() -> tuple[str, str, str]:
    return (_SHARED_BODY, _SHARED_SEAT, blake3_512_of(_SHARED_BODY.encode("utf-8")))


def _open_shared() -> object:
    return SourceFile(_identity())


def _assert_unit_is_not_inherited(source_file: object, *, arm: str) -> None:
    """Refuse a unit another test already touched. Names the coordinate.

    Absence and lookup-failure do not share a representation: a unit this test
    prepared has no sentinel ATTRIBUTE at all, while an inherited unit carries
    the sentinel naming the arm that stranded it.
    """
    stranded = getattr(source_file.unit, _SENTINEL, None)
    assert stranded is None, (
        f"construct=SourceUnit coordinate=(source_cid={source_file.unit.source_cid}, "
        f"seat={_SHARED_SEAT!r}) shape=inherited-residency: arm {arm!r} was handed a "
        f"unit already mutated by arm {stranded!r}. The process-resident cache "
        f"survived the test boundary, so this arm never ran _prepare_uncached and "
        f"its mechanism was never exercised (#7364)."
    )


def _strand(source_file: object, *, arm: str) -> None:
    object.__setattr__(source_file.unit, _SENTINEL, arm)


def test_resident_unit_is_not_inherited_arm_a() -> None:
    """Arm A: clean unit on entry, then strand it for whoever comes next."""
    source_file = _open_shared()
    _assert_unit_is_not_inherited(source_file, arm="arm_a")
    _strand(source_file, arm="arm_a")


def test_resident_unit_is_not_inherited_arm_b() -> None:
    """Arm B: byte-identical body, same seat, same key. Must still be clean."""
    source_file = _open_shared()
    _assert_unit_is_not_inherited(source_file, arm="arm_b")
    _strand(source_file, arm="arm_b")


def test_residency_still_shares_within_one_test() -> None:
    """Other arm: protocol §4 amortisation inside one test body is intact.

    The reset is a test-BOUNDARY reset. Within one body, the same CID and seat
    must still hit residency and pay MaterializeModule exactly once.
    """
    cid = blake3_512_of(_SHARED_BODY.encode("utf-8"))
    first = _open_shared()
    second = _open_shared()
    assert second is first, (
        "construct=SourceUnit coordinate=(source_cid=%s, seat=%r) shape=residency-repealed: "
        "two opens of the same content and seat inside ONE test body produced "
        "distinct SourceFiles. The test-boundary reset must not break within-test "
        "amortisation (protocol §4)." % (cid, _SHARED_SEAT)
    )
    assert prepare_count_for(cid, _SHARED_SEAT) == 1
    assert resident_size() == 1
