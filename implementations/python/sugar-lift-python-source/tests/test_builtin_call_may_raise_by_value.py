"""A builtin over ground operands is decided by the builtin's own semantics.

``try: int('x') except ValueError: return 1; return 2`` lifted as always
returning ``2``: once every operand of ``int`` was a decided builtin, the call
was cited as total -- but ``int('x')`` raises ``ValueError``.  It then became
a two-faced call that owed nothing (``BuiltinValueCallV1``), a second way of
saying "not decided here".  Every operand is a known value, so the outcome is
decided: the pinned interpreter's own builtin applied to those values
(``cpython_cited_fold``).  ``int('x')`` is the one ``ValueError`` halt and
nothing else; ``int('3')`` completes with ``3`` and nothing else.  An operand
known only by its type (``int(s)`` with ``s`` a ``str`` nothing here knows)
is not decided here: the call is the one unanswered call, two-faced and owed
as ``undecided``/``unanswered``.  The shapes CPython documents as never
raising (``len`` of a sized builtin, ``str``/``repr``/``bool`` of one
operand, ``print``, ``list`` of a builtin iterable, ``int`` of a ground int,
...) still complete outright.
"""

from __future__ import annotations

import pytest

from sugar_lift_py_tests.floor import ListValue, StringValue, TermValue

from test_builtin_container_mutation import _returns
from test_unknown_callee_call_faces import _two_faced_and_owed


def _halt_names(halts):
    return [getattr(halt, "exception_name", None) for halt in halts]


def test_a_handler_for_int_of_a_bad_string_is_the_only_return(tmp_path):
    source = (
        "def f():\n"
        "    try:\n"
        "        int('x')\n"
        "    except ValueError:\n"
        "        return 1\n"
        "    return 2\n"
    )
    returns, halts = _returns(tmp_path, source)
    assert returns == [TermValue(1)]
    assert halts == []


@pytest.mark.parametrize(
    "expression, exception",
    [
        ("int('x')", "ValueError"),
        ("float('x')", "ValueError"),
        ("int(None)", "TypeError"),
        ("chr(-1)", "ValueError"),
        ("ord('ab')", "TypeError"),
        ("max([])", "ValueError"),
        ("divmod(1, 0)", "ZeroDivisionError"),
        ("range(0, 1, 0)", "ValueError"),
        ("sorted([1, 'a'])", "TypeError"),
        ("sum(['a'])", "TypeError"),
    ],
)
def test_a_builtin_cpython_refuses_over_ground_operands_is_the_one_halt(
    tmp_path, expression, exception
):
    returns, halts = _returns(tmp_path, f"def f():\n    return {expression}\n")
    assert returns == []
    assert _halt_names(halts) == [exception]


@pytest.mark.parametrize(
    "expression, value",
    [
        ("int('3')", 3),
        ("float('2.5')", 2.5),
        ("ord('a')", 97),
        ("divmod(7, 2)[0]", 3),
    ],
)
def test_a_builtin_over_ground_operands_completes_with_its_value(
    tmp_path, expression, value
):
    returns, halts = _returns(tmp_path, f"def f():\n    return {expression}\n")
    assert returns == [TermValue(value)]
    assert halts == []


def test_a_builtin_over_an_operand_known_only_by_type_is_the_one_unanswered_call(
    tmp_path,
):
    # ``s`` is a ``str`` nothing here knows the value of: whether ``int(s)``
    # completes is not decided here.
    _returns_, owners = _two_faced_and_owed(
        tmp_path, "def f(s: str):\n    return int(s)\n"
    )
    assert owners == ["UnknownCallee:int"]


