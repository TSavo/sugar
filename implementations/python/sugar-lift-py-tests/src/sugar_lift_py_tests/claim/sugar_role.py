from __future__ import annotations

from enum import Enum


class SugarRole(str, Enum):
    TERM = "term"
    # A definition selected as an audit root. Its body becomes a universe or
    # testimony. Executable def statements use STATEMENT and bind a callable.
    DEFINITION = "definition"
    # An assertion surface that emits a vendor fact (`assert <shape>`). This is
    # separate from STATEMENT because an assertion is evidence, not a block effect.
    ASSERTION = "assertion"
    # A statement -- a member of a block (suite). Comment, Return, Assign, If, ...
    # each own their statement shape. Their OUTCOME is a category (a comment's is
    # Support); the role is just the dispatch key, parallel to TERM for expressions.
    STATEMENT = "statement"

    def __str__(self) -> str:
        return self.value
