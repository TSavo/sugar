"""A comprehension is a scoped recurrence over an iterable, reduced at lift.

Not bounded unrolling, and not a shortcut for any particular library's
spelling. Over a SYMBOLIC iterable the four collection forms run one
recurrence and differ only in the collection coordinate they head:

    for symbolic member x from iterable:
        bound     = unpack(target, x)
        condition = filter_1(bound) and ... and filter_n(bound)
        candidate = element(bound)

That is a RECURRENCE, so the construction never guesses an iteration count and
never fabricates normal completion. Evaluation order is iterable, then the
target's unpack, then the conditions, then the element -- each runs on the
face the one before it completed on, and each halt is an arm of the
comprehension at lift (#7757: a halt is never dropped).

What the comprehension accumulates is not interpreted at prove: the proof
states the comprehension's own coordinate, its kind over its occurrence and
evaluation (``ComprehensionSugar._own_coordinate``), and reading it owes the
undecided member (#8916).  None of the recurrence is stated inside that term.

The binding target is the capability under test. A generator target is the
SAME binding problem a statement loop's target solves, so a tuple/list target
binds each position to a projection of the symbolic member, recursively. A
member that does not destructure is a Python raise, never a skipped member:
the unpack's complement is a halted arm, distinct from a condition, which
excludes a member without raising.
"""

import os
import tempfile

from sugar_lift_python_source.source_oracle import path_source
from sugar_source_tree.tree import SourceFile
from sugar_lift_py_tests.ir import _Lambda, _Var, ctor as _ctor, make_var, num
from sugar_lift_py_tests.context_manager_resolution import TreeConstructionContextV1


def _outcome_of(source, path=None):
    """The function's outcome as its own proof states it."""
    if path is None:
        path = os.path.join(tempfile.mkdtemp(), "m.py")
    with open(path, "w") as handle:
        handle.write(source)
    function = list(
        SourceFile(
            path_source(path),
            construction_context=TreeConstructionContextV1.for_test_without_workspace(),
        ).functions()
    )[0]
    from sugar_lift_py_tests.tree_enumerate import as_its_own_proof_states

    # ``iter(xs)`` over a formal waits on the caller's actual: the function's
    # own proof discharges it with none (``as_its_own_proof_states``).
    return as_its_own_proof_states(function.sugar().desugar(None), None)


def _post_of(source, path=None):
    return _completed(_outcome_of(source, path)).post()


# The owner of the halt of a member that does not destructure into the
# target (``ComprehensionSugar._symbolic_member``, ``runtime_unpack_faces``).
_UNPACK = "ComprehensionSugar.target.unpack"

# The owners of the halts an undecided ``iter`` of the iterable states: over
# a formal with no actual (the function's own proof), over any other
# symbolic value (an inner generator's member).
_ITERATION_HALT_OWNERS = (
    "UnansweredNativeOperation:iter",
    "SymbolicValue.iter",
    # ``next`` of the iterator ``iter`` completed with, whose ``__next__``
    # is not decided here (``iterator_operation.stepped``).
    "SymbolicValue.next",
    _UNPACK,
)


def _completed(outcome):
    """The one completed face's value.

    A call whose callee nothing resolved (``g``, ``p``, ``h``) may raise: it
    halts with an ``UndeterminedRaiseEffect`` under the complement of its
    completion atom, beside the completion this file inspects.  So may
    ``iter`` of a symbolic iterable, which the fold runs before any member
    (``ComprehensionSugar._iterated``), and the unpack of a member into a
    destructuring target."""
    from sugar_lift_py_tests.effect.raise_effect import UndeterminedRaiseEffect
    from sugar_lift_py_tests.outcome import Completed, Halted

    exits = outcome.exits
    completed = [face for face in exits if isinstance(face, Completed)]
    halted = [face for face in exits if isinstance(face, Halted)]
    assert len(completed) == 1, exits
    assert all(
        isinstance(face.effect, UndeterminedRaiseEffect)
        and (
            face.effect.producer_node_owner.startswith("UnknownCallee:")
            or face.effect.producer_node_owner in _ITERATION_HALT_OWNERS
        )
        for face in halted
    ), halted
    return completed[0].value


