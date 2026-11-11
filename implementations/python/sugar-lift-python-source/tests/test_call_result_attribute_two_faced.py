"""``opaque().name`` is two-faced, the attribute twin of the #7587 subscript law.

``pandas.util.version.Version.__init__`` reads ``self._version.epoch`` where
``_version`` is an ``_Version(...)`` namedtuple call result whose runtime
type the lift did not decide.  ``CallSiteValue.attribute`` refused it as an
undecided receiver.  Under the #7585 law the member completes as the
coordinate ``attr:epoch(<receiver>)`` only under
``python:attribute.completes(...)`` and halts with an
``UndeterminedRaiseEffect`` under the complement.
"""

from __future__ import annotations

from test_contextmanager_generator_protocol import _function_rows, _imported


def _rows(tmp_path, init: str):
    impl = (
        "import re\n"
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


def test_attribute_of_call_result_halts_or_completes(tmp_path):
    rows = _rows(tmp_path, "        p = re.compile('a')\n        self.e = p.pattern\n")
    assert ("halt", None) in rows
    assert rows.count(("halt", None)) == 2


def test_call_result_without_attribute_has_only_the_call_halt(tmp_path):
    # The lying twin: binding the call result alone reads no member.
    # (``re.compile`` itself is two-faced; the member read adds its own halt.)
    without = _rows(tmp_path, "        self.p = re.compile('a')\n")
    assert ("return", 7) in without
    assert without.count(("halt", None)) == 1
