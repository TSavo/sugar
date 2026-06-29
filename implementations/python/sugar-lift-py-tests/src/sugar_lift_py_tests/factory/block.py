from __future__ import annotations

import ast
from dataclasses import dataclass


@dataclass(frozen=True)
class Block:
    """A Python suite -- the ordered statements under one indentation (a
    `FunctionDef.body`, an `If.body`, an `If.orelse`, ...).

    Python's AST has no node for it: a suite is a bare `list[stmt]` field, so the
    stack walk would flatten it into loose statements with nothing to compose them.
    Block is the synthetic node that puts the suite ON the stack as a single
    composite, so the inside-out read composes its statements (a BlockSugar) instead
    of an external loop faking it. It carries a position so it is a normal SourceSite.
    """

    body: tuple[ast.stmt, ...]
    lineno: int
    col_offset: int

    @classmethod
    def of(cls, suite: list[ast.stmt]) -> "Block":
        first = suite[0]
        return cls(
            body=tuple(suite),
            lineno=getattr(first, "lineno", 0),
            col_offset=getattr(first, "col_offset", 0),
        )
