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

from frame_fresh import fresh
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
    ("'a b'.split()", fresh(ListValue, (StringValue("a"), StringValue("b")))),
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
        (
            "[1, 2].copy()",
            fresh(ListValue, (TermValue(1), TermValue(2))),
            "list.copy",
        ),
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
    assert not cited_container_method(arrived(made, "binding-read"), "index")
    unmade = ListValue((TermValue(1),), allocation=None)
    assert not cited_container_method(unmade, "index")
    assert not cited_container_method(made, "pop")
    assert cited_container_method(TupleValue((TermValue(1),)), "index")
    assert not cited_container_method(TupleValue((made,)), "index")


def test_arrived_takes_the_allocation_off_every_container_in_the_value():
    from sugar_lift_py_tests.floor import DictValue
    from sugar_lift_py_tests.floor.object_identity import arrived, contents_current
    from sugar_lift_py_tests.floor.tuple_value import TupleValue

    inner = ListValue((TermValue(1),), allocation="inner")
    outer = TupleValue((DictValue(((StringValue("k"), inner),), allocation="d"),))
    stripped = arrived(outer, "binding-read")
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
    assert not arrived(made, "binding-read").supports_closed_method("items")


# One currency rule (#7757, after #8105): every read of a list/dict/set's
# contents asks ``object_identity.contents_current`` -- the cited fold, the
# one door's container law, and each floor read.  A container that is not
# current (it arrived by binding) is read in the read's own undecided form,
# never from the contents it held when it arrived.


def _made_and_arrived():
    from sugar_lift_py_tests.floor.object_identity import arrived

    made = ListValue((TermValue(1), TermValue(2)), allocation="made-here")
    return made, arrived(made, "binding-read")


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
        DictValue(((StringValue("k"), TermValue(1)),), allocation="made-here"),
        "binding-read",
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
    assert member_equal(made, fresh(ListValue, (TermValue(1), TermValue(2)))) is True
    assert member_equal(stale, fresh(ListValue, (TermValue(1), TermValue(2)))) is None


def test_a_concatenation_of_current_lists_is_current_and_of_a_stale_one_is_not():
    from sugar_lift_py_tests.floor.object_identity import contents_current

    made, stale = _made_and_arrived()
    joined = made.add(made, "add-site", None).completed_value()
    assert contents_current(joined)
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
    assert held.value == fresh(ListValue, (TermValue(1),))
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
            DictValue(((StringValue("k"), TermValue(1)),), allocation="made-here"),
            "dict-read",
        ),
        arrived(SetValue((TermValue(1),), allocation="made-here"), "set-read"),
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
    assert stored == fresh(ListValue, (TermValue(1), TermValue(2)))


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


def test_a_sequence_pattern_over_a_stale_list_splits_on_its_length():
    from sugar_lift_py_tests.outcome import Completed
    from sugar_lift_py_tests.sugar.match_sugar import (
        SequencePatternSpec,
        match_pattern,
    )

    _made, stale = _made_and_arrived()
    # Its length is the ``call:len`` coordinate: the pattern splits on it,
    # matched under ``len == 0`` and not under its complement -- never
    # decided from the two members it arrived with.
    outcome = match_pattern(SequencePatternSpec(before=()), stale, "match-site", None)
    faces = [exit_ for exit_ in outcome.exits if isinstance(exit_, Completed)]
    assert sorted(face.value.matched for face in faces) == [False, True]
    for face in faces:
        names = _term_names(face.guard)
        assert any("len" in str(name) for name in names)
        assert "python:object_read" in names
        assert "array" not in names


@pytest.mark.parametrize("pattern", ["[a, b]", "[a, *rest]", "[*rest, b]"])
def test_a_helper_matches_the_list_it_arrived_with_on_both_lengths(
    tmp_path, pattern
):
    # ``xs`` reaches ``g`` by binding: whether it has the pattern's length is
    # not read from the contents the caller built, so both cases stand.
    source = (
        "def g(xs):\n"
        + "    match xs:\n"
        + f"        case {pattern}:\n"
        + "            return 1\n"
        + "        case _:\n"
        + "            return 0\n"
        + "def f():\n"
        + "    return g([1, 2])\n"
    )
    returns, _halts = _returns(tmp_path, source)
    assert TermValue(1) in returns
    assert TermValue(0) in returns


