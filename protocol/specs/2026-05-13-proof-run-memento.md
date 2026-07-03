# Proof Run Memento and Stage Receipt

**Status:** v1.0.0 normative draft.
**Date:** 2026-05-13
**Author:** T Savo
**Related:**
- `2026-05-12-plugin-protocol.md` §9 (`PluginRegistryMemento`)
- `2026-04-30-proof-file-format.md` (`ProofEnvelope` and `.proof` bundle format)
- `2026-05-03-bridge-linkage-protocol.md` (`LinkBundle`)
- `2026-05-12-concept-site-memento.md` and `2026-05-13-compound-contract-memento.md` (admissible substrate claims)
- TSavo/sugar#796 (admissibility-spine umbrella)
- TSavo/sugar#791 (`PromotionDecisionMemento`)
- TSavo/sugar#799 (generic `RunMemento` + `VerifierPipelineMemento`, deferred — this spec is the verifier-pipeline profile of that generic shape)
- `implementations/rust/sugar-verifier/src/lib.rs` and `runner.rs` (current verifier stage sequence)

## §0. Purpose

`sugar prove` is an admissibility boundary. It consumes a `.proof` bundle, the link closure the bundle depends on, and the plugin registry active for the run. It then decides whether the substrate claims in that input may compose downstream.

Before this spec, that decision was documented in prose and partially in source comments. The CLI comments still say "six-stage verifier", while `sugar-verifier` composes seven source stages. A verifier run that only emits a terminal report forces downstream consumers to trust the report writer's summary of what happened.

`ProofRunMemento` and `StageReceipt` replace that prose boundary with content-addressed facts:

1. A `StageReceipt` records one completed verifier stage: what CIDs it read, what CIDs it produced, which refusals it emitted, and the stage verdict.
2. A `ProofRunMemento` records the whole `sugar prove` invocation: the input roots, the sealed plugin registry, the ordered receipt chain, and the run verdict.

Together they make a run replayable. Given the same `ProofEnvelope`, `PluginRegistryMemento`, and `LinkBundle`, a verifier can execute the same stage sequence, compare each stage to its receipt, and reconstruct the same run verdict without trusting a human report.

### §0.1 Profile of the generic RunMemento

