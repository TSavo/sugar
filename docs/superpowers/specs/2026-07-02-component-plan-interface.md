# Component Plan Interface

**Status:** grounded design draft against current `sugar-cli/src/component_plan.rs`.  
**Date:** 2026-07-02

## 1. Purpose

`ComponentPlan` is Sugar's zero-config rendezvous contract. It answers: given a workspace and an intent, which plugins, lift manifests, and IR compilers are allowed to participate?

The planner owns generic discovery and composition. Components own language and tool semantics. That split is stated directly in `component_plan.rs` lines 3-9 and expressed in the exported typed surface at lines 28-126.

## 2. Inputs

```rust
pub fn plan_workspace(project_root: &Path, intent: PlanIntent) -> ComponentPlan

pub fn plan_workspace_with_options(
    project_root: &Path,
    intent: PlanIntent,
    options: ComponentPlanOptions,
) -> ComponentPlan
```

### `PlanIntent`

```rust
pub enum PlanIntent {
    Lift,
    Prove,
    Verify,
}
```

Intent is not display text. It is part of the routing key sent to component planners through `COMPONENT_PLAN_RPC_METHOD = "sugar.component.plan"` and serialized by `PlanIntent::as_str()` as `lift`, `prove`, or `verify`.

### `ComponentPlanOptions`

```rust
pub struct ComponentPlanOptions {
    pub allow_failed_components: bool,
}
```

Current behavior: a failed component planner is an `Error` diagnostic unless `allow_failed_components` is set, in which case it becomes a `Warning` diagnostic. `cmd_lift.rs` and `cmd_prove.rs` both thread this option from CLI args.

## 3. Workspace census

The planner starts with `WorkspaceCensus`:

```rust
pub struct WorkspaceCensus {
    pub languages: Vec<LanguageEvidence>,
    pub items: Vec<ForensicItem>,
}

pub struct LanguageEvidence {
    pub language: String,
    pub path: String,
    pub reason: String,
}

pub struct ForensicItem {
    pub id: String,
    pub kind: String,
    pub path: String,
    pub language_hint: Option<String>,
    pub reason: String,
}
```

Current census evidence is intentionally modest and deterministic: `Cargo.toml` and source extensions for Rust, Java, and Python are collected in `census_workspace` / `collect_forensic_items` (`component_plan.rs` lines 386-488). The census is evidence for routing; it is not a language parser and must not be treated as semantic proof.

## 4. Output type

```rust
pub struct ComponentPlan {
    pub plugins: Vec<PluginEntry>,
    pub lift_manifests: Vec<PlannedLiftManifest>,
    pub ir_compilers: Vec<PlannedIrCompiler>,
    pub diagnostics: Vec<ComponentDiagnostic>,
    pub census: WorkspaceCensus,
}
```

### `plugins`

`plugins` is the command-facing projection. It uses `ProjectConfig::PluginEntry`:

```rust
pub struct PluginEntry {
    pub name: Option<String>,
    pub kind: Option<String>,       // "lift" | "emit" | legacy absent
    pub surface: String,
    pub workspace_override: Option<String>,
    pub emit: Option<String>,
    pub layer: Option<String>,
}
```

This is consumed by lift graph/report selection and by `lift_options_for_plugin` in `cmd_lift.rs`.

### `lift_manifests`

```rust
pub struct PlannedLiftManifest {
    pub surface: String,
    pub name: String,
    pub version: Option<String>,
    pub protocol_version: Option<String>,
    pub command: Vec<String>,
    pub working_dir: Option<PathBuf>,
    pub method: Option<String>,
    pub phase: Option<String>,
    pub discharge_command: Vec<String>,
    pub witness_tool: Option<String>,
    pub resolve_witness_command: Vec<String>,
    pub resolve_witness_method: Option<String>,
}
```

This is the typed replacement for a discovered `.sugar/lift/<surface>/manifest.toml` when no authored manifest exists. `cmd_prove.rs::find_manifest_with_plan` converts it into the local witness-discharge manifest shape; `lift_plugin.rs` can also find a planned manifest through `component_plan::planned_lift_manifest`.

### `ir_compilers`

```rust
pub struct PlannedIrCompiler {
    pub name: String,
    pub version: Option<String>,
    pub protocol_version: String,
    pub command: Vec<String>,
    pub working_dir: Option<PathBuf>,
    pub dialects: Vec<String>,
    pub supported_sorts: Vec<String>,
    pub supported_predicates: Vec<String>,
}
```

`component_plan::compiler_registry_from_plan` registers only compilers matching `sugar_ir_compiler::PROTOCOL_VERSION` and only for dialects not already registered. That makes the plan additive and compatibility-checked.

## 5. Diagnostics contract

```rust
pub struct ComponentDiagnostic {
    pub level: DiagnosticLevel,
    pub message: String,
}

pub enum DiagnosticLevel {
    Info,
    Warning,
    Error,
}
```

Commands must fail closed on the first error diagnostic unless explicitly running in an allow-failed mode. `cmd_prove.rs::check_component_plan_errors` enforces that before constructing `RunnerConfig`.

## 6. Invariants

1. **Explicit config wins:** authored project/user manifests override planning. Component planning is the default only when explicit config is absent.
2. **Component failure is loud:** failure becomes a diagnostic, not silent absence.
3. **Deduplication before use:** planner dedupes plugins, manifests, and compilers before returning the plan.
4. **Ordering is meaningful:** plugin ordering is normalized by `order_component_plugins`; consumers must not resort casually.
5. **Protocol version is load-bearing:** planned IR compilers with incompatible `protocol_version` are skipped, not registered.

## 7. Current migration opportunities

- Unify the two manifest projections (`LiftPluginManifest` in `lift_plugin.rs` and local `PluginManifest` in `cmd_prove.rs`) around `PlannedLiftManifest` plus authored-manifest parser output.
- Make component diagnostics structured beyond `message: String` once they cross machine-consumed boundaries.
- Surface a single `PlanArtifact` memento when component planning affects a proof run, so replay can pin the exact selected components rather than recomputing discovery.