@pytest.mark.parametrize(
    "expression",
    [
        "len([1, 2])",
        "len('ab')",
        "str([1])",
        "repr(1)",
        "bool([])",
        "list('ab')",
        "tuple([1])",
        "set('ab')",
        "int(5)",
        "float(2)",
        "abs(-3)",
        "range(3)",
        "hash('a')",
        "any([0, 1])",
        "sum([1, 2])",
        "sorted([2, 1])",
        "max([1, 2])",
        "min(1, 2)",
    ],
)
def test_a_documented_total_builtin_still_completes(tmp_path, expression):
    returns, halts = _returns(tmp_path, f"def f():\n    return {expression}\n")
    assert halts == []
    assert len(returns) == 1


def test_print_of_builtins_completes(tmp_path):
    returns, halts = _returns(tmp_path, "def f():\n    print('a', 1)\n    return 0\n")
    assert halts == []
    assert returns == [TermValue(0)]


# One answerer (#7757): a builtin call, or a ``str`` method, whose every
# operand is ground is decided by the pinned interpreter through the cited
# fold alone -- no floor value folds it by hand.  ``len('ab')``,
# ``'a b'.split()`` and ``','.join(['a', 'b'])`` answer what the deleted hand
# folds answered; ``abs(-2)`` was the bare call coordinate (its hand fold,
# ``TermValue.absolute``, had no caller) and is now ``2``.

_ONE_FOLD = [
    ("len('ab')", TermValue(2)),
    ("abs(-2)", TermValue(2)),
    ("'a b'.split()", ListValue((StringValue("a"), StringValue("b")))),
    ("','.join(['a', 'b'])", StringValue("a,b")),
]


@pytest.mark.parametrize("expression, value", _ONE_FOLD)
def test_a_ground_call_is_answered_by_the_one_fold(
    tmp_path, monkeypatch, expression, value
):
    from sugar_lift_py_tests import source_call_resolution

    applied = []
    host_applied = source_call_resolution._host_applied

    def recording(function, operands, site, **kwargs):
        applied.append(kwargs["owner"])
        return host_applied(function, operands, site, **kwargs)

    monkeypatch.setattr(source_call_resolution, "_host_applied", recording)
    returns, halts = _returns(
        tmp_path, f"def f():\n    answer = {expression}\n    return answer\n"
    )
    assert returns == [value]
    assert halts == []
    assert applied, f"{expression} was not answered by the cited fold"
    assert all(owner.startswith("cpython_cited_fold:") for owner in applied)


def test_the_hand_written_ground_folds_are_gone():
    from sugar_lift_py_tests.floor import string_value
    from sugar_lift_py_tests.floor.call_site_value import CallSiteValue
    from sugar_lift_py_tests.floor.floor_value import FloorValue
    from sugar_lift_py_tests.floor.symbolic_value import SymbolicValue

    for floor in (FloorValue, TermValue, SymbolicValue, CallSiteValue):
        assert not hasattr(floor, "absolute")
    assert not hasattr(string_value, "_static_str_parts")


def test_a_str_method_over_a_ground_non_string_is_the_one_halt(tmp_path):
    # ``str.join`` of a list holding an ``int``: the pinned interpreter
    # refuses it with ``TypeError``, nothing else.
    returns, halts = _returns(tmp_path, "def f():\n    return ','.join([1])\n")
    assert returns == []
    assert [getattr(halt, "exception_name", None) for halt in halts] == ["TypeError"]


def _recording_host_applied(monkeypatch):
    from sugar_lift_py_tests import source_call_resolution

    applied = []
    host_applied = source_call_resolution._host_applied

    def recording(function, operands, site, **kwargs):
        applied.append(kwargs["owner"])
        return host_applied(function, operands, site, **kwargs)

    monkeypatch.setattr(source_call_resolution, "_host_applied", recording)
    return applied


# One answerer (#7757): a method of a ground ``list``/``tuple``/``dict``
# receiver that does not change it, with ground arguments, is decided by the
# pinned interpreter through the cited fold.  These were two-faced (the
# container's opaque ``python:builtin_method`` pair, or the unknown callee).