# The residue of #8129: an undecided read's term names a stale container by
# its identity, a ``match`` sequence pattern splits on a stale list's
# ``call:len``, and a path store through a stale root is the opaque
# post-state.


def _term_names(term, depth=0):
    """Every constructor and atom name in ``term``, at any depth."""
    names = {getattr(term, "name", None)}
    if depth > 64:
        return names
    children = (
        *(getattr(term, "args", ()) or ()),
        *(getattr(term, "operands", ()) or ()),
    )
    body = getattr(term, "body", None)
    for child in (*children, *(() if body is None else (body,))):
        names |= _term_names(child, depth + 1)
    return names


def _object_reads(term, depth=0):
    found = []
    if getattr(term, "name", None) == "python:object_read":
        found.append(term)
    if depth > 64:
        return found
    for arg in getattr(term, "args", ()) or ():
        found.extend(_object_reads(arg, depth + 1))
    return found


def test_an_undecided_reads_term_never_carries_stale_contents():
    from sugar_lift_py_tests.floor.object_identity import identity_term

    made, stale = _made_and_arrived()
    terms = (
        stale.length("len-site").completed_value().term,
        stale.truth("truth-site").completed_value().formula,
        _completed_values(stale.subscript(TermValue(0), "sub-site"))[0].term,
        _completed_values(stale.equals(TermValue(3), "eq-site", None))[0].formula,
        _completed_values(stale.contains(TermValue(1), "in-site"))[0].formula,
    )
    for term in terms:
        names = _term_names(term)
        # The object, never the ``array(1, 2)`` it arrived as.
        assert "python:object_read" in names
        assert "array" not in names
    # A current list is its contents: its term is unchanged.
    assert identity_term(made, "site", "receiver", owner="t") == made.to_term(
        owner="t"
    )
    # Inside a tuple, only the stale member is named by its object.
    from sugar_lift_py_tests.floor.tuple_value import TupleValue

    held = identity_term(TupleValue((stale, made)), "site", "left", owner="t")
    assert len(_object_reads(held)) == 1
    assert "array" in _term_names(held)


def test_a_stale_object_is_named_per_read_and_per_arrival():
    from dataclasses import replace

    from sugar_lift_py_tests.floor.object_identity import arrived, identity_term

    _made, stale = _made_and_arrived()
    first = replace(stale, arrival="read-a")
    second = replace(stale, arrival="read-b")
    # Two reads of one object are two unknowns: it may change between them.
    assert identity_term(first, "len-1", "receiver", owner="t") != identity_term(
        first, "len-2", "receiver", owner="t"
    )
    # Two objects one read meets (a ``match``'s patterns all read at the
    # match) are told apart by the binding read each arrived through, never
    # by their contents -- equal here.
    assert identity_term(first, "site", "receiver", owner="t") != identity_term(
        second, "site", "receiver", owner="t"
    )
    # A container that already arrived keeps its arrival: it is that object.
    assert arrived(first, "read-c").arrival == "read-a"


def test_a_siteless_read_of_a_stale_object_refuses_by_name():
    from sugar_lift_py_tests.floor.object_identity import identity_term
    from sugar_source_tree.panic import SugarNotWritten

    made, stale = _made_and_arrived()
    assert identity_term(made, None, "receiver", owner="t") == made.to_term(owner="t")
    with pytest.raises(SugarNotWritten):
        identity_term(stale, None, "receiver", owner="t")


# The residue of #8137: a stale container with no arrival took ``""``, so two
# different such objects one read met shared one term.  Every path that
# makes a stale value names it; one that cannot refuses by name.


