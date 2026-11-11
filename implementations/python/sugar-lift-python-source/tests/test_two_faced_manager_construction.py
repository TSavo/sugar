"""A source manager whose construction may raise is entered on each receiver.

``pandas.compat._optional.import_optional_dependency`` (reached from
``HDFStore.__init__``) reads ``sys.modules[install_name]``.  ``sys.modules`` is
an import member whose runtime value is not projected, so the subscript used
to refuse (``ImportMemberValue.subscript``: undecided receiver runtime type)
and voided the manager.  It is now the #7587 opaque-subscript law: it
completes under ``python:subscript.completes(...)`` and halts with an
``UndeterminedRaiseEffect`` under the complement.

A two-faced constructor leaves a receiver-state partition, not one receiver.
The ``with`` used to hand that partition to ``__enter__`` as if it were the
object (``AttributeError: ... call_method_value``, a bare crash).  The
manager's operation now runs on each receiver it can be: the construction
halt leaves as itself, and each completed receiver is entered.
"""

from __future__ import annotations

from test_contextmanager_generator_protocol import _function_rows, _imported


def _manager(init: str) -> str:
    return (
        "import sys\n"
        "class cm:\n"
        "    def __init__(self):\n"
        f"        {init}\n"
        "    def __enter__(self):\n"
        "        return 1\n"
        "    def __exit__(self, *exc):\n"
        "        return False\n"
    )


def _rows(tmp_path, init: str, body: str = "pass"):
    return _function_rows(
        *_imported(tmp_path, _manager(init), body, contextlib_enrolled=False)
    )[1]


def test_import_member_subscript_in_construction_is_two_faced(tmp_path):
    assert _rows(tmp_path, "self.m = sys.modules['os']") == [
        ("halt", None),
        ("return", 7),
    ]


def test_total_construction_has_no_construction_halt(tmp_path):
    # The lying twin: a constructor that cannot raise adds no face.
    assert _rows(tmp_path, "self.m = 1") == [("return", 7)]