def test_index_of_a_missing_member_of_a_ground_list_is_the_one_value_error(
    tmp_path, monkeypatch
):
    applied = _recording_host_applied(monkeypatch)
    returns, halts = _returns(tmp_path, "def f():\n    return [1, 2].index(3)\n")
    assert returns == []
    assert _halt_names(halts) == ["ValueError"]
    assert "cpython_cited_fold:list.index" in applied


def test_get_of_a_missing_key_of_a_ground_dict_is_none(tmp_path, monkeypatch):
    from sugar_lift_py_tests.floor.none_value import NoneValue

    applied = _recording_host_applied(monkeypatch)
    returns, halts = _returns(tmp_path, "def f():\n    return {'a': 1}.get('b')\n")
    assert returns == [NoneValue()]
    assert halts == []
    assert "cpython_cited_fold:dict.get" in applied


@pytest.mark.parametrize(
    "expression, value, owner",
    [
        ("[1, 2, 1].count(1)", TermValue(2), "list.count"),
        ("(1, 2).index(2)", TermValue(1), "tuple.index"),
        ("{'a': 1}.get('a')", TermValue(1), "dict.get"),
        ("[1, 2].copy()", ListValue((TermValue(1), TermValue(2))), "list.copy"),
    ],
)
def test_a_reading_method_of_a_ground_container_is_answered_by_the_one_fold(
    tmp_path, monkeypatch, expression, value, owner
):
    applied = _recording_host_applied(monkeypatch)
    returns, halts = _returns(
        tmp_path, f"def f():\n    answer = {expression}\n    return answer\n"
    )
    assert returns == [value]
    assert halts == []
    assert f"cpython_cited_fold:{owner}" in applied


def test_pop_of_a_ground_list_takes_its_value_from_the_fold(tmp_path, monkeypatch):
    applied = _recording_host_applied(monkeypatch)
    returns, halts = _returns(
        tmp_path,
        "def f():\n    xs = [1, 2]\n    y = xs.pop()\n    return y\n",
    )
    assert returns == [TermValue(2)]
    assert halts == []
    assert "cpython_cited_fold:list.pop" in applied


def test_contents_not_current_at_the_call_are_not_folded():
    # A list or dict reached by binding may have been changed since it was
    # built (#7618): only a receiver whose value says its contents are
    # current (a construction in this frame made it), or an immutable tuple,
    # folds.
    from sugar_lift_py_tests.floor.object_identity import arrived
    from sugar_lift_py_tests.floor.tuple_value import TupleValue
    from sugar_lift_py_tests.source_call_resolution import cited_container_method

    made = ListValue((TermValue(1),), allocation="made-here")
    assert cited_container_method(made, "index")
    assert not cited_container_method(arrived(made), "index")
    unmade = ListValue((TermValue(1),), allocation=None)
    assert not cited_container_method(unmade, "index")
    # A value built with no allocation given was made here by a construction
    # it does not name: current.
    assert cited_container_method(ListValue((TermValue(1),)), "index")
    assert not cited_container_method(made, "pop")
    assert cited_container_method(TupleValue((TermValue(1),)), "index")
    assert not cited_container_method(TupleValue((made,)), "index")


def test_arrived_takes_the_allocation_off_every_container_in_the_value():
    from sugar_lift_py_tests.floor import DictValue
    from sugar_lift_py_tests.floor.object_identity import arrived, contents_current
    from sugar_lift_py_tests.floor.tuple_value import TupleValue

    inner = ListValue((TermValue(1),), allocation="inner")
    outer = TupleValue((DictValue(((StringValue("k"), inner),), allocation="d"),))
    stripped = arrived(outer)
    assert stripped == outer
    ((_key, held),) = stripped.elements[0].entries
    assert not contents_current(stripped.elements[0])
    assert not contents_current(held)