def _halts(outcome, owner):
    """The halted arms whose raise ``owner`` produced."""
    from sugar_lift_py_tests.outcome import Halted

    return [
        face
        for face in outcome.exits
        if isinstance(face, Halted)
        and getattr(face.effect, "producer_node_owner", None) == owner
    ]


def _call_halts(outcome, callee):
    """The halts of the unanswered call of ``callee``: owner
    ``UnknownCallee:<target>``, the target the call's spelling where no
    workspace names a join symbol, as here."""
    found = []
    for face in _halts_of(outcome):
        owner = str(getattr(face.effect, "producer_node_owner", ""))
        prefix, _, target = owner.partition(":")
        if prefix == "UnknownCallee" and target.rsplit(".", 1)[-1] == callee:
            found.append(face)
    return found


def _halts_of(outcome):
    from sugar_lift_py_tests.outcome import Halted

    return [face for face in outcome.exits if isinstance(face, Halted)]


def _owners(outcome):
    from sugar_lift_py_tests.outcome import Halted

    return sorted(
        face.effect.producer_node_owner
        for face in outcome.exits
        if isinstance(face, Halted)
    )


def _children(term) -> tuple:
    """A term's or a formula's immediate subterms and subformulas."""
    children = (
        *(getattr(term, "args", ()) or ()),
        *(getattr(term, "operands", ()) or ()),
    )
    body = getattr(term, "body", None)
    return children if body is None else (*children, body)


def _terms_named(term, name, found=None):
    """Every constructor named ``name`` in a term or a formula."""
    found = [] if found is None else found
    if getattr(term, "name", None) == name and hasattr(term, "args"):
        found.append(term)
    for child in _children(term):
        _terms_named(child, name, found)
    return found


def _has_lambda(term) -> bool:
    if isinstance(term, _Lambda):
        return True
    return any(_has_lambda(child) for child in _children(term))


def _own(post):
    """The kind of the comprehension's own coordinate this post binds: its
    kind over its occurrence and this evaluation of it, and nothing else."""
    coordinate = post.args[1]
    occurrence, evaluation = coordinate.args
    assert occurrence.name == "python:source-occurrence", coordinate
    assert evaluation.name == "python:occurrence", coordinate
    return coordinate.name


def _call_args(outcome, callee):
    """The argument terms of the one call of ``callee`` the comprehension
    made, read off the completes atom its halt's guard negates."""
    (halt,) = _call_halts(outcome, callee)
    calls = _terms_named(halt.guard, f"call:{callee}")
    assert calls, halt.guard
    assert all(call.args == calls[0].args for call in calls), calls
    return calls[0].args


def _unpacked_member(outcome, arity):
    """The member the comprehension's one unpack destructured, checked to
    demand exactly ``arity`` positions."""
    (halt,) = _halts(outcome, _UNPACK)
    (destructure,) = _terms_named(halt.guard, "python:unpack.destructure")
    member, demanded = destructure.args
    assert demanded == num(arity), destructure
    return member


def _project(element, index, arity):
    return _ctor(
        "python:unpack.project",
        [element, num(index), num(arity)],
        symbol_kind="coordinate",
    )


def _names(term, found=None):
    """Every constructor name appearing in a term."""
    found = [] if found is None else found
    name = getattr(term, "name", None)
    if name is not None:
        found.append(name)
    for arg in getattr(term, "args", ()) or ():
        _names(arg, found)
    body = getattr(term, "body", None)
    if body is not None:
        _names(body, found)
    return found


# -- concrete iterable: the fold dissolves to the exact concrete result -------


