# IR Compiler and Solver Interface

**Status:** grounded design draft against `sugar-ir-compiler` and `sugar-verifier/src/solvers`.  
**Date:** 2026-07-02

## 1. Purpose

The compiler/solver seam transforms ProofIR obligations into tool-specific artifacts, executes a configured solver plan, and returns typed verdict telemetry. The compiler is responsible for sound translation. The solver is responsible for running a concrete proof/search/checking tool and reporting what happened.

## 2. Compiler trait

```rust
pub trait IrCompiler: Send + Sync {
    fn compile(&self, ir: &Json, dialect: &str) -> Result<CompiledFormula, CompileError>;
    fn capabilities(&self) -> Capabilities;
}
```

The protocol version is currently:

```rust
pub const PROTOCOL_VERSION: &str = "sugar-ir-compiler/1";
```

Component-planned compilers are registered only when their `protocol_version` matches this value.

## 3. CompiledFormula

```rust
pub struct CompiledFormula {
    pub preamble: String,
    pub body: String,
    pub free_vars: Vec<FreeVar>,
    pub opacity_manifest: OpacityManifest,
    pub metadata: Json,
}
```

Field semantics:

| Field | Meaning |
|---|---|
| `preamble` | Logic declarations and variable declarations. |
| `body` | Assertion plus dialect driver terminator. |
| `free_vars` | Declared variables and dialect-native sorts. |
| `opacity_manifest` | Positions not soundly translated; empty only when coverage is total. |
| `metadata` | Dialect-specific structured data for solver adapters. |

`CompiledFormula::script()` is only `preamble + body`. The script is not the whole compiler output.

## 4. Capabilities

```rust
pub struct Capabilities {
    pub name: String,
    pub version: String,
    pub protocol_version: String,
    pub dialects: Vec<String>,
    pub supported_sorts: Vec<String>,
    pub supported_predicates: Vec<String>,
}
```

Capabilities are the routing surface. They decide whether a compiler can claim a dialect and what it claims to translate.

## 5. Solver configuration

The `[solvers]` table maps to:

```rust
pub struct SolverConfig {
    pub binary: String,
    pub ir_compiler: String,
    pub timeout_seconds: Option<u64>,
    pub flags: Vec<String>,
    pub ceta_gate: bool,
    pub ceta_binary: String,
    pub termination_prover: String,
    pub confluence_checker: String,
    pub version: String,
    pub binary_cid: Option<String>,
    pub vendor_pin: Option<String>,
    pub lake_project: Option<String>,
    pub lean_toolchain: Option<String>,
}
```

Plans are exactly one of default, chain, portfolio, or dispatch. Current comments say `default` wins if multiple are present.

```rust
pub enum SolverSeat {
    Maude, Z3, Cvc5, Vampire, Coq, Lean, Bitwuzla, Yices2, Mathsat,
}
```

## 6. Solver trait

```rust
pub trait Solver: Send + Sync {
    fn name(&self) -> &str;
    fn version(&self) -> &str;
    fn ir_compiler(&self) -> &str;
    fn identity(&self) -> SolverIdentity;
    fn solve(&self, smt: &str) -> SolveResult;
    fn solve_compiled(&self, compiled: &CompiledFormula) -> SolveResult;
}
```

The default `solve_compiled` calls `compiled.script()`. Specialized solvers may consume `CompiledFormula.metadata`.

## 7. Solver identity and result

```rust
pub struct SolverIdentity {
    pub artifact_cid: Option<String>,
    pub invocation_cid: Option<String>,
    pub vendor_memento_cid: Option<String>,
    pub vendor_memento: Option<Json>,
}

pub struct SolveResult {
    pub verdict: ObligationVerdict,
    pub solver_name: String,
    pub solver_version: String,
    pub error: String,
    pub solver_stdout: String,
    pub wall_clock: Duration,
    pub timed_out: bool,
}
```

Human labels are diagnostics. Replay pins are CIDs. Vendor address spaces are carried as mementos and related to Sugar CIDs rather than substituted for them.

## 8. Plan executor

```rust
pub struct SolverInvocation {
    pub authoritative: bool,
    pub compiler: String,
    pub identity: SolverIdentity,
    pub result: SolveResult,
}

pub fn run_plan_with_compilers(
    plan: &SolverPlan,
    registry: &Registry,
    compilers: &CompilerRegistry,
    formula: &Json,
) -> (ObligationVerdict, String, Vec<SolverInvocation>)
```

Execution semantics:

| Plan | Semantics |
|---|---|
| `Single` | Invoke one solver; that invocation is authoritative. |
| `Chain` | Invoke sequentially; first definitive verdict wins. |
| `Portfolio { first-wins }` | Run all in parallel; fastest definitive verdict wins after collection. |
| `Portfolio { consensus }` | Definitive verdicts must agree; disagreement is a distinct loud result. |
| `Dispatch` | Classify the formula and select a solver by theory/config. |

`SolverInvocation.authoritative` is the typed handoff to report and memento minting: every invocation may be useful telemetry, but only the authoritative one decides the callsite verdict.

## 9. Runner integration

`RunnerConfig` carries:

```rust
pub struct RunnerConfig {
    pub project_root: PathBuf,
    pub z3_path: String,
    pub cache_dir: Option<PathBuf>,
    pub mint_seed: Option<[u8; 32]>,
    pub mint_producer_id: Option<String>,
    pub trusted_implication_signers: Vec<String>,
    pub solvers_config: Option<SolversConfig>,
    pub extra_projects: Vec<PathBuf>,
    pub extra_proof_files: Vec<PathBuf>,
    pub extra_proofs: Vec<ProofBytes>,
}
```

`Runner::new_with_compilers` resolves solver config in order:

1. explicit `cfg.solvers_config`,
2. `.sugar/config.toml`,
3. legacy single Z3 fallback at `cfg.z3_path`.

`cmd_prove.rs` constructs this config after component planning and passes a compiler registry built from that same plan.

## 10. Invariants

1. **Compiler opacity is load-bearing:** a solver discharge is not complete if the compiler marked relevant positions opaque without a separate admissible discharge.
2. **Solver identity is CID-addressed:** names and versions are not replay roots.
3. **Plan semantics are centralized:** report code must not re-decide first-wins, consensus, or dispatch behavior.
4. **Definitive verdicts are explicit:** `Discharged` and `Unsatisfied` are definitive; `Undecidable`, timeout, parse error, and missing solver are not.
5. **Telemetry is typed:** wall clock, timeout, stdout, error, compiler, and identity cross as `SolveResult` / `SolverInvocation`, not parsed report strings.

## 11. Current drift / cleanup

- `solvers/mod.rs` comment says first-wins remaining solvers are best-effort cancelled, while `plan.rs` says subprocess cancellation is not implemented and all continue until natural completion or timeout. The code in `plan.rs` is authoritative for current behavior.
- The old `z3_path` fallback remains in `RunnerConfig`; it should be treated as compatibility, not the long-term solver interface.
- `SolveResult.error` and `solver_stdout` are raw strings. If they become replay artifacts, they should be pinned as sidecar evidence with CIDs and structured exit metadata.
