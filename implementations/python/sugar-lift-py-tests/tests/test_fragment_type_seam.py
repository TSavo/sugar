"""RuntimeEffectSite admits the one SourceFragment structurally.

Exactly one SourceFragment: sugar_source_tree.fragment.SourceFragment,
minted only by enumeration through the one SourceOracle. Admission is
filename/line/col — never isinstance of a second currency.
"""

import tempfile

import pytest

from sugar_lift_py_tests.effect.runtime_effect import (
    RuntimeEffectSite,
    resolve_runtime_effect_site,
    runtime_effect_evidence,
)
from sugar_lift_python_source.source_oracle import path_source
from sugar_source_tree.tree import SourceFile


def _tree_fragment(src: str):
    with tempfile.NamedTemporaryFile("w", suffix=".py", delete=False, dir="/tmp") as f:
        f.write(src)
        path = f.name
    fn = next(SourceFile(path_source(path)).functions())
    return fn.fragment


def test_tree_fragment_satisfies_the_site_protocol_structurally():
    frag = _tree_fragment("def A(z):\n    return z\n")
    assert isinstance(frag, RuntimeEffectSite)
    assert resolve_runtime_effect_site(frag) is frag


def test_tree_fragment_mints_full_runtime_effect_evidence():
    from sugar_lift_py_tests.ir import make_var

    frag = _tree_fragment("def A(z):\n    return z\n")
    evidence = runtime_effect_evidence("py.setattr", make_var("runtime_v"), frag)
    witness = evidence["witness"]
    assert witness.site is frag
    assert witness.locus == f"{frag.filename}:{frag.line}:{frag.col}"


def test_an_object_missing_line_col_is_unrepresentable_as_a_site():
    class NotAFragment:
        filename = "x.py"
        # no line, no col

    with pytest.raises(TypeError, match="filename/"):
        resolve_runtime_effect_site(NotAFragment())


def test_no_isinstance_of_a_named_fragment_class_gates_the_door():
    class DuckFragment:
        filename = "duck.py"
        line = 3
        col = 4

    duck = DuckFragment()
    assert resolve_runtime_effect_site(duck) is duck
