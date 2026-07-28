"""BANKED RED — Name AugAssign must own authenticated inplace as the rebind.

#6718 advisor: do not dual-eval project_inplace while substitute binds
``_make_binop`` (__add__).  Required twins when the Name vertical lands:

  1. divergent __iadd__ / __add__ (rebind must use iadd result)
  2. RHS evaluated once
  3. halt blocks rebind (no tail read of partial update)

Until then these stay @pytest.mark.xfail / banked — not silent green.
"""

from __future__ import annotations

import pytest

from sugar_lift_py_tests.context_manager_resolution import TreeConstructionContextV1
from sugar_lift_python_source.canonical import blake3_512_of
from sugar_source_tree.tree import SourceFile


def _tree(source: str, name: str = "name_aug_banked.py") -> SourceFile:
    return SourceFile(
        (source, name, blake3_512_of(source.encode())),
        construction_context=TreeConstructionContextV1.for_source_call_construction(),
    )


@pytest.mark.xfail(
    reason=(
        "Name AugAssign: substitute binds _make_binop while effect path must not "
        "dual-eval discarded project_inplace; rebind must own iadd result "
        "(banked #6718 split — Attribute lands first)"
    ),
    strict=True,
)
def test_banked_name_rebind_uses_iadd_not_add_when_they_diverge() -> None:
    """Twin: species with divergent __iadd__/__add__ — rebind must follow iadd."""
    raise AssertionError(
        "not implemented: Name AugAssign rebind must be authenticated inplace result"
    )


@pytest.mark.xfail(
    reason="Name AugAssign: RHS must evaluate once (no binop rebind + discarded iadd)",
    strict=True,
)
def test_banked_name_rhs_evaluated_once() -> None:
    raise AssertionError("not implemented: Name AugAssign RHS once-eval")


@pytest.mark.xfail(
    reason="Name AugAssign: halt must block rebind of the name",
    strict=True,
)
def test_banked_name_halt_blocks_rebind() -> None:
    raise AssertionError("not implemented: Name AugAssign halt-blocks-rebind")
