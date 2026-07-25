"""A comprehension is a scoped guarded fold over an iterable.

Not bounded unrolling, and not a shortcut for any particular library's
spelling. Over a SYMBOLIC iterable the four collection forms construct one
recurrence and differ only in the collection coordinate they head:

    state0 = empty
    for symbolic element x from iterable:
        bound     = bind(target, x)
        condition = filter_1(bound) and ... and filter_n(bound)
        candidate = element(bound)
        state_next = condition ? append(state, candidate) : state

That is a RECURRENCE, so the construction never guesses an iteration count and
never fabricates normal completion. Evaluation order is iterable, then target
binding, then filters, then element -- which is why the destructuring
obligation wraps the filter guards, and the filter guards wrap the element.

The binding target is the capability under test. A generator target is the
SAME binding problem a statement loop's target solves, so a tuple/list target
binds each position to a projection of the symbolic element, recursively. A
destructure that cannot succeed is a Python raise, never a skipped element:
its exit is the halt coordinate, distinct from the filter latch that a
false guard uses.
"""

import os
import tempfile

from sugar_lift_python_source.source_oracle import path_source
from sugar_source_tree.tree import SourceFile
from sugar_lift_py_tests.ir import ctor as _ctor, make_var, num


def _post_of(source, path=None):
    if path is None:
        path = os.path.join(tempfile.mkdtemp(), "m.py")
    with open(path, "w") as handle:
        handle.write(source)
    function = list(SourceFile(path_source(path)).functions())[0]
    return function.sugar().desugar(None).value.post()


def _fold(post):
    """The collection coordinate this post binds, as (kind, iterable, lambda)."""
    coordinate = post.args[1]
    return coordinate.name, coordinate.args[0], coordinate.args[1]


def _coordinate(term):
    """The recurrence coordinate a fold's lambda binds per element."""
    return make_var(term.param_name)


def _project(element, index, arity):
    return _ctor(
        "python:unpack.project",
        [element, num(index), num(arity)],
        symbol_kind="coordinate",
    )


def _halt():
    return _ctor("python:unpack.halt", [], symbol_kind="coordinate")


def _destructure(element, arity, body):
    return _ctor(
        "python:unpack.destructure",
        [element, num(arity), body, _halt()],
        symbol_kind="coordinate",
    )


