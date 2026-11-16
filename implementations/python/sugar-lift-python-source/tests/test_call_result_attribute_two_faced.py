"""``opaque().name`` is two-faced, the attribute twin of the #7587 subscript law.

``pandas.util.version.Version.__init__`` reads ``self._version.epoch`` where
``_version`` is an ``_Version(...)`` namedtuple call result whose runtime
type the lift did not decide.  ``CallSiteValue.attribute`` refused it as an
undecided receiver.  Under the #7585 law the member completes as the one
undecided read ``python:attribute_result("epoch", <receiver>, <key>)``
only under ``python:attribute_op.completes(...)`` and halts with an
``UndeterminedRaiseEffect`` under the complement.

The read is taken in ``f``'s own body: a same-file class's ``__init__`` is
not reduced at lift when the class is called (#7757 step 6), so a manager's
initializer is no window onto it.
"""

from __future__ import annotations

from sugar_lift_py_tests.effect.raise_effect import UndeterminedRaiseEffect

from test_assignment_evaluates_rhs import _rows
from test_undetermined_raise_except_matching import _exits


def _halts(tmp_path, body: str):
    rows = _rows(_exits(tmp_path, f"import re\ndef f():\n{body}"))
    halts = [payload for kind, payload, _ in rows if kind == "halt"]
    assert all(isinstance(halt, UndeterminedRaiseEffect) for halt in halts)
    assert all(halt.exception_name is None for halt in halts)
    return [halt.producer_node_owner for halt in halts]


def test_attribute_of_call_result_halts_or_completes(tmp_path):
    owners = _halts(tmp_path, "    p = re.compile('a')\n    return p.pattern\n")
    # The call's halt and the member read's own.
    assert len(owners) == 2
    assert "CallSiteValue.attribute" in owners


def test_call_result_without_attribute_has_only_the_call_halt(tmp_path):
    # The lying twin: binding the call result alone reads no member.
    owners = _halts(tmp_path, "    p = re.compile('a')\n    return p\n")
    assert len(owners) == 1
    assert "CallSiteValue.attribute" not in owners
