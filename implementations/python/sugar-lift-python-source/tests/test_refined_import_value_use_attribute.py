"""A frame's import value-use reads as its import member (#7744).

Inside a dependency frame, the authenticated value-use receipt at
``urllib.request.urlopen`` is the whole answer: no dependency source refines
it (step 3).  ``pandas.io.common.urlopen`` is::

    def urlopen(*args, **kwargs):
        import urllib.request
        return urllib.request.urlopen(*args, **kwargs)

The spread call has no call receipt, so the callee Attribute itself is read.
It reads as the import member its transported receipt testifies (an
off-population stdlib callable, called two-faced), never as an attribute of
the module value ``urllib.request`` (an undecided-receiver refusal).

The function is reduced as itself: a same-file call is its coordinate and
edge (#7757 step 6, #8744), so no caller's reduction follows a manager's
``__enter__`` into it.
"""

from __future__ import annotations

from pathlib import Path

from sugar_lift_py_tests.outcome import Halted

from test_undetermined_raise_except_matching import _exits

_SOURCE = (
    "def f(*args, **kwargs):\n"
    "    import urllib.request\n"
    "    return urllib.request.{member}(*args, **kwargs)\n"
)


def _owners(tmp_path: Path, member: str):
    exits = _exits(tmp_path, _SOURCE.format(member=member)).exits
    return {
        str(getattr(face.effect, "producer_node_owner", None))
        for face in exits
        if isinstance(face, Halted)
    }


def test_a_refined_member_reads_as_the_import_member(tmp_path):
    owners = _owners(tmp_path, "urlopen")
    # The stdlib callable is called two-faced: it may raise.
    assert any("urllib.request.urlopen" in owner for owner in owners)
    # Never read as an attribute of an unknown or module value.
    assert not any(owner.startswith("UnknownAttribute") for owner in owners)