def test_concrete_iterable_reproduces_the_exact_concrete_result():
    # A concrete iterable is not a recurrence at all: it is a finite number of
    # substitutions, and the answer must be the ACTUAL elements -- here the
    # first coordinate of each pair, in source order.
    post = _post_of("def f():\n    return [a for a, b in [(1, 2), (3, 4)]]\n")
    assert post.args[1] == _ctor("array", [num(1), num(3)]), f"post was {post!r}"


def test_concrete_iterable_with_a_true_filter_includes_every_element():
    post = _post_of("def f():\n    return [a for a, b in [(1, 2), (3, 4)] if True]\n")
    assert post.args[1] == _ctor("array", [num(1), num(3)]), f"post was {post!r}"


def test_concrete_iterable_with_a_false_filter_excludes_every_element():
    # The discrimination against the true-filter twin above: same source, one
    # guard flipped, and the result must be the EMPTY display -- not the
    # unfiltered elements and not a retained guard.
    post = _post_of("def f():\n    return [a for a, b in [(1, 2), (3, 4)] if False]\n")
    assert post.args[1] == _ctor("array", []), f"post was {post!r}"


def test_concrete_iterable_filter_selects_exactly_the_passing_elements():
    post = _post_of("def f():\n    return [a for a, b in [(1, 2), (3, 4)] if b > 2]\n")
    assert post.args[1] == _ctor("array", [num(3)]), f"post was {post!r}"


# -- symbolic iterable: recurrence, never a guessed bound --------------------


def test_a_symbolic_comprehension_states_its_own_coordinate_not_its_fold():
    # The iterable is a parameter, so no member and no count is known. The
    # proof states the comprehension's own coordinate -- its kind over its
    # occurrence -- and nothing it accumulates: prove interprets no fold, so
    # reading it owes the undecided member (#8916), and a member binder (a
    # lambda) is nothing the term table carries.
    outcome = _outcome_of("def f(xs):\n    return [g(x) for x in xs]\n")
    post = _completed(outcome).post()
    assert _own(post) == "py.listcomp"
    assert not _has_lambda(post), post
    assert make_var("xs") not in post.args[1].args, post
    assert outcome.owed_items(), outcome


def test_symbolic_iterable_never_fabricates_a_finite_element_count():
    # The discrimination against unrolling: nothing anywhere in a symbolic
    # comprehension's term may be a concrete collection display.
    post = _post_of("def f(xs):\n    return [g(x) for x in xs]\n")
    assert "array" not in _names(post), f"post was {post!r}"


def test_a_symbolic_condition_is_reduced_at_lift_rather_than_decided():
    # `p(x)` is not decidable at lift time: its call stands two-faced, its
    # halt kept, and the element runs on the face it completes on -- over the
    # same member the condition read.
    outcome = _outcome_of("def f(xs):\n    return [g(x) for x in xs if p(x)]\n")
    (p_halt,) = _call_halts(outcome, "p")
    (g_halt,) = _call_halts(outcome, "g")
    assert _terms_named(g_halt.guard, "call:p"), g_halt.guard
    assert not _terms_named(p_halt.guard, "call:g"), p_halt.guard
    (member,) = _call_args(outcome, "p")
    assert _call_args(outcome, "g") == (member,)
    assert _own(_completed(outcome).post()) == "py.listcomp"


def test_symbolic_conditions_run_in_source_order():
    # The second condition runs only where the first completed -- the
    # conjunction Python actually performs, short-circuit and all.
    outcome = _outcome_of("def f(xs):\n    return [x for x in xs if p(x) if q(x)]\n")
    (p_halt,) = _call_halts(outcome, "p")
    (q_halt,) = _call_halts(outcome, "q")
    assert _terms_named(q_halt.guard, "call:p"), q_halt.guard
    assert not _terms_named(p_halt.guard, "call:q"), p_halt.guard


# -- lexical scope -----------------------------------------------------------


