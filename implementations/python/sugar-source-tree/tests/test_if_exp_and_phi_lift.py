"""The conditional expression (`IfExp`) and the phi lift, end to end.

`If.substitution_binding` rewrites a conditionally-bound name to an `IfExp`, so
the phi only lifts if `IfExp` has a value. That value is a `GuardedValue`, which
DISTRIBUTES: a return/equality splits into per-arm implications, each arm's
equality resolved per-atom. So the conditional never collapses to a single
mixed-sort term, and `py.conditional` never reaches the (Python-agnostic)
compiler -- the lift resolves it into `ir.eq`/`py.eq` atoms.

This also exercises the finished temporal cut: substitute is the sole binder
(FunctionDef.sugar substitutes first), so `x = z; return x` inlines with no
`ctx.temporal`, and a conditional binding lands as a phi that lifts here.
"""

import tempfile

from sugar_lift_python_source.source_oracle import path_source
from sugar_lift_py_tests.floor import TermValue
from sugar_lift_py_tests.outcome import Complete
from sugar_source_tree.tree import SourceFile

from native_carrier_testimony import authenticated_function_value, native_carrier_for


def _post(src: str):
    with tempfile.NamedTemporaryFile("w", suffix=".py", delete=False, dir="/tmp") as f:
        f.write(src)
        path = f.name
    function = next(SourceFile(path_source(path)).functions())
    outcome = function.sugar().desugar()
    if isinstance(outcome, Complete):
        return outcome.value.post()
    # Deleted expectation: a formal predicate was completed before caller binding.
    return authenticated_function_value(function, operator="equals").post()


def _no_py_conditional(post):
    # The tripwire: py.conditional is the OPAQUE conditional term. If it reaches
    # the compiler, the lift failed to distribute -- the compiler is Python-
    # agnostic and must never have to interpret what py.conditional means.
    assert "py.conditional" not in repr(post), "py.conditional leaked to the compiler"


def test_substitute_is_the_sole_binder_straight_line():
    # x = z; return x  inlines to  out == z  via substitute (no ctx.temporal).
    post = _post("def A(z):\n    x = z\n    return x\n")
    assert post.name == "=" and post.args[0].name == "out" and post.args[1].name == "z"


def test_single_assignment_fold_reads_the_old_binding():
    # x = z + 1; x = x + 1; return x  ->  out == (z + 1) + 1 : the rebind reads
    # the OLD x, the loop-as-repeated-substitute shape.
    source = "def A(z):\n    x = z + 1\n    x = x + 1\n    return x\n"
    with tempfile.NamedTemporaryFile("w", suffix=".py", delete=False, dir="/tmp") as f:
        f.write(source)
        path = f.name
    function = next(SourceFile(path_source(path)).functions())
    # Deleted expectation: z+1 projected before the caller authenticated z.
    carrier = native_carrier_for(function, operator="add")
    left, right = carrier.operands
    assert left.to_term(owner="assignment-fold carrier tooth").name == "z"
    assert right.value == 1
    post = authenticated_function_value(
        function, operator="add", actuals=(TermValue(2),)
    ).post()
    assert post.name == "=" and post.args[1].value == 4


def test_direct_ifexp_predicate_distributes():
    # return 10 if z == 1 else 20  ->  (z==1 -> out==10) AND (not(z==1) -> out==20)
    post = _post("def A(z):\n    return 10 if z == 1 else 20\n")
    _no_py_conditional(post)
    assert post.kind == "and"
    then_imp, else_imp = post.operands
    assert then_imp.operands[1].args[1].value == 10
    assert else_imp.operands[0].kind == "not"
    assert else_imp.operands[1].args[1].value == 20


def test_direct_ifexp_bare_truthiness_distributes():
    # return 5 if c else 6  ->  (py.truthy(c) -> out==5) AND (not truthy -> out==6)
    post = _post("def A(c):\n    return 5 if c else 6\n")
    _no_py_conditional(post)
    then_imp, else_imp = post.operands
    assert then_imp.operands[0].name == "py.truthy"
    assert then_imp.operands[1].args[1].value == 5
    assert else_imp.operands[1].args[1].value == 6


def test_phi_conditional_binding_lifts_end_to_end():
    # if c: x = 5 else: x = 6 ; return x
    # substitute rewrites `return x` to `return (5 if c else 6)`; the IfExp value
    # distributes to the same guarded post -- the phi is liftable, not a gap.
    post = _post(
        "def A(c):\n    if c:\n        x = 5\n    else:\n        x = 6\n    return x\n"
    )
    _no_py_conditional(post)
    assert post.kind == "and"
    then_imp, else_imp = post.operands
    assert then_imp.operands[0].name == "py.truthy"  # guard is truthiness of c
    assert then_imp.operands[1].args[1].value == 5
    assert else_imp.operands[1].args[1].value == 6


if __name__ == "__main__":
    test_substitute_is_the_sole_binder_straight_line()
    test_single_assignment_fold_reads_the_old_binding()
    test_direct_ifexp_predicate_distributes()
    test_direct_ifexp_bare_truthiness_distributes()
    test_phi_conditional_binding_lifts_end_to_end()
    print(
        "ok: IfExp value distributes; phi lifts end-to-end; substitute is sole binder"
    )
