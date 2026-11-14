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
"""

from __future__ import annotations

from pathlib import Path

from sugar_lift_py_tests.outcome import Halted, outcome_to_exitset
from sugar_source_tree.nodes import FunctionDef

from test_contextmanager_generator_protocol import _imported

_IMPL = (
    "def u(*args, **kwargs):\n"
    "    import urllib.request\n"
    "    return urllib.request.{member}(*args, **kwargs)\n"
    "class M:\n"
    "    def __enter__(self):\n"
    "        u('http://x')\n"
    "        return 1\n"
    "    def __exit__(self, *exc):\n"
    "        return False\n"
    "def cm():\n"
    "    return M()\n"
)


def _owners(tmp_path: Path, member: str):
    tree, _with_node = _imported(
        tmp_path, _IMPL.format(member=member), "pass", contextlib_enrolled=False
    )
    func = next(
        n for n in tree.nodes() if isinstance(n, FunctionDef) and n.name == "f"
    )
    exits = outcome_to_exitset(func.sugar().desugar()).exits
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