def test_nested_generators_preserve_ordering_and_binding_dependency():
    # The second generator's iterable is the FIRST generator's member: a
    # symbolic value that is no formal, so its ``iter`` is the undecided read
    # of that member (``SymbolicValue.iter``), never the formal's.  The
    # element reads both members, each its own coordinate.
    outcome = _outcome_of("def f(xs):\n    return [g(x, y) for x in xs for y in x]\n")
    assert _halts(outcome, "SymbolicValue.iter"), _owners(outcome)
    x, y = _call_args(outcome, "g")
    assert isinstance(x, _Var) and isinstance(y, _Var), (x, y)
    assert x != y, "each generator binds its own coordinate"
    assert make_var("xs") not in (x, y)


def test_target_variable_does_not_leak_out_of_the_comprehension():
    # `x` after the comprehension is the PARAMETER x, never the comprehension's
    # per-element coordinate. If the target leaked, the returned term would
    # mention the recurrence coordinate.
    post = _post_of("def f(x, xs):\n    ys = [g(x) for x in xs]\n    return h(x)\n")
    result = post.args[1]
    assert result.name == "python:call_result", f"post was {post!r}"
    assert result.args[0] == _ctor("call:h", [make_var("x")]), f"post was {post!r}"


def test_shadowed_outer_variable_remains_unchanged():
    # The discrimination against over-substitution: inside the comprehension,
    # `x` is the member; outside it, the same name is still the outer
    # binding. Both faces are asserted in ONE program.
    source = "def f(x, xs):\n    return h(x, [g(x) for x in xs])\n"
    outcome = _outcome_of(source)
    result = _completed(outcome).post().args[1]
    assert result.name == "python:call_result"
    call = result.args[0]
    assert call.name == "call:h"
    assert call.args[0] == make_var("x"), "outer x survives unshadowed"
    assert call.args[1].name == "py.listcomp", call.args[1]
    (inner,) = _call_args(outcome, "g")
    assert inner != make_var("x"), "inner x is the member"


# -- destructuring targets ---------------------------------------------------


def test_tuple_destructuring_binds_every_leaf_to_its_projection():
    # Each position binds its OWN projection of the symbolic member, in
    # order, carrying the arity the source demanded.
    outcome = _outcome_of("def f(xs):\n    return [g(a, b) for a, b in xs]\n")
    member = _unpacked_member(outcome, 2)
    assert _call_args(outcome, "g") == (
        _project(member, 0, 2),
        _project(member, 1, 2),
    )


def test_destructuring_positions_are_not_interchangeable():
    # The discrimination against a positionally-blind binding: swapping the
    # target names must swap the projections the element reads.
    straight = _outcome_of("def f(xs):\n    return [g(a, b) for a, b in xs]\n")
    swapped = _outcome_of("def f(xs):\n    return [g(b, a) for a, b in xs]\n")
    member = _unpacked_member(straight, 2)
    assert _call_args(straight, "g") == (
        _project(member, 0, 2),
        _project(member, 1, 2),
    )
    member = _unpacked_member(swapped, 2)
    assert _call_args(swapped, "g") == (
        _project(member, 1, 2),
        _project(member, 0, 2),
    )


def test_list_shaped_target_destructures_like_a_tuple_target():
    # `for [a, b] in xs` is the same binding as `for a, b in xs`. The two sit
    # at different binding SITES, so their coordinates differ by design; what
    # must match is the unpack and the projections built over each.
    for source in (
        "def f(xs):\n    return [g(a, b) for [a, b] in xs]\n",
        "def f(xs):\n    return [g(a, b) for a, b in xs]\n",
    ):
        outcome = _outcome_of(source)
        member = _unpacked_member(outcome, 2)
        assert _call_args(outcome, "g") == (
            _project(member, 0, 2),
            _project(member, 1, 2),
        ), source


