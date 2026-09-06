"""SubscriptOperation exposes ``site`` (regression: warnings tip board).

Reducing a subscript over an undecided receiver -- an ImportMemberValue under
an enrolled stdlib body -- reads ``operation.site``. SubscriptOperation
recorded that fragment under ``blame``; the missing ``site`` raised
AttributeError and voided 31 files on the warnings-enrolled board. ``site`` is
the same locus as ``blame`` and turns the crash into an honest undecided
subscript boundary.
"""

from __future__ import annotations

from sugar_lift_py_tests.floor.term_value import TermValue
from sugar_lift_py_tests.operations.subscript_operation import SubscriptOperation


def test_site_is_the_blame_locus() -> None:
    op = SubscriptOperation(index=TermValue(0), owner="t", blame="f.py:3:1")
    assert op.site == "f.py:3:1"
    assert op.site is op.blame
