from __future__ import annotations

from enum import Enum


class SugarRole(str, Enum):
    TERM = "term"
    # A resolved FunctionDef selected as the executable body of a callsite dig.
    # This is distinct from DEFINITION: definitions mint universes, while a
    # control-flow body owns the callable's composed return paths.
    CONTROL_FLOW_BODY = "control-flow-body"
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
    # A match-case pattern shape. Selected by the factory for `case` patterns so
    # MatchSugar consumes recognized pattern sugars, never raw `ast.pattern`
    # isinstance walks. Ground matching is `match_ground`; desugar is identity.
    PATTERN = "pattern"
    # A module selected for structural package-source testimony. The owning
    # Sugar recognizes imported package roots and cites every accounted locus;
    # factory/ never interprets the module's control flow.
    PACKAGE_SOURCE = "package-source"

    def __str__(self) -> str:
        return self.value