def _stale_length_reads(subject):
    """The ``python:object_read`` terms a sequence pattern over ``subject``
    at one ``match`` site names in its faces' guards."""
    from sugar_lift_py_tests.outcome import Completed
    from sugar_lift_py_tests.sugar.match_sugar import (
        SequencePatternSpec,
        match_pattern,
    )

    outcome = match_pattern(SequencePatternSpec(before=()), subject, "match-site", None)
    found = set()
    for face in outcome.exits:
        if isinstance(face, Completed):
            found |= {str(term) for term in _object_reads_anywhere(face.guard)}
    return found


def _object_reads_anywhere(term, depth=0):
    found = []
    if getattr(term, "name", None) == "python:object_read":
        found.append(term)
    if depth > 64:
        return found
    body = getattr(term, "body", None)
    for child in (
        *(getattr(term, "args", ()) or ()),
        *(getattr(term, "operands", ()) or ()),
        *(() if body is None else (body,)),
    ):
        found.extend(_object_reads_anywhere(child, depth + 1))
    return found


def test_two_lists_computed_from_stale_ones_read_at_one_match_get_two_terms():
    from sugar_lift_py_tests.floor.object_identity import arrived, contents_current

    made = ListValue((TermValue(1), TermValue(2)), allocation="made-here")
    xs = arrived(made, "read-xs")
    ys = arrived(made, "read-ys")
    # Two new lists, each computed from contents its operand may no longer
    # hold: equal contents, two objects.
    left = xs.add(made, "add-site", None).completed_value()
    right = ys.add(made, "add-site", None).completed_value()
    assert left == right
    assert not contents_current(left) and not contents_current(right)
    # Each is named by its derivation, never by ``""``.
    assert left.arrival and right.arrival and left.arrival != right.arrival
    assert "read-xs" in left.arrival and "add-site" in left.arrival
    # One ``match`` site reads each: two objects, two terms.
    left_reads = _stale_length_reads(left)
    right_reads = _stale_length_reads(right)
    assert left_reads and right_reads
    assert not left_reads & right_reads


def test_one_object_read_twice_at_one_match_is_one_object():
    from sugar_lift_py_tests.floor.object_identity import arrived, identity_term

    _made, stale = _made_and_arrived()
    computed = stale.add(stale, "add-site", None).completed_value()
    for value in (stale, computed):
        # The same arrival at the same read: the same object component.
        assert _stale_length_reads(value) == _stale_length_reads(value)
        term = identity_term(value, "match-site", "receiver", owner="t")
        assert term == identity_term(value, "match-site", "receiver", owner="t")
        # Reached again by a later binding read, it is still that object.
        again = arrived(value, "later-read")
        assert again.arrival == value.arrival
        assert _stale_length_reads(again) == _stale_length_reads(value)


def test_a_stale_object_nothing_names_refuses_by_name():
    from sugar_lift_py_tests.floor.object_identity import (
        arrived,
        identity_term,
        made_from,
    )
    from sugar_source_tree.panic import SugarNotWritten

    made = ListValue((TermValue(1),), allocation="made-here")
    # A read whose site names no coordinate names no arrival.
    unnamed = arrived(made, None)
    assert unnamed.arrival is None
    with pytest.raises(SugarNotWritten):
        identity_term(unnamed, "len-site", "receiver", owner="t")
    # Nor does a derivation from it, or one at a site with no coordinate.
    assert made_from("+", "add-site", unnamed)["arrival"] is None
    named = arrived(made, "binding-read")
    assert made_from("+", None, named) == {"allocation": None, "arrival": None}
    derived = made_from("+", "add-site", named, made)
    assert derived == {"allocation": None, "arrival": "+(binding-read)@add-site"}
    # Current operands make a current object, named by its allocation.
    assert made_from("+", "add-site", made) == {
        "allocation": "add-site",
        "arrival": None,
    }


