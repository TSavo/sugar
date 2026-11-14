"""re.search/match/fullmatch: the cited fold is the call's one answerer (#7757).

Ground operands: the pinned interpreter's own ``re`` through ``_host_applied``
(a truthy ReMatchValue, None, or a builtin raise's one halt).  A ground ``str``
pattern over a subject known only to be a ``str``: the two faces of
``py.re_<name>(pattern, subject)``, owing nothing.  Anything else: the one
two-faced unanswered call, owing one debt.  Never a panic.
"""

from __future__ import annotations

from sugar_lift_py_tests.floor import BuiltinSemanticCallable
from sugar_lift_py_tests.floor.none_value import NoneValue
from sugar_lift_py_tests.floor.re_match_value import ReMatchValue
from sugar_lift_py_tests.floor.string_value import StringValue
from sugar_lift_py_tests.floor.symbolic_value import SymbolicValue
from sugar_lift_py_tests.floor.term_value import TermValue
from sugar_lift_py_tests.ir import make_var
from sugar_lift_py_tests.outcome.exit_set import Completed


class _Op:
    def __init__(self, args, site="re.py:1", keyword_names=()):
        self.arguments = tuple(args)
        self.keyword_names = tuple(keyword_names)
        self.site = site


def _operand(value):
    return StringValue(value) if isinstance(value, str) else value


def _apply(op_name, pattern, subject, keyword_names=()):
    callee = BuiltinSemanticCallable(operation=op_name)
    return callee.callable_application_with(
        _Op([_operand(pattern), _operand(subject)], keyword_names=keyword_names),
        None,
    )


def _str_typed_subject():
    """``type(x).__name__``: a value known only to be a ``str``."""
    name = SymbolicValue(make_var("exc_type")).attribute("__name__", "name-attr", None)
    subject = name.completed_value()
    assert subject.names_a_string()
    return subject


def _completed(outcome):
    return [exit_ for exit_ in outcome.exits if isinstance(exit_, Completed)]


def _is_unanswered(outcome, callee):
    owed = outcome.owed_items()
    halts = outcome.halts()
    return (
        len(owed) == 1
        and len(halts) == 1
        and halts[0].effect.producer_node_owner == f"UnknownCallee:{callee}"
        and len(_completed(outcome)) == 1
    )


# -- ground pattern, ground subject: the cited fold --------------------------


def test_search_truthful_and_lying() -> None:
    msg = "A value is being set on a copy of a DataFrame"
    hit = _apply("python.re.search", "A value is being set", msg)
    assert isinstance(hit.completed_value(), ReMatchValue)
    from sugar_lift_py_tests.sugar.true_bool_literal_sugar import TrueBoolLiteralSugar

    truth = hit.completed_value().truth(site="s")
    assert isinstance(truth.completed_value(), TrueBoolLiteralSugar)
    miss = _apply("python.re.search", "NOT the message", msg)
    assert isinstance(miss.completed_value(), NoneValue)
    assert hit.owed_items() == () and miss.owed_items() == ()


def test_match_is_anchored_at_start() -> None:
    assert isinstance(_apply("python.re.match", "abc", "abcdef").value, ReMatchValue)
    assert isinstance(_apply("python.re.match", "bcd", "abcdef").value, NoneValue)


def test_fullmatch_requires_both_ends() -> None:
    assert isinstance(_apply("python.re.fullmatch", "a.c", "abc").value, ReMatchValue)
    assert isinstance(_apply("python.re.fullmatch", "ab", "abc").value, NoneValue)


def test_groups_are_recoverable() -> None:
    m = _apply("python.re.search", r"(\d+)-(\d+)", "id 12-345").value
    assert m.group_text(0) == "12-345"
    assert m.group_text(1) == "12" and m.group_text(2) == "345"


def test_ground_call_goes_through_the_cited_fold(monkeypatch) -> None:
    import sugar_lift_py_tests.source_call_resolution as resolution

    owners = []
    applied = resolution._host_applied

    def recorder(function, operands, site, **kwargs):
        owners.append(kwargs["owner"])
        return applied(function, operands, site, **kwargs)

    monkeypatch.setattr(resolution, "_host_applied", recorder)
    _apply("python.re.search", "nee", "a needle")
    assert owners == ["cpython_cited_fold:re.search"]


def test_any_pattern_the_interpreter_compiles_is_decided() -> None:
    """No subset gate: a look-ahead is CPython's ``_sre``'s to decide."""
    hit = _apply("python.re.search", "a(?=b)", "xab").completed_value()
    assert isinstance(hit, ReMatchValue) and hit.group_text(0) == "a"
    miss = _apply("python.re.search", "a(?=b)", "xac").completed_value()
    assert isinstance(miss, NoneValue)


def test_a_ground_subject_that_is_not_a_string_is_the_one_halt() -> None:
    outcome = _apply("python.re.search", "a", TermValue(5))
    assert len(outcome.halts()) == 1
    assert _completed(outcome) == []
    assert outcome.owed_items() == ()


def test_a_ground_pattern_that_does_not_compile_is_unanswered() -> None:
    """``re.error`` is no builtin exception: nothing is decided."""
    outcome = _apply("python.re.search", "(unclosed", "text")
    assert _is_unanswered(outcome, "re.search")


# -- ground pattern, subject known only to be a str: the predicate -----------


def test_a_str_subject_completes_on_the_two_faces_of_its_predicate() -> None:
    subject = _str_typed_subject()
    outcome = _apply("python.re.search", "Error$", subject)
    assert outcome.halts() == ()
    assert outcome.owed_items() == ()
    completed = _completed(outcome)
    assert len(completed) == 2
    values = {type(exit_.value) for exit_ in completed}
    assert values == {ReMatchValue, NoneValue}
    for exit_ in completed:
        assert "py.re_search" in str(exit_.guard)
    match = next(e.value for e in completed if type(e.value) is ReMatchValue)
    assert match.span is None
    assert match.to_term(owner="test").name == "python:call_result"


def test_match_and_fullmatch_carry_their_own_predicate() -> None:
    subject = _str_typed_subject()
    for op_name, atom in (
        ("python.re.match", "py.re_match"),
        ("python.re.fullmatch", "py.re_fullmatch"),
    ):
        outcome = _apply(op_name, "Err", subject)
        assert outcome.owed_items() == ()
        assert all(atom in str(exit_.guard) for exit_ in _completed(outcome))


def test_a_str_subject_with_a_pattern_that_does_not_compile_is_unanswered() -> None:
    outcome = _apply("python.re.search", "(unclosed", _str_typed_subject())
    assert _is_unanswered(outcome, "re.search")


# -- anything else: the one unanswered call -----------------------------------


def test_a_subject_of_undecided_type_is_unanswered() -> None:
    outcome = _apply("python.re.search", "abc", SymbolicValue(make_var("s")))
    assert _is_unanswered(outcome, "re.search")


def test_a_symbolic_pattern_is_unanswered() -> None:
    outcome = _apply("python.re.match", SymbolicValue(make_var("p")), "text")
    assert _is_unanswered(outcome, "re.match")


def test_a_keyword_actual_is_unanswered() -> None:
    outcome = _apply("python.re.search", "a", "abc", keyword_names=("string",))
    assert _is_unanswered(outcome, "re.search")