def test_nested_destructuring_unpacks_a_projection_after_its_outer_unpack():
    # `for a, (b, c) in xs`: the outer unpack runs first, because the member
    # must unpack before position 1 exists to unpack again.  Each unpack is
    # its own halt; the inner one runs only where the outer one completed.
    outcome = _outcome_of("def f(xs):\n    return [g(a, b, c) for a, (b, c) in xs]\n")
    halts = _halts(outcome, _UNPACK)
    assert len(halts) == 2, _owners(outcome)
    outer, inner = sorted(
        halts,
        key=lambda halt: len(_terms_named(halt.guard, "python:unpack.destructure")),
    )
    (outer_destructure,) = _terms_named(outer.guard, "python:unpack.destructure")
    member, arity = outer_destructure.args
    assert arity == num(2)
    position = _project(member, 1, 2)
    inner_destructure = _ctor(
        "python:unpack.destructure", [position, num(2)], symbol_kind="coordinate"
    )
    assert set(_terms_named(inner.guard, "python:unpack.destructure")) == {
        outer_destructure,
        inner_destructure,
    }
    assert _call_args(outcome, "g") == (
        _project(member, 0, 2),
        _project(position, 0, 2),
        _project(position, 1, 2),
    )


def test_destructuring_arity_is_carried_not_assumed():
    # A three-wide target demands arity 3, not the two-wide shape.
    outcome = _outcome_of("def f(xs):\n    return [g(a, b, c) for a, b, c in xs]\n")
    member = _unpacked_member(outcome, 3)
    assert _call_args(outcome, "g") == tuple(
        _project(member, index, 3) for index in range(3)
    )


def test_a_failing_destructure_is_a_halt_of_the_comprehension_never_a_skip():
    # A member of the wrong length makes Python RAISE.  The unpack's
    # complement is a halted arm of the comprehension at lift -- the one
    # undetermined raise, which owes -- never a member silently skipped, and
    # never only a coordinate inside a stated term, where nothing reads it.
    from sugar_lift_py_tests.effect.raise_effect import UndeterminedRaiseEffect

    outcome = _outcome_of("def f(xs):\n    return [g(a, b) for a, b in xs]\n")
    (halt,) = _halts(outcome, _UNPACK)
    assert type(halt.effect) is UndeterminedRaiseEffect
    assert halt.owed, halt
    post = _completed(outcome).post()
    assert not _terms_named(post, "python:unpack.destructure"), post


def test_the_unpack_precedes_every_condition():
    # Evaluation order: bind the target, THEN run the conditions.  A
    # condition reads a projection, so it runs only where the unpack
    # completed; the unpack's halt is a raise, a condition's exclusion is not.
    outcome = _outcome_of("def f(xs):\n    return [a for a, b in xs if p(b)]\n")
    (unpack,) = _halts(outcome, _UNPACK)
    (p_halt,) = _call_halts(outcome, "p")
    assert _terms_named(p_halt.guard, "python:unpack.destructure"), p_halt.guard
    assert not _terms_named(unpack.guard, "call:p"), unpack.guard
    member = _unpacked_member(outcome, 2)
    assert _call_args(outcome, "p") == (_project(member, 1, 2),)


def test_a_starred_target_remains_loud():
    # `for a, *b in xs` binds a variable-arity remainder, which this
    # recurrence does not model. It must stay SugarNotWritten -- a legitimate
    # gap kept red, not a guessed arity.
    from sugar_source_tree.panic import SugarNotWritten

    try:
        _post_of("def f(xs):\n    return [a for a, *b in xs]\n")
    except SugarNotWritten:
        return
    raise AssertionError("a starred comprehension target must stay loud")


def test_an_attribute_target_remains_loud():
    from sugar_source_tree.panic import SugarNotWritten

    try:
        _post_of("def f(xs, o):\n    return [o.a for o.a, b in xs]\n")
    except SugarNotWritten:
        return
    raise AssertionError("an attribute comprehension target must stay loud")


# -- effects and unknown members ---------------------------------------------


def test_an_unresolved_element_call_stays_its_call_not_omitted():
    # `g(x)` has no body here. Its member value is unknown, and the honest
    # construction keeps the call -- two-faced, owed -- never drops the
    # element and never invents a value for it.
    outcome = _outcome_of("def f(xs):\n    return [g(x) for x in xs]\n")
    assert _call_halts(outcome, "g"), _owners(outcome)
    assert outcome.owed_items(), outcome