def test_two_bindings_released_at_one_yield_are_two_objects():
    from dataclasses import dataclass

    from sugar_lift_py_tests.generator_construction import (
        GeneratorAssignBindingV1,
        _released_at_yield,
    )

    @dataclass(frozen=True)
    class _Frame:
        binding_state: tuple

    made = ListValue((TermValue(1),), allocation="made-here")
    frame = _Frame(
        (
            GeneratorAssignBindingV1("xs", made, "fragment-xs"),
            GeneratorAssignBindingV1("ys", made, "fragment-ys"),
        )
    )
    first, second = _released_at_yield(frame, "yield-at").binding_state
    assert first.value.arrival == "yield-at/0"
    assert second.value.arrival == "yield-at/1"


def test_a_path_store_through_a_stale_root_finds_no_position():
    from sugar_lift_py_tests.floor import DictValue
    from sugar_lift_py_tests.floor.object_identity import arrived
    from sugar_lift_py_tests.sugar.builtin_container_call_sugar import _replace_path

    inner = ListValue((TermValue(1),), allocation="inner")
    root = DictValue(((StringValue("k"), inner),), allocation="root")
    post = ListValue((TermValue(1), TermValue(2)), allocation="inner")
    steps = (("item", "k"),)
    # A current root: the member at the path is replaced by the post-state.
    updated = _replace_path(root, steps, post, False)
    assert updated == DictValue(((StringValue("k"), post),), allocation="root")
    assert updated.allocation == "root"
    # A stale root: the key's place is not read from contents it may no
    # longer hold -- the root after the call is the opaque post-state.
    assert _replace_path(arrived(root, "root-read"), steps, post, False) is None
    # Nor a stale container further down the path.
    nested = DictValue(
        ((StringValue("r"), arrived(root, "root-read")),), allocation="outer"
    )
    assert _replace_path(nested, (("item", "r"), ("item", "k")), post, False) is None


def test_a_helper_storing_through_the_dict_it_arrived_with_never_reads_it(
    tmp_path,
):
    # ``d`` reaches ``g`` by binding: ``d["k"].append(2)`` locates nothing in
    # the contents the caller built, so ``d`` after it is not those contents
    # with the member replaced.
    source = (
        "def g(d):\n"
        + '    d["k"].append(2)\n'
        + "    return d\n"
        + "def f():\n"
        + '    return g({"k": [1]})\n'
    )
    from sugar_lift_py_tests.floor import DictValue

    returns, _halts = _returns(tmp_path, source)
    assert not any(type(value) is DictValue for value in returns)


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
    (held,) = _released_at_yield(frame, "yield-at").binding_state
    assert held.name == "xs" and held.evaluation == "walrus-key"
    assert held.bind.assigned_value == made
    assert not contents_current(held.bind.assigned_value)
    assert not contents_current(held.bind.presented_value)
    # Released at the yield, each is named by the yield's occurrence and its
    # place in the frame's writes.
    assert held.bind.assigned_value.arrival == "yield-at/0/assigned"
    assert held.bind.presented_value.arrival == "yield-at/0/presented"


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
    assert held.bind.assigned_value == fresh(ListValue, (TermValue(1),))
    assert not contents_current(held.bind.assigned_value)


# No default ``allocation`` (#7757, after #8117): a default that said
# "current" was a guess.  Every construction names it.


@pytest.mark.parametrize("kind", ["ListValue", "DictValue", "SetValue"])
def test_a_container_built_without_an_allocation_is_refused(kind):
    from sugar_lift_py_tests import floor

    with pytest.raises(TypeError):
        getattr(floor, kind)(())


def test_a_site_that_names_no_coordinate_makes_no_current_object():
    from sugar_lift_py_tests.floor import object_identity

    assert not hasattr(object_identity, "UNNAMED_CONSTRUCTION")
    assert object_identity.made_at(None) is None
    assert object_identity.made_from("+", None) == {
        "allocation": None,
        "arrival": None,
    }
    assert object_identity.made_at("add-site") == "add-site"


