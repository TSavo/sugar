# Report and Witness Interface

**Status:** grounded design draft against `cmd_prove.rs`, `report_fmt`, and `report_witness.rs`.  
**Date:** 2026-07-02

## 1. Purpose

`Report` is the terminal verdict summary for people and API consumers. A witness proof is the replayable content-addressed claim about that report or another evidence source.

The key boundary is: **reports summarize; witnesses pin.**

## 2. Prove report construction

`cmd_prove.rs::build_prove_report_with_options` currently performs the CLI-to-verifier handoff:

1. reads `.sugar/config.toml`,
2. builds `ComponentPlan` with `PlanIntent::Prove`,
3. fails on component-plan error diagnostics,
4. configures witness-discharge environment from planned/authored lift manifests,
5. resolves `--with` and `[verify].callees`,
6. asks kits for dependency proofs via RPC,
7. builds `RunnerConfig`,
8. builds compiler registry from the component plan,
9. runs `Runner::new_with_compilers(...).run_with_proof_run()`,
10. returns `artifact.report`.

The report is therefore downstream of the typed verifier run and upstream of optional witness minting.

## 3. Report witness output

```rust
pub(crate) struct ReportWitnessProof {
    pub name: String,
    pub proof_cid: String,
    pub proof_file: PathBuf,
    pub witness_cid: String,
    pub evidence_cid: String,
    pub evidence_file: PathBuf,
}
```

This is the CLI-side receipt for witness minting. It names both the proof bundle and the external evidence sidecar.

## 4. Witness options

```rust
pub(crate) struct JsonWitnessOptions {
    pub produced_by: Option<String>,
    pub produced_at: Option<String>,
    pub verifier_cid: Option<String>,
    pub policy_cid: Option<String>,
    pub extra_input_cids: Vec<String>,
    pub proof_metadata: BTreeMap<String, String>,
    pub plan_cid: Option<String>,
    pub actual_output_cids: Vec<String>,
}
```

Current invariant: `actual_output_cids` requires `plan_cid`. This prevents a toolchain-output witness from claiming outputs without pinning the plan that authorized those outputs.

## 5. Report witness shape

`mint_report_witness(project_root, report_json, replay_pins, out_dir)` builds:

```json
{
  "kind": "sugar-prove-report-evidence",
  "schemaVersion": "1",
  "reportCid": "<jcs-cid(report)>",
  "replayPinsCid": "<jcs-cid(replayPins)>",
  "report": { ... },
  "replayPins": { ... }
}
```

and a claim body:

```json
{
  "kind": "sugar-prove-report-witness",
  "schemaVersion": "1",
  "reportCid": "<cid>",
  "replayPinsCid": "<cid>",
  "project": "<project root>",
  "summary": {
    "totalCallsites": <...>,
    "discharged": <...>,
    "violations": <...>,
    "refused": <...>,
    "loadErrors": <count>
  }
}
```

The evidence sidecar contains the bulky report and replay pins. The proof envelope carries a witness memento pointer.

## 6. Generic JSON witness shape

`mint_json_witness_with_options` constructs a witness body:

```json
{
  "kind": "sugar-json-witness-body",
  "schemaVersion": "1",
  "claimKind": "<claim kind>",
  "claimBodyCid": "<jcs-cid(claimBody)>",
  "evidenceRootCid": "<jcs-cid(evidence)>",
  "verifierCid": "<verifier cid or builtin tag>",
  "policyCid": "<policy cid or builtin tag>",
  "claimBody": { ... },
  "evidence": { ... },
  "toolchainScope": { ... optional ... }
}
```

Then it creates a `witness-memento` pointer with:

- `witness_cid` / `witnessCid`,
- `witness_kind` / `witnessKind`,
- signer and signature,
- claim/evidence/verifier/policy CIDs,
- `inputCids`,
- `producedBy`,
- `producedAt`,
- optional `planCid` and `actualOutputCids`.

That pointer is JCS-encoded, CID-checked against `WitnessMemento::new`, pushed into a `ProofGraph`, and sealed with `build_proof_envelope`.

## 7. Replay pins

`cmd_prove.rs::build_replay_pins` currently pins:

```json
{
  "kind": "sugar-prove-replay-pins",
  "schemaVersion": "1",
  "producer": { "package": "...", "version": "..." },
  "projectConfig": { ... },
  "lifters": [ ... ],
  "solvers": [ ... ],
  "proofInputs": [ ... ],
  "witnessSources": [ ... ]
}
```

This is the right separation: the report says what happened; replay pins say what inputs and tools would be needed to test that claim again.

## 8. Configured witness sources

`ProjectConfig::WitnessEntry` supports:

```rust
pub struct WitnessEntry {
    pub name: String,
    pub kind: String,        // report | command | file
    pub command: Vec<String>,
    pub working_dir: Option<String>,
    pub path: Option<String>,
}
```

`cmd_prove.rs::emit_configured_witnesses` interprets:

- `report`: built-in prove report witness,
- `command`: run command, capture stdout/stderr/exit status as evidence,
- `file`: pin arbitrary bytes by path as evidence.

Unknown kinds fail with a user error rather than silently skipping.

## 9. Witness discharge configuration

The witness-discharge path resolves each lift surface's manifest — authored
or planned — and builds a typed `WitnessDischargeContext` (project_dir +
`resolve_witness_command` resolvers). That typed context is the sole config
channel (#3809 step 3; #3860).

`SUGAR_WITNESS_DISCHARGE_<TOOL>` is **not** a config channel: there is no
production reader, and production no longer stages those env vars. Showcase
lie scripts may still set the env as process pollution to prove the package
recompute path ignores kit-stdout lies. Verdict inputs remain
content-addressed (packageCid + contract + resolver body).

The important interface point is that witness recompute rides the same
manifest as lift (`resolve_witness_command`). There is no separate bespoke
discharge registry and no process-env side channel for discharge commands.

## 10. Invariants

1. **Evidence is external and pinned:** bulky witness evidence is sidecar bytes addressed by CID; proof carries the pointer memento.
2. **Claim body and evidence root are independently addressed:** `claimBodyCid` and `evidenceRootCid` are both included in input CIDs.
3. **Signatures cover the witness CID:** current signer signs `witness_cid.as_bytes()`.
4. **Toolchain outputs require a plan:** `actualOutputCids` without `planCid` is rejected.
5. **Witness config fails closed:** unsupported witness kinds return errors.
6. **Report JSON is not replay proof by itself:** replay requires pins and/or witness proof.

## 11. Migration target

The target is a typed witness API:

```rust
pub enum WitnessSource {
    Report { report: Report, replay_pins: ReplayPins },
    Command { name: WitnessName, command: CommandSpec },
    File { name: WitnessName, path: ProjectRelativePath },
}

pub struct WitnessBundle {
    pub pointer: WitnessMemento,
    pub evidence: EvidenceSidecar,
    pub proof: ProofEnvelopeOutput,
}
```

`serde_json::Value` can remain the external evidence encoding, but source selection, claim kind, input CIDs, and toolchain scope should be typed before minting.