def test_a_split_result_is_current_and_its_index_folds(tmp_path, monkeypatch):
    # ``'a b'.split()`` is a new list made in this frame: its contents are
    # current by its value, not because the source spelled a display.
    applied = _recording_host_applied(monkeypatch)
    returns, halts = _returns(
        tmp_path,
        "def f():\n    xs = 'a b'.split()\n    return xs.index('b')\n",
    )
    assert returns == [TermValue(1)]
    assert halts == []
    assert "cpython_cited_fold:list.index" in applied


def test_a_parameters_index_does_not_fold(tmp_path, monkeypatch):
    # ``xs`` reaches ``f`` by binding: even a list the caller made in its own
    # frame is not current here, so nothing reads its contents.
    from test_formal_method_call_defers import _carrier, _discharge, _faces
    from test_unprojected_method_call_faces import _owners

    applied = _recording_host_applied(monkeypatch)
    carrier = _carrier(tmp_path, "def f(xs):\n    return xs.index(1)\n")
    actual = ListValue((TermValue(1),), allocation="made-by-the-caller")
    _completed, halted = _faces(_discharge(carrier, actual))
    assert "cpython_cited_fold:list.index" not in applied
    assert _owners(halted) == ["BuiltinMethodCall:list.index"]


def test_a_bound_dicts_items_is_not_read_from_its_contents(tmp_path, monkeypatch):
    # ``DictValue.items()`` was read off a dict that reached the frame by
    # binding (#8084's flagged hand path): it is the opaque method now.
    from sugar_lift_py_tests.floor import DictValue
    from test_formal_method_call_defers import _carrier, _discharge, _faces
    from test_unprojected_method_call_faces import _owners

    applied = _recording_host_applied(monkeypatch)
    carrier = _carrier(tmp_path, "def f(d):\n    return d.items()\n")
    actual = DictValue(
        ((StringValue("a"), TermValue(1)),), allocation="made-by-the-caller"
    )
    _completed, halted = _faces(_discharge(carrier, actual))
    assert "cpython_cited_fold:dict.items" not in applied
    # Two-faced under the method's own atom: never the pairs the binding held.
    assert _owners(halted) == ["BuiltinMethodCall:dict.items"]


def test_a_bound_dict_has_no_closed_items():
    from sugar_lift_py_tests.floor import DictValue
    from sugar_lift_py_tests.floor.object_identity import arrived

    made = DictValue(((StringValue("a"), TermValue(1)),), allocation="made-here")
    assert made.supports_closed_method("items")
    assert not arrived(made).supports_closed_method("items")


# One currency rule (#7757, after #8105): every read of a list/dict/set's
# contents asks ``object_identity.contents_current`` -- the cited fold, the
# one door's container law, and each floor read.  A container that is not
# current (it arrived by binding) is read in the read's own undecided form,
# never from the contents it held when it arrived.


def _made_and_arrived():
    from sugar_lift_py_tests.floor.object_identity import arrived

    made = ListValue((TermValue(1), TermValue(2)), allocation="made-here")
    return made, arrived(made)


def test_the_one_rule_answers_every_reader():
    from sugar_lift_py_tests.floor.object_identity import (
        contents_current,
        contents_stale,
    )

    made, stale = _made_and_arrived()
    assert contents_current(made) and not contents_stale(made)
    assert not contents_current(stale) and contents_stale(stale)
    # A tuple has no currency of its own; it is never stale.
    from sugar_lift_py_tests.floor.tuple_value import TupleValue

    assert not contents_stale(TupleValue((stale,)))


def test_a_stale_lists_length_is_the_len_coordinate_never_its_count():
    from sugar_lift_py_tests.floor.call_site_value import CallSiteValue

    made, stale = _made_and_arrived()
    assert made.length("len-site").completed_value() == TermValue(2)
    counted = stale.length("len-site").completed_value()
    assert type(counted) is CallSiteValue
    assert counted.target_name == "len"