def test_the_doors_post_state_names_its_receivers_allocation():
    from sugar_lift_py_tests.floor import builtin_container_method as law

    made, stale = _made_and_arrived()
    for receiver in (made, stale):
        for method, args in (("append", (TermValue(3),)), ("clear", ())):
            pair = law.apply("list", method, receiver, args, "door", None)
            post, _result = pair.completed_value().elements
            assert post.allocation == receiver.allocation
            # The same object: the binding read that names it names it still.
            assert post.arrival == receiver.arrival


def test_a_dict_subclass_instances_dict_state_is_not_current():
    # Whether an instance's ``dict`` base state is its state now is not
    # decided (its currency is not threaded through a source override's
    # post-state): never read as fresh, whatever the instance's own.
    from sugar_lift_py_tests.floor.mapping_object_value import MappingObjectValue
    from sugar_lift_py_tests.floor.object_identity import contents_current

    state = MappingObjectValue.__new__(MappingObjectValue)
    object.__setattr__(state, "entries", ((StringValue("k"), TermValue(1)),))
    assert not contents_current(state._builtin_dict())


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


# An instance of a source class (``ObjectValue``) carries currency by the one
# rule (#7757, residue of #8117/#8137): made in this frame (its class call's
# ``allocation``) or arrived by binding (none).  A field read on one that
# arrived is the undecided attribute read over its identity, never the field
# values recorded where it was built.


def _instance_made_and_arrived():
    from sugar_lift_py_tests.floor.object_field import ObjectField
    from sugar_lift_py_tests.floor.object_identity import arrived
    from sugar_lift_py_tests.floor.object_value import ObjectValue

    inner = ObjectValue("D", (ObjectField("y", TermValue(2)),), allocation="inner")
    made = ObjectValue(
        "C",
        (
            ObjectField("x", TermValue(1)),
            ObjectField("items", ListValue((TermValue(3),), allocation="items")),
            ObjectField("inner", inner),
        ),
        allocation="made-here",
    )
    return made, arrived(made, "binding-read")


@pytest.mark.parametrize("kind", ["ObjectValue", "MappingObjectValue"])
def test_an_instance_built_without_an_allocation_is_refused(kind):
    from sugar_lift_py_tests import floor

    with pytest.raises(TypeError):
        getattr(floor, kind)("C", ())


def test_arrived_takes_the_allocation_off_an_instance_and_all_it_holds():
    from sugar_lift_py_tests.floor.object_identity import (
        contents_current,
        instance_stale,
    )

    made, stale = _instance_made_and_arrived()
    assert contents_current(made) and not instance_stale(made)
    assert not contents_current(stale) and instance_stale(stale)
    assert stale.arrival == "binding-read"
    held = {field.name: field.value for field in stale.fields}
    # Every object reachable through its fields arrived with it, named by
    # the path to it.
    assert not contents_current(held["items"])
    assert held["items"].arrival == "binding-read/.items"
    assert not contents_current(held["inner"])
    assert held["inner"].arrival == "binding-read/.inner"
    # The values are the same; only the currency is gone.
    assert held["x"] == TermValue(1)
    assert stale == made


def test_a_stale_instances_field_read_is_the_undecided_read_never_its_value():
    from dataclasses import replace

    from sugar_lift_py_tests.floor import CallSiteValue

    made, stale = _instance_made_and_arrived()
    assert made.attribute("x", "read-site", None).completed_value() == TermValue(1)
    outcome = stale.attribute("x", "read-site", None)
    completed = _completed_values(outcome)
    assert completed and TermValue(1) not in completed
    assert all(type(value) is CallSiteValue for value in completed)
    # The member names the object, never the fields it was built with.
    for value in completed:
        assert value.term.name == "attr:x"
        assert _object_reads(value.term)
    # Whether the read completes is not decided: it may raise.
    assert outcome.halts()
    # A field it was built with and since deleted is not decided either.
    deleted = made.delattr("x", "del-site", None).completed_value()
    assert deleted.attribute("x", "read-site", None).halts()
    stale_deleted = replace(deleted, allocation=None, arrival="read-b")
    assert _completed_values(stale_deleted.attribute("x", "read-site", None))
    # An instance that names no arrival cannot be told apart: refused.
    from sugar_source_tree.panic import SugarNotWritten

    with pytest.raises(SugarNotWritten):
        replace(stale, arrival=None).attribute("x", "read-site", None)