This spec defines the verifier-pipeline profile of the generic `RunMemento` (TSavo/sugar#799, deferred). `ProofRunMemento` is `RunMemento` specialized to `sugar prove`: the `verifier_pipeline_cid` slot points at a `VerifierPipelineMemento` (#799) that pins the ordered stage vocabulary, and the `stage_receipt_cids` chain matches that vocabulary. Other pipelines (`sugar bind`, `sugar link`, `sugar lift`) will define their own profile mementos against the same `RunMemento` shape; this spec does not constrain them. When #799 lands, this memento becomes the canonical first instantiation of that umbrella.

## §1. Wire Shapes

The CDDL display order below follows locked JCS alphabetical key order within each object. JCS canonicalization is normative; producers MUST emit semantically equivalent objects in canonical key order before hashing or signing.

### §1.1 `ProofRunMemento`

```cddl
; Shared scalar types:
;   cid, signature, pubkey, iso8601, json-value
;
cid = tstr             ; "blake3-512:" plus 128 lowercase hex digits
signature = tstr       ; "ed25519:" tagged signature text
pubkey = tstr          ; "ed25519:" tagged public key text
iso8601 = tstr         ; RFC 3339 timestamp
json-value = any
;
; Locked JCS key order:
; top-level: envelope, header, metadata
; envelope: declaredAt, signature, signer
; header: cid, input_artifact_cids, input_run_cids, kind,
;         link_bundle_cid, output_artifact_cids,
;         plugin_registry_cid, proof_envelope_cid, schemaVersion,
;         sealed_at, stage_receipt_cids, verdict,
;         verifier_pipeline_cid
; metadata: note, source_url

proof-run-memento = {
  envelope: {
    declaredAt: iso8601,
    signature:  signature,
    signer:     pubkey
  },
  header: {
    cid:                   cid,            ; DERIVED -- see §4
    input_artifact_cids:   [+ cid],        ; all artifact CIDs this run consumed (proof, link bundle, registry are also listed by name above)
    input_run_cids:        [* cid],        ; predecessor RunMementos whose outputs were consumed; explicit replay graph, no reverse lookup
    kind:                  "proof-run",
    link_bundle_cid:       cid,
    output_artifact_cids:  [* cid],        ; artifacts this run produced (DischargeReceipts, CounterexampleReceipts, etc.)
    plugin_registry_cid:   cid,
    proof_envelope_cid:    cid,
    schemaVersion:         "1",
    sealed_at:             iso8601,
    stage_receipt_cids:    [+ cid],        ; ordered list matching the verifier_pipeline stage vocabulary
    verdict:               run-verdict,
    verifier_pipeline_cid: cid             ; the VerifierPipelineMemento (separate spec, deferred) that pins the ordered stage vocabulary for this run's verifier version
  },
  metadata: {
    ? note:       tstr,
    ? source_url: tstr
  }
}

run-verdict = "admissible" / "refused" / "partial"
```

The `verifier_pipeline_cid` field is the key separation: ProofRunMemento does NOT bake the stage count or stage names into its shape. Stage vocabulary lives in a separate `VerifierPipelineMemento` (deferred spec, queued for second wave). Future pipelines can add, split, or reorder stages without breaking any minted ProofRunMemento. The current `sugar-verifier`/`sugar-cli` source defines pipeline v1; that pipeline's stage names appear in §3 as the canonical reference, not as a spec-level constraint.

`input_run_cids` makes provenance across runs an EXPLICIT graph rather than a reverse lookup. When `sugar prove` consumes the output of a `sugar bind` or `sugar link` run, it cites those predecessor RunMementos here. Verifiers walk forward from a starting input; replay is graph traversal, not search.

### §1.2 `StageReceipt`

```cddl
; Shared scalar types:
;   cid, signature, pubkey, iso8601, json-value
;
cid = tstr             ; "blake3-512:" plus 128 lowercase hex digits
signature = tstr       ; "ed25519:" tagged signature text
pubkey = tstr          ; "ed25519:" tagged public key text
iso8601 = tstr         ; RFC 3339 timestamp
json-value = any
;
; Locked JCS key order:
; top-level: envelope, header, metadata
; envelope: declaredAt, signature, signer
; header: cid, diagnostics, finished_at, input_cids, kind,
;         output_cids, refusal_cids, schemaVersion, stage_name,
;         started_at, verdict
; metadata: note

stage-receipt = {
  envelope: {
    declaredAt: iso8601,
    signature:  signature,
    signer:     pubkey
  },
  header: {
    cid:           cid,             ; DERIVED -- see §4
    diagnostics:   [* json-value],
    finished_at:   iso8601,
    input_cids:    [+ cid],
    kind:          "stage-receipt",
    output_cids:   [* cid],
    refusal_cids:  [* cid],
    schemaVersion: "1",
    stage_name:    stage-name,
    started_at:    iso8601,
    verdict:       stage-verdict
  },
  metadata: {
    ? note: tstr
  }
}

stage-name = tstr

stage-verdict = "ok" / "warned" / "refused" / "skipped"
```

`stage-name` is intentionally `tstr` only. This spec does NOT bake any stage vocabulary into the CDDL. The ordered stage vocabulary for a verifier version lives in a separate `VerifierPipelineMemento` (deferred to the second-wave spec queue, see TSavo/sugar#799 PipelineMemento + RunMemento).

The current `sugar-verifier`/`sugar-cli` source defines pipeline v1 with the following seven stage names (verbatim from source, file paths in `implementations/rust/sugar-verifier/src/`):

- `load_all_proofs` (`load_all_proofs.rs`)
- `enumerate_callsites` (`enumerate_callsites.rs`)
- `resolve_target` (`resolve_target.rs`)
- `instantiate` (`instantiate.rs`)
- `smt_emit` (`smt_emitter.rs`)
- `solve_obligation` (`solve_obligation.rs`)
- `report` (`report.rs`)

Those names are pipeline v1's reference vocabulary, NOT spec-level constraints. The stage label is `smt_emit`; the source module remains `smt_emitter.rs`. Older sealed receipts that carried the legacy label `smt_emitter` remain replayable as extension/legacy `tstr` stage labels, but new Rust verifier pipeline-v1 receipts use `smt_emit`. Future pipelines may add, split, or reorder stages by minting a new `VerifierPipelineMemento` and citing it via `verifier_pipeline_cid`. ProofRunMementos minted under different pipelines remain individually replayable against their declared pipeline.

## §2. Field Semantics

### §2.1 `ProofRunMemento` fields

| Layer | Field | Required | Meaning |
|---|---|---:|---|
| envelope | `declaredAt` | yes | ISO-8601 timestamp at which the run memento was declared. |
| envelope | `signature` | yes | Ed25519 signature over `JCS({header, metadata})`. |
| envelope | `signer` | yes | Public key of the verifier or verifier authority that sealed the run. |
| header | `cid` | yes | Content CID of this run memento, DERIVED per §4. |
| header | `input_artifact_cids` | yes | All artifact CIDs this run consumed. MUST include `proof_envelope_cid`, `link_bundle_cid`, and `plugin_registry_cid`, plus any other inputs the run depended on. Sorted ascending for canonical form. |
| header | `input_run_cids` | yes | Predecessor `RunMemento` CIDs whose outputs this run consumed. Empty array `[]` when the run has no run-predecessors. Explicit lineage; replay does not depend on reverse lookup. |
| header | `kind` | yes | MUST be `"proof-run"`. |
| header | `link_bundle_cid` | yes | CID of the `LinkBundle` consumed by the run, per `2026-05-03-bridge-linkage-protocol.md`. Also appears in `input_artifact_cids`. |
| header | `output_artifact_cids` | yes | Artifact CIDs this run produced (`DischargeReceipt`s, `CounterexampleReceipt`s, follow-on derived mementos). May be empty for `refused` runs. Sorted ascending for canonical form. |
| header | `plugin_registry_cid` | yes | CID of the `PluginRegistryMemento` sealed at run start, per `2026-05-12-plugin-protocol.md` §9. Also appears in `input_artifact_cids`. |
| header | `proof_envelope_cid` | yes | CID of the `.proof` bundle or proof envelope being verified. This is the run's claim root. Also appears in `input_artifact_cids`. |
| header | `schemaVersion` | yes | MUST be `"1"` for this spec version. |
| header | `sealed_at` | yes | ISO-8601 timestamp at which the final run verdict was sealed. |
| header | `stage_receipt_cids` | yes | Ordered list of `StageReceipt` CIDs in execution order. Order length and stage sequence MUST match the pipeline named by `verifier_pipeline_cid`. |
| header | `verdict` | yes | Run verdict per §5. |
| header | `verifier_pipeline_cid` | yes | CID of the `VerifierPipelineMemento` (deferred spec, see TSavo/sugar#799) that pins the ordered stage vocabulary for this run's verifier version. The vocabulary is NOT baked into this spec. |
| metadata | `note` | no | Human-readable operator note. Omitted when absent. |
| metadata | `source_url` | no | Optional URL or locator for the run context, CI job, or artifact page. Omitted when absent. |

### §2.2 `StageReceipt` fields

| Layer | Field | Required | Meaning |
|---|---|---:|---|
| envelope | `declaredAt` | yes | ISO-8601 timestamp at which the stage receipt was declared. |
| envelope | `signature` | yes | Ed25519 signature over `JCS({header, metadata})`. |
| envelope | `signer` | yes | Public key of the verifier, verifier worker, or extension plugin that emitted the receipt. |
| header | `cid` | yes | Content CID of this stage receipt, DERIVED per §4. |
| header | `diagnostics` | yes | Structured warnings, informational messages, and non-fatal replay notes. Producers MUST use deterministic JSON values and MUST NOT place volatile data here when replay identity depends on it. Empty array means no diagnostics. |
| header | `finished_at` | yes | ISO-8601 timestamp when the stage completed or stopped. See §7 for replay treatment. |
| header | `input_cids` | yes | Non-empty set of CIDs read by the stage, sorted ascending by bytewise CID unless a stage-specific memento records an ordered input. |
| header | `kind` | yes | MUST be `"stage-receipt"`. |
| header | `output_cids` | yes | CIDs produced or accepted as durable outputs by the stage, sorted ascending by bytewise CID unless the stage output memento records order. Empty array is allowed only when the stage produced no durable CID output. |
| header | `refusal_cids` | yes | CIDs of explicit refusal mementos produced by the stage, sorted ascending by bytewise CID. Empty array means no explicit refusal. |
| header | `schemaVersion` | yes | MUST be `"1"` for this spec version. |
| header | `stage_name` | yes | Canonical stage label from §3, or an extension label. |
| header | `started_at` | yes | ISO-8601 timestamp when the stage began. See §7 for replay treatment. |
| header | `verdict` | yes | Stage verdict per §5. |
| metadata | `note` | no | Human-readable note. Omitted when absent. |

Any stage output that is consumed by a later stage and is not already a substrate memento MUST be materialized as a content-addressed stage-output memento and listed in `output_cids`. In-memory-only transfer is allowed inside an implementation, but it is not admissible unless the same bytes are recoverable from the receipt chain.

## §3. Stage Canonical Labels

The canonical labels are the current Rust verifier module labels. They are intentionally not the older CLI prose label "six-stage verifier".

| Order | `stage_name` | Source evidence | Consumes | Produces |
|---:|---|---|---|---|
| 1 | `load_all_proofs` | `implementations/rust/sugar-verifier/src/load_all_proofs.rs:3` | `proof_envelope_cid`, `.proof` member bytes, extra project proof roots | Accepted member CIDs, bundle-membership index mementos when materialized, load-error refusal CIDs or diagnostics |
| 2 | `enumerate_callsites` | `implementations/rust/sugar-verifier/src/enumerate_callsites.rs:3` | Loaded contract and bridge memento CIDs | Deterministic callsite-set memento CIDs |
| 3 | `resolve_target` | `implementations/rust/sugar-verifier/src/resolve_target.rs:3` | Callsite-set CIDs, bridge target CIDs, `LinkBundle` membership facts | Resolved-property-set memento CIDs, forward-pin refusal CIDs |
| 4 | `instantiate` | `implementations/rust/sugar-verifier/src/instantiate.rs:3` | Resolved-property CIDs and call argument term CIDs or their enclosing callsite-set CID | Obligation memento CIDs. The implication-handshake path in `runner.rs` and `handshake.rs` is part of this discharge-preparation stage unless a future extension splits it. |
| 5 | `smt_emit` | `implementations/rust/sugar-verifier/src/smt_emitter.rs:3` | Obligation memento CIDs or implication-obligation CIDs | SMT artifact CIDs or compiler refusal CIDs |
| 6 | `solve_obligation` | `implementations/rust/sugar-verifier/src/solve_obligation.rs:3` | SMT artifact CIDs, solver-plan plugin CIDs from the sealed registry | Discharge receipt CIDs, implication memento CIDs, solver refusal CIDs |
| 7 | `report` | `implementations/rust/sugar-verifier/src/report.rs:3` | Prior stage receipt CIDs, callsite verdict CIDs, load-error CIDs | Final report memento CIDs and terminal diagnostics |

The top-level verifier source also enumerates the seven-stage sequence in `implementations/rust/sugar-verifier/src/lib.rs:5-30`, while the runner states that it composes seven stages in `implementations/rust/sugar-verifier/src/runner.rs:3-6`.

Extension stages MAY appear before, after, or between canonical stages only when the sealed `PluginRegistryMemento` names the extension plugin and the extension stage declares its ordering constraints. A canonical verifier MUST NOT silently drop an unknown extension stage from `stage_receipt_cids`; it MUST either replay it through the registry or refuse the run.

## §4. CID Construction

`ProofRunMemento.header.cid` and `StageReceipt.header.cid` are DERIVED with the same rule:

```
cid_input = JCS(header object with the cid field elided)
cid = "blake3-512:" ++ hex(BLAKE3-512(cid_input))
```

All header fields except `cid` itself are part of the CID input. For `ProofRunMemento`, this includes `sealed_at`, `stage_receipt_cids`, and `verdict`. For `StageReceipt`, this includes `diagnostics`, `started_at`, `finished_at`, `input_cids`, `output_cids`, `refusal_cids`, `stage_name`, and `verdict`.

The envelope signature is computed after `header.cid` is filled:

```
signature_input = JCS({ "header": header, "metadata": metadata })
signature = Ed25519(signature_input, signer_private_key)
```

Validators MUST:

1. Parse the object.
2. Recompute `header.cid` from JCS-canonical header bytes with `cid` elided.
3. Reject if the asserted `header.cid` differs.
4. Verify `envelope.signature` over `JCS({header, metadata})`.
5. Reject if the signature does not verify under `envelope.signer`.

Every object and sub-object MUST use JCS alphabetical key order. Arrays are order-preserving under JCS; fields that are sets, including `input_cids`, `output_cids`, and `refusal_cids`, MUST be sorted as specified in §2. Fields whose order is semantic, including `stage_receipt_cids`, MUST preserve execution order.

## §5. Verdict Semantics

### §5.1 Stage verdicts

| `stage-verdict` | Meaning |
|---|---|
| `ok` | The stage completed, produced all required durable outputs, and emitted no warning diagnostics. |
| `warned` | The stage completed and produced all required durable outputs, but emitted deterministic diagnostics that do not invalidate the run. |
| `refused` | The stage failed closed. At least one reason MUST appear in `refusal_cids` or in a deterministic diagnostic that explains why a refusal memento could not be minted. |
| `skipped` | The stage did not execute. This is admissible only for an extension stage or a canonical stage whose skip condition is recorded in diagnostics and follows from earlier stage outputs. A skipped canonical stage with required inputs present makes the run `partial` or `refused` per §5.2. |

### §5.2 Run verdicts

| `run-verdict` | Required condition |
|---|---|
| `admissible` | All seven canonical stage receipts are present in the order listed in §3, every required extension stage is present, no stage has `verdict = "refused"` or invalid CID/signature, every canonical stage has `verdict = "ok"` or `"warned"`, all `refusal_cids` arrays are empty, and the `report` stage records no undischarged obligation or load-error row. |
| `refused` | Any mandatory stage refuses, any mandatory receipt is missing, any receipt CID or signature is invalid, any required input CID is absent from the replay pool, the plugin registry refuses, or the final report contains a hard failure that the verifier policy treats as non-composable. |
| `partial` | The run is replayable but not fully admissible: for example, an optional extension stage was skipped, a solver returned undecidable without a hard refusal, a warning is policy-bounded but prevents full admission, or the final report contains characterized residue that policy allows to be carried forward as incomplete evidence. |

`partial` is not success. It is a durable statement that the verifier reached a bounded but incomplete result. Downstream policy MAY reject `partial` runs even when the receipt chain is well-formed.

## §6. Lifecycle

1. At run start, the runtime loads CLI plugins and built-ins, then seals a `PluginRegistryMemento` per `2026-05-12-plugin-protocol.md` §9.
2. The runtime determines the canonical stage plan: the seven stages in §3 plus any extension stages admitted by the sealed registry.
3. As each stage starts, the runtime records the input CIDs it will read.
4. As each stage completes, the runtime materializes every load-bearing stage output as a CID-bearing artifact, fills `output_cids`, `refusal_cids`, `diagnostics`, timestamps, and `verdict`, derives the `StageReceipt` CID, signs the receipt, and appends the receipt CID to the in-progress run list.
5. A refused stage still emits a `StageReceipt` unless the process terminates before it can sign. If it cannot emit a receipt, the run cannot seal an admissible `ProofRunMemento`.
6. At the end of `sugar prove`, the runtime computes the run verdict from §5, fills `stage_receipt_cids` in execution order, derives the `ProofRunMemento` CID, signs it, and seals the run.

A `ProofRunMemento` MUST NOT be sealed before all stage receipts that contributed to its verdict are durable.

## §7. Federation and Replay

A verifier that receives a `ProofRunMemento` MUST be able to replay the run from content-addressed inputs:

1. Fetch and validate the `ProofRunMemento`.
2. Fetch and validate each `StageReceipt` named by `stage_receipt_cids`, preserving order.
3. Fetch the `ProofEnvelope` at `proof_envelope_cid`.
4. Fetch the `PluginRegistryMemento` at `plugin_registry_cid` and load the same plugin set and load order.
5. Fetch or reconstruct the `LinkBundle` at `link_bundle_cid`.
6. Re-execute each canonical and extension stage against the recorded input CIDs.
7. Confirm that the replayed output, refusal, diagnostic, and verdict fields match the recorded receipt fields.
8. Recompute each recorded `StageReceipt` CID and confirm byte identity.
9. Recompute the run verdict and confirm it matches `ProofRunMemento.header.verdict`.

Because `started_at`, `finished_at`, and `sealed_at` are part of the CID input, replay verification compares against the original recorded timestamp fields. A fresh replay MAY mint its own receipts with current timestamps, but those fresh receipt CIDs are distinct audit facts and MUST NOT be expected to match the original run's CIDs.

Federation follows from CID identity. Any verifier that accepts BLAKE3-512, JCS, Ed25519, the referenced specs, and the sealed plugin registry can validate the run without trusting the original machine, CI system, or operator.

## §8. Cross-References

- PEP 1.7.0 plugin protocol: `2026-05-12-plugin-protocol.md`. The `PluginRegistryMemento` is sealed at run start and is referenced by `ProofRunMemento.header.plugin_registry_cid`.
- Proof envelope and `.proof` bundle format: `2026-04-30-proof-file-format.md`. The verified proof root is referenced by `ProofRunMemento.header.proof_envelope_cid`.
- Link bundle: `2026-05-03-bridge-linkage-protocol.md`. The bridge closure consumed by the run is referenced by `ProofRunMemento.header.link_bundle_cid`.
- Admissibility spine umbrella: TSavo/sugar#796. This spec occupies the "proof runs + receipts" slot.
- Promotion decisions: TSavo/sugar#791. A `PromotionDecisionMemento` may cite a `ProofRunMemento` when promotion depends on a replayable proof run rather than on a terminal report string.

## §9. Out of Scope

- Partial-rerun caching.
- Distributed verification across multiple verifier authorities.
- Mid-stage checkpointing.
- A new durable shape for callsite-set, obligation-set, SMT artifact, or final report mementos. This spec requires such outputs to be content-addressed when they are load-bearing, but their inner schemas are follow-up work.
- Replacing the existing verifier implementation. This spec names the normative receipt boundary the implementation must converge on.