def test_a_stale_list_is_not_handed_to_the_fold():
    from sugar_lift_py_tests.floor.tuple_value import TupleValue
    from sugar_lift_py_tests.source_call_resolution import _NOT_GROUND, _host_ground

    made, stale = _made_and_arrived()
    assert _host_ground(made) == [1, 2]
    assert _host_ground(stale) is _NOT_GROUND
    # Nor inside a value that holds it.
    assert _host_ground(TupleValue((stale,))) is _NOT_GROUND


def test_the_door_does_not_read_a_stale_receiver():
    from sugar_lift_py_tests.floor import DictValue
    from sugar_lift_py_tests.floor import builtin_container_method as law
    from sugar_lift_py_tests.floor.object_identity import arrived, contents_current
    from sugar_lift_py_tests.floor.tuple_value import TupleValue

    made, stale = _made_and_arrived()
    popped = law.apply("list", "pop", made, (), "pop", None).completed_value()
    assert type(popped) is TupleValue and popped.elements[1] == TermValue(2)
    # ``pop``'s value, ``remove``'s membership, a dict's ``setdefault`` read
    # the contents: undecided, and the door applies an opaque post-state.
    assert law.apply("list", "pop", stale, (), "pop", None) is law.UNDECIDED
    assert law.apply("list", "remove", stale, (TermValue(1),), "rm", None) is None
    stale_dict = arrived(
        DictValue(((StringValue("k"), TermValue(1)),), allocation="made-here")
    )
    assert (
        law.apply("dict", "setdefault", stale_dict, (StringValue("k"),), "sd", None)
        is law.UNDECIDED
    )
    # ``append`` reads nothing: it applies, and its post-state is not current.
    appended = law.apply("list", "append", stale, (TermValue(3),), "append", None)
    post, result = appended.completed_value().elements
    assert not contents_current(post)
    assert type(result).__name__ == "NoneValue"


def test_a_stale_member_is_never_equal_by_its_contents():
    from sugar_lift_py_tests.floor.membership import member_equal

    made, stale = _made_and_arrived()
    assert member_equal(made, ListValue((TermValue(1), TermValue(2)))) is True
    assert member_equal(stale, ListValue((TermValue(1), TermValue(2)))) is None


def test_a_concatenation_of_current_lists_is_current_and_of_a_stale_one_is_not():
    from sugar_lift_py_tests.floor.object_identity import contents_current

    made, stale = _made_and_arrived()
    fresh = made.add(made, "add-site", None).completed_value()
    assert contents_current(fresh)
    assert not contents_current(stale.add(made, "add-site", None).completed_value())


_CLEAR = "def clear(ys):\n    ys.clear()\n"


@pytest.mark.parametrize(
    "read, stale_answer",
    [
        ("len(xs)", TermValue(2)),
        ("xs[0]", TermValue(1)),
        ("xs.pop()", TermValue(2)),
        ("1 in xs", None),
    ],
)
def test_a_helper_never_reads_the_contents_its_list_arrived_with(
    tmp_path, read, stale_answer
):
    # ``xs`` reaches ``g`` by binding, and code ``g`` calls empties it: the
    # contents the caller built are not ``xs``'s contents at the read.
    from sugar_lift_py_tests.sugar.true_bool_literal_sugar import (
        TrueBoolLiteralSugar,
    )

    source = (
        _CLEAR
        + "def g(xs):\n"
        + "    clear(xs)\n"
        + f"    return {read}\n"
        + "def f():\n"
        + "    return g([1, 2])\n"
    )
    returns, _halts = _returns(tmp_path, source)
    if stale_answer is None:
        assert not any(type(value) is TrueBoolLiteralSugar for value in returns)
    else:
        assert stale_answer not in returns


@pytest.mark.parametrize(
    "body, value",
    [
        ("xs = [1, 2]\n    return len(xs)\n", TermValue(2)),
        ("xs = [1, 2]\n    return xs[1]\n", TermValue(2)),
        ("xs = [1, 2]\n    ys = xs + [3]\n    return len(ys)\n", TermValue(3)),
        ("xs = [1, 2]\n    a, b = xs\n    return b\n", TermValue(2)),
    ],
)
def test_a_list_this_frame_built_still_folds(tmp_path, body, value):
    returns, halts = _returns(tmp_path, f"def f():\n    {body}")
    assert returns == [value]
    assert halts == []


