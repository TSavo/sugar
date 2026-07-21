"""`<expr>` in statement position states nothing; effects ride."""

import tempfile

from sugar_lift_python_source.source_oracle import path_source
from sugar_source_tree.tree import SourceFile


def _val(src):
    with tempfile.NamedTemporaryFile("w", suffix=".py", delete=False, dir="/tmp") as f:
        f.write(src)
        path = f.name
    return next(SourceFile(path_source(path)).functions()).sugar().desugar().value


def test_docstring_and_bare_call_are_inert():
    v = _val('def A(z):\n    """doc."""\n    z.validate()\n    return z\n')
    assert v.invs() == ()
    assert v.post().args[1].name == "z"  # the function lifts through them


def test_bare_int_is_inert():
    v = _val("def A(z):\n    42\n    return z\n")
    assert v.invs() == () and v.post().args[1].name == "z"


if __name__ == "__main__":
    test_docstring_and_bare_call_are_inert()
    test_bare_int_is_inert()
    print("ok: expression statements inert; effects ride")