def test_a_raising_element_body_propagates_rather_than_completing_quietly():
    # A comprehension whose body raises does not produce a list. Construction
    # must not hand back a plain collection coordinate as if it completed.
    from sugar_source_tree.panic import SugarNotWritten

    source = "def f(xs):\n    return [raise_it(x) for x in xs]\n"
    try:
        post = _post_of(source)
    except SugarNotWritten:
        return
    assert "array" not in _names(post), f"post was {post!r}"


def test_a_raising_filter_propagates_rather_than_deciding_membership():
    from sugar_source_tree.panic import SugarNotWritten

    source = "def f(xs):\n    return [x for x in xs if raise_it(x)]\n"
    try:
        outcome = _outcome_of(source)
    except SugarNotWritten:
        return
    assert _call_halts(
        outcome, "raise_it"
    ), "an undecided condition keeps its halt rather than choosing a side"


# -- the four collection semantics -------------------------------------------


def test_the_four_collection_forms_head_distinct_coordinates():
    # One mechanism, four collection semantics. If any two shared a
    # coordinate their results could alias, and set/dict/generator semantics
    # would be indistinguishable from a list's.
    listcomp = _post_of("def f(xs):\n    return [g(a, b) for a, b in xs]\n")
    setcomp = _post_of("def f(xs):\n    return {g(a, b) for a, b in xs}\n")
    genexp = _post_of("def f(xs):\n    return (g(a, b) for a, b in xs)\n")
    dictcomp = _post_of("def f(xs):\n    return {a: b for a, b in xs}\n")
    kinds = [_own(p) for p in (listcomp, setcomp, genexp, dictcomp)]
    assert kinds == [
        "py.listcomp",
        "py.setcomp",
        "py.generatorexp",
        "py.dictcomp",
    ], kinds
    assert len(set(kinds)) == 4


def test_list_set_and_generator_results_cannot_alias_one_another():
    # Same source text, same binding, same element -- only the brackets
    # differ. The constructed terms must still differ.
    listcomp = _post_of("def f(xs):\n    return [g(a, b) for a, b in xs]\n")
    setcomp = _post_of("def f(xs):\n    return {g(a, b) for a, b in xs}\n")
    genexp = _post_of("def f(xs):\n    return (g(a, b) for a, b in xs)\n")
    terms = [p.args[1] for p in (listcomp, setcomp, genexp)]
    assert len(set(terms)) == 3, terms


def test_a_generator_expression_stays_lazy_rather_than_becoming_a_list():
    # The discrimination against eager fabrication: a genexp over a symbolic
    # iterable is a generator coordinate, never a list display or listcomp.
    # Its pull -- the unpack, the element -- runs where it is pulled, so none
    # of its halts is this expression's.
    source = "def f(xs):\n    return (g(a, b) for a, b in xs)\n"
    post = _post_of(source)
    names = _names(post)
    assert "py.generatorexp" in names
    assert "py.listcomp" not in names and "array" not in names, names
    outcome = _outcome_of(source)
    assert not _halts(outcome, _UNPACK), _owners(outcome)
    assert not _call_halts(outcome, "g"), _owners(outcome)


def test_a_dict_comprehension_reads_key_and_value_off_one_member():
    # The key and value are projections of the SAME member, the key read
    # first -- the association Python builds, not two independent sequences.
    outcome = _outcome_of("def f(xs):\n    return {g(a): h(b) for a, b in xs}\n")
    assert _own(_completed(outcome).post()) == "py.dictcomp"
    member = _unpacked_member(outcome, 2)
    assert _call_args(outcome, "g") == (_project(member, 0, 2),)
    assert _call_args(outcome, "h") == (_project(member, 1, 2),)
    (h_halt,) = _call_halts(outcome, "h")
    assert _terms_named(h_halt.guard, "call:g"), h_halt.guard