def test_a_list_a_generator_yielded_is_not_current_when_it_resumes():
    # The consumer holds the yielded list and may change it before the
    # generator resumes: the generator's own binding of it is released at the
    # yield, so a read after the resume never takes the contents it yielded.
    from sugar_lift_py_tests.floor.object_identity import contents_current
    from sugar_lift_py_tests.generator_construction import (
        GeneratorAssignBindingV1,
        GeneratorConstructionV1,
        YieldEffect,
    )

    from test_generator_pre_yield_assign_execution import _steps

    steps = _steps("def g():\n    xs = [1]\n    yield xs\n    return len(xs)\n")
    yielded = GeneratorConstructionV1.allocate(
        allocation_coordinate="enter:yielded-list",
        frame_coordinate="frame:yielded-list",
        binding_state=(),
        steps=steps,
    ).resume()
    assert isinstance(yielded, YieldEffect)
    assert not contents_current(yielded.value)
    (held,) = [
        binding
        for binding in yielded.machine.binding_state
        if isinstance(binding, GeneratorAssignBindingV1) and binding.name == "xs"
    ]
    assert held.value == ListValue((TermValue(1),))
    assert not contents_current(held.value)


# The residue of #8117: truth, a slice assignment's right-hand side, item
# stores and deletes outside the one door, ``match`` patterns, and a
# generator's walrus bindings each read through ``contents_current``.


def _stale_containers():
    from sugar_lift_py_tests.floor import DictValue
    from sugar_lift_py_tests.floor.object_identity import arrived
    from sugar_lift_py_tests.floor.set_value import SetValue

    _made, stale = _made_and_arrived()
    return (
        stale,
        arrived(
            DictValue(((StringValue("k"), TermValue(1)),), allocation="made-here")
        ),
        arrived(SetValue((TermValue(1),), allocation="made-here")),
    )


def test_a_current_containers_truth_is_its_emptiness():
    from sugar_lift_py_tests.sugar.false_bool_literal_sugar import (
        FalseBoolLiteralSugar,
    )
    from sugar_lift_py_tests.sugar.true_bool_literal_sugar import (
        TrueBoolLiteralSugar,
    )

    made, _stale = _made_and_arrived()
    assert type(made.truth("truth-site").completed_value()) is TrueBoolLiteralSugar
    empty = ListValue((), allocation="made-here")
    assert type(empty.truth("truth-site").completed_value()) is FalseBoolLiteralSugar


def test_a_stale_containers_truth_is_the_undecided_truth_never_its_emptiness():
    from sugar_lift_py_tests.floor.predicate_value import PredicateValue

    for container in _stale_containers():
        outcome = container.truth("truth-site")
        truth = outcome.completed_value()
        # One boolean, true under the opaque truth of the value and false
        # under its complement: neither face is chosen.
        assert type(truth) is PredicateValue
        assert truth.formula.name == "py.truthy"
        assert truth.formula.args[0].name == "python:truth"
        # A builtin container's truth runs no code: no halt, no debt.
        assert outcome.halts() == ()
        assert outcome.owed_items() == ()
    # Keyed on the site: two truth tests are never forced to agree.
    stale = _stale_containers()[0]
    assert (
        stale.truth("truth-site").completed_value().formula
        != stale.truth("other-truth-site").completed_value().formula
    )


def test_a_siteless_undecided_truth_refuses_by_name():
    from sugar_source_tree.panic import SugarNotWritten

    with pytest.raises(SugarNotWritten):
        _stale_containers()[0].truth(None)