def test_a_store_keeps_an_instances_currency_and_an_alias_never_gains_it():
    from dataclasses import replace

    from sugar_lift_py_tests.floor.object_identity import (
        as_the_alias_holds,
        contents_current,
    )

    made, stale = _instance_made_and_arrived()
    # The same object after a field store: its allocation is kept.
    assert made.with_field_store("x", TermValue(9)).allocation == "made-here"
    assert not contents_current(stale.with_field_store("x", TermValue(9)))
    # An alias holding the instance as it arrived stays not current after a
    # store through a current one, and keeps its own arrival.
    held = replace(stale, arrival="alias-read")
    rebound = as_the_alias_holds(made.with_field_store("x", TermValue(9)), held)
    assert not contents_current(rebound) and rebound.arrival == "alias-read"
    assert contents_current(
        as_the_alias_holds(made.with_field_store("x", TermValue(9)), made)
    )


def test_a_path_store_through_a_stale_instance_finds_no_field():
    from sugar_lift_py_tests.sugar.builtin_container_call_sugar import _replace_path

    made, stale = _instance_made_and_arrived()
    post = ListValue((TermValue(3), TermValue(4)), allocation="items")
    steps = (("attr", "items"),)
    assert _replace_path(made, steps, post, False) is not None
    assert _replace_path(stale, steps, post, False) is None


_C = "class C:\n    def __init__(self, x):\n        self.x = x\n"


def test_a_helper_never_reads_the_fields_its_object_arrived_with(tmp_path):
    # ``o`` reaches ``g`` by binding: the ``x`` the caller built it with is
    # not ``o.x`` at the read (another alias may have changed it since).
    source = (
        _C
        + "def g(o):\n"
        + "    return o.x\n"
        + "def f():\n"
        + "    return g(C(5))\n"
    )
    returns, _halts = _returns(tmp_path, source)
    assert TermValue(5) not in returns


def test_an_instance_this_frame_built_still_answers_its_field(tmp_path):
    returns, halts = _returns(
        tmp_path, _C + "def f():\n    o = C(5)\n    return o.x\n"
    )
    assert returns == [TermValue(5)]
    assert halts == []


# The residue of #8145: a mapping pattern's ``**rest`` over a stale dict
# walked the entries the dict arrived with (a contents read that bypassed
# ``contents_current``), and a container a builtin handed back from its
# operand had no ``allocation`` and no ``arrival``, so an undecided read of
# it refused.


def test_a_stale_dicts_rest_is_a_new_dict_whose_contents_are_undecided():
    from sugar_lift_py_tests.floor import DictValue
    from sugar_lift_py_tests.floor.object_identity import (
        arrived,
        contents_current,
        identity_term,
    )
    from sugar_lift_py_tests.sugar.false_bool_literal_sugar import (
        FalseBoolLiteralSugar,
    )
    from sugar_lift_py_tests.sugar.match_sugar import _mapping_rest

    made = DictValue(((StringValue("k"), TermValue(1)),), allocation="made-here")
    rests = []
    for read in ("read-a", "read-b"):
        stale = arrived(made, read)
        matched = _mapping_rest(stale, (), "rest", "match-site").completed_value()
        ((_key, rest),) = matched.binds
        # A new dict, holding none of the entries the subject arrived with.
        assert type(rest) is DictValue
        assert rest.entries == ()
        assert not contents_current(rest)
        # Named by its derivation from the subject's arrival.
        assert rest.arrival == f"{{**}}({read})@match-site"
        # No read takes its contents: its truth is not its emptiness.
        truth = rest.truth("truth-site").completed_value()
        assert type(truth) is not FalseBoolLiteralSugar
        rests.append(rest)
    # Two rests of two stale dicts at one match: two objects, two terms.
    first, second = (
        identity_term(rest, "len-site", "receiver", owner="t") for rest in rests
    )
    assert first != second
    # A current subject's rest is still its other entries, current.
    matched = _mapping_rest(made, (), "rest", "match-site").completed_value()
    ((_key, rest),) = matched.binds
    assert rest.entries == made.entries
    assert contents_current(rest)