def _filtered(guard, body):
    return _ctor(
        "python:loop.filter_guard",
        [guard, body, _ctor("python:loop.latch", [], symbol_kind="coordinate")],
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


def test_symbolic_iterable_constructs_a_recurrence_not_an_unrolling():
    # The iterable is a parameter, so no element is known and no count is
    # known. The construction heads the collection coordinate over the
    # SYMBOLIC iterable with a per-element lambda and an explicit exhaustion
    # face -- never a display of invented elements.
    post = _post_of("def f(xs):\n    return [g(x) for x in xs]\n")
    kind, iterable, body = _fold(post)
    assert kind == "py.listcomp"
    assert iterable == make_var("xs")
    element = _coordinate(body)
    assert body.body == _ctor("call:g", [element]), f"body was {body.body!r}"
    assert post.args[1].args[2] == _ctor(
        "python:loop.exhaustion", [], symbol_kind="coordinate"
    )


def test_symbolic_iterable_never_fabricates_a_finite_element_count():
    # The discrimination against unrolling: nothing anywhere in a symbolic
    # comprehension's term may be a concrete collection display.
    post = _post_of("def f(xs):\n    return [g(x) for x in xs]\n")
    assert "array" not in _names(post), f"post was {post!r}"


def test_symbolic_filter_retains_a_guard_rather_than_deciding_it():
    # `p(x)` is not decidable at lift time, so membership stays CONDITIONAL:
    # the element sits under a filter guard with its latch, and the guard's
    # formula is the real predicate over the bound coordinate.
    post = _post_of("def f(xs):\n    return [g(x) for x in xs if p(x)]\n")
    _kind, _iterable, body = _fold(post)
    element = _coordinate(body)
    assert body.body == _filtered(
        _ctor("call:p", [element]), _ctor("call:g", [element])
    ), f"body was {body.body!r}"


def test_symbolic_filters_conjoin_in_source_order():
    # Two guards nest outermost-first, so the first filter is evaluated first
    # -- the conjunction Python actually performs, short-circuit and all.
    post = _post_of("def f(xs):\n    return [x for x in xs if p(x) if q(x)]\n")
    _kind, _iterable, body = _fold(post)
    element = _coordinate(body)
    assert body.body == _filtered(
        _ctor("call:p", [element]),
        _filtered(_ctor("call:q", [element]), element),
    ), f"body was {body.body!r}"


# -- lexical scope -----------------------------------------------------------


def test_nested_generators_preserve_ordering_and_binding_dependency():
    # The second generator's iterable is the FIRST generator's binding, so the
    # outer fold must wrap the inner one and the inner iterable must read the
    # outer coordinate. An inner-first nesting would be a different program.
    post = _post_of("def f(xs):\n    return [g(x, y) for x in xs for y in x]\n")
    _kind, iterable, outer = _fold(post)
    assert iterable == make_var("xs")
    x = _coordinate(outer)
    inner_fold = outer.body
    assert inner_fold.name == "python:loop.flat_map", f"outer body {inner_fold!r}"
    assert inner_fold.args[0] == x, "inner iterable must be the outer binding"
    y = _coordinate(inner_fold.args[1])
    assert inner_fold.args[1].body == _ctor("call:g", [x, y])
    assert x != y, "each generator binds its own coordinate"


def test_target_variable_does_not_leak_out_of_the_comprehension():
    # `x` after the comprehension is the PARAMETER x, never the comprehension's
    # per-element coordinate. If the target leaked, the returned term would
    # mention the recurrence coordinate.
    post = _post_of("def f(x, xs):\n    ys = [g(x) for x in xs]\n    return h(x)\n")
    assert post.args[1] == _ctor("call:h", [make_var("x")]), f"post was {post!r}"


def test_shadowed_outer_variable_remains_unchanged():
    # The discrimination against over-substitution: inside the comprehension,
    # `x` is the element coordinate; outside it, the same name is still the
    # outer binding. Both faces are asserted in ONE program.
    source = "def f(x, xs):\n    return h(x, [g(x) for x in xs])\n"
    post = _post_of(source)
    call = post.args[1]
    assert call.name == "call:h"
    assert call.args[0] == make_var("x"), "outer x survives unshadowed"
    _kind, _iterable, body = _fold_of_term(call.args[1])
    element = _coordinate(body)
    assert body.body == _ctor("call:g", [element]), "inner x is the coordinate"
    assert element != make_var("x")


def _fold_of_term(coordinate):
    return coordinate.name, coordinate.args[0], coordinate.args[1]


# -- destructuring targets ---------------------------------------------------


def test_tuple_destructuring_binds_every_coordinate_correctly():
    # Each position binds its OWN projection of the symbolic element, in
    # order, carrying the arity the source demanded.
    post = _post_of("def f(xs):\n    return [g(a, b) for a, b in xs]\n")
    _kind, _iterable, body = _fold(post)
    element = _coordinate(body)
    assert body.body == _destructure(
        element,
        2,
        _ctor("call:g", [_project(element, 0, 2), _project(element, 1, 2)]),
    ), f"body was {body.body!r}"


def test_destructuring_positions_are_not_interchangeable():
    # The discrimination against a positionally-blind binding: swapping the
    # target names must change the constructed term.
    straight = _post_of("def f(xs):\n    return [g(a, b) for a, b in xs]\n")
    swapped = _post_of("def f(xs):\n    return [g(b, a) for a, b in xs]\n")
    assert _fold(straight)[2].body != _fold(swapped)[2].body


def test_list_shaped_target_destructures_like_a_tuple_target():
    # `for [a, b] in xs` is the same binding as `for a, b in xs`. The two sit
    # at different binding SITES, so their coordinates differ by design; what
    # must match is the projection structure built over each.
    def structure(source):
        _kind, _iterable, body = _fold(_post_of(source))
        element = _coordinate(body)
        return _destructure(
            element,
            2,
            _ctor("call:g", [_project(element, 0, 2), _project(element, 1, 2)]),
        ) == body.body

    assert structure("def f(xs):\n    return [g(a, b) for [a, b] in xs]\n")
    assert structure("def f(xs):\n    return [g(a, b) for a, b in xs]\n")


def test_nested_destructuring_projects_a_projection():
    # `for a, (b, c) in xs`: the outer obligation wraps the inner one, because
    # the outer element must unpack before position 1 exists to unpack again.
    post = _post_of("def f(xs):\n    return [g(a, b, c) for a, (b, c) in xs]\n")
    _kind, _iterable, body = _fold(post)
    element = _coordinate(body)
    inner = _project(element, 1, 2)
    assert body.body == _destructure(
        element,
        2,
        _destructure(
            inner,
            2,
            _ctor(
                "call:g",
                [_project(element, 0, 2), _project(inner, 0, 2), _project(inner, 1, 2)],
            ),
        ),
    ), f"body was {body.body!r}"


def test_destructuring_arity_is_carried_not_assumed():
    # A three-wide target carries arity 3, not the two-wide shape.
    post = _post_of("def f(xs):\n    return [g(a, b, c) for a, b, c in xs]\n")
    _kind, _iterable, body = _fold(post)
    element = _coordinate(body)
    assert body.body == _destructure(
        element,
        3,
        _ctor(
            "call:g",
            [_project(element, 0, 3), _project(element, 1, 3), _project(element, 2, 3)],
        ),
    ), f"body was {body.body!r}"


def test_a_failing_destructure_stays_halted_never_silently_skipped():
    # A wrong-arity element makes Python RAISE. So the destructuring
    # obligation's exit is the halt coordinate -- and it must NOT be the
    # filter latch, which is the exit for an element a guard excludes.
    post = _post_of("def f(xs):\n    return [g(a, b) for a, b in xs]\n")
    _kind, _iterable, body = _fold(post)
    obligation = body.body
    assert obligation.name == "python:unpack.destructure"
    assert obligation.args[3] == _halt(), f"exit was {obligation.args[3]!r}"
    assert "python:loop.latch" not in _names(obligation.args[3])


def test_destructure_halt_and_filter_latch_are_distinct_exits():
    # Both faces in one program: the destructure exit is a halt, the filter
    # exit is a latch. Collapsing them would turn a raise into a skip.
    post = _post_of("def f(xs):\n    return [a for a, b in xs if p(b)]\n")
    _kind, _iterable, body = _fold(post)
    element = _coordinate(body)
    assert body.body == _destructure(
        element,
        2,
        _filtered(
            _ctor("call:p", [_project(element, 1, 2)]), _project(element, 0, 2)
        ),
    ), f"body was {body.body!r}"


def test_destructuring_obligation_precedes_the_filter_guard():
    # Evaluation order: bind the target, THEN run filters. A filter reads a
    # projection, so the projection cannot be legal before the unpack is.
    post = _post_of("def f(xs):\n    return [a for a, b in xs if p(b)]\n")
    _kind, _iterable, body = _fold(post)
    assert body.body.name == "python:unpack.destructure"
    assert body.body.args[2].name == "python:loop.filter_guard"


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


def test_an_unresolved_element_call_stays_a_symbolic_coordinate_not_omitted():
    # `g(x)` has no body here. Its member value is unknown, and the honest
    # construction keeps the call coordinate -- never drops the element and
    # never invents a value for it.
    post = _post_of("def f(xs):\n    return [g(x) for x in xs]\n")
    _kind, _iterable, body = _fold(post)
    assert "call:g" in _names(body.body), f"body was {body.body!r}"


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
        post = _post_of(source)
    except SugarNotWritten:
        return
    _kind, _iterable, body = _fold(post)
    assert body.body.name == "python:loop.filter_guard", (
        "an undecided filter keeps its guard rather than choosing a side"
    )


# -- the four collection semantics -------------------------------------------


def test_the_four_collection_forms_head_distinct_coordinates():
    # One mechanism, four collection semantics. If any two shared a
    # coordinate their results could alias, and set/dict/generator semantics
    # would be indistinguishable from a list's.
    listcomp = _post_of("def f(xs):\n    return [g(a, b) for a, b in xs]\n")
    setcomp = _post_of("def f(xs):\n    return {g(a, b) for a, b in xs}\n")
    genexp = _post_of("def f(xs):\n    return (g(a, b) for a, b in xs)\n")
    dictcomp = _post_of("def f(xs):\n    return {a: b for a, b in xs}\n")
    kinds = [_fold(p)[0] for p in (listcomp, setcomp, genexp, dictcomp)]
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
    post = _post_of("def f(xs):\n    return (g(a, b) for a, b in xs)\n")
    names = _names(post)
    assert "py.generatorexp" in names
    assert "py.listcomp" not in names and "array" not in names, names


def test_a_dict_comprehension_retains_its_guarded_key_value_association():
    # The key and value are projections of the SAME element, paired in one
    # entry -- the association Python builds, not two independent sequences.
    post = _post_of("def f(xs):\n    return {a: b for a, b in xs}\n")
    _kind, _iterable, body = _fold(post)
    element = _coordinate(body)
    assert body.body == _destructure(
        element,
        2,
        _ctor(
            "python:dict_entry",
            [_project(element, 0, 2), _project(element, 1, 2)],
            symbol_kind="coordinate",
        ),
    ), f"body was {body.body!r}"


def test_a_concrete_dict_comprehension_keeps_last_write_overwrite_behaviour():
    # A repeated key keeps the LAST value and the FIRST position -- Python's
    # actual dict overwrite semantics, not a duplicated entry.
    post = _post_of(
        "def f():\n    return {a: b for a, b in [(1, 2), (3, 4), (1, 5)]}\n"
    )
    entries = post.args[1]
    assert entries.name == "python:dict", f"post was {post!r}"
    assert [
        (entry.args[0].value, entry.args[1].value) for entry in entries.args
    ] == [(1, 5), (3, 4)], f"post was {post!r}"


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


def test_a_name_target_construction_carries_no_destructuring_obligation():
    # The 'nothing else moved' twin: adding destructuring must not put an
    # unpack obligation on the simple-name path.
    post = _post_of("def f(xs):\n    return [g(x) for x in xs if p(x)]\n")
    names = _names(post)
    assert "python:unpack.destructure" not in names, names
    assert "python:unpack.project" not in names, names
    assert "python:loop.filter_guard" in names, names


# -- a nested comprehension is just another sugar in that position -----------
#
# A comprehension appearing in another comprehension's element (or in a dict
# comprehension's key or value) is NOT a shape the fold must refuse: it is one
# more sugar the element position lifts, folded over the ENCLOSING coordinate.
# Every collection form shares that one reader, so none of the four may refuse
# what the others accept. The only obstruction is a walrus, which binds into
# the enclosing scope -- a binding the scoped guarded fold does not model.


def _exhaustion():
    return _ctor("python:loop.exhaustion", [], symbol_kind="coordinate")


def _inner_listcomp(iterable, coordinate_body):
    return _ctor(
        "py.listcomp",
        [iterable, coordinate_body, _exhaustion()],
        symbol_kind="coordinate",
    )


def test_a_comprehension_nested_in_a_dict_comprehension_value_is_constructed():
    # The exact formula, not merely "it did not raise": the outer dictcomp
    # folds over `xs`, and each entry pairs the outer coordinate with an INNER
    # listcomp folded over that SAME outer coordinate.
    post = _post_of("def f(xs, g):\n    return {x: [g(y) for y in x] for x in xs}\n")
    kind, iterable, body = _fold(post)
    assert kind == "py.dictcomp"
    assert iterable == make_var("xs")
    outer = _coordinate(body)
    entry = body.body
    assert entry.name == "python:dict_entry", f"entry was {entry!r}"
    key, value = entry.args
    assert key == outer, f"key was {key!r}"
    assert value.name == "py.listcomp", f"value was {value!r}"
    # The DISCRIMINATION that makes this test worth running: the inner fold
    # ranges over the outer COORDINATE, not over the outer iterable. A lying
    # construction that folded the inner comprehension over `xs` would satisfy
    # "a listcomp is present" and be flatly wrong.
    assert value.args[0] == outer, f"inner iterable was {value.args[0]!r}"
    assert value.args[0] != make_var("xs"), f"inner iterable was {value.args[0]!r}"
    inner = _coordinate(value.args[1])
    assert inner != outer, "inner and outer coordinates must be distinct"
    assert value.args[1].body == _ctor(
        "py.call", [make_var("g"), inner]
    ), f"inner body was {value.args[1].body!r}"
    assert value == _inner_listcomp(outer, value.args[1]), f"value was {value!r}"


def test_a_comprehension_nested_in_a_dict_comprehension_key_is_constructed():
    # The key position is the value position's twin: same obligation, same
    # coordinate, so a construction that served one and refused the other
    # would be reading the dict's punctuation rather than its meaning.
    post = _post_of(
        "def f(xs, g):\n    return {tuple([g(y) for y in x]): x for x in xs}\n"
    )
    _kind, _iterable, body = _fold(post)
    outer = _coordinate(body)
    entry = body.body
    assert entry.name == "python:dict_entry", f"entry was {entry!r}"
    key, value = entry.args
    assert value == outer, f"value was {value!r}"
    nested = key.args[-1]
    assert nested.name == "py.listcomp", f"nested was {nested!r}"
    assert nested.args[0] == outer, f"inner iterable was {nested.args[0]!r}"


def test_a_comprehension_nested_in_a_set_comprehension_element_is_constructed():
    post = _post_of("def f(xs, g):\n    return {tuple([g(y) for y in x]) for x in xs}\n")
    kind, iterable, body = _fold(post)
    assert kind == "py.setcomp"
    assert iterable == make_var("xs")
    outer = _coordinate(body)
    nested = body.body.args[-1]
    assert nested.name == "py.listcomp", f"nested was {nested!r}"
    assert nested.args[0] == outer, f"inner iterable was {nested.args[0]!r}"


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
        ("def f(xs, g):\n    return {x: [g(y) for y in x] for x in xs}\n", "py.dictcomp"),
    ):
        post = _post_of(source)
        observed, _iterable, _body = _fold(post)
        assert observed == kind, f"{source} constructed {observed}"
        assert "py.listcomp" in _names(post), f"{source} lost its nested fold"