@pytest.mark.parametrize(
    "test",
    [
        "return 1 if xs else 0\n",
        "if xs:\n        return 1\n    return 0\n",
        "return 0 if not xs else 1\n",
    ],
)
def test_a_helper_never_tests_the_truth_its_list_arrived_with(tmp_path, test):
    # ``xs`` reaches ``g`` by binding: its truth is not the emptiness of the
    # contents the caller built, so both faces stand.
    source = "def g(xs):\n    " + test + "def f():\n    return g([1, 2])\n"
    returns, _halts = _returns(tmp_path, source)
    assert TermValue(1) in returns
    assert TermValue(0) in returns


def _completed_values(outcome):
    from sugar_lift_py_tests.outcome import Completed

    return [exit_.value for exit_ in outcome.exits if isinstance(exit_, Completed)]


def _undecided_mutation(outcome):
    """The undecided item mutation: the receiver after it unknown, and only
    an undetermined raise -- never an exception read from stale contents."""
    from sugar_lift_py_tests.effect.raise_effect import UndeterminedRaiseEffect
    from sugar_lift_py_tests.floor.symbolic_value import SymbolicValue

    completed = _completed_values(outcome)
    assert completed
    assert all(
        type(value) is SymbolicValue
        and value.term.name == "python:receiver_after_call"
        for value in completed
    )
    assert outcome.halts()
    assert all(
        type(halt.effect) is UndeterminedRaiseEffect for halt in outcome.halts()
    )


def test_a_stale_list_on_the_right_of_a_slice_assignment_has_no_members():
    from sugar_lift_py_tests.floor.slice_value import SliceValue
    from sugar_lift_py_tests.operations.slice_assign_iterable_operation import (
        SliceAssignIterableOperation,
    )

    made, stale = _made_and_arrived()
    operation = SliceAssignIterableOperation(owner="test", blame="slice-site")
    assert operation.submit(made, None).completed_value() == made.elements
    _undecided_mutation(operation.submit(stale, None))
    # The store into a current list takes no member from it either.
    target = ListValue((TermValue(0),), allocation="made-here")
    whole = SliceValue(None, None, None)
    _undecided_mutation(target.setitem(whole, stale, "slice-site", None))
    stored = target.setitem(whole, made, "slice-site", None).completed_value()
    assert stored == ListValue((TermValue(1), TermValue(2)))


def test_a_store_or_delete_outside_the_door_never_reads_stale_contents():
    from sugar_lift_py_tests.effect.raise_effect import UndeterminedRaiseEffect
    from sugar_lift_py_tests.floor.slice_value import SliceValue

    made, stale = _made_and_arrived()
    # Current contents decide the bound: index 5 of ``[1, 2]`` is IndexError,
    # the store's one decided halt.
    decided = made.setitem(TermValue(5), TermValue(0), "store-site", None)
    assert decided.halts() and not _completed_values(decided)
    assert all(
        type(halt.effect) is not UndeterminedRaiseEffect for halt in decided.halts()
    )
    # Stale ones do not: no IndexError, no member written or removed.
    _undecided_mutation(stale.setitem(TermValue(5), TermValue(0), "store-site", None))
    _undecided_mutation(stale.setitem(TermValue(0), TermValue(9), "store-site", None))
    _undecided_mutation(stale.delitem(TermValue(5), "del-site", None))
    _undecided_mutation(stale.delitem(SliceValue(None, None, None), "del-site", None))
    stale_dict = _stale_containers()[1]
    _undecided_mutation(stale_dict.delitem(StringValue("z"), "del-site", None))
    _undecided_mutation(stale_dict.delitem(StringValue("k"), "del-site", None))


def test_a_mapping_patterns_rest_of_a_stale_dict_is_not_current():
    from sugar_lift_py_tests.floor import DictValue
    from sugar_lift_py_tests.floor.object_identity import contents_current
    from sugar_lift_py_tests.sugar.match_sugar import _mapping_rest

    stale_dict = _stale_containers()[1]
    made_dict = DictValue(((StringValue("k"), TermValue(1)),), allocation="made-here")
    for subject, current in ((made_dict, True), (stale_dict, False)):
        matched = _mapping_rest(subject, (), "rest", "match-site").completed_value()
        ((key, rest),) = matched.binds
        assert key == "rest"
        assert contents_current(rest) is current