def test_a_concrete_dict_comprehension_keeps_last_write_overwrite_behaviour():
    # A repeated key keeps the LAST value and the FIRST position -- Python's
    # actual dict overwrite semantics, not a duplicated entry.
    post = _post_of(
        "def f():\n    return {a: b for a, b in [(1, 2), (3, 4), (1, 5)]}\n"
    )
    entries = post.args[1]
    assert entries.name == "python:dict", f"post was {post!r}"
    assert [(entry.args[0].value, entry.args[1].value) for entry in entries.args] == [
        (1, 5),
        (3, 4),
    ], f"post was {post!r}"


def test_a_set_comprehension_uses_set_membership_over_a_concrete_iterable():
    # Duplicates collapse: three elements, two distinct members.
    post = _post_of("def f():\n    return {a for a, b in [(1, 2), (1, 3), (4, 5)]}\n")
    members = post.args[1]
    assert members.name == "python:set", f"post was {post!r}"
    assert [member.value for member in members.args] == [1, 4], f"post was {post!r}"


# -- determinism -------------------------------------------------------------


def test_repeated_construction_is_byte_identical():
    # Same file, constructed twice: identical terms. A coordinate that drifted
    # between runs would make every downstream CID unstable.
    path = os.path.join(tempfile.mkdtemp(), "m.py")
    source = "def f(xs):\n    return [g(a, b) for a, b in xs if p(b)]\n"
    first = _post_of(source, path)
    second = _post_of(source, path)
    assert repr(first) == repr(second)
    assert first == second


def test_every_collection_form_is_byte_identical_across_repeats():
    for source in (
        "def f(xs):\n    return [g(a, b) for a, b in xs]\n",
        "def f(xs):\n    return {g(a, b) for a, b in xs}\n",
        "def f(xs):\n    return (g(a, b) for a, b in xs)\n",
        "def f(xs):\n    return {a: b for a, b in xs}\n",
    ):
        path = os.path.join(tempfile.mkdtemp(), "m.py")
        assert _post_of(source, path) == _post_of(source, path), source


def test_a_name_target_carries_no_unpack():
    # The 'nothing else moved' twin: a destructuring target's unpack must not
    # reach the simple-name path.
    outcome = _outcome_of("def f(xs):\n    return [g(x) for x in xs if p(x)]\n")
    assert not _halts(outcome, _UNPACK), _owners(outcome)
    for face in outcome.exits:
        assert not _terms_named(face.guard, "python:unpack.destructure"), face
        assert not _terms_named(face.guard, "python:unpack.project"), face
    assert _call_halts(outcome, "p"), _owners(outcome)


# -- a nested comprehension is just another sugar in that position -----------
#
# A comprehension appearing in another comprehension's element (or in a dict
# comprehension's key or value) is NOT a shape the recurrence must refuse: it
# is one more sugar the element position lifts, iterating the ENCLOSING
# member.  Every collection form shares that one reader, so none of the four
# may refuse what the others accept. The only obstruction is a walrus, which
# binds into the enclosing scope -- a binding the scoped recurrence does not
# model.


def test_a_comprehension_nested_in_a_dict_comprehension_value_is_constructed():
    # The outer dictcomp runs over `xs`; each entry's value is an INNER
    # listcomp over the outer MEMBER.  The DISCRIMINATION that makes this test
    # worth running: the inner comprehension iterates a symbolic value that
    # is no formal (``SymbolicValue.iter``), never the formal `xs` -- a lying
    # construction that iterated `xs` again would state only the formal's.
    outcome = _outcome_of(
        "def f(xs, g):\n    return {x: [g(y) for y in x] for x in xs}\n"
    )
    assert _own(_completed(outcome).post()) == "py.dictcomp"
    assert _halts(outcome, "SymbolicValue.iter"), _owners(outcome)


