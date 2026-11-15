"""Source-fragment coordinates and the tree construction context.

The context names the workspace a tree is built under and holds no table
(#7757): a ``with``'s manager is what its head reduces to, so no contract ref,
gap row or native definition is installed before construction.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any


class ContractRefProtocolError(ValueError):
    pass


@dataclass(frozen=True, order=True)
class SourceFragmentCoordinateV1:
    source_cid: str
    start_line: int
    start_col: int
    end_line: int
    end_col: int

    @classmethod
    def decode(cls, raw: Any) -> "SourceFragmentCoordinateV1":
        if not isinstance(raw, dict) or set(raw) != {
            "sourceCid",
            "startLine",
            "startCol",
            "endLine",
            "endCol",
        }:
            raise ContractRefProtocolError("malformed source-fragment coordinate")
        values = (raw["startLine"], raw["startCol"], raw["endLine"], raw["endCol"])
        if not isinstance(raw["sourceCid"], str) or not all(
            isinstance(value, int) and value >= 0 for value in values
        ):
            raise ContractRefProtocolError(
                "malformed source-fragment coordinate fields"
            )
        return cls(raw["sourceCid"], *values)

    def wire(self) -> dict[str, Any]:
        return {
            "sourceCid": self.source_cid,
            "startLine": self.start_line,
            "startCol": self.start_col,
            "endLine": self.end_line,
            "endCol": self.end_col,
        }

    @property
    def cid(self) -> str:
        """Canonical CID of this owner's existing wire representation."""
        from sugar_lift_python_source.canonical import cid_of_json

        return cid_of_json(self.wire())


@dataclass(frozen=True)
class TreeConstructionContextV1:
    """Explicit tree construction handle: the workspace a tree is built under.

    It holds no table (#7757). A ``with``'s manager is what its head reduces
    to (``With._reduced_manager_sugar``); a call's frame is the one its own
    lexical row's definition applies (``Call._construct_sugar``). Nothing
    outside the tree fills anything a node reads here.
    """

    workspace_root: str | None = None

    @classmethod
    def for_source_call_construction(
        cls,
        *,
        workspace_root: str | None = None,
    ) -> "TreeConstructionContextV1":
        """A construction context naming ``workspace_root`` (or none)."""
        return cls(workspace_root=workspace_root)

    @classmethod
    def for_test_without_workspace(cls) -> "TreeConstructionContextV1":
        """A caller ASSERTING it has no workspace. The name is the claim.

        Use this only where the assertion is true: a test that builds one
        function from a string literal, in a throwaway ``tempfile`` directory,
        with no corpus and no cross-language bridge to name. Every lookup
        through the returned context then answers "looked up, genuinely
        absent" -- which is a FACT, and is exactly the state
        ``_require_construction_context`` was built to make distinguishable
        from "this tree was opened without a context" (an instrument defect).

        WHAT IT DOES NOT MEAN, and why this constructor exists at all.
        ``workspace_root`` is None here, and ``workspace_root`` gates
        ``FunctionDef``'s ``bridge_source_symbol``. So a value constructed
        through this context is BYTE-IDENTICAL to the one the bare door
        produced -- ``bridge_source_symbol=None`` either way -- with the
        refusal removed::

            bare door                : bridge_source_symbol=None
            this context             : bridge_source_symbol=None
            a real workspace context : 'python:subject.module_level'

        Turning a loud refusal into a silent construction of the same answer is
        the defect this law exists to eliminate. It is legitimate HERE only
        because the caller genuinely has no workspace, and illegitimate the
        moment that is untrue.

        That is why this is a distinct constructor and not
        ``for_source_call_construction()`` with a default. "No workspace" is a
        claim about the CALLER, it has to be made per caller, and it must not
        arrive by inheritance in a file nobody read. Spelled this way it is
        explicit, greppable and auditable: every site that asserts it says so
        in the name, and a reviewer can enumerate them.

        ``test_an_empty_context_constructs_the_bare_doors_value`` pins the
        three-way result above, so a suite that goes green through this door
        can never be read as evidence the enrichment came back.
        """
        return cls.for_source_call_construction()
