"""``bool(opaque())`` in ``and`` / ``or`` is two-faced, not a refusal.

``pandas.compat._optional.import_optional_dependency`` (reached from
``HDFStore.__init__``) writes ``if version and Version(version) < ...``
where ``version = get_version(module)`` is a call result whose runtime type
the lift did not decide.  The BoolOp producer refused that truth
(``boolean_operation_exception_floor: CallSiteValue and``) and voided the
manager.  Under the #7585 two-faced law the truth selection completes only
under ``python:truth.completes(python:truth(<call term>, <site>))`` and halts
with an ``UndeterminedRaiseEffect`` under the complement; no exception type
is named and no truth is decided.
"""

from __future__ import annotations

from test_contextmanager_generator_protocol import _function_rows, _imported


def _rows(tmp_path, init: str):
    impl = (
        "import os\n"
        "def ver(m):\n"
        "    return getattr(m, '__version__', None)\n"
        "class cm:\n"
        "    def __init__(self):\n"
        f"{init}"
        "    def __enter__(self):\n"
        "        return 1\n"
        "    def __exit__(self, *exc):\n"
        "        return False\n"
    )
    return _function_rows(
        *_imported(tmp_path, impl, "pass", contextlib_enrolled=False)
    )[1]


def test_call_result_truth_in_and_halts_or_selects(tmp_path):
    rows = _rows(tmp_path, "        v = ver(os)\n        self.ok = v and 1\n")
    assert ("halt", None) in rows
    assert set(rows) == {("halt", None), ("return", 7)}


# The decided twin (``self.ok = 0 and 1`` adds no halt) is deleted: ``cm()``
# is the same-file class call's coordinate and edge (#7757 step 6), so
# ``__init__`` is not reduced at lift and ``f``'s rows hold the ``with``'s own
# undecided faces whatever the initializer writes.  A decided operand's truth
# is read in ``__init__``'s own universe, where its rows are stated.
