# Lift Plugin Interface

**Status:** grounded design draft against current `sugar-cli/src/lift_plugin.rs` and `cmd_lift.rs`.  
**Date:** 2026-07-02

## 1. Purpose

The lift interface turns a workspace and a selected surface into a substrate claim. It is the boundary between language/tool-owned semantics and Sugar's proof substrate.

Current code says this boundary is split intentionally: `libsugar::core::Kit` owns transport and primitive claim construction, while `sugar-cli/src/lift_plugin.rs` resolves the surface manifest, builds the request, and maintains legacy CLI response compatibility.

## 2. Manifest type

```rust
pub(crate) struct LiftPluginManifest {
    pub name: String,
    pub version: Option<String>,
    pub protocol_version: Option<String>,
    pub command: Vec<String>,
    pub working_dir: Option<PathBuf>,
    pub method: Option<String>,
    pub phase: Option<String>,
}
```

Resolution order in current code:

1. `<project>/.sugar/lift/<surface>/manifest.toml`
2. `$HOME/.config/sugar/lift/<surface>/manifest.toml`
3. discovered component plan manifest via `component_plan::planned_lift_manifest(project_root, surface)`

The manifest's `command` is required. `method` defaults to the kit's lift method unless present. `phase = "consumer"` is meaningful; anything else falls back to producer behavior through `surface_phase`.

## 3. Request options

```rust
pub struct LiftPluginOptions {
    pub identify_only: bool,
    pub library_bindings: bool,
    pub workspace_override: Option<String>,
    pub emit: Option<String>,
    pub layer: Option<String>,
    pub report_summary: bool,
    pub contract_bindings: Vec<Value>,
}
```

Option semantics currently encoded in comments and callsites:

| Field | Meaning |
|---|---|
| `identify_only` | Request identity/package-inspection output instead of full lift. |
| `library_bindings` | Ask lifter for library binding surfaces. |
| `workspace_override` | Replace `workspace_root` for this plugin only; used for dependency source shims. |
| `emit` | Pass `options.emit`; `ir-document` opts a self-minting plugin into composable mode. |
| `layer` | Explicit layer override (`all`, `library-bindings`, `identify-only` patterns). |
| `report_summary` | Ask reporting-capable lifter for summary accounting instead of full sidecars. |
| `contract_bindings` | Forward producer contract CIDs to consumer surfaces. |

## 4. Output session

```rust
pub(crate) struct LiftPluginSession {
    pub claim: DomainClaim,
    legacy_response: Value,
}
```

The typed output is `DomainClaim`. The legacy response remains because `cmd_lift.rs` still renders reports and prepares mint/prove inputs from JSON response projections.

### Required direction

New consumers should consume `claim` or an explicit typed projection of `claim`. They should not add new dependencies on `legacy_response` unless the work is explicitly a compatibility adapter.

## 5. Path execution shape

`dispatch_lift_path` is the current typed path route. It constructs:

```rust
Input::Source { dialect, bytes: serde_json::to_vec(&lift_params) }
Input::Path(Box::new(CorePath {
    algebra: vec![PathAlgebra {
        name: "lift".to_string(),
        kit: format!("lift-{surface}"),
        inputs: vec![source_cid],
        depends_on: vec![],
        verb: Verb::Transform,
    }],
}))
```

Then it registers a `LiftKit` in `KitRegistry` if a manifest exists and runs `execute_path`. That means lift is already expressible as a core path transform, not just as a special CLI subprocess.

## 6. Failure type

```rust
pub(crate) enum LiftPluginError {
    MissingBinary { binary: String },
    Refused(Box<CompositionRefusalMemento>),
    Failed(String),
}
```

This is the right shape: missing environment, substrate refusal, and ordinary failure are distinct. The remaining weak point is `Failed(String)` for machine-crossing detail. If this crosses into replay artifacts, it should become a structured diagnostic/refusal memento.

## 7. Lift report seam

`cmd_lift.rs` currently does three jobs after dispatch:

1. validate identify-only response kind,
2. render source report / summary report,
3. optionally call `cmd_prove::build_prove_report_with_options` and merge prove results into lift report output.

That is useful CLI behavior, but it means the lift command is both a substrate transform and a report orchestrator. Future typed design should name those as separate interfaces:

```rust
LiftRequest -> LiftPluginSession
LiftPluginSession -> SourceReport
(SourceReport, Option<Report>) -> RenderedLiftReport
```

## 8. Invariants

1. **Manifest command required:** no command means the surface is unusable.
2. **Working directory is resolved relative to project root:** manifest paths are not interpreted relative to the process CWD.
3. **Surface chooses dialect, but unknown surfaces are allowed:** unknown names become `Dialect::Other(surface)`, preserving extension ability.
4. **Consumer lift is explicit:** only manifest `phase = "consumer"` gets consumer behavior.
5. **Claim payload is stripped after legacy extraction in path mode:** `dispatch_lift_path` clones the payload response, then clears `claim.payload`; the claim remains the durable output.

## 9. Migration target

The final lift interface should be:

```rust
pub struct LiftRequest {
    pub project_root: PathBuf,
    pub surface: SurfaceId,
    pub options: LiftPluginOptions,
    pub manifest: ResolvedLiftManifest,
}

pub struct LiftOutput {
    pub claim: DomainClaim,
    pub response_projection: Option<LiftResponseProjection>, // compatibility only
    pub diagnostics: Vec<LiftDiagnostic>,
}
```

`LiftResponseProjection` should shrink over time until all report/mint/prove callers consume typed claim projections.
