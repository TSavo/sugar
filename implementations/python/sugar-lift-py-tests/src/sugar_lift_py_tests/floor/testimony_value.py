from __future__ import annotations

from dataclasses import dataclass

from .floor_value import FloorValue


@dataclass(frozen=True)
class TestimonyValue(FloorValue):
    """A test function is testimony, not a contract: nobody calls it, nobody
    discharges its post. Its asserts are the VENDOR FACTS -- first-encounter
    stated facts about the callees, the rows the whole join runs on. A test
    assert with no call coordinate is still a fact row: a trivial axiom in the
    system, a literal tautology, and the vendor carries it. (Ground-true folds
    to support before mint -- a named gap until a per-body-mode ruling lands.)

    Projects ONLY facts: facts() from the record's inv_contribution. No post,
    no universe.

    Ground callsite equalities mint under the callsite-keyed `#euf#` name so
    ambient consistency can join duals that share a left call term across test
    functions (A2 dual-logo class). Bare `{test}::assertion` remains for
    non-callsite facts.
    """

    name: str
    formals: tuple[str, ...]
    record: object  # the body's BlockValue

    def facts(self):
        # The vendor facts: each assert's stated formula, projected from the record.
        return tuple(
            formula
            for entry in self.record.statements
            for formula in entry.inv_contribution()
        )

    def call_edges(self):
        return tuple(
            edge
            for entry in self.record.statements
            for edge in entry.edge_contribution(self.name)
        )

    def runtime_effects(self):
        """Return every typed terminal effect carried by this testimony block."""
        from sugar_lift_py_tests.outcome import Incomplete

        return tuple(
            entry.effect
            for entry in self.record.statements
            if isinstance(entry, Incomplete)
        )

    def payload_rows(self, def_memento):
        # Testimony mints NO function-contract row. Each fact is a contract row.
        # Ground callsite equality rides under its `#euf#` key (verifier
        # ambient join); everything else keeps the historical
        # `{test}::assertion` mark.
        import dataclasses

        from sugar_lift_py_tests.kit_rpc import BodyUniverseDto

        rows = []
        for entry in self.record.statements:
            for row in entry.mint_contribution(self.name, self.formals):
                rows.append(
                    BodyUniverseDto(
                        name=_assertion_contract_name(self.name, row.formula),
                        inv=row.formula,
                        source_warrants=[
                            dataclasses.replace(
                                warrant,
                                source_function_name=self.name,
                                role="assertion",
                            )
                            for warrant in row.source_warrants
                        ],
                        formals=list(row.formals),
                        kind="contract",
                        proofir_provenance=row.provenance().to_rpc(),
                    )
                )
        del def_memento  # no function-contract row to attach the def warrant to
        return rows


def _assertion_contract_name(test_name: str, formula) -> str:
    euf = _ground_callsite_euf_name(formula)
    if euf is not None:
        return euf
    return f"{test_name}::assertion"


def _ground_callsite_euf_name(formula) -> str | None:
    """Return the `#euf#` name for stated or derived call equality."""
    from sugar_lift_py_tests.ir import _Atomic, _Ctor
    from sugar_lift_py_tests.proofir.nodes.equality_fact import (
        canonical_euf_callsite_name,
    )

    ir = getattr(formula, "ir_formula", None)
    if ir is None:
        ir = formula
    if (
        not isinstance(ir, _Atomic)
        or ir.name not in {"=", "py.eq"}
        or len(ir.args) != 2
    ):
        return None
    left = ir.args[0]
    if not isinstance(left, _Ctor) or not left.name.startswith("call:"):
        return None
    return canonical_euf_callsite_name(left)
