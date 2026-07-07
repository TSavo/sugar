# SPDX-License-Identifier: MIT OR Apache-2.0
#
# sugar-lift-py-tests : Python structural lift adapter.
#
# Layer 2 sits ABOVE Layer 0 (mechanical assert recognition; the future
# Python Layer 0 will be analogous to the Rust one) and BELOW the
# eventual Layer 3 LLM lift. It recognizes five structural patterns over
# pytest/unittest test syntax that Layer 0 cannot. The production walker
# mirrors Rust `sugar-walk`: callee preconditions are propagated
# backward from Python production callsites to function entry as WP edges.
#
# Patterns:
#   1. Bounded ``for`` loop -> forall-implies.
#   2. Helper function inlined at each call site.
#   3. Multi-assertion characterization conjunction.
#   4. ``@pytest.mark.parametrize`` over a literal list -> one contract per row (per-row independent).
#   5. Callsite value-scope facts plus implication edges from tests.
#
# Out of scope for v0: ``hypothesis`` (Layer 1 already), ``pytest.raises``,
# fixtures, parametrize over factories, nested loops.

from .canonicalizer import (
    BLAKE3_512_PREFIX,
    blake3_512_of,
    encode_jcs,
    jcs_hash,
)
from .op_cid import (
    bare_local_operator_name,
    local_op_cid,
    local_operator_shape,
    op_cid_from_shape,
)
from .ir import (
    Bool,
    BridgeDecl,
    CallEdgeDecl,
    ContractDecl,
    EvidenceCertificate,
    EvidenceTerm,
    Int,
    Locus,
    Real,
    Sort,
    String,
    and_,
    atomic,
    bool_const,
    bridge_decl_to_value,
    call_edge_decl_to_value,
    call_edges_to_value,
    connective,
    contract_decl_to_value,
    ctor,
    declarations_to_value,
    eq,
    evidence_to_value,
    exists,
    forall,
    formula_to_value,
    gt,
    gte,
    implies,
    locus_to_value,
    lt,
    lte,
    make_var,
    ne,
    not_,
    num,
    or_,
    str_const,
    subst_var_in_formula,
    subst_var_in_term,
    term_to_value,
)
from .proof_envelope import ProofEnvelopeInput, envelope_body_to_value
from .claim_envelope import (
    Authoring,
    AuthoringKitAuthor,
    AuthoringLift,
    AuthoringLlm,
    ClaimEnvelope,
    ClaimEnvelopeError,
    EmptyContractError,
    EmptyOutBindingError,
    LAYERED_SCHEMA_VERSION,
    compute_contract_set_cid,
    contract_cid,
    mint_bridge,
    mint_contract,
    mint_implication,
)
from .signing import Signer
from .verifier import (
    verify_project,
    prove_contract,
    HandshakeReport,
    VerifierNotFoundError,
)

__all__ = [
    "Authoring",
    "AuthoringKitAuthor",
    "AuthoringLift",
    "AuthoringLlm",
    "BLAKE3_512_PREFIX",
    "Bool",
    "BridgeDecl",
    "CallEdgeDecl",
    "ClaimEnvelope",
    "ClaimEnvelopeError",
    "ContractDecl",
    "EmptyContractError",
    "EmptyOutBindingError",
    "EvidenceCertificate",
    "EvidenceTerm",
    "HandshakeReport",
    "Int",
    "LAYERED_SCHEMA_VERSION",
    "Locus",
    "ProofEnvelopeInput",
    "Real",
    "Signer",
    "Sort",
    "String",
    "VerifierNotFoundError",
    "and_",
    "atomic",
    "blake3_512_of",
    "bool_const",
    "bridge_decl_to_value",
    "call_edge_decl_to_value",
    "call_edges_to_value",
    "compute_contract_set_cid",
    "connective",
    "contract_cid",
    "contract_decl_to_value",
    "ctor",
    "declarations_to_value",
    "encode_jcs",
    "envelope_body_to_value",
    "eq",
    "evidence_to_value",
    "exists",
    "forall",
    "formula_to_value",
    "gt",
    "gte",
    "implies",
    "jcs_hash",
    "locus_to_value",
    "lt",
    "lte",
    "bare_local_operator_name",
    "local_op_cid",
    "local_operator_shape",
    "make_var",
    "mint_bridge",
    "mint_contract",
    "mint_implication",
    "ne",
    "not_",
    "num",
    "op_cid_from_shape",
    "or_",
    "prove_contract",
    "str_const",
    "subst_var_in_formula",
    "subst_var_in_term",
    "term_to_value",
    "verify_project",
]
