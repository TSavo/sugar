from __future__ import annotations

import json
from dataclasses import dataclass, replace

from sugar_lift_py_tests.canonicalizer import encode_jcs
from sugar_lift_py_tests.floor import Bv32Value, EncodedStringValue, StringValue
from sugar_lift_py_tests.ir import Formula, atomic, eq, make_var, str_const, term_to_value
from sugar_lift_py_tests.outcome import complete_value
from sugar_lift_py_tests.sugar_body import SugarBody
from sugar_lift_py_tests.temporal import TemporalContext


@dataclass(frozen=True)
class GenericBodySugar:
    """A string-encoder body lifted by composition, not by a base64 special case.

    `def f(param): <table = "...">  <b_i = ord(param[k])>...  return <table[...] + ...>`

    The table literal and the per-byte `ord`s become temporal bindings; the
    return expression is composed from the generic catalog (NameSugar resolves
    the bindings, BitwiseOpSugar builds the BV indices, StringSubscriptSugar
    indexes the table, BinOpSugar concatenates). Reducing that composition
    yields an EncodedStringValue whose (table, per-char index terms) IS the
    `str.eq-bv-blocks` universe. Nothing about base64 is special-cased: any
    table, any byte count, any block structure lifts the same way.
    """

    parameter: str
    table_name: str
    table_value: str
    byte_names: tuple[str, ...]
    assign_kinds: tuple[str, ...]  # per assignment, in body order: "table" or "ord"
    return_body: SugarBody
    build_ctx: object

    def apply(self, argument):  # pragma: no cover - lowers to ProofIR
        del argument
        raise TypeError(
            "GenericBodySugar lowers to ProofIR; call constraint_formulas instead of "
            "computing the encoding in Python"
        )

    def _temporal(self) -> TemporalContext:
        temporal = TemporalContext.empty().bind_value(
            self.table_name, StringValue(self.table_value)
        )
        for name in self.byte_names:
            temporal = temporal.bind_value(name, Bv32Value(make_var(name)))
        return temporal

    def _encoded(self) -> EncodedStringValue:
        ctx = replace(self.build_ctx, temporal=self._temporal())
        encoded = complete_value(self.return_body.reduce(ctx), owner="GenericBodySugar return")
        if not isinstance(encoded, EncodedStringValue):
            raise TypeError(
                "GenericBodySugar return must compose to an encoded string; got "
                f"{type(encoded).__name__}"
            )
        return encoded

    def constraint_formulas(self) -> list[Formula]:
        encoded = self._encoded()
        payload = json.dumps(
            {
                "vars": list(self.byte_names),
                "per_char": [_term_json(term) for term in encoded.indices],
                "table": list(encoded.table),
            },
            sort_keys=True,
            separators=(",", ":"),
        )
        return [
            atomic(
                "str.eq-bv-blocks",
                [make_var("out"), make_var(self.parameter), str_const(payload)],
            )
        ]

    def factory_steps(self, function) -> list[tuple[str, str, object, str]]:
        steps: list[tuple[str, str, object, str]] = []
        for stmt, kind in zip(function.body[:-1], self.assign_kinds):
            if kind == "table":
                steps.append(("StringLiteralSugar", "Assign", stmt, "StringValue"))
            else:
                steps.append(("OrdSugar", "Assign", stmt, "Bv32Value"))
        steps.append(("BinOpSugar", "Return", function.body[-1], "EncodedStringValue"))
        return steps

    def constraint_formula_steps(self) -> list[Formula | None]:
        blocks = self.constraint_formulas()[0]
        steps: list[Formula | None] = []
        for kind in self.assign_kinds:
            if kind == "table":
                steps.append(eq(make_var(self.table_name), str_const(self.table_value)))
            else:
                steps.append(None)
        steps.append(blocks)
        return steps


def _term_json(term) -> dict:
    return json.loads(encode_jcs(term_to_value(term)))