def test_a_comprehension_substituted_into_a_dict_value_is_constructed():
    # The source text holds NO nested comprehension -- substitution puts one
    # there by threading a local bound to a fold. The obstruction was read off
    # the node as it stands at construction time, so this refused while its
    # own source text looked innocent. It must construct like any other.
    post = _post_of(
        "def f(xs, g):\n"
        "    ys = [g(x) for x in xs]\n"
        "    return {k: ys for k in xs}\n"
    )
    kind, iterable, body = _fold(post)
    assert kind == "py.dictcomp"
    assert iterable == make_var("xs")
    outer = _coordinate(body)
    key, value = body.body.args
    assert key == outer, f"key was {key!r}"
    # `ys` does not depend on the outer coordinate, so the substituted fold
    # ranges over `xs` -- the discrimination against the twin above, where the
    # inner fold ranged over the coordinate. Same shape, different scope.
    assert value.name == "py.listcomp", f"value was {value!r}"
    assert value.args[0] == make_var("xs"), f"inner iterable was {value.args[0]!r}"
    assert value.args[0] != outer, f"inner iterable was {value.args[0]!r}"


def test_a_walrus_in_a_comprehension_element_stays_loud_in_every_form():
    # The LYING twin's arm: opening the door to a nested comprehension must
    # not open it to a walrus. A walrus binds into the enclosing scope, which
    # the scoped guarded fold does not model, so every form stays loud.
    from sugar_source_tree.panic import SugarNotWritten

    for source in (
        "def f(xs, g):\n    return [(n := g(x)) for x in xs]\n",
        "def f(xs, g):\n    return {(n := g(x)) for x in xs}\n",
        "def f(xs, g):\n    return ((n := g(x)) for x in xs)\n",
        "def f(xs, g):\n    return {x: (n := g(x)) for x in xs}\n",
    ):
        try:
            _post_of(source)
        except SugarNotWritten:
            continue
        raise AssertionError(f"walrus constructed silently: {source}")
