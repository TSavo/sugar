"""`match` -- sequential, first-case-wins guards.

case i runs when the subject matches P_i AND no earlier case matched, so its
body facts ride under `match_i AND NOT match_<i`. Structural patterns and
guards are built (tests/test_match_structural_patterns.py in
sugar-lift-py-tests).

A value pattern on a formal subject is the undecided equality's two faces
(#7757 NEW-1): its selection is the truth of ``python:compare_result("Eq",
z, <literal>, <key>)``, and a singleton pattern is ``identity(z, <None |
True>)``.  Each test reads the condition a fact or a return rides under --
the antecedent of the implication a joined arm states it as, or the guard of
the arm that holds it -- and asks which selections it holds and which it
holds negated, never the spelling of the arm list.
"""

import tempfile
from pathlib import Path

from sugar_lift_py_tests.lift_rpc import open_source_file_for_construction
from sugar_lift_py_tests.outcome import Completed

_MATCH = (
    "def A(z):\n"
    "    match z:\n"
    "        case 1:\n"
    "            assert z == 10\n"
    "        case 2:\n"
    "            assert z == 20\n"
    "        case _:\n"
    "            assert z == 30\n"
    "    return z\n"
)


def _fn(src):
    # The one construction door, under a workspace (#9054): an ``assert``
    # halts at a ground ``AssertionError`` exit whose locus is
    # workspace-relative, as every lifted file's is.
    root = Path(tempfile.mkdtemp())
    path = root / "m.py"
    path.write_text(src, encoding="utf-8")
    return next(open_source_file_for_construction(path, root=root).functions())


def _completed(src):
    outcome = _fn(src).sugar().desugar()
    return [exit_ for exit_ in outcome.normalize().exits if isinstance(exit_, Completed)]


def _spelled(term):
    return getattr(term, "value", getattr(term, "name", None))


def _selections(formula, negated=False, found=None, depth=0):
    """Every ``(test, literal, negated)`` in ``formula``: a value pattern's
    ``python:compare_result(<op>, z, <literal>, <key>)`` and a singleton's
    ``identity(z, <literal>)``, with whether a ``not`` encloses it."""
    found = set() if found is None else found
    if depth > 64 or formula is None:
        return found
    name = getattr(formula, "name", None)
    args = tuple(getattr(formula, "args", ()) or ())
    if name == "python:compare_result" and len(args) >= 3:
        found.add((_spelled(args[0]), _spelled(args[2]), negated))
    elif name == "identity" and len(args) == 2:
        found.add(("Is", _spelled(args[1]), negated))
    if getattr(formula, "kind", None) == "not":
        negated = not negated
    for child in (*args, *(getattr(formula, "operands", ()) or ())):
        _selections(child, negated, found, depth + 1)
    return found


def _conditions(arm, statement):
    """What ``statement`` (a fact or a post) rides under in ``arm``, and
    what it states: an implication's antecedent and consequent, else the
    arm's own guard and the statement."""
    if getattr(statement, "kind", None) == "implies":
        return statement.operands[0], statement.operands[1]
    return arm.guard, statement


def _mentions(term, literal):
    return any(_spelled(node) == literal for node in _walk(term))


def _walk(term, depth=0):
    if depth > 64 or term is None:
        return
    yield term
    for child in (
        *(getattr(term, "args", ()) or ()),
        *(getattr(term, "operands", ()) or ()),
    ):
        yield from _walk(child, depth + 1)


def _fact_conditions(src, literal):
    """The selections every condition the fact naming ``literal`` rides
    under holds.  At least one condition: the fact is never dropped."""
    conditions = []
    for arm in _completed(src):
        for inv in arm.value.invs():
            condition, fact = _conditions(arm, inv)
            if _mentions(fact, literal):
                conditions.append(_selections(condition))
    assert conditions, f"no fact names {literal!r}"
    return conditions


def test_first_case_guarded_by_its_match():
    for selections in _fact_conditions(_MATCH, 10):
        assert ("Eq", 1, False) in selections, selections
        assert ("Eq", 1, True) not in selections, selections


def test_later_case_excludes_earlier():
    for selections in _fact_conditions(_MATCH, 20):
        assert ("Eq", 1, True) in selections, selections  # not (z == 1)
        assert ("Eq", 2, False) in selections, selections
        assert ("Eq", 2, True) not in selections, selections


def test_wildcard_guarded_by_all_negations():
    for selections in _fact_conditions(_MATCH, 30):
        assert ("Eq", 1, True) in selections, selections
        assert ("Eq", 2, True) in selections, selections


def _returns(src):
    """``(selections, returned term)`` of every completed face's post."""
    found = []
    for arm in _completed(src):
        post = arm.value.post()
        posts = post.operands if getattr(post, "kind", None) == "and" else (post,)
        for face in posts:
            condition, stated = _conditions(arm, face)
            found.append((_selections(condition), stated.args[1]))
    return found


def test_capture_binds_the_subject():
    # case x: binds x = subject (the temporal half, via substitute). So a
    # `case 1: return 10; case x: return x` capture arm is `not(z==1) -> out==z`.
    returns = _returns(
        "def A(z):\n    match z:\n        case 1:\n            return 10\n"
        "        case x:\n            return x\n"
    )
    captured = [selections for selections, term in returns if _spelled(term) == "z"]
    literal = [selections for selections, term in returns if _spelled(term) == 10]
    assert captured and literal, returns
    assert all(("Eq", 1, True) in selections for selections in captured), captured
    assert all(("Eq", 1, False) in selections for selections in literal), literal
    assert all(("Eq", 1, True) not in selections for selections in literal), literal


def test_singleton_pattern_none_and_bool():
    src = (
        "def A(z):\n    match z:\n        case None:\n            assert z == 0\n"
        "        case True:\n            assert z == 1\n"
        "        case _:\n            assert z == 2\n    return z\n"
    )
    # A singleton pattern is an identity test, never an equality.
    for selections in _fact_conditions(src, 0):
        assert ("Is", "None", False) in selections, selections
        assert not any(
            test == "Eq" and literal == "None" for test, literal, _ in selections
        ), selections
    for selections in _fact_conditions(src, 1):
        # excluded by not (z is None), then z is True
        assert ("Is", "None", True) in selections, selections
        assert ("Is", True, False) in selections, selections


def test_or_pattern_disjoins_alternatives():
    src = (
        "def A(z):\n    match z:\n        case 1 | 2 | 3:\n            assert z == 100\n"
        "        case _:\n            assert z == 200\n    return z\n"
    )
    chosen = set().union(*_fact_conditions(src, 100))
    assert {("Eq", n, False) for n in (1, 2, 3)} <= chosen, chosen
    for selections in _fact_conditions(src, 200):
        assert {("Eq", n, True) for n in (1, 2, 3)} <= selections, selections


if __name__ == "__main__":
    test_first_case_guarded_by_its_match()
    test_later_case_excludes_earlier()
    test_wildcard_guarded_by_all_negations()
    test_capture_binds_the_subject()
    test_singleton_pattern_none_and_bool()
    test_or_pattern_disjoins_alternatives()
    print("ok: match patterns -- sequential guarded split; opaque tests undecided")
