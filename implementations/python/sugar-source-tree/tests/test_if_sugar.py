"""`if` on the AST tree: the two halves, proven through the node.

An if splits across BOTH verbs:

  * substitute owns the TEMPORAL half -- what a name binds to after the branch is
    the phi `x = <then> if <test> else <else>`, an IfExp rewrite. A name bound in
    only one branch takes its prior binding in the other arm, or stays an honest
    gap when there is none.
  * sugar owns the MEANING half -- the guard. Each branch's stated facts ride
    under the branch polarity, and a guarded fact IS an implication:
    `if c: assert P` emits `c -> P`.

The two never touch each other's failure mode: substitute cannot form an
implication, sugar cannot mis-bind (it does no binding join at all).
"""

import tempfile
from pathlib import Path

from sugar_lift_py_tests.lift_rpc import open_source_file_for_construction


def _fn(src: str):
    # The one construction door, under a workspace: an ``assert`` halts at a
    # ground ``AssertionError`` exit whose locus is workspace-relative, as
    # every lifted file's is (``ground_exit``).
    root = Path(tempfile.mkdtemp())
    path = root / "m.py"
    path.write_text(src, encoding="utf-8")
    return next(open_source_file_for_construction(path, root=root).functions())


def _return_of(fn):
    sub = fn.substitute({})
    return next(n for n in sub.walk() if n.kind == "Return")


# ---- Half 1: the phi (substitute) --------------------------------------------


def test_if_else_assignment_becomes_a_phi():
    # if c: x = 5 else: x = 6 ; return x  ->  return (5 if c else 6)
    ret = _return_of(
        _fn(
            "def A(c):\n    if c:\n        x = 5\n    else:\n        x = 6\n    return x\n"
        )
    )
    assert ret.value.kind == "IfExp"
    assert ret.value.test.kind == "BranchResultRef"
    # Each arm reads its assignment's key: the reference whose ground
    # value is the literal assigned (``EvaluationRef``, ``_ground_value``).
    assert ret.value.body.kind == "EvaluationRef"
    assert ret.value.body.ground_value().value == 5  # then arm
    assert ret.value.orelse.ground_value().value == 6  # else arm


def test_one_armed_if_uses_the_prior_binding_for_the_missing_arm():
    # x = 9 ; if c: x = 5 ; return x  ->  return (5 if c else 9)
    ret = _return_of(
        _fn("def A(c):\n    x = 9\n    if c:\n        x = 5\n    return x\n")
    )
    assert ret.value.kind == "IfExp"
    assert ret.value.body.ground_value().value == 5  # bound under c
    assert ret.value.orelse.ground_value().value == 9  # prior binding under not c


def test_one_armed_if_with_no_prior_is_an_honest_gap_not_a_guess():
    # if c: x = 5 ; return x -- x is bound only under c, with no prior. Rather
    # than invent a value for the not-c arm, x stays unbound: `return x` keeps a
    # free Name (a gap the sugar layer meets loudly), never a wrong phi.
    ret = _return_of(_fn("def A(c):\n    if c:\n        x = 5\n    return x\n"))
    assert ret.value.kind == "GuardedBindingRead" and ret.value.name == "x"


def test_the_phi_borrows_the_if_source_span():
    # The synthesized IfExp is a shadow that still addresses the if's source site
    # (the memento invariant survives rewriting).
    fn = _fn(
        "def A(c):\n    if c:\n        x = 5\n    else:\n        x = 6\n    return x\n"
    )
    if_node = next(n for n in fn.walk() if n.kind == "If")
    phi = _return_of(fn).value
    assert phi.span == if_node.span


# ---- Half 2: the guard (sugar) -----------------------------------------------
#
# A branch guard is ``py.truthy(python:branch_result(<slot>))``
# (``branch_result_coordinate``).  A fact a branch states rides under it: as
# the antecedent of the implication a joined arm states (``InvValue.guarded``)
# or as the guard of the arm that holds it.  Each test reads that condition and
# asks whether it holds the branch guard, and with which polarity.


def _branch_guards(formula, negated=False, found=None, depth=0):
    """Every branch guard in ``formula``, as ``negated`` (a ``not`` encloses
    it) or not."""
    found = [] if found is None else found
    if depth > 64 or formula is None:
        return found
    args = tuple(getattr(formula, "args", ()) or ())
    if (
        getattr(formula, "name", None) == "py.truthy"
        and len(args) == 1
        and getattr(args[0], "name", None) == "python:branch_result"
    ):
        found.append(negated)
    if getattr(formula, "kind", None) == "not":
        negated = not negated
    for child in (*args, *(getattr(formula, "operands", ()) or ())):
        _branch_guards(child, negated, found, depth + 1)
    return found


