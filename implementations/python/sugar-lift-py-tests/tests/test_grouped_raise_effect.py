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


def _leaf(identity, occurrence: str, *mro):
    from sugar_lift_py_tests.effect import RaiseEffect

    return RaiseEffect(
        exception_type_coordinate=identity,
        exception_type_mro=tuple(mro) or (identity,),
        occurrence=occurrence,
        raised_value=_typed_value(identity, *(tuple(mro) or (identity,))),
    )


def test_nested_group_partition_preserves_tree_and_leaf_identities():
    from sugar_lift_py_tests.effect import GroupedRaiseEffect

    base = _identity("renamed", "Base")
    child = _identity("renamed", "Child")
    other = _identity("renamed", "Other")
    matched_leaf = _leaf(child, "leaf:matched", child, base)
    residual_leaf = _leaf(other, "leaf:residual")
    nested = GroupedRaiseEffect("group:nested", "nested", (matched_leaf, residual_leaf))
    incoming = GroupedRaiseEffect("group:root", "root", (nested,))

    partition = incoming.partition(_typed_value(base), "site")

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
    incoming = GroupedRaiseEffect(
        "group:root", "root", (_leaf(wanted, "leaf:wanted"),)
    )

    all_matched = incoming.partition(_typed_value(wanted), "site")
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
