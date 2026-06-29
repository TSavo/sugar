from __future__ import annotations

import json
from dataclasses import dataclass

from sugar_lift_py_tests.canonicalizer import encode_jcs
from sugar_lift_py_tests.floor import EncodedStringValue
from sugar_lift_py_tests.ir import Formula, atomic, make_var, str_const, term_to_value


def _term_json(term) -> dict:
    return json.loads(encode_jcs(term_to_value(term)))


def _byte_vars(indices: tuple) -> list[str]:
    """The byte variables referenced by the per-char index terms, in byte-index order.

    str.eq-bv-blocks binds `vars[k]` to value's k-th byte, so the order is the byte
    position. OrdByteSugar names each `byte_<source>_<index>`, so we collect the
    distinct `byte_*` vars from the composed indices and sort by that index."""
    names: set[str] = set()

    def walk(node) -> None:
        if isinstance(node, dict):
            if node.get("kind") == "var" and str(node.get("name", "")).startswith(
                "byte_"
            ):
                names.add(node["name"])
            for value in node.values():
                walk(value)
        elif isinstance(node, list):
            for item in node:
                walk(item)

    for index_term in indices:
        walk(_term_json(index_term))
    return sorted(names, key=lambda name: int(name.rsplit("_", 1)[1]))


@dataclass(frozen=True)
class EncoderBodySugar:
    """A string-encoder body, composed through the Block to an EncodedStringValue, and
    lowered to the existing `str.eq-bv-blocks` atom.

    The Block did the recognition: the table literal became a BoundVar, each
    `b_i = ord(value[i])` a BoundVar aliasing a symbolic byte, and the return composed
    (BitwiseOp / StringSubscript / BinOp) into the (table, per-char index) encoding.
    This sugar just reads that EncodedStringValue and emits the predicate -- the byte
    vars come from the indices, in byte order. No base64 special case, no compiler
    change; the encoder is a recognized leaf inside the one Block path."""

    parameter: str
    encoded: EncodedStringValue
    statement_count: int

    def constraint_formulas(self) -> list[Formula]:
        payload = json.dumps(
            {
                "vars": _byte_vars(self.encoded.indices),
                "per_char": [_term_json(term) for term in self.encoded.indices],
                "table": list(self.encoded.table),
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
        # the whole encoder universe is the body composed as one Block.
        return [("BlockSugar", "Block", function, "EncodedStringValue")]

    def constraint_formula_steps(self) -> list[Formula | None]:
        # one walk row (the Block), carrying the str.eq-bv-blocks it emitted.
        return [self.constraint_formulas()[0]]