def _walk(term, depth=0):
    if depth > 64 or term is None:
        return
    yield term
    for child in (
        *(getattr(term, "args", ()) or ()),
        *(getattr(term, "operands", ()) or ()),
    ):
        yield from _walk(child, depth + 1)


def _mentions(term, literal):
    return any(getattr(node, "value", None) == literal for node in _walk(term))


def _conditions(arm, statement):
    """An implication's antecedent and consequent, else the arm's guard and
    the statement."""
    if getattr(statement, "kind", None) == "implies":
        return statement.operands[0], statement.operands[1]
    return arm.guard, statement


def _outcome(src):
    return _fn(src).sugar().desugar()


def _completed(outcome):
    from sugar_lift_py_tests.outcome import Completed

    return [e for e in outcome.normalize().exits if isinstance(e, Completed)]


def _facts(src, literal):
    """``(condition, fact)`` of every fact naming ``literal``; never none."""
    found = []
    for arm in _completed(_outcome(src)):
        for inv in arm.value.invs():
            condition, fact = _conditions(arm, inv)
            if _mentions(fact, literal):
                found.append((condition, fact))
    assert found, f"no fact names {literal!r}"
    return found


def test_guarded_assert_is_an_implication():
    # if z == 1: assert z == 1  ->  (branch guard) -> (z == 1)
    for condition, fact in _facts(
        "def A(z):\n    if z == 1:\n        assert z == 1\n    return z\n", 1
    ):
        # The antecedent is the authenticated branch result, the consequent
        # the guarded fact: never the bare fact.
        assert False in _branch_guards(condition), condition
        assert True not in _branch_guards(condition), condition
        assert _branch_guards(fact) == [], fact


def test_guard_discriminates_condition_from_fact():
    # if z == 1: assert z == 2  ->  (z == 1) -> (z == 2): antecedent is the
    # CONDITION, consequent the FACT, and they are not conflated.
    for condition, fact in _facts(
        "def A(z):\n    if z == 1:\n        assert z == 2\n    return z\n", 2
    ):
        assert False in _branch_guards(condition), condition
        assert True not in _branch_guards(condition), condition
        assert not _mentions(condition, 2), condition


# ---- Half 2: guarded EXITS (return / raise) ----------------------------------


def test_guarded_return_posts_both_faces():
    # if z == 1: return 10 ; return 20  ->  the exiting branch posts under
    # the guard; the fall-through tail posts under its negation. No face is
    # dropped.
    faces = {}
    for arm in _completed(
        _outcome("def A(z):\n    if z == 1:\n        return 10\n    return 20\n")
    ):
        post = arm.value.post()
        posts = post.operands if getattr(post, "kind", None) == "and" else (post,)
        for face in posts:
            condition, stated = _conditions(arm, face)
            faces.setdefault(stated.args[1].value, []).append(
                _branch_guards(condition)
            )
    assert set(faces) == {10, 20}, faces
    assert all(False in g and True not in g for g in faces[10]), faces
    assert all(True in g and False not in g for g in faces[20]), faces


def test_guarded_raise_halts_its_branch_and_guards_the_tail():
    # if z == 1: raise ValueError ; assert z == 2 ; return z
    # The raise halts the z == 1 branch, so the tail rides under its negation:
    # the assert becomes  not(z == 1) -> (z == 2).
    src = (
        "def A(z):\n    if z == 1:\n        raise ValueError\n"
        "    assert z == 2\n    return z\n"
    )
    for condition, _fact in _facts(src, 2):
        assert True in _branch_guards(condition), condition
        assert False not in _branch_guards(condition), condition

    # The raise itself is red testimony, pristine RaiseEffect, with the branch
    # condition recorded on the halted arm's guard (not smashed into the effect).
    raised = [
        halt
        for halt in _outcome(src).halts()
        if getattr(halt.effect, "exception_name", None) == "ValueError"
    ]
    assert len(raised) == 1, raised
    (halted,) = raised
    assert type(halted.effect).__name__ == "RaiseEffect"
    assert False in _branch_guards(halted.guard), halted.guard
    assert True not in _branch_guards(halted.guard), halted.guard


if __name__ == "__main__":
    test_if_else_assignment_becomes_a_phi()
    test_one_armed_if_uses_the_prior_binding_for_the_missing_arm()
    test_one_armed_if_with_no_prior_is_an_honest_gap_not_a_guess()
    test_the_phi_borrows_the_if_source_span()
    test_guarded_assert_is_an_implication()
    test_guard_discriminates_condition_from_fact()
    test_guarded_return_posts_both_faces()
    test_guarded_raise_halts_its_branch_and_guards_the_tail()
    print("ok: if -- phi (substitute) + guard (sugar), both halves through the node")
