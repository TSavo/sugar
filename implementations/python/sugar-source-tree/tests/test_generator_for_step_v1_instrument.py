"""Honest-red instrument for the general generator ``ForStepV1`` law.

The concrete reproducer is the source shape used by an option-pair generator:
apply every ``(pat, value)`` before the yield, then apply the saved ``undo``
pairs in ``finally``.  The names are evidence only; admission must remain
structural.  The renamed twin below must construct the same step vocabulary.

Green requires one producer-owned ``ForStepV1`` mechanism that carries the
iterable as ``ConstructedTermSugar``, authenticated target binding coordinates,
and ordered ``TermStepV1`` body calls.  Transition must use the existing
``iter_with`` / ``next_with`` floor doors, thread the advanced iterator and
per-iteration bindings, preserve body halts, recognize only authenticated
``StopIteration`` as exhaustion, and run paired ``finally`` cleanup on every
outgoing edge.  No spelling/vendor arm or consumer reconstruction can satisfy
these tests.
"""

from __future__ import annotations

from sugar_lift_py_tests import generator_construction as generator_api
from sugar_lift_py_tests.sugar.sugar_base import ConstructedTermSugar
from sugar_lift_python_source.canonical import blake3_512_of
from sugar_source_tree.nodes import FunctionDef
from sugar_source_tree.tree import SourceFile


_OPTION_PAIR_MANAGER = (
    "def option_pair_manager(ops, undo):\n"
    "    for pat, value in ops:\n"
    "        _set_option(pat, value)\n"
    "    try:\n"
    "        yield None\n"
    "    finally:\n"
    "        for pat, value in undo:\n"
    "            _set_option(pat, value)\n"
)

_RENAMED_TWIN = (
    "def renamed_pair_scope(pairs, restore_pairs):\n"
    "    for left, right in pairs:\n"
    "        apply_pair(left, right)\n"
    "    try:\n"
    "        yield None\n"
    "    finally:\n"
    "        for left, right in restore_pairs:\n"
    "            apply_pair(left, right)\n"
)


def _function(source: str) -> FunctionDef:
    tree = SourceFile(
        (source, "generator_for_step_v1.py", blake3_512_of(source.encode("utf-8")))
    )
    return next(node for node in tree.nodes() if isinstance(node, FunctionDef))


def _missing_for_step_message() -> str:
    return (
        "ForStepV1 is the missing general generator step: retain the constructed "
        "iterable and authenticated target binding coordinates; transition only "
        "through iter_with/next_with and authenticated StopIteration"
    )


def _for_step_type():
    step_type = getattr(generator_api, "ForStepV1", None)
    assert step_type is not None, _missing_for_step_message()
    return step_type


def _term_step_type():
    step_type = getattr(generator_api, "TermStepV1", None)
    assert step_type is not None, (
        "ForStepV1 body calls must be ordered TermStepV1 values; land the "
        "general term-step vocabulary before implementing this mechanism"
    )
    return step_type


def _steps(source: str):
    function = _function(source)
    return function._source_visible_generator_steps_from(function.body)


def _for_steps(source: str):
    for_step_type = _for_step_type()
    found = []

    def visit(step) -> None:
        if isinstance(step, for_step_type):
            found.append(step)
        # The cleanup loop remains paired with FinallyStepV1.  Permit the
        # finally owner to name its child-step field; do not require flattening
        # the cleanup into the ordinary fall-through sequence.
        for field_name in (
            "body_steps",
            "then_steps",
            "else_steps",
            "cleanup_steps",
            "statements",
        ):
            children = getattr(step, field_name, ())
            if isinstance(children, tuple):
                for child in children:
                    visit(child)

    for root in _steps(source):
        visit(root)
    return tuple(found)


def _target_coordinate_cids(step) -> tuple[str, ...]:
    coordinates = getattr(step, "target_coordinates", None)
    assert coordinates is not None, (
        "ForStepV1 must carry producer-authenticated target_coordinates; names "
        "or transition-time reconstruction are forbidden"
    )
    cids = tuple(getattr(coordinate, "cid", None) for coordinate in coordinates)
    assert cids and all(
        isinstance(cid, str) and cid.startswith("blake3-512:") for cid in cids
    ), "every ForStepV1 target coordinate must be producer-authenticated"
    assert len(cids) == len(set(cids)), "tuple target positions require distinct CIDs"
    return cids


def test_option_pair_loops_construct_two_general_for_steps() -> None:
    """Truthful face: pre-yield apply and paired cleanup are both ForStepV1."""
    _for_step_type()
    term_step_type = _term_step_type()

    for_steps = _for_steps(_OPTION_PAIR_MANAGER)

    assert len(for_steps) == 2, (
        "the pre-yield ops loop and finally undo loop must both remain explicit"
    )
    assert all(isinstance(step.iterable, ConstructedTermSugar) for step in for_steps)
    assert all(
        len(step.body_steps) == 1 and isinstance(step.body_steps[0], term_step_type)
        for step in for_steps
    ), "each iteration performs exactly one ordered TermStepV1 call"
    assert all(len(_target_coordinate_cids(step)) == 2 for step in for_steps)


def test_renamed_pair_manager_uses_the_same_general_step_vocabulary() -> None:
    """Lying-name twin: no function, iterable, target, or callee spelling arm."""
    for_step_type = _for_step_type()
    exact = _for_steps(_OPTION_PAIR_MANAGER)
    renamed = _for_steps(_RENAMED_TWIN)

    assert tuple(type(step) for step in exact) == (for_step_type, for_step_type)
    assert tuple(type(step) for step in renamed) == (for_step_type, for_step_type)
    assert tuple(len(_target_coordinate_cids(step)) for step in exact) == (2, 2)
    assert tuple(len(_target_coordinate_cids(step)) for step in renamed) == (2, 2)


def test_cleanup_iterable_and_target_coordinates_are_not_reconstructed() -> None:
    """Lying testimony twin: cleanup identity and both target sites stay distinct."""
    before, cleanup = _for_steps(_OPTION_PAIR_MANAGER)

    assert before.iterable != cleanup.iterable, (
        "ops and undo are distinct authenticated constructed iterables"
    )
    assert _target_coordinate_cids(before) != _target_coordinate_cids(cleanup), (
        "same target spellings at different loop sites must not share identity"
    )
    assert before.fragment_cid != cleanup.fragment_cid


def test_for_step_transition_contract_is_explicit_and_owner_complete() -> None:
    """The step itself names every state/exit obligation; consumers do not infer it."""
    for_step_type = _for_step_type()
    fields = getattr(for_step_type, "__dataclass_fields__", {})

    required = {
        "iterable",
        "target_coordinates",
        "body_steps",
        "fragment_cid",
    }
    assert required <= set(fields), (
        "ForStepV1 must own iterable, target coordinates, ordered body, and "
        "occurrence testimony so transition can thread iterator/binding state, "
        "preserve body halts, accept only authenticated StopIteration, and route "
        "fall-through/return/halt through paired finally cleanup"
    )
