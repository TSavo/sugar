from __future__ import annotations

from dataclasses import field as dataclass_field, dataclass

from sugar_lift_py_tests.ir import Formula

from .floor_value import FloorValue


@dataclass(frozen=True)
class PredicateValue(FloorValue):
    """A boolean formula carried as a floor value.

    Atomic formulas project to a same-name constructor term. Connectives
    project recursively to the established ``py.<kind>`` constructor family.
    Quantifiers stay loud because the term algebra has no binder-bearing term
    shape, so projecting one would lose its bound variable or invent a parallel
    vocabulary.
    """

    formula: Formula
    site: object = dataclass_field(default=None, compare=False)
    # CallSiteValues that stood as operands when this formula was emitted --
    # carried so callEdges project from the collapse without a side channel.
    operand_callsites: tuple = dataclass_field(default=(), compare=False)
    derived_formulas: tuple = dataclass_field(default=(), compare=False)
    rewrite_chains: tuple[tuple[str, str, int], ...] = dataclass_field(
        default=(), compare=False
    )
    then_bindings: tuple[tuple[str, FloorValue], ...] = dataclass_field(
        default=(), compare=False
    )
    else_bindings: tuple[tuple[str, FloorValue], ...] = dataclass_field(
        default=(), compare=False
    )

    def denotes_value(self) -> bool:
        """A carried boolean formula denotes a Python ``bool``."""
        return True

    def to_term(self, *, owner: str):
        from sugar_lift_py_tests.ir import _Atomic, _Connective, ctor

        if isinstance(self.formula, _Atomic):
            return ctor(self.formula.name, list(self.formula.args))
        if isinstance(self.formula, _Connective):
            return ctor(
                f"py.{self.formula.kind}",
                [
                    PredicateValue(operand, self.site).to_term(owner=owner)
                    for operand in self.formula.operands
                ],
            )
        return super().to_term(owner=owner)

    def attribute(self, name, site, ctx):
        # A boolean formula is not a field-bearing object; attribute projection
        # stays py.getattr over the predicate term (never invent a field).
        del site, ctx
        from sugar_lift_py_tests.floor.symbolic_value import SymbolicValue
        from sugar_lift_py_tests.ir import ctor, str_const
        from sugar_lift_py_tests.outcome import ExitSet

        return ExitSet.completed(
            SymbolicValue(
                ctor(
                    "py.getattr",
                    [
                        self.to_term(owner="PredicateValue.attribute"),
                        str_const(name),
                    ],
                )
            )
        )

    def setattr(self, name, value, site, ctx):
        del name, value, ctx
        from sugar_lift_py_tests.floor.ground_exit import ground_exceptional_exit

        return ground_exceptional_exit(
            exception_name="AttributeError", site=site, owner="PredicateValue.setattr"
        )

    def delattr(self, name, site, ctx):
        del name, ctx
        from sugar_lift_py_tests.floor.ground_exit import ground_exceptional_exit

        return ground_exceptional_exit(
            exception_name="AttributeError", site=site, owner="PredicateValue.delattr"
        )

    def setitem(self, index, value, site, ctx):
        del index, value, ctx
        from sugar_lift_py_tests.floor.ground_exit import ground_exceptional_exit

        return ground_exceptional_exit(
            exception_name="TypeError", site=site, owner="PredicateValue.setitem"
        )

    def delitem(self, index, site, ctx):
        del index, ctx
        from sugar_lift_py_tests.floor.ground_exit import ground_exceptional_exit

        return ground_exceptional_exit(
            exception_name="TypeError", site=site, owner="PredicateValue.delitem"
        )

    def guarded(self, formula):
        """A carried boolean rides under a guard unchanged.

        Same arm as ``CallSiteValue``: this is a VALUE,
        not an exit and not an obligation. A PredicateValue states no
        ``inv_contribution`` and no ``post_contribution``, so a branch guard
        over it is already owned by the branch's own control -- there is
        nothing here for the guard to weaken.

        Weakening the carried formula to ``formula -> self.formula`` would be a
        different value, not a guarded one: for `x = (a == b) if c else d` it
        would make `x` TRUE wherever `c` is false, which the source never
        states. An assertion over this predicate is an ``InvValue``, and THAT
        is the arm that becomes an implication (``InvValue.guarded``); the
        obligation is weakened where the obligation lives, never here.
        """
        del formula
        return self

    def negate(self):
        # A predicate flips by wrapping its formula in not_ -- the formula owns
        # the polarity, the carrier stays PredicateValue; operand callsites ride.
        from sugar_lift_py_tests.ir import not_
        from sugar_lift_py_tests.outcome import ExitSet

        return ExitSet.completed(
            PredicateValue(
                not_(self.formula),
                self.site,
                self.operand_callsites,
                self.derived_formulas,
                self.rewrite_chains,
                self.else_bindings,
                self.then_bindings,
            )
        )

    def unary_minus(self, site):
        # pandas defines unary minus on boolean array predicates as logical
        # negation, the same closed construction as bitwise invert.
        del site
        return self.negate()

    def truth(self, site):
        """An already-boolean predicate stands as its existing formula."""
        del site
        from sugar_lift_py_tests.outcome import ExitSet

        return ExitSet.completed(self)

    def subscript(self, index, site):
        """Keep unknown scalar-versus-array predicate results visibly red.

        ``PredicateValue`` carries a formula, not enough Python type/shape
        evidence to decide whether indexing yields an element or raises.  The
        runtime effect is authenticated by the receiver formula and source
        site, so presence cannot masquerade as a verified result.
        """
        from sugar_lift_py_tests.effect import (
            SubscriptResultRuntimeEffect,
            runtime_effect_evidence,
        )
        from sugar_lift_py_tests.outcome import ExitSet

        return ExitSet.halted(
            SubscriptResultRuntimeEffect(
                "predicate subscript runtime boundary: PredicateValue runtime "
                "result shape may be a scalar boolean or an indexable array; "
                "keep as typed red until the producing operation carries "
                f"container shape evidence. site={site}",
                **runtime_effect_evidence("py.subscript", self, site),
            )
        )

    def bitwise_or(self, other, site, ctx):
        from sugar_lift_py_tests.floor.symbolic_value import SymbolicValue

        if type(other) is SymbolicValue:
            return SymbolicValue(self.to_term(owner=str(site))).bitwise_or(
                other, site, ctx
            )
        if type(other) is not PredicateValue:
            return super().bitwise_or(other, site, ctx)
        del site
        from sugar_lift_py_tests.ir import or_
        from sugar_lift_py_tests.outcome import ExitSet

        return ExitSet.completed(PredicateValue(or_([self.formula, other.formula])))

    def bitwise_and(self, other, site, ctx):
        from sugar_lift_py_tests.floor.symbolic_value import SymbolicValue

        if type(other) is SymbolicValue:
            return SymbolicValue(self.to_term(owner=str(site))).bitwise_and(
                other, site, ctx
            )
        if type(other) is not PredicateValue:
            return super().bitwise_and(other, site, ctx)
        from sugar_lift_py_tests.ir import and_
        from sugar_lift_py_tests.outcome import ExitSet

        return ExitSet.completed(
            PredicateValue(
                and_([self.formula, other.formula]),
                site,
                (*self.operand_callsites, *other.operand_callsites),
                (*self.derived_formulas, *other.derived_formulas),
                (*self.rewrite_chains, *other.rewrite_chains),
            )
        )

    def bitwise_xor(self, other, site, ctx):
        if type(other) is not PredicateValue:
            return super().bitwise_xor(other, site, ctx)
        from sugar_lift_py_tests.ir import and_, not_, or_
        from sugar_lift_py_tests.outcome import ExitSet

        return ExitSet.completed(
            PredicateValue(
                or_(
                    [
                        and_([self.formula, not_(other.formula)]),
                        and_([not_(self.formula), other.formula]),
                    ]
                ),
                site,
                (*self.operand_callsites, *other.operand_callsites),
                (*self.derived_formulas, *other.derived_formulas),
                (*self.rewrite_chains, *other.rewrite_chains),
            )
        )

    def bitwise_invert(self, site):
        """Boolean bitwise invert is the standing predicate's negation."""
        del site
        return self.negate()

    def stated(self, site):
        # A symbolic predicate states an inv: the fact the record emits. Operand
        # callsites ride into the InvValue so edges project later. then_bindings
        # become definite under the asserted fact (assert x in domain → x is
        # one of the domain faces for the continuing tail).
        from sugar_lift_py_tests.floor.inv_value import InvValue
        from sugar_lift_py_tests.outcome import ExitSet

        return ExitSet.completed(
            InvValue(
                self.formula,
                site,
                self.operand_callsites,
                self.derived_formulas,
                self.rewrite_chains,
                self.then_bindings,
            )
        )
