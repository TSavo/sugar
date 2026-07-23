from __future__ import annotations

from dataclasses import dataclass, field

from sugar_source_tree.unpack_assignment import (
    Position,
    UnpackNamePattern,
    UnpackSequencePattern,
)

from .floor_value import FloorValue


def unpack_slot_term(slot):
    from sugar_lift_py_tests.ir import ctor, str_const

    return ctor(
        "python:unpack_assignment_ref",
        [str_const(slot.slot_id)],
        symbol_kind="coordinate",
    )


def unpack_pattern_term(pattern):
    from sugar_lift_py_tests.ir import ctor, make_var

    if isinstance(pattern, UnpackNamePattern):
        # Byte-identical to the Python reference. The typed unpack-target FV
        # decoder interprets this Var as a store declaration, never a value read.
        return make_var(pattern.name)
    nested = [unpack_pattern_term(element) for element in pattern.elements]
    return ctor(
        "python:tuple_target" if pattern.kind == "tuple" else "python:list_target",
        nested,
    )


def unpack_targets_term(pattern: UnpackSequencePattern):
    from sugar_lift_py_tests.ir import ctor

    return ctor(
        "python:unpack_targets",
        [unpack_pattern_term(element) for element in pattern.elements],
    )


def validate_unpack_projections(formulas, bindings) -> None:
    """Link typed projection coordinates to their occurrence testimony."""
    by_slot = {binding.slot.slot_id: binding.pattern for binding in bindings}

    def loud(observed):
        from sugar_lift_py_tests.gap.info import GapKind, GapLocus
        from sugar_lift_py_tests.gap.panic import construction_panic_gap

        construction_panic_gap(
            owner="UnpackProjectionLinker",
            blame="function universe",
            observed=observed,
            requested="a projection admitted by its matching unpack occurrence",
            fix="use the occurrence's exact slot and structural target path",
            gap_kind=GapKind.CONSTRUCTOR,
            gap_locus=GapLocus.CONSTRUCTION,
        )

    def visit_term(term):
        name = getattr(term, "name", None)
        args = getattr(term, "args", ())
        if name == "python:unpack_projection":
            if len(args) != 2:
                loud("malformed python:unpack_projection arity")
            slot_term, path_term = args
            if (
                getattr(slot_term, "name", None) != "python:unpack_assignment_ref"
                or len(getattr(slot_term, "args", ())) != 1
            ):
                loud("projection has no typed unpack-assignment reference")
            slot_id = getattr(slot_term.args[0], "value", None)
            pattern = by_slot.get(slot_id)
            if pattern is None:
                loud(f"projection references unmatched slot {slot_id!r}")
            if getattr(path_term, "name", None) != "python:unpack_path":
                loud("projection path is not a typed python:unpack_path")
            positions = []
            for step in path_term.args:
                if getattr(step, "name", None) != "python:position" or len(step.args) != 1:
                    loud("projection path contains a non-Position step")
                positions.append(Position(getattr(step.args[0], "value", None)))
            from sugar_source_tree.unpack_assignment import path_in_pattern

            if not path_in_pattern(pattern, tuple(positions)):
                loud(f"projection path {tuple(positions)!r} is outside its pattern")
        for arg in args:
            visit_term(arg)

    def visit_formula(formula):
        for arg in getattr(formula, "args", ()):
            visit_term(arg)
        for operand in getattr(formula, "operands", ()):
            visit_formula(operand)
        body = getattr(formula, "body", None)
        if body is not None:
            visit_formula(body)

    for formula in formulas:
        visit_formula(formula)


@dataclass(frozen=True)
class UnpackValueBinding(FloorValue):
    slot: object
    rhs_value: FloorValue
    pattern: UnpackSequencePattern
    site: object = field(default=None, compare=False)

    def unpack_term(self):
        from sugar_lift_py_tests.ir import ctor, str_const

        return ctor(
            "python:unpack_assign",
            [
                str_const(self.pattern.kind),
                unpack_targets_term(self.pattern),
                self.rhs_value.to_term(owner=str(self.site)),
            ],
        )

    def inv_contribution(self):
        from sugar_lift_py_tests.ir import atomic

        return (
            atomic(
                "python:unpack_value_binding",
                [unpack_slot_term(self.slot), self.unpack_term()],
            ),
        )

    def callsites(self):
        return self.rhs_value.callsites()

    def guarded(self, formula):
        return GuardedUnpackValueBinding(formula, self)


@dataclass(frozen=True)
class GuardedUnpackValueBinding(FloorValue):
    guard: object
    binding: UnpackValueBinding

    def inv_contribution(self):
        from sugar_lift_py_tests.ir import implies

        return tuple(
            implies(self.guard, formula)
            for formula in self.binding.inv_contribution()
        )

    def callsites(self):
        return self.binding.callsites()

    def guarded(self, formula):
        from sugar_lift_py_tests.ir import and_

        return GuardedUnpackValueBinding(and_([formula, self.guard]), self.binding)
