"""AnnAssign (`x: T = v` / bare `x: T`) and AugAssign (`x OP= e`) -- both are
INERT at the meaning layer for a plain Name target, because their binding (if
any) already threaded via substitute/substitution_binding before sugar runs;
an annotation states nothing at runtime either way. Attribute/subscript
augmented targets and valued annotations build one typed runtime-store effect;
bare non-Name annotations remain loud gaps."""

import tempfile

from sugar_lift_python_source.source_oracle import path_source
from sugar_lift_py_tests.effect import (
    AttributeStoreRuntimeEffect,
    SubscriptStoreRuntimeEffect,
)
from sugar_lift_py_tests.outcome import Incomplete
from sugar_lift_py_tests.sugar.expr_statement_sugar import ExprStatementSugar
from sugar_lift_py_tests.sugar.store_effect_sugar import AttributeStoreEffectSugar
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


def _red_effects(source):
    entries = _fn(source).sugar().desugar().value.record.statements
    return [entry.effect for entry in entries if isinstance(entry, Incomplete)]


def test_attribute_aug_assign_builds_store_effect():
    effects = _red_effects("def A(obj, y):\n    obj.a += y\n    return y\n")

    assert len(effects) == 1
    assert isinstance(effects[0], AttributeStoreRuntimeEffect)


def test_subscript_aug_assign_builds_store_effect():
    effects = _red_effects("def A(d, k, y):\n    d[k] += y\n    return y\n")

    assert len(effects) == 1
    assert isinstance(effects[0], SubscriptStoreRuntimeEffect)


def test_annotated_attribute_with_value_builds_store_effect():
    effects = _red_effects("def A(obj, y):\n    obj.a: int = y\n    return y\n")

    assert len(effects) == 1
    assert isinstance(effects[0], AttributeStoreRuntimeEffect)


def test_annotated_subscript_with_value_builds_store_effect():
    effects = _red_effects("def A(d, k, y):\n    d[k]: int = y\n    return y\n")

    assert len(effects) == 1
    assert isinstance(effects[0], SubscriptStoreRuntimeEffect)


def test_bare_attribute_annotation_evaluates_only_renamed_receiver():
    function = _fn(
        "def record_shape(receiver):\n"
        "    receiver.payload: MissingType\n"
        "    return receiver\n"
    )
    substituted = function.substitute({})
    declaration = substituted.body[0]
    sugar = declaration.sugar()
    assert isinstance(sugar, ExprStatementSugar)
    assert sugar.value == declaration.target.value.sugar()

    value = function.sugar().desugar().value
    assert value.post().args[1].name == "receiver"


def test_valued_attribute_annotation_does_not_enter_bare_declaration_arm():
    function = _fn(
        "def record_shape(receiver, supplied):\n"
        "    receiver.payload: MissingType = supplied\n"
        "    return supplied\n"
    ).substitute({})
    sugar = function.body[0].sugar()
    assert isinstance(sugar, AttributeStoreEffectSugar)
    assert not isinstance(sugar, ExprStatementSugar)


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
    test_attribute_aug_assign_builds_store_effect()
    test_subscript_aug_assign_builds_store_effect()
    test_annotated_attribute_with_value_builds_store_effect()
    test_annotated_subscript_with_value_builds_store_effect()
    test_aug_assign_with_no_prior_binding_is_sound()
    test_discrimination_annassign_value_changes_the_post()
    print("ok: AnnAssign/AugAssign target roles build or stay loud by shape")
