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
from pathlib import Path

from sugar_lift_py_tests.lift_rpc import open_source_file_for_construction
from sugar_lift_py_tests.outcome import ExitSet

from native_carrier_testimony import undecided_function_value


def _val(src):
    # The one construction door, under a workspace: an ``assert`` halts at a
    # ground ``AssertionError`` exit whose locus is workspace-relative.
    root = Path(tempfile.mkdtemp())
    path = root / "m.py"
    path.write_text(src, encoding="utf-8")
    function = next(open_source_file_for_construction(path, root=root).functions())
    outcome = function.sugar().desugar()
    if isinstance(outcome, ExitSet) and outcome.completed_value() is not None:
        return outcome.completed_value()
    # The later formal equality is the undecided equality's two faces: the
    # universe completes under its own completes atom (#7757, audit row NEW-1).
    return undecided_function_value(function, owner="UndecidedCompare:Eq")


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
    # The truth of the undecided ``==``'s value, keyed per evaluation
    # (#7757 NEW-1).
    assert v.invs()[0].name == "python:truth_result"
    assert v.invs()[0].args[0].name == "python:compare_result"
    assert v.invs()[0].args[0].args[0].value == "Eq"
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