def test_a_comprehension_nested_in_a_dict_comprehension_key_is_constructed():
    # The key position is the value position's twin: same obligation, same
    # member, so a construction that served one and refused the other would
    # be reading the dict's punctuation rather than its meaning.
    outcome = _outcome_of(
        "def f(xs, g):\n    return {tuple([g(y) for y in x]): x for x in xs}\n"
    )
    assert _own(_completed(outcome).post()) == "py.dictcomp"
    assert _halts(outcome, "SymbolicValue.iter"), _owners(outcome)


def test_a_comprehension_nested_in_a_set_comprehension_element_is_constructed():
    outcome = _outcome_of(
        "def f(xs, g):\n    return {tuple([g(y) for y in x]) for x in xs}\n"
    )
    assert _own(_completed(outcome).post()) == "py.setcomp"
    assert _halts(outcome, "SymbolicValue.iter"), _owners(outcome)


def test_every_collection_form_accepts_a_nested_comprehension():
    # The unification itself under test. Four forms, one nested comprehension
    # in the element position; a form that refused would be reading its own
    # spelling rather than the shared obligation.
    for source, kind in (
        ("def f(xs, g):\n    return [[g(y) for y in x] for x in xs]\n", "py.listcomp"),
        (
            "def f(xs, g):\n    return ([g(y) for y in x] for x in xs)\n",
            "py.generatorexp",
        ),
        (
            "def f(xs, g):\n    return {tuple([g(y) for y in x]) for x in xs}\n",
            "py.setcomp",
        ),
        (
            "def f(xs, g):\n    return {x: [g(y) for y in x] for x in xs}\n",
            "py.dictcomp",
        ),
    ):
        post = _post_of(source)
        assert _own(post) == kind, f"{source} constructed {post!r}"
        assert not _has_lambda(post), post


def test_a_comprehension_substituted_into_a_dict_value_is_constructed():
    # The source text holds NO nested comprehension -- substitution puts one
    # there by threading a local bound to a fold. The obstruction was read off
    # the node as it stands at construction time, so this refused while its
    # own source text looked innocent. It must construct like any other.
    outcome = _outcome_of(
        "def f(xs, g):\n"
        "    ys = [g(x) for x in xs]\n"
        "    return {k: ys for k in xs}\n"
    )
    assert _own(_completed(outcome).post()) == "py.dictcomp"
    # `ys` does not depend on the outer member, so whatever it iterates is
    # the formal `xs` -- the discrimination against the twins above, where
    # the inner comprehension iterated the member.  Same shape, different
    # scope.
    assert not _halts(outcome, "SymbolicValue.iter"), _owners(outcome)


def test_a_walrus_in_a_comprehension_element_over_an_undecided_iterator_is_refused_by_name():
    # A walrus binds into the enclosing scope on every member that reaches
    # it.  Over a formal, the comprehension runs ``iter`` and then ``next``
    # per member through the one iterator path (#8832, #8844): ``iter``'s
    # halt and each ``next``'s halt are kept.  A ``next`` that halts on a
    # later member halts after an earlier member's walrus bound ``n``, and
    # the symbolic fold holds no record of that write; the statement's
    # prefix (where the deferred ``iter`` carrier leaves from) would drop it.
    # So the statement is refused by name at the block reducer, never handed
    # a record that drops the bind and never let through with the halt
    # dropped (#7757 step 6, a halt and its record are never dropped).  The
    # fold of the presented value it built before #8832 stated no halt of
    # ``iter`` or ``next`` at all.
    from sugar_source_tree.panic import SugarNotWritten

    for source in (
        "def f(xs, g):\n    return [(n := g(x)) for x in xs]\n",
        "def f(xs, g):\n    return {(n := g(x)) for x in xs}\n",
        "def f(xs, g):\n    return ((n := g(x)) for x in xs)\n",
        "def f(xs, g):\n    return {x: (n := g(x)) for x in xs}\n",
    ):
        try:
            _post_of(source)
        except SugarNotWritten as refused:
            assert "reduce_block_to_exitset.statement" in str(refused), refused
            assert "walrus" in str(refused), refused
            continue
        raise AssertionError(f"{source} must be refused by name, not folded")
