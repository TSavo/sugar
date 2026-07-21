"""AnnAssign (`x: T = v` / bare `x: T`) and AugAssign (`x OP= e`) -- both are
INERT at the meaning layer for a plain Name target, because their binding (if
any) already threaded via substitute/substitution_binding before sugar runs;
an annotation states nothing at runtime either way. Non-Name targets (and
attribute/subscript augmented targets, the shape substitution_binding refuses)
stay loud gaps."""

import tempfile

import pytest

from sugar_lift_python_source.source_oracle import path_source
from sugar_source_tree.panic import SugarNotWritten
from sugar_source_tree.tree import SourceFile


def _fn(src):
    with tempfile.NamedTemporaryFile("w", suffix=".py", delete=False, dir="/tmp") as f:
        f.write(src)
        path = f.name
    return next(SourceFile(path_source(path)).functions())


def test_annotated_assign_with_value_is_inert_and_threads():
    v = _fn("def A():\n    x: int = 5\n    return x\n").sugar().desugar().value
    assert v.invs() == ()
    assert v.post().args[1].value == 5


def test_bare_annotation_lifts_and_states_nothing():
    v = _fn("def A(z):\n    x: int\n    return z\n").sugar().desugar().value
    assert v.invs() == ()
    assert v.post().args[1].name == "z"


def test_aug_assign_rebinds_and_is_inert():
    v = _fn("def A():\n    t = 0\n    t += 2\n    return t\n").sugar().desugar().value
    assert v.invs() == ()
    assert v.post().args[1].value == 2


def test_attribute_aug_assign_stays_loud():
    # obj.a += 1 -- the target is not a plain Name, so substitution_binding
    # refuses it (returns None, never threads); sugar() mirrors that refusal
    # exactly and stays a loud gap rather than a silent/partial binding.
    fn = _fn("def A(obj):\n    obj.a += 1\n    return obj\n")
    with pytest.raises(SugarNotWritten):
        fn.sugar()


def test_aug_assign_with_no_prior_binding_is_sound():
    # x += 1 as the FIRST statement: substitution_binding cannot see a prior
    # x in scope, so it falls back to the target itself as the "old" value
    # (scope.get(name, self.target)) -- the binding still threads, just with
    # x left free/symbolic. Pinning what actually happens: `return x` inlines
    # to the BinOp `x + 1` over the still-free x, not a panic and not a
    # silent drop -- sound, not spent.
    v = _fn("def A(x):\n    x += 1\n    return x\n").sugar().desugar().value
    assert v.invs() == ()
    post = v.post()
    rhs = post.args[1]
    assert rhs.name == "+"
    assert rhs.args[0].name == "x"  # the still-free x, not a panic
    assert rhs.args[1].value == 1


def test_discrimination_annassign_value_changes_the_post():
    a = _fn("def A():\n    x: int = 5\n    return x\n").sugar().desugar().value.post()
    b = _fn("def A():\n    x: int = 6\n    return x\n").sugar().desugar().value.post()
    assert a.args[1].value == 5
    assert b.args[1].value == 6
    assert a.args[1].value != b.args[1].value


if __name__ == "__main__":
    test_annotated_assign_with_value_is_inert_and_threads()
    test_bare_annotation_lifts_and_states_nothing()
    test_aug_assign_rebinds_and_is_inert()
    test_attribute_aug_assign_stays_loud()
    test_aug_assign_with_no_prior_binding_is_sound()
    test_discrimination_annassign_value_changes_the_post()
    print("ok: AnnAssign/AugAssign inert for Name targets, loud otherwise")
