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

    (partition,) = incoming.partition(base_type, "site")

    assert partition.conditions == ()
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

    (all_matched,) = incoming.partition(wanted_type, "site")
    (none_matched,) = incoming.partition(_typed_value(other), "site")

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

    (partition,) = incoming.partition(_typed_value(lying), "site")

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

    (partition,) = GroupedRaiseEffect("group:root", "root", (leaf,)).partition(
        base_type, "except-star-site"
    )

    assert partition.matched.children == (leaf,)
    assert calls == [(leaf, base_type)]


def test_an_undetermined_leaf_is_never_partitioned_by_a_guess():
    """A leaf whose construction carried no class is undecided: only
    ``except* BaseException`` decides it (every raise is one).  Any other
    type is the two-way split ordinary ``except`` owns for an undecided
    match: matched under the retained type test, residual under its
    complement, each with its face -- never a refusal, never a guess."""
    from sugar_lift_py_tests.authenticated_exception_matching import (
        MatchRetained,
        matches_raise_effect,
    )
    from sugar_lift_py_tests.effect import GroupedRaiseEffect
    from sugar_lift_py_tests.effect.raise_effect import UndeterminedRaiseEffect
    from sugar_lift_py_tests.ir import ctor, not_, str_const

    base_exception = ctor(
        "python:exception_type_identity",
        [str_const("builtins"), str_const("BaseException")],
    )
    other = _identity("truthful", "Other")
    undecided = UndeterminedRaiseEffect(blame="leaf:undecided", occurrence="leaf:u")
    decided = _leaf(other, "leaf:other", other, base_exception)
    group = GroupedRaiseEffect("group:root", "root", (undecided, decided))

    (caught,) = group.partition(_typed_value(base_exception), "site")
    assert caught.matched.children == (undecided, decided)
    assert caught.conditions == ()

    handler = _typed_value(_identity("truthful", "Base"))
    verdict = matches_raise_effect(undecided, handler)
    assert isinstance(verdict, MatchRetained)
    matched, missed = group.partition(handler, "site")
    assert matched.matched.children == (undecided,)
    assert matched.residual.children == (decided,)
    assert missed.matched.children == ()
    assert missed.residual.children == (undecided, decided)
    ((held, caught_face),) = matched.conditions
    ((complement, missed_face),) = missed.conditions
    assert held == verdict.obligation
    assert complement == not_(verdict.obligation)
    assert caught_face.partition == missed_face.partition
    assert caught_face.side != missed_face.side


def _builtin_group(children):
    from sugar_lift_py_tests.effect import GroupedRaiseEffect
    from sugar_lift_py_tests.floor.ground_exit import _builtin_exception_identity

    identity, mro = _builtin_exception_identity("ExceptionGroup")
    return GroupedRaiseEffect(
        "group:root",
        "root",
        tuple(children),
        exception_type_coordinate=identity,
        exception_type_mro=mro,
    )


def test_group_split_asks_the_one_raise_matcher(monkeypatch):
    """``BaseExceptionGroup.split`` checks the group itself first, then each
    leaf, and asks each of the one matcher ``except`` asks
    (``matches_raise_effect``): never a type reader of its own."""
    from sugar_lift_py_tests import authenticated_exception_matching
    from sugar_lift_py_tests.floor.grouped_exception_value import (
        GroupedExceptionValue,
    )
    from sugar_lift_py_tests.floor.none_value import NoneValue

    base = _identity("truthful", "Base")
    leaf_identity = _identity("truthful", "Leaf")
    base_type = _typed_value(base)
    leaf = _leaf(leaf_identity, "leaf:truthful", leaf_identity, base)
    group = _builtin_group((leaf,))
    calls = []
    matcher = authenticated_exception_matching.matches_raise_effect

    def recording_matcher(effect, expected):
        calls.append((effect, expected))
        return matcher(effect, expected)

    monkeypatch.setattr(
        authenticated_exception_matching, "matches_raise_effect", recording_matcher
    )

    exits = GroupedExceptionValue(group, "site").split((base_type,), (), "site")

    assert calls == [(group, base_type), (leaf, base_type)]
    pair = exits.completed_value()
    matched, residual = pair.elements
    assert isinstance(matched, GroupedExceptionValue)
    assert matched.effect.children == (leaf,)
    assert isinstance(residual, NoneValue)


def test_group_split_of_an_undetermined_leaf_is_two_faces_never_a_refusal():
    """A leaf whose construction carried no class is retained by the one
    matcher, so ``split`` is the two-way split it owns: matched under the
    retained type test, residual under its complement -- each an arm of its
    own, never a refusal and never a guess."""
    from sugar_lift_py_tests.authenticated_exception_matching import (
        matches_raise_effect,
    )
    from sugar_lift_py_tests.effect.raise_effect import UndeterminedRaiseEffect
    from sugar_lift_py_tests.floor.grouped_exception_value import (
        GroupedExceptionValue,
    )
    from sugar_lift_py_tests.floor.none_value import NoneValue
    from sugar_lift_py_tests.ir import not_
    from sugar_lift_py_tests.outcome.exit_set import Completed

    other = _identity("truthful", "Other")
    undecided = UndeterminedRaiseEffect(blame="leaf:undecided", occurrence="leaf:u")
    decided = _leaf(other, "leaf:other")
    group = _builtin_group((undecided, decided))
    handler = _typed_value(_identity("truthful", "Base"))
    obligation = matches_raise_effect(undecided, handler).obligation

    exits = GroupedExceptionValue(group, "site").split((handler,), (), "site")

    assert all(isinstance(arm, Completed) for arm in exits.exits)
    assert len(exits.exits) == 2, exits.exits
    by_match = {type(arm.value.elements[0]): arm for arm in exits.exits}
    caught = by_match[GroupedExceptionValue]
    missed = by_match[NoneValue]
    caught_matched, caught_residual = caught.value.elements
    assert caught_matched.effect.children == (undecided,)
    assert caught_residual.effect.children == (decided,)
    assert missed.value.elements[1].effect.children == (undecided, decided)
    assert repr(obligation) in repr(caught.guard)
    assert repr(not_(obligation)) in repr(missed.guard)
    assert caught.faces and missed.faces and caught.faces != missed.faces
