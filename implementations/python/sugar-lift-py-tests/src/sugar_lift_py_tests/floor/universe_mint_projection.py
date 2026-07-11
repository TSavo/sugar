from __future__ import annotations

"""The shared projection helpers for minting: how a spine sentence enters the
proof language. ONE named door -- formula_from_ir -- plus scoping (formals and
`out` stay sort-silent as UnknownSort; the compiler decides), provenance
wrapping, and the claim role. Nothing here computes; it projects what the
values carry."""


def construction_site(site):
    from sugar_lift_py_tests.proofir.nodes import ConstructionSite

    return ConstructionSite(path=site.filename, line=site.line, column=site.col)


def claim_formula(ir_formula, *, formals, provenance, role):
    from sugar_lift_py_tests.proofir.formulas import formula_from_ir
    from sugar_lift_py_tests.proofir.scope import (
        ClaimFormula,
        ProvenancedFormula,
        ScopedFormula,
    )
    from sugar_lift_py_tests.proofir.sorts import UnknownSort

    sort = UnknownSort(reason="lift is sort-silent; the compiler decides")
    allowed = {name: sort for name in (*formals, "out")}
    return ClaimFormula(
        ProvenancedFormula(
            ScopedFormula(
                formula_from_ir(ir_formula, var_sorts=allowed),
                allowed_vars=allowed,
            ),
            provenance=provenance,
        ),
        role=role,
    )