def test_a_sequence_pattern_over_a_stale_list_never_takes_its_length():
    from sugar_lift_py_tests.sugar.match_sugar import (
        CapturePatternSpec,
        SequencePatternSpec,
        match_pattern,
    )
    from sugar_source_tree.panic import SugarNotWritten

    _made, stale = _made_and_arrived()
    wildcard = CapturePatternSpec(None, None)
    spec = SequencePatternSpec(before=(wildcard, wildcard))
    # Its length is the ``call:len`` coordinate: the pattern test is refused
    # by name, never matched against the two members it arrived with.
    with pytest.raises(SugarNotWritten):
        match_pattern(spec, stale, "match-site", None)


def test_a_generators_walrus_binding_is_not_current_when_it_resumes():
    from dataclasses import dataclass

    from sugar_lift_py_tests.floor.named_expression_value import (
        NamedExpressionValue,
    )
    from sugar_lift_py_tests.floor.object_identity import contents_current
    from sugar_lift_py_tests.generator_construction import (
        GeneratorWalrusBindingV1,
        _released_at_yield,
    )

    @dataclass(frozen=True)
    class _Frame:
        binding_state: tuple

    made, _stale = _made_and_arrived()
    walrus = NamedExpressionValue("xs", made, evaluation="walrus-key")
    frame = _Frame((GeneratorWalrusBindingV1(walrus),))
    (held,) = _released_at_yield(frame).binding_state
    assert held.name == "xs" and held.evaluation == "walrus-key"
    assert held.bind.assigned_value == made
    assert not contents_current(held.bind.assigned_value)
    assert not contents_current(held.bind.presented_value)


def test_a_list_a_generators_walrus_yielded_is_not_current_when_it_resumes():
    from sugar_lift_py_tests.floor.object_identity import contents_current
    from sugar_lift_py_tests.generator_construction import (
        GeneratorConstructionV1,
        GeneratorWalrusBindingV1,
        YieldEffect,
    )

    from test_generator_pre_yield_assign_execution import _steps

    steps = _steps("def g():\n    yield (xs := [1])\n    return len(xs)\n")
    yielded = GeneratorConstructionV1.allocate(
        allocation_coordinate="enter:walrus-yielded-list",
        frame_coordinate="frame:walrus-yielded-list",
        binding_state=(),
        steps=steps,
    ).resume()
    assert isinstance(yielded, YieldEffect)
    (held,) = [
        binding
        for binding in yielded.machine.binding_state
        if isinstance(binding, GeneratorWalrusBindingV1) and binding.name == "xs"
    ]
    assert held.bind.assigned_value == ListValue((TermValue(1),))
    assert not contents_current(held.bind.assigned_value)


def test_a_str_method_over_an_opaque_argument_keeps_its_marker():
    from types import SimpleNamespace

    from sugar_lift_py_tests.floor import SymbolicValue
    from sugar_lift_py_tests.floor.opaque_op_callsite import OpaqueOpCallsite
    from sugar_lift_py_tests.floor.string_value import _fold_string_method
    from sugar_lift_py_tests.ir import make_var
    from sugar_source_tree.nodes import LanguageCallee

    for name, marker in (
        ("join", LanguageCallee.STR_JOIN),
        ("split", LanguageCallee.STR_SPLIT),
    ):
        minted = _fold_string_method(
            StringValue(","),
            SimpleNamespace(
                name=name, arguments=(SymbolicValue(make_var("xs")),), blame=name
            ),
        ).completed_value()
        assert type(minted) is OpaqueOpCallsite
        assert minted.language_callee is marker
