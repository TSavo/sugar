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
    no universe."""

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

    def payload_rows(self, def_memento):
        # Testimony mints NO function-contract row. Each fact is a contract row
        # named `{name}::assertion` -- the wire mark observed facts ride under.
        import dataclasses

        from sugar_lift_py_tests.kit_rpc import BodyUniverseDto

        rows = []
        for entry in self.record.statements:
            for row in entry.mint_contribution(self.name, self.formals):
                rows.append(
                    BodyUniverseDto(
                        name=f"{self.name}::assertion",
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
                    )
                )
        del def_memento  # no function-contract row to attach the def warrant to
        return rows
