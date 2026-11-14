from sugar_lift_py_tests.effect.authenticated_raise_locus import AuthenticatedRaiseLocus


def _identity(module: str, name: str):
    """A source-class identity: one class, so a miss over a closed ancestry
    is decided (``matches_raise_effect``).  ``module`` keeps two same-spelled
    classes apart."""
    from sugar_lift_py_tests.ir import ctor, str_const

    return ctor(
        "python:exception_type_identity",
        [str_const("source-class"), str_const(f"{module}.{name}")],
    )


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
    return RaiseEffect(
        exception_type_coordinate=identity,
        occurrence=AuthenticatedRaiseLocus.of(occurrence),
        exception_type_mro=tuple(mro) or (identity,),
        raised_value=raised_value,
    )


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


def test_except_star_partition_asks_the_one_raise_matcher(monkeypatch):
    """A leaf is matched by the matcher ``except`` and ``with`` ask
    (``matches_raise_effect``), over the class its raise read off the
    constructed value (the effect's coordinate and ancestry): never a class
    floor of the leaf's own."""
    from sugar_lift_py_tests import authenticated_exception_matching
    from sugar_lift_py_tests.effect import GroupedRaiseEffect

    base = _identity("truthful", "Base")
    leaf_identity = _identity("truthful", "Leaf")
    base_type = _typed_value(base)
    leaf = _leaf(leaf_identity, "leaf:truthful", leaf_identity, base)
    calls = []
    matcher = authenticated_exception_matching.matches_raise_effect

    def recording_matcher(effect, expected):
        calls.append((effect, expected))
        return matcher(effect, expected)

    monkeypatch.setattr(
        authenticated_exception_matching, "matches_raise_effect", recording_matcher
    )

    partition = GroupedRaiseEffect("group:root", "root", (leaf,)).partition(
        base_type, "except-star-site"
    )

    assert partition.matched.children == (leaf,)
    assert calls == [(leaf, base_type)]


def test_an_undetermined_leaf_is_never_partitioned_by_a_guess():
    """A leaf whose construction carried no class is undecided: only
    ``except* BaseException`` catches it (every raise is one); any other
    type is refused by name, never decided a hit or a miss."""
    import pytest

    from sugar_lift_py_tests.effect import GroupedRaiseEffect
    from sugar_lift_py_tests.effect.raise_effect import UndeterminedRaiseEffect
    from sugar_lift_py_tests.ir import ctor, str_const
    from sugar_source_tree.panic import SugarNotWritten

    undecided = UndeterminedRaiseEffect(blame="leaf:undecided", occurrence="leaf:u")
    group = GroupedRaiseEffect("group:root", "root", (undecided,))
    base_exception = ctor(
        "python:exception_type_identity",
        [str_const("builtins"), str_const("BaseException")],
    )

    caught = group.partition(_typed_value(base_exception), "site")
    assert caught.matched.children == (undecided,)
    with pytest.raises(SugarNotWritten):
        group.partition(_typed_value(_identity("truthful", "Base")), "site")
