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

from sugar_lift_python_source.source_oracle import path_source
from sugar_source_tree.tree import SourceFile


def _fn(src: str):
    with tempfile.NamedTemporaryFile("w", suffix=".py", delete=False, dir="/tmp") as f:
        f.write(src)
        path = f.name
    return next(SourceFile(path_source(path)).functions())


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
    assert ret.value.body.value == 5  # then arm
    assert ret.value.orelse.value == 6  # else arm


def test_one_armed_if_uses_the_prior_binding_for_the_missing_arm():
    # x = 9 ; if c: x = 5 ; return x  ->  return (5 if c else 9)
    ret = _return_of(
        _fn("def A(c):\n    x = 9\n    if c:\n        x = 5\n    return x\n")
    )
    assert ret.value.kind == "IfExp"
    assert ret.value.body.value == 5  # bound under c
    assert ret.value.orelse.value == 9  # prior binding under not c


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


def _invs(fn):
    uni = fn.sugar().desugar()
    return uni.value.invs()


def test_guarded_assert_is_an_implication():
    # if z == 1: assert z == 1  ->  inv  (z == 1) -> (z == 1)
    invs = _invs(
        _fn("def A(z):\n    if z == 1:\n        assert z == 1\n    return z\n")
    )
    assert len(invs) == 2
    guard = invs[-1]
    assert getattr(guard, "kind", None) == "implies", guard
    # The antecedent is the authenticated branch result and the consequent is
    # the guarded fact.
    ante, cons = guard.operands
    assert ante.name == "py.truthy" and cons.name == "py.eq"


def test_guard_discriminates_condition_from_fact():
    # if z == 1: assert z == 2  ->  (z == 1) -> (z == 2): antecedent is the
    # CONDITION, consequent the FACT, and they are not conflated.
    invs = _invs(
        _fn("def A(z):\n    if z == 1:\n        assert z == 2\n    return z\n")
    )
    ante, cons = invs[-1].operands
    # The antecedent is the authenticated branch-result coordinate; the fact
    # retains its original value.
    assert ante.args[0].name == "python:branch_result"
    assert cons.args[1].value == 2


# ---- Half 2: guarded EXITS (return / raise) ----------------------------------


def test_guarded_return_posts_both_faces():
    # if z == 1: return 10 ; return 20  ->  the exit constraint is
    #   (z == 1 -> out == 10)  AND  (not(z == 1) -> out == 20)
    # The exiting branch posts under the guard; the fall-through tail posts under
    # its negation. No face is dropped.
    uni = (
        _fn("def A(z):\n    if z == 1:\n        return 10\n    return 20\n")
        .sugar()
        .desugar()
    )
    post = uni.value.post()
    assert post.kind == "and"
    then_imp, else_imp = post.operands
    assert then_imp.kind == "implies" and else_imp.kind == "implies"
    # then face: z == 1 -> out == 10
    assert then_imp.operands[0].args[0].name == "python:branch_result"
    assert then_imp.operands[1].args[1].value == 10
    # else face: not(z == 1) -> out == 20
    assert else_imp.operands[0].kind == "not"
    assert else_imp.operands[1].args[1].value == 20


def test_guarded_raise_halts_its_branch_and_guards_the_tail():
    # if z == 1: raise ValueError ; assert z == 2 ; return z
    # The raise halts the z == 1 branch, so the tail rides under its negation:
    # the assert becomes  not(z == 1) -> (z == 2).
    from sugar_lift_py_tests.outcome import Completed, ExitSet, Halted

    out = (
        _fn(
            "def A(z):\n    if z == 1:\n        raise ValueError\n    assert z == 2\n    return z\n"
        )
        .sugar()
        .desugar()
    )
    assert isinstance(out, ExitSet)
    completed = next(e for e in out.exits if isinstance(e, Completed))
    halted = next(e for e in out.exits if isinstance(e, Halted))
    v = completed.value
    invs = v.invs()
    assert len(invs) == 2
    tail = invs[-1]
    assert completed.guard.kind == "not"  # tail edge is guarded by not(z == 1)
    assert tail.args[1].value == 2  # the tail fact z == 2

    # The raise itself is red testimony, pristine RaiseEffect, with the branch
    # condition recorded on the Incomplete wrapper (not smashed into the effect).
    assert type(halted.effect).__name__ == "RaiseEffect"
    assert halted.effect.exception_name == "ValueError"
    assert halted.guard.args[0].name == "python:branch_result"


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