def test_a_stale_dicts_entries_are_never_walked_for_the_rest():
    # Whether a symbolic key is a pattern key is undecided: walking the
    # entries the dict arrived with would refuse over contents it may no
    # longer hold.  Nothing reads them.
    from sugar_lift_py_tests.floor import DictValue, SymbolicValue
    from sugar_lift_py_tests.floor.object_identity import arrived
    from sugar_lift_py_tests.ir import make_var
    from sugar_lift_py_tests.sugar.match_sugar import _mapping_rest

    stale = arrived(
        DictValue(
            ((SymbolicValue(make_var("k")), TermValue(1)),), allocation="made-here"
        ),
        "dict-read",
    )
    outcome = _mapping_rest(stale, (StringValue("a"),), "rest", "match-site")
    ((_key, rest),) = outcome.completed_value().binds
    assert rest.entries == ()
    assert rest.arrival == "{**}(dict-read)@match-site"


def test_a_builtin_that_returns_its_operand_returns_that_object():
    from sugar_lift_py_tests.floor.object_identity import (
        contents_current,
        identity_term,
        object_identity,
    )
    from sugar_lift_py_tests.source_call_resolution import builtin_ground_fold
    from sugar_lift_py_tests.sugar.true_bool_literal_sugar import (
        TrueBoolLiteralSugar,
    )
    from sugar_source_tree.nodes import LanguageCallee

    xs = ListValue((TermValue(3),), allocation="xs-display")
    ys = ListValue((TermValue(1),), allocation="ys-display")
    # ``max(xs, ys)`` is ``xs``: the same object, so the same value.
    larger = builtin_ground_fold(
        LanguageCallee.BUILTIN_MAX, (xs, ys), "max-site"
    ).completed_value()
    assert larger is xs
    assert contents_current(larger)
    # An undecided read of it names it by its contents, never refuses.
    assert identity_term(larger, "len-site", "receiver", owner="t") == xs.to_term(
        owner="t"
    )
    same = object_identity(larger, xs, "is-site").completed_value()
    assert type(same) is TrueBoolLiteralSugar
    # ``sum([], start)`` is ``start``.
    start = ListValue((TermValue(7),), allocation="start-display")
    empty = ListValue((), allocation="empty-display")
    total = builtin_ground_fold(
        LanguageCallee.BUILTIN_SUM, (empty, start), "sum-site"
    ).completed_value()
    assert total is start
    # A list the builtin made is new here, at the call's site.
    copied = builtin_ground_fold(
        LanguageCallee.BUILTIN_LIST, (xs,), "list-site"
    ).completed_value()
    assert copied is not xs
    assert copied.elements == xs.elements
    assert copied.allocation == "list-site"


def test_a_member_a_method_hands_back_is_that_member():
    from sugar_lift_py_tests.floor import DictValue
    from sugar_lift_py_tests.floor.object_identity import contents_current
    from sugar_lift_py_tests.source_call_resolution import container_method_cited_fold

    inner = ListValue((TermValue(1),), allocation="inner-display")
    receiver = DictValue(((StringValue("k"), inner),), allocation="dict-display")
    got = container_method_cited_fold(
        receiver, "get", (StringValue("k"),), "get-site"
    ).completed_value()
    assert got is inner
    assert contents_current(got)


def test_a_list_max_hands_back_is_current(tmp_path):
    # ``m`` is ``xs``, a list this frame built: its length is read from it.
    returns, halts = _returns(
        tmp_path,
        "def f():\n"
        "    xs = [3]\n"
        "    ys = [1]\n"
        "    m = max(xs, ys)\n"
        "    return len(m)\n",
    )
    assert returns == [TermValue(1)]
    assert halts == []
