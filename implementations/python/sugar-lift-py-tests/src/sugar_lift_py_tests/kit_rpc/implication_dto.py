from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class ImplicationDto:
    name: str
    antecedent: str
    consequent: str
    antecedent_slot: str = "post"
    consequent_slot: str = "pre"
    prover: str | None = None

    def to_rpc(self) -> dict[str, str]:
        out = {
            "name": self.name,
            "antecedent": self.antecedent,
            "consequent": self.consequent,
            "antecedentSlot": self.antecedent_slot,
            "consequentSlot": self.consequent_slot,
        }
        if self.prover is not None:
            out["prover"] = self.prover
        return out
