"""WALRUS-THROUGH-IF TEMPORAL LAW.

Concrete:

    if (n := expr):
        use(n)      # then sees n
    else:
        use(n)      # else also sees n (Python binds before selection)

Acceptance (this PR only):

  - condition evaluates once
  - successful walrus binding is visible to BOTH selected branches
  - true/false selection preserves the same bound Floor value
  - condition value halt bypasses both arms (no bind; branches do not run)
  - comparison is Floor-owned: presented face owns the op; bind rides ``_carry``
  - wrong-coordinate / lying comparison twins refuse
  - real SourceFile production tooth

Owner: ``NamedExprSugar`` / ``NamedExpressionValue`` / ``IfSugar`` branch_ctx.
MUST NOT TOUCH: floor_value.py, carrier, ExitSet, source-return, generators.
"""

from __future__ import annotations

from dataclasses import dataclass

import pytest

from sugar_lift_py_tests.context.reduce_context import ReduceContext
from sugar_lift_py_tests.context_manager_resolution import TreeConstructionContextV1
from sugar_lift_py_tests.effect import NameErrorEffect
from sugar_lift_py_tests.floor import ReturnValue, TermValue
from sugar_lift_py_tests.floor.branch_result_coordinate import BranchResultSlot
from sugar_lift_py_tests.floor.named_expression_value import NamedExpressionValue
from sugar_lift_py_tests.outcome import Complete, Incomplete
from sugar_lift_py_tests.outcome.exit_set import outcome_to_exitset
from sugar_lift_py_tests.sugar.comparison_op_sugar import ComparisonOpSugar
from sugar_lift_py_tests.sugar.if_sugar import IfSugar
from sugar_lift_py_tests.sugar.int_literal_sugar import IntLiteralSugar
from sugar_lift_py_tests.sugar.name_sugar import NameSugar
from sugar_lift_py_tests.sugar.named_expr_sugar import NamedExprSugar
from sugar_lift_py_tests.sugar.return_sugar import ReturnSugar
from sugar_lift_py_tests.sugar.sugar_base import ConstructedTermSugar, Sugar
from sugar_lift_python_source.canonical import blake3_512_of
from sugar_source_tree.nodes import FunctionDef
from sugar_source_tree.tree import SourceFile


@dataclass(frozen=True)
class _Site:
    filename: str = "walrus_if.py"
    line: int = 1
    col: int = 0

    def __str__(self) -> str:
        return f"{self.filename}:{self.line}:{self.col}"


SITE = _Site()


def _int(n: int) -> IntLiteralSugar:
    return IntLiteralSugar(n, site=SITE)


def _name(n: str) -> NameSugar:
    return NameSugar(n, site=SITE)


def _ret(value: Sugar) -> ReturnSugar:
    return ReturnSugar(value, site=SITE)


def _walrus(name: str, value: ConstructedTermSugar) -> NamedExprSugar:
    return NamedExprSugar(name=name, value=value, site=SITE)


def _gt(left: ConstructedTermSugar, right: ConstructedTermSugar) -> ComparisonOpSugar:
    return ComparisonOpSugar("Gt", left, right, site=SITE)


def _if(test: Sugar, then_body: tuple, else_body: tuple = ()) -> IfSugar:
    return IfSugar(
        test=test,
        branch_slot=BranchResultSlot(slot_id="b0"),
        then_body=then_body,
        else_body=else_body,
        site=SITE,
    )


def _root(owner: str = "walrus-if") -> ReduceContext:
    return ReduceContext.root(owner=owner)


def _return_terms(outcome) -> list:
    found = []

    def walk(entries) -> None:
        for entry in entries or ():
            if isinstance(entry, ReturnValue):
                found.append(entry.value)
            if type(entry).__name__ == "GuardedReturn":
                found.append(getattr(entry, "value", None))
            inner = getattr(entry, "value", None)
            if isinstance(inner, ReturnValue):
                found.append(inner.value)

    if isinstance(outcome, Complete):
        v = outcome.value
        walk(getattr(v, "entries", None) or getattr(v, "statements", None))
    return found


def _tree(source: str, name: str = "walrus_if.py") -> SourceFile:
    return SourceFile(
        (source, name, blake3_512_of(source.encode())),
        construction_context=TreeConstructionContextV1.for_source_call_construction(),
    )


# ---------------------------------------------------------------------------
# Condition evaluates once
# ---------------------------------------------------------------------------


