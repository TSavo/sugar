from __future__ import annotations

from dataclasses import dataclass

from .floor_value import FloorValue


@dataclass(frozen=True)
class BridgedContractValue(FloorValue):
    term: object
    contract_cid: str
    member_cid: str
    callsite: object

    def to_term(self, *, owner: str):
        del owner
        return self.term

    def callsites(self):
        return (self.callsite,)

    def edge_contribution(self, source_contract):
        return self.callsite.edge_contribution(source_contract)

    def subscript(self, index, site):
        from sugar_lift_py_tests.floor.symbolic_value import SymbolicValue
        from sugar_lift_py_tests.floor.term_value import TermValue
        from sugar_lift_py_tests.ir import _Ctor
        from sugar_lift_py_tests.outcome import Complete
        from sugar_source_tree.panic import SugarNotWritten

        if (
            isinstance(self.term, _Ctor)
            and self.term.name in {"tuple", "python:tuple", "python:list"}
            and isinstance(index, TermValue)
            and type(index.value) is int
            and 0 <= index.value < len(self.term.args)
        ):
            return Complete(SymbolicValue(self.term.args[index.value]))
        raise SugarNotWritten(
            owner="BridgedContractValue.subscript",
            observed="contract return does not warrant this projection",
            requested="ground in-range projection from an authenticated structural return",
            fix="strengthen the contract or keep the projection loud",
        )
