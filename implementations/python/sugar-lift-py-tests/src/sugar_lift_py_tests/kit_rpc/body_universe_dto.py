from __future__ import annotations

from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any

from .callsite_fact_dto import CallsiteFactDto
from .rpc_value import to_rpc_value
from .source_memento_dto import SourceMementoDto

if TYPE_CHECKING:
    from sugar_lift_py_tests.ir import Term, TermTableBuilder
    from sugar_lift_py_tests.proofir.scope import ClaimFormula


# The panic-freedom leaf a Python halt is stated under: a runtime failure with
# no static guard (``sugar_ir_types::panic_freedom::RUNTIME_FAILURE_SITE``).
RUNTIME_FAILURE_SITE = "concept:panic-freedom.leaf.runtime-failure-site"


@dataclass(frozen=True)
class PanicLocusDto:
    """One halted arm of a reduction, in the existing panic-locus row shape.

    No new row shape (#7766, ruling 3): a ``panicLoci`` entry on the
    function's contract row, filled with exactly the fields the verifier's one
    panic-locus reader reads (``enumerate_callsites::callsite_from_panic_locus``):

    * ``callee``: the runtime-failure-site leaf;
    * ``file`` / ``line``: the fragment the halt left at, when its halt record
      states one; absent otherwise, never borrowed from somewhere else;
    * ``argTerm``: what the halt is about: the raised type's coordinate for a
      raise, the failing operation for a runtime effect; absent when the halt
      states neither;
    * ``guard``: the halted arm's guard, the path condition the halt is reached
      under, written exactly as the contract's ``post`` is (a ``ClaimFormula``
      through ``universe_value.contract_claim``). The same reader reads it
      into the obligation's guard facts.

    Nothing in a proof links a Python halt to a bridge, so the row the
    verifier makes of it stays ``undecidable``.
    """

    file: str | None = None
    line: int | None = None
    arg_term: Term | None = None
    guard: ClaimFormula | None = None

    def __post_init__(self) -> None:
        _require_claim_formula_slot("guard", self.guard)

    def to_rpc_with_term_table(self, term_table: TermTableBuilder) -> dict[str, Any]:
        out = self._site()
        if self.arg_term is not None:
            out["argTerm"] = term_table.reference(self.arg_term)
        if self.guard is not None:
            out["guard"] = term_table.formula(self.guard.ir_formula)
        return out

    def to_semantic_rpc(self) -> dict[str, Any]:
        import json

        from sugar_lift_py_tests.canonicalizer import encode_jcs
        from sugar_lift_py_tests.ir import term_to_value

        out = self._site()
        if self.arg_term is not None:
            out["argTerm"] = json.loads(encode_jcs(term_to_value(self.arg_term)))
        if self.guard is not None:
            out["guard"] = to_rpc_value(self.guard)
        return out

    def _site(self) -> dict[str, Any]:
        out: dict[str, Any] = {"callee": RUNTIME_FAILURE_SITE}
        if self.file is not None:
            out["file"] = self.file
        if self.line is not None:
            out["line"] = self.line
        return out