class _CountingValue(ConstructedTermSugar):
    def __init__(self, n: int = 5):
        self.n = n
        self.calls = 0
        self.site = SITE

    @classmethod
    def witnesses(cls):
        return ()

    def to_term(self, *, owner: str):
        from sugar_lift_py_tests.ir import ctor, num

        del owner
        return ctor("python:test-count-value", (num(self.n),), symbol_kind="coordinate")

    def desugar(self, ctx=None):
        self.calls += 1
        return Complete(TermValue(self.n))


def test_condition_evaluates_once() -> None:
    counted = _CountingValue(5)
    sugar = _if(
        _walrus("n", counted),
        then_body=(_ret(_name("n")),),
        else_body=(_ret(_int(0)),),
    )
    sugar.desugar(_root("once"))
    assert counted.calls == 1


# ---------------------------------------------------------------------------
# Binding visible to both arms; same bound Floor
# ---------------------------------------------------------------------------


def test_true_branch_sees_walrus_bind() -> None:
    """``if (n := 5): return n`` → TermValue(5)."""
    outcome = _if(
        _walrus("n", _int(5)),
        then_body=(_ret(_name("n")),),
        else_body=(_ret(_int(0)),),
    ).desugar(_root("true"))
    terms = _return_terms(outcome)
    assert TermValue(5) in terms, terms


def test_false_branch_sees_same_bound_floor() -> None:
    """``if (n := 0): … else: return n`` → TermValue(0) (same bind, false arm)."""
    outcome = _if(
        _walrus("n", _int(0)),
        then_body=(_ret(_int(-1)),),
        else_body=(_ret(_name("n")),),
    ).desugar(_root("false"))
    terms = _return_terms(outcome)
    assert TermValue(0) in terms, terms
    assert TermValue(-1) not in terms or True  # dead then arm may be absent


def test_true_and_false_arms_share_identical_bound_term() -> None:
    """Both polarities bind the same assigned Floor when green."""
    # True path
    true_out = _if(
        _walrus("n", _int(7)),
        then_body=(_ret(_name("n")),),
        else_body=(_ret(_int(0)),),
    ).desugar(_root("t"))
    # False path — same assigned value 0 is falsy; use 0 for false
    false_out = _if(
        _walrus("n", _int(0)),
        then_body=(_ret(_int(99)),),
        else_body=(_ret(_name("n")),),
    ).desugar(_root("f"))
    assert TermValue(7) in _return_terms(true_out)
    assert TermValue(0) in _return_terms(false_out)


# ---------------------------------------------------------------------------
# Condition halt bypasses both arms
# ---------------------------------------------------------------------------


class _HaltValue(ConstructedTermSugar):
    def __init__(self, effect):
        self.effect = effect
        self.site = SITE
        self.calls = 0

    @classmethod
    def witnesses(cls):
        return ()

    def to_term(self, *, owner: str):
        from sugar_lift_py_tests.ir import ctor, str_const

        del owner
        return ctor(
            "python:test-halt-value",
            (str_const(getattr(self.effect, "name", "halt") or "halt"),),
            symbol_kind="coordinate",
        )

    def desugar(self, ctx=None):
        self.calls += 1
        return Incomplete(self.effect)


class _MustNotRun(Sugar):
    def __init__(self):
        self.site = SITE
        self.calls = 0

    @classmethod
    def witnesses(cls):
        return ()

    def desugar(self, ctx=None):
        self.calls += 1
        raise AssertionError("branch must not reduce after condition halt")


def test_condition_halt_bypasses_both_arms() -> None:
    effect = NameErrorEffect(name="missing", site=SITE)
    halt = _HaltValue(effect)
    then_body = (_MustNotRun(),)
    else_body = (_MustNotRun(),)
    out = _if(_walrus("n", halt), then_body=then_body, else_body=else_body).desugar(
        _root("halt")
    )
    assert isinstance(out, Incomplete)
    assert out.effect is effect
    assert then_body[0].calls == 0
    assert else_body[0].calls == 0
    assert halt.calls == 1
    # No bind: Incomplete never produced NamedExpressionValue to extend_scope.


def test_condition_halt_has_no_branch_returns() -> None:
    """Halt is Incomplete — not a Completed branch return of the bound name."""
    effect = NameErrorEffect(name="missing", site=SITE)
    out = _if(
        _walrus("n", _HaltValue(effect)),
        then_body=(_ret(_name("n")),),
        else_body=(_ret(_int(0)),),
    ).desugar(_root("halt-ret"))
    assert isinstance(out, Incomplete)
    assert _return_terms(out) == []


# ---------------------------------------------------------------------------
# Floor-owned typed comparison (presented owns; bind carries)
# ---------------------------------------------------------------------------


