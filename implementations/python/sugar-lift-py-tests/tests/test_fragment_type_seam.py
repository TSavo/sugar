"""The fragment-type seam: `resolve_runtime_effect_site` admits a fragment
structurally (RuntimeEffectSite: filename/line/col), not by isinstance-ing
one concrete class. The tree's own SourceFragment (the hot-path currency for
statement-level effect attachment) and the kit's factory-era SourceFragment
(still the currency the floor evaluators mint their evidence from) are both
admitted through the SAME predicate -- there is no separate isinstance arm
naming either class, so neither is a silently-preferred dual citizen and
neither is a name-checked legacy branch. An object that does NOT answer
filename/line/col is unrepresentable as a witness address."""

import tempfile

import pytest

from sugar_lift_py_tests.effect.runtime_effect import (
    RuntimeEffectSite,
    resolve_runtime_effect_site,
    runtime_effect_evidence,
)
from sugar_lift_py_tests.factory.source_fragment import SourceFragment as FactoryFragment
from sugar_lift_python_source.source_oracle import path_source
from sugar_source_tree.fragment import SourceFragment as TreeFragment
from sugar_source_tree.tree import SourceFile


def _tree_fragment(src):
    with tempfile.NamedTemporaryFile("w", suffix=".py", delete=False, dir="/tmp") as f:
        f.write(src)
        path = f.name
    fn = next(SourceFile(path_source(path)).functions())
    return fn.fragment


def test_tree_fragment_satisfies_the_site_protocol_structurally():
    frag = _tree_fragment("def A(z):\n    return z\n")
    assert isinstance(frag, RuntimeEffectSite)
    assert resolve_runtime_effect_site(frag) is frag


def test_factory_fragment_satisfies_the_same_site_protocol():
    frag = FactoryFragment.from_source("x = 1", "t.py").statements()[0]
    assert isinstance(frag, RuntimeEffectSite)
    assert resolve_runtime_effect_site(frag) is frag


def test_tree_fragment_mints_full_runtime_effect_evidence():
    """No adapter, no shim: the tree fragment builds a real witness through
    the same door the factory fragment uses."""
    from sugar_lift_py_tests.ir import make_var

    frag = _tree_fragment("def A(z):\n    return z\n")
    evidence = runtime_effect_evidence("py.setattr", make_var("runtime_v"), frag)
    witness = evidence["witness"]
    assert witness.site is frag
    assert witness.locus == f"{frag.filename}:{frag.line}:{frag.col}"


def test_an_object_missing_line_col_is_unrepresentable_as_a_site():
    """The negative space: nothing that fails the structural contract can
    mint evidence, regardless of which fragment "family" a caller intended."""

    class NotAFragment:
        filename = "x.py"
        # no line, no col

    with pytest.raises(TypeError, match="filename/"):
        resolve_runtime_effect_site(NotAFragment())


def test_no_isinstance_of_a_named_fragment_class_gates_the_door():
    """Structural discipline check: the seam's admission predicate is the
    protocol, not either concrete fragment class -- so a duck-typed
    stand-in with the right shape is admitted too, proving there is no
    hidden isinstance(..., SomeConcreteFragment) arm left in the door."""

    class DuckFragment:
        filename = "duck.py"
        line = 3
        col = 4

    duck = DuckFragment()
    assert resolve_runtime_effect_site(duck) is duck


if __name__ == "__main__":
    test_tree_fragment_satisfies_the_site_protocol_structurally()
    test_factory_fragment_satisfies_the_same_site_protocol()
    test_tree_fragment_mints_full_runtime_effect_evidence()
    test_an_object_missing_line_col_is_unrepresentable_as_a_site()
    test_no_isinstance_of_a_named_fragment_class_gates_the_door()
    print("ok: fragment-type seam unified on the structural site protocol")