@dataclass(frozen=True)
class BodyUniverseDto:
    name: str
    out_binding: str = "out"
    pre: ClaimFormula | None = None
    post: ClaimFormula | None = None
    inv: ClaimFormula | None = None
    source_warrants: list[SourceMementoDto | dict[str, Any]] = field(
        default_factory=list
    )
    proofir_provenance: dict[str, Any] | None = None
    warranted_by: CallsiteFactDto | dict[str, Any] | None = None
    # The universal variables of `post` (the function's formal params). The
    # verifier's `collect_ambient_posts` only treats a post as an ambient
    # universal -- specializable into a consumer's callsite obligation -- when the
    # contract carries `formals`.
    formals: list[str] = field(default_factory=list)
    # One sort per formal, stated by a function-contract whose formals carry
    # authenticated coordinates; the linker reads the signature from it.
    formal_sorts: list[dict] = field(default_factory=list)
    # `function-contract` (with `post` + `formals`) makes the mint auto-mint a
    # `sourceSymbol -> this contract` bridge (`bind_function_bridge`), resolving the
    # target CID at seal -- which is what lets `collect_ambient_posts` pick the post
    # up as an ambient universal. `bridge_source_symbol` is the definition's one
    # symbol, `python:<module>.<qualname>` (`@<line>:<col>` where the qualname
    # alone is not unique), and the contract's `name`; the Python kit states no
    # bare name. (The
    # verifier still matches a bridge's symbol against a call ctor's name with
    # `call:` or `method:` stripped: a tolerance other kits may rely on, to be
    # deleted with the join by `target_symbol`.)
    kind: str = "contract"
    bridge_source_symbol: str | None = None
    # One entry per halted arm of the function's one reduction (#7766): a
    # halt is never dropped. Stated on the function's contract row only.
    panic_loci: tuple[PanicLocusDto, ...] = ()
    # ``((formal, term), ...)``: the value the module's one run left for each
    # ``global:<name>`` input the contract states its post and claims over
    # (#7757 step 5, ``call_site_sugar.stated_global_values``). Prove's one
    # binder binds an input no call supplies to it, as it binds an omitted
    # parameter to its default; the row's own claims are bound so too.
    input_values: tuple[tuple[str, Term], ...] = ()

    def __post_init__(self) -> None:
        for slot in ("pre", "post", "inv"):
            _require_claim_formula_slot(slot, getattr(self, slot))

    def to_rpc(self) -> dict[str, Any]:
        raise RuntimeError(
            "BodyUniverseDto requires the payload term-table writer; "
            "fix=serialize through LiftReportPayloadDto.to_rpc "
            "or BodyUniverseDto.to_rpc_with_term_table"
        )

    def to_rpc_with_term_table(self, term_table: TermTableBuilder) -> dict[str, Any]:
        """Payload/wire declaration: formula term positions are term-refs."""
        out = self._envelope()
        if self.pre is not None:
            out["pre"] = term_table.formula(self.pre.ir_formula)
        if self.post is not None:
            out["post"] = term_table.formula(self.post.ir_formula)
        if self.inv is not None:
            out["inv"] = term_table.formula(self.inv.ir_formula)
        if self.panic_loci:
            out["panicLoci"] = [
                locus.to_rpc_with_term_table(term_table) for locus in self.panic_loci
            ]
        if self.input_values:
            out["inputValues"] = [
                {"formal": formal, "value": term_table.reference(term)}
                for formal, term in self.input_values
            ]
        self._attach_sidecars(out)
        return out

    def to_semantic_rpc(self) -> dict[str, Any]:
        """Local identity preimage only — expanded formula trees, not the wire door.

        Semantic CIDs hash fully-resolved term bytes (the same preimage the
        term-table keys). This method must never be the transport path for a
        payload; transport is ``to_rpc_with_term_table`` / LiftReportPayloadDto.
        """
        out = self._envelope()
        if self.pre is not None:
            out["pre"] = to_rpc_value(self.pre)
        if self.post is not None:
            out["post"] = to_rpc_value(self.post)
        if self.inv is not None:
            out["inv"] = to_rpc_value(self.inv)
        if self.panic_loci:
            out["panicLoci"] = [locus.to_semantic_rpc() for locus in self.panic_loci]
        if self.input_values:
            import json

            from sugar_lift_py_tests.canonicalizer import encode_jcs
            from sugar_lift_py_tests.ir import term_to_value

            out["inputValues"] = [
                {
                    "formal": formal,
                    "value": json.loads(encode_jcs(term_to_value(term))),
                }
                for formal, term in self.input_values
            ]
        self._attach_sidecars(out)
        return out

    def _envelope(self) -> dict[str, Any]:
        out: dict[str, Any] = {
            "kind": self.kind,
            "name": self.name,
            "outBinding": self.out_binding,
        }
        if self.formals or self.kind == "function-contract":
            out["formals"] = list(self.formals)
        if self.formal_sorts:
            out["formalSorts"] = list(self.formal_sorts)
        if self.bridge_source_symbol is not None:
            out["bridgeSourceSymbol"] = self.bridge_source_symbol
        return out

    def _attach_sidecars(self, out: dict[str, Any]) -> None:
        if self.source_warrants:
            out["sourceWarrants"] = [
                to_rpc_value(warrant) for warrant in self.source_warrants
            ]
        if self.proofir_provenance is not None:
            out["proofirProvenance"] = to_rpc_value(self.proofir_provenance)
        if self.warranted_by is not None:
            out["warrantedBy"] = to_rpc_value(self.warranted_by)


def _require_claim_formula_slot(field_name: str, value: object) -> None:
    if value is None:
        return
    from sugar_lift_py_tests.proofir.scope import ClaimFormula

    if not isinstance(value, ClaimFormula):
        raise TypeError(f"BodyUniverseDto.{field_name} must be ClaimFormula")
