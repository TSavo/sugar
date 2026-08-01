def _identity(module: str, name: str):
    from sugar_lift_py_tests.ir import ctor, str_const

    return ctor("python:exception_type_identity", [str_const(module), str_const(name)])


def _typed_value(identity, *mro):
    from sugar_lift_py_tests.floor import BlockValue, ClassValue
    from sugar_lift_py_tests.floor.authenticated_exception_type_value import (
        AuthenticatedExceptionTypeValue,
    )

    return AuthenticatedExceptionTypeValue(
        ClassValue("Renamed", (), BlockValue(())), identity, tuple(mro) or (identity,)
    )


def _leaf(identity, occurrence: str, *mro, raised_value=None):
    from sugar_lift_py_tests.effect import RaiseEffect

    if raised_value is None:
        raised_value = _typed_value(identity, *(tuple(mro) or (identity,)))
    return RaiseEffect(exception_type_coordinate=identity, occurrence=AuthenticatedRaiseLocus.of(occurrence), exception_type_mro=tuple(mro) or (identity,), raised_value=raised_value)


def test_nested_group_partition_preserves_tree_and_leaf_identities():
    from sugar_lift_py_tests.effect import GroupedRaiseEffect

    base = _identity("renamed", "Base")
    child = _identity("renamed", "Child")
    other = _identity("renamed", "Other")
    base_type = _typed_value(base)
    child_type = type(base_type)(
        type(base_type.value)("Renamed", (base_type.value,), base_type.value.record),
        child,
        (child, base),
    )
    matched_leaf = _leaf(child, "leaf:matched", child, base, raised_value=child_type)
    residual_leaf = _leaf(other, "leaf:residual")
    nested = GroupedRaiseEffect("group:nested", "nested", (matched_leaf, residual_leaf))
    incoming = GroupedRaiseEffect("group:root", "root", (nested,))

    partition = incoming.partition(base_type, "site")

    assert partition.matched.group_identity == "group:root"
    assert partition.residual.group_identity == "group:root"
    assert partition.matched.children[0].group_identity == "group:nested"
    assert partition.residual.children[0].group_identity == "group:nested"
    assert partition.matched.children[0].children == (matched_leaf,)
    assert partition.residual.children[0].children == (residual_leaf,)
    assert partition.matched.children[0].children[0] is matched_leaf
    assert partition.residual.children[0].children[0] is residual_leaf


def test_partition_keeps_both_empty_faces_explicit():
    from sugar_lift_py_tests.effect import GroupedRaiseEffect

    wanted = _identity("renamed", "Wanted")
    other = _identity("renamed", "Other")
    wanted_type = _typed_value(wanted)
    incoming = GroupedRaiseEffect(
        "group:root",
        "root",
        (_leaf(wanted, "leaf:wanted", raised_value=wanted_type),),
    )

    all_matched = incoming.partition(wanted_type, "site")
    none_matched = incoming.partition(_typed_value(other), "site")

    assert all_matched.residual.children == ()
    assert all_matched.residual.group_identity == "group:root"
    assert none_matched.matched.children == ()
    assert none_matched.matched.group_identity == "group:root"


def test_equal_spelling_with_lying_identity_does_not_match():
    from sugar_lift_py_tests.effect import GroupedRaiseEffect

    truthful = _identity("truthful", "RenamedError")
    lying = _identity("lying", "RenamedError")
    leaf = _leaf(truthful, "leaf:truthful")
    incoming = GroupedRaiseEffect("group:root", "root", (leaf,))

    partition = incoming.partition(_typed_value(lying), "site")

    assert partition.matched.children == ()
    assert partition.residual.children == (leaf,)


def test_except_star_partition_and_issubclass_share_class_value_floor(monkeypatch):
    from sugar_lift_py_tests.callable_application import CallableApplication
    from sugar_lift_py_tests.effect import GroupedRaiseEffect, RaiseEffect
    from sugar_lift_py_tests.floor import BlockValue, ClassValue
    from sugar_lift_py_tests.floor.authenticated_exception_type_value import (
        AuthenticatedExceptionTypeValue,
    )
    from sugar_lift_py_tests.temporal.builtin_name_bindings import builtin_name_temporal

    base_class = ClassValue("RenamedBase", (), BlockValue(()))
    leaf_class = ClassValue("RenamedLeaf", (base_class,), BlockValue(()))
    base_identity = _identity("truthful", "Base")
    leaf_identity = _identity("truthful", "Leaf")
    base_type = AuthenticatedExceptionTypeValue(base_class, base_identity)
    leaf_type = AuthenticatedExceptionTypeValue(leaf_class, leaf_identity)
    calls = []
    class_floor = ClassValue.test_python_subtype

    def recording_class_floor(self, supertype, site):
        calls.append((self, supertype))
        return class_floor(self, supertype, site)

    monkeypatch.setattr(ClassValue, "test_python_subtype", recording_class_floor)

    issubclass = builtin_name_temporal().value_for("issubclass")
    issubclass.callable_application_with(
        CallableApplication((leaf_class, base_class), (), "issubclass-site"), None
    )
    leaf = RaiseEffect(exception_type_coordinate=leaf_identity, occurrence=AuthenticatedRaiseLocus.of('leaf:truthful'), raised_value=leaf_type)
    partition = GroupedRaiseEffect("group:root", "root", (leaf,)).partition(
        base_type, "except-star-site"
    )

    assert partition.matched.children == (leaf,)
    assert calls == [(leaf_class, base_class), (leaf_class, base_class)]