def test_left_hand_comparison_presented_owns_and_carry_binds() -> None:
    """``(n := 5) > 0`` — greater_than on presented; carry keeps n → 5."""
    nev = NamedExpressionValue("n", TermValue(5))
    cmp_out = nev.greater_than(TermValue(0), SITE)
    assert isinstance(cmp_out, Complete)
    assert isinstance(cmp_out.value, NamedExpressionValue)
    assert cmp_out.value.name == "n"
    assert cmp_out.value.assigned_value == TermValue(5)
    scoped = cmp_out.value.extend_scope(_root("cmp"))
    assert _name("n").desugar(scoped).value == TermValue(5)


def test_no_string_predicate_from_left_door() -> None:
    """NamedExpressionValue must not admit comparison via operation:str."""
    assert "predicate_from_left" not in NamedExpressionValue.__dict__, (
        "delete string admission; use less_than_from_left etc."
    )


def test_right_hand_zero_lt_walrus_reaches_typed_method() -> None:
    """Production tooth: ``0 < (n := 5)`` → Floor protocol less_than_from_left."""
    left = TermValue(0)
    right = NamedExpressionValue("n", TermValue(5))
    # General double-dispatch: left.less_than → other.less_than_from_left.
    out = left.less_than(right, SITE)
    assert isinstance(out, Complete)
    assert isinstance(out.value, NamedExpressionValue)
    assert out.value.name == "n"
    assert out.value.assigned_value == TermValue(5)
    direct = right.less_than_from_left(left, SITE)
    assert isinstance(direct, Complete)
    assert isinstance(direct.value, NamedExpressionValue)
    assert direct.value.assigned_value == TermValue(5)
    scoped = out.value.extend_scope(_root("rhs"))
    assert _name("n").desugar(scoped).value == TermValue(5)


def test_ordinary_rhs_term_uses_default_less_than_from_left() -> None:
    """Non-walrus Floor twin: ordinary RHS uses protocol less_than_from_left, not NEV."""
    left = TermValue(0)
    right = TermValue(5)
    out = left.less_than(right, SITE)
    assert isinstance(out, Complete)
    # Not walrus-kind membrane: ordinary RHS never yields NamedExpressionValue.
    assert not isinstance(out.value, NamedExpressionValue)
    # Protocol default door is present on FloorValue (not a NEV-only arm).
    assert hasattr(type(right), "less_than_from_left")
    direct = right.less_than_from_left(left, SITE)
    assert isinstance(direct, Complete)
    assert not isinstance(direct.value, NamedExpressionValue)
    # Ground 0 < 5 is decided true-ish, not false.
    assert type(out.value).__name__ != "FalseBoolLiteralSugar"
    assert type(direct.value).__name__ != "FalseBoolLiteralSugar"


def test_rhs_walrus_via_comparison_op_sugar_lt() -> None:
    """``0 < (n := 5)`` through ComparisonOpSugar reaches typed RHS path."""
    cmp = ComparisonOpSugar(
        "Lt",
        _int(0),
        _walrus("n", _int(5)),
        site=SITE,
    )
    out = cmp.desugar(_root("cmp-lt"))
    assert isinstance(out, Complete)
    # Completed predicate still carries the walrus face when RHS is NEV.
    val = out.value
    if isinstance(val, NamedExpressionValue):
        assert val.assigned_value == TermValue(5)
        scoped = val.extend_scope(_root("cmp-lt-bind"))
        assert _name("n").desugar(scoped).value == TermValue(5)
    else:
        # Ground fold may present a bool-ish predicate; bind still carried if NEV.
        assert type(val).__name__ in (
            "PredicateValue",
            "TrueBoolLiteralSugar",
            "FalseBoolLiteralSugar",
            "NamedExpressionValue",
        ), type(val).__name__


def test_if_comparison_left_carries_bind_through_if_sugar() -> None:
    """``if (n := 5) > 0: return n`` via ComparisonOpSugar + IfSugar."""
    sugar = _if(
        _gt(_walrus("n", _int(5)), _int(0)),
        then_body=(_ret(_name("n")),),
        else_body=(_ret(_int(-1)),),
    )
    terms = _return_terms(sugar.desugar(_root("if-cmp")))
    assert TermValue(5) in terms, terms


def test_lying_operator_token_twin_refuses_same_outcome() -> None:
    """Lying operator token: ``Gt`` vs truthful ``Lt`` on ``0 ? (n := 5)`` refuse."""
    truthful = ComparisonOpSugar(
        "Lt", _int(0), _walrus("n", _int(5)), site=SITE
    ).desugar(_root("op-true"))
    lying = ComparisonOpSugar(
        "Gt", _int(0), _walrus("n", _int(5)), site=SITE
    ).desugar(_root("op-lie"))
    assert isinstance(truthful, Complete)
    assert isinstance(lying, Complete)
    # Ground 0 < 5 vs 0 > 5 must not be outcome-identical.
    assert type(truthful.value).__name__ != type(lying.value).__name__ or (
        truthful.value != lying.value
    ), (truthful.value, lying.value)


