from __future__ import annotations

from enum import Enum


class SugarRole(str, Enum):
    TERM = "term"
    # An assertion surface that emits a vendor fact (`assert <shape>`). This is
    # separate from STATEMENT because an assertion is evidence, not a block effect.
    ASSERTION = "assertion"
    # A statement -- a member of a block (suite). Comment, Return, Assign, If, ...
    # each own their statement shape. Their OUTCOME is a category (a comment's is
    # Support); the role is just the dispatch key, parallel to TERM for expressions.
    STATEMENT = "statement"

    def __str__(self) -> str:
        return self.value
