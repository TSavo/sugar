"""Import, ImportFrom, Pass, Global, Nonlocal state nothing at function-lift
level: they are honestly inert, not gaps.

An `import` binds a module name that stays a FREE SYMBOLIC in the meaning
layer -- a later `pd.concat(...)` reduces as a method coordinate on the free
name `pd`, correct without the import ever stating anything. `pass` states
nothing by definition. `global`/`nonlocal` are scope DECLARATIONS whose
binding semantics live in substitute, not meaning -- by sugar time there is
nothing left for them to say.
"""

import tempfile

from sugar_lift_python_source.source_oracle import path_source
from sugar_source_tree.tree import SourceFile


def _val(src):
    with tempfile.NamedTemporaryFile("w", suffix=".py", delete=False, dir="/tmp") as f:
        f.write(src)
        path = f.name
    return next(SourceFile(path_source(path)).functions()).sugar().desugar().value


def test_import_is_inert():
    v = _val("def A(z):\n    import os\n    return z\n")
    assert v.invs() == ()
    assert v.post().args[1].name == "z"


def test_import_from_is_inert():
    v = _val("def A(z):\n    from x import y\n    return z\n")
    assert v.invs() == ()
    assert v.post().args[1].name == "z"


def test_pass_is_inert():
    v = _val("def A(z):\n    pass\n    return z\n")
    assert v.invs() == ()
    assert v.post().args[1].name == "z"


def test_global_is_inert():
    v = _val("def A(z):\n    global g\n    return z\n")
    assert v.invs() == ()
    assert v.post().args[1].name == "z"


def test_nonlocal_is_inert():
    v = _val(
        "def A(z):\n"
        "    def inner():\n"
        "        nonlocal z\n"
        "        return z\n"
        "    return z\n"
    )
    assert v.invs() == ()
    assert v.post().args[1].name == "z"


def test_import_does_not_block_a_later_fact():
    v = _val("def A(z):\n    import m\n    assert z == 1\n    return z\n")
    assert len(v.invs()) == 1
    assert v.invs()[0].name == "py.eq"
    assert v.post().args[1].name == "z"


if __name__ == "__main__":
    test_import_is_inert()
    test_import_from_is_inert()
    test_pass_is_inert()
    test_global_is_inert()
    test_nonlocal_is_inert()
    test_import_does_not_block_a_later_fact()
    print(
        "ok: import/importfrom/pass/global/nonlocal inert; effects still ride through"
    )