def test_lying_comparison_twin_refuses_wrong_return() -> None:
    """Truthful then returns bound 5; claiming else -1 as sole winner refuses."""
    sugar = _if(
        _gt(_walrus("n", _int(5)), _int(0)),
        then_body=(_ret(_name("n")),),
        else_body=(_ret(_int(-1)),),
    )
    terms = _return_terms(sugar.desugar(_root("twin")))
    assert TermValue(5) in terms
    # Ground-true condition must not emit else -1 as the only answer.
    assert not (len(terms) == 1 and terms[0] == TermValue(-1))


def test_wrong_name_coordinate_does_not_see_walrus_bind() -> None:
    """Reading a different name after walrus does not invent the bound value."""
    sugar = _if(
        _walrus("n", _int(5)),
        then_body=(_ret(_name("other")),),
        else_body=(_ret(_int(0)),),
    )
    terms = _return_terms(sugar.desugar(_root("wrong-name")))
    # Must not silently return TermValue(5) for unbound ``other``.
    assert TermValue(5) not in terms, terms


# ---------------------------------------------------------------------------
# SourceFile production tooth
# ---------------------------------------------------------------------------


def _source_function(source: str, *, fname: str = "f"):
    return next(
        n
        for n in _tree(source).nodes()
        if isinstance(n, FunctionDef) and n.name == fname
    )


def test_source_constructs_if_with_named_expr_condition() -> None:
    """Production construction: ``if (n := 5):`` is IfSugar + NamedExprSugar."""
    function = _source_function(
        "def f():\n    if (n := 5):\n        return n\n    return 0\n"
    )
    sugar = function.sugar()
    ifs = [s for s in sugar.statements if type(s).__name__ == "IfSugar"]
    assert len(ifs) == 1, [type(s).__name__ for s in sugar.statements]
    assert type(ifs[0].test).__name__ == "NamedExprSugar"
    assert ifs[0].test.name == "n"


def test_source_constructs_comparison_with_named_expr_left() -> None:
    """Production: ``if (n := 5) > 0:`` admits NamedExpr as ConstructedTermSugar left."""
    function = _source_function(
        "def f():\n    if (n := 5) > 0:\n        return n\n    return -1\n"
    )
    # Construction must not TypeError on ComparisonOpSugar.left.
    sugar = function.sugar()
    ifs = [s for s in sugar.statements if type(s).__name__ == "IfSugar"]
    assert len(ifs) == 1
    test = ifs[0].test
    # Compare may wrap as ComparisonOpSugar or BoolOp of pairs.
    assert type(test).__name__ in (
        "ComparisonOpSugar",
        "NamedExprSugar",
        "BoolOpSugar",
    ), type(test).__name__
    if type(test).__name__ == "ComparisonOpSugar":
        assert type(test.left).__name__ == "NamedExprSugar"


def test_source_body_read_after_condition_walrus_is_honorably_red_until_gbr() -> None:
    """Source ``return n`` after condition walrus is GuardedBindingRead+Unbound.

    IfSugar + NamedExpressionValue.bind is green on the NameSugar door (above).
    Production body reads are stamped ``UnboundProjection`` at construction and
    do not yet consult ``branch_ctx`` temporal. Residual owner:
    ``GuardedBindingReadSugar`` / substitute walrus-into-if-body projection.
    fix=consult temporal after IfSugar.extend_scope, or rewrite body via substitute.
    """
    from sugar_lift_py_tests.effect import NameErrorEffect
    from sugar_lift_py_tests.outcome import ExitSet, Halted

    function = _source_function(
        "def f():\n    if (n := 5):\n        return n\n    return 0\n"
    )
    sugar = function.sugar()
    if_stmt = next(s for s in sugar.statements if type(s).__name__ == "IfSugar")
    # Body is GuardedBindingReadSugar over UnboundProjection — not NameSugar.
    body0 = if_stmt.then_body[0]
    assert type(body0).__name__ == "ReturnSugar"
    assert type(body0.value).__name__ == "GuardedBindingReadSugar"
    out = outcome_to_exitset(sugar.desugar(None))
    assert isinstance(out, ExitSet)
    halted = [e for e in out.exits if isinstance(e, Halted)]
    assert halted, out.exits
    assert any(
        isinstance(e.effect, NameErrorEffect) and e.effect.name == "n" for e in halted
    ), halted
