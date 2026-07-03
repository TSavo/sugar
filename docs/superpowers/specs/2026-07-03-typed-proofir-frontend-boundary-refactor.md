# Typed ProofIR Frontend Boundary Refactor

**Status:** design doc for a refactor of the existing IR compiler stack.  
**Date:** 2026-07-03  
**Scope:** `sugar-ir-compiler`, bundled compiler backends, verifier solver planning, and the frontend decode seam.  
**Non-goal:** this is not a new compiler project. The compiler already exists; this refactor moves the existing frontend/backend boundary from transport JSON to typed ProofIR.

## 1. Thesis

The IR compiler boundary is currently shaped like this:

```text
serde_json::Value ProofIR transport
  -> IrCompiler backend
  -> CompiledFormula
  -> Solver::solve_compiled
```

The desired refactor shape is:

```text
JSON frontend            Binary frontend
  -> decode/typecheck      -> decode/typecheck
          \                 /
           -> Typed ProofIR
                    -> existing IrCompiler backends
                    -> CompiledFormula
                    -> existing Solver::solve_compiled
```

The completion test is strict:

> Replace the JSON frontend with a binary frontend and make **zero backend changes**.

That is the evidence that serialization format terminates at the frontend and that types are the only payload crossing from frontend to backend.

## 2. Existing compiler, not new compiler

The repo already has the compiler spine. The refactor should preserve it.

Evidence:

- `sugar-ir-compiler/src/lib.rs:3-8` defines this crate as the “IR compiler protocol core” and names the manifest/JSON-RPC/compiler trait responsibilities.
- `sugar-ir-compiler/src/lib.rs:28-47` defines `CompiledFormula` as the compiler product: `preamble`, `body`, `free_vars`, `opacity_manifest`, and `metadata`.
- `sugar-ir-compiler/src/lib.rs:49-52` defines `CompiledFormula::script()` as only `preamble + body`, confirming that the emitted script is a projection of the compiler product, not the whole product.
- `sugar-ir-compiler/src/registry.rs:12-18` defines a dialect-keyed compiler registry.
- `sugar-verifier/src/solvers/plan.rs:69-81` already has `run_plan_with_compilers`, which passes a ProofIR formula through compiler selection before solving.
- `sugar-verifier/src/solvers/plan.rs:392-400` already routes compiled artifacts to `solver.solve_compiled(&compiled)`.
- `sugar-verifier/src/solvers/mod.rs:77-88` already exposes `Solver::ir_compiler()` and `Solver::solve_compiled()`.

So the work is not “introduce a compiler.” The work is “make the existing compiler boundary typed enough that frontends are swappable.”

## 3. Current drift: transport still crosses the backend boundary

Today, the public in-process compiler trait accepts transport JSON:

```rust
pub trait IrCompiler: Send + Sync {
    fn compile(&self, ir: &Json, dialect: &str) -> Result<CompiledFormula, CompileError>;
    fn capabilities(&self) -> Capabilities;
}
```

Source: `sugar-ir-compiler/src/lib.rs:98-107`.

The registry preserves the same untyped transport ingress:

```rust
pub fn compile(
    &self,
    ir: &serde_json::Value,
    dialect: &str,
) -> Result<crate::CompiledFormula, CompileError>
```

Source: `sugar-ir-compiler/src/registry.rs:47-58`.

Bundled backends implement the same shape:

- SMT-LIB: `SmtLibCompiler::compile(&self, ir: &Json, dialect: &str)` at `sugar-ir-compiler-smt-lib/src/lib.rs:42-48`.
- Lean: `LeanCompiler::compile(&self, ir: &Json, dialect: &str)` at `sugar-ir-compiler-lean/src/lib.rs:35-41`.
- Coq: `CoqCompiler::compile(&self, ir: &Json, dialect: &str)` at `sugar-ir-compiler-coq/src/lib.rs:81-99`.
- Maude: `MaudeCompiler::compile(&self, ir: &Json, dialect: &str)` at `sugar-ir-compiler-maude/src/lib.rs:134-140`.
- JSON-RPC wrappers: `LazyJsonRpcCompiler::compile(&self, ir: &Json, ...)` and `JsonRpcCompiler::compile(&self, ir: &Json, ...)` at `sugar-ir-compiler/src/subprocess.rs:186-229`.

The JSON-RPC wire protocol is also explicitly transport JSON:

- Client sends params `{ "ir_json": ir, "target_dialect": dialect }` at `sugar-ir-compiler/src/subprocess.rs:235-243`.
- Server reads `params.ir_json`, clones it, then calls `compiler.compile(&ir, dialect)` at `sugar-ir-compiler/src/server.rs:69-89`.

This is the seam to refactor. The backend contract should not know whether the source obligation arrived as JSON text, JSON-RPC JSON, CBOR, protobuf, postcard, capnp, or an in-memory generated value.

## 4. Current typed substrate already exists

The refactor should reuse existing typed ProofIR definitions rather than inventing a new compiler IR.

Evidence:

- `sugar-ir-types/src/lib.rs:340-365` defines `IrTerm` as a typed Rust enum.
- `sugar-ir-types/src/lib.rs:381-453` defines `IrFormula` as a typed Rust enum.
- `sugar-ir-types/src/lib.rs:462-463` aliases `Term = IrTerm` and `Formula = IrFormula`.

The backends already deserialize JSON into those types internally:

- SMT-LIB: `compile_to_parts` deserializes `Json` to `sugar_ir_types::Formula`, validates, checks mixed-sort conjunctions, then emits: `sugar-ir-compiler-smt-lib/src/lib.rs:267-274`.
- Lean: `compile_to_parts` deserializes term/formula JSON into `Term` / `Formula`: `sugar-ir-compiler-lean/src/lib.rs:89-114`.
- Coq: `compile_inner` deserializes term/formula JSON into `Term` / `Formula`: `sugar-ir-compiler-coq/src/lib.rs:56-71`.
- Maude: `compile_artifact` deserializes into a backend-local `RawObligation` whose equation terms are typed `IrTerm`: `sugar-ir-compiler-maude/src/lib.rs:56-109` and `sugar-ir-compiler-maude/src/lib.rs:162-165`.

This proves the backend logic is already trying to operate on types. The JSON step is an ingress artifact, not the semantic substrate.

## 5. Boundary law

**Serialization formats terminate at frontends. Typed obligations cross into backends.**

Allowed at frontend ingress:

```rust
JsonFrontend::decode(&str | &[u8]) -> Result<TypedProofIr, FrontendError>
BinaryFrontend::decode(&[u8]) -> Result<TypedProofIr, FrontendError>
GeneratedFrontend::from_parts(...) -> Result<TypedProofIr, FrontendError>
```

Allowed at backend ingress:

```rust
IrCompiler::compile(&self, ir: &TypedProofIr, dialect: &str) -> Result<CompiledFormula, CompileError>
```

Not allowed at backend ingress after the refactor:

```rust
serde_json::Value
Json
RawValue
&str as source obligation
Vec<u8> as source obligation
```

Backend code may still emit target-language strings. That is not the issue. The issue is what carries ProofIR meaning across the frontend/backend boundary.

## 6. Proposed target types

Introduce one narrow in-process compiler input type in `sugar-ir-compiler`, backed by `sugar-ir-types`:

```rust
pub enum TypedProofIr {
    Formula(sugar_ir_types::Formula),
    Term(sugar_ir_types::Term),
    EquationalTheory(EquationalTheoryObligation),
}
```

The exact enum name can change. The important property is that each variant is typed and owns a contract.

Why include non-formula variants?

- SMT-LIB and Lean currently accept bare terms for legacy compatibility: SMT-LIB documents this at `sugar-ir-compiler-smt-lib/src/lib.rs:243-265`; Lean handles term input at `sugar-ir-compiler-lean/src/lib.rs:89-108`.
- Maude currently compiles an equational-theory document, not a normal `IrFormula`: `sugar-ir-compiler-maude/src/lib.rs:56-62` and `sugar-ir-compiler-maude/src/lib.rs:162-165`.

So `TypedProofIr` should not pretend every backend input is only `Formula`. It should make each existing accepted input class explicit.

Recommended first slice:

```rust
pub enum CompilerInput {
    Formula(sugar_ir_types::Formula),
    Term(sugar_ir_types::Term),
    EquationalTheory(EquationalTheoryObligation),
}
```

Then migrate callsites behind helpers:

```rust
impl CompilerInput {
    pub fn decode_json(value: serde_json::Value) -> Result<Self, FrontendError>;
    pub fn decode_binary(bytes: &[u8]) -> Result<Self, FrontendError>;
}
```

`decode_json` is a frontend adapter. It may use `serde_json::from_value`. Backends should not.

## 7. Refactor phases

### Phase 1: Introduce typed compiler input without changing backend behavior

Files:

- Add/modify: `implementations/rust/sugar-ir-compiler/src/lib.rs:16-107`.
- Add typed frontend module, likely `implementations/rust/sugar-ir-compiler/src/frontend.rs`.
- Keep the old JSON trait method temporarily as a compatibility adapter.

Target API shape:

```rust
pub trait IrCompiler: Send + Sync {
    fn compile_typed(
        &self,
        ir: &CompilerInput,
        dialect: &str,
    ) -> Result<CompiledFormula, CompileError>;

    fn capabilities(&self) -> Capabilities;
}
```

Temporary adapter:

```rust
fn compile_json(&self, ir: &serde_json::Value, dialect: &str) -> Result<CompiledFormula, CompileError> {
    let typed = CompilerInput::decode_json(ir.clone())?;
    self.compile_typed(&typed, dialect)
}
```

The adapter exists only to keep JSON-RPC and current verifier callsites moving during the refactor.

### Phase 2: Move backend JSON decoding into frontend adapters

Files:

- SMT-LIB: `sugar-ir-compiler-smt-lib/src/lib.rs:42-48`, `267-274`, `276-282`.
- Lean: `sugar-ir-compiler-lean/src/lib.rs:35-41`, `89-114`.
- Coq: `sugar-ir-compiler-coq/src/lib.rs:56-71`, `81-99`.
- Maude: `sugar-ir-compiler-maude/src/lib.rs:134-140`, `162-165`.

Target effect:

- `SmtLibCompiler` receives `CompilerInput::Formula` or `CompilerInput::Term` and no longer calls `serde_json::from_value` in its compile entrypoint.
- `LeanCompiler` receives `CompilerInput::Formula` or `CompilerInput::Term` and no longer calls `serde_json::from_value` in its compile entrypoint.
- `MaudeCompiler` receives `CompilerInput::EquationalTheory` and no longer owns raw JSON shape decoding at compile ingress.

Backend-local semantic checks remain backend-local. Examples that must stay in the SMT-LIB backend:

- empty variable validation at `sugar-ir-compiler-smt-lib/src/lib.rs:88-107`;
- mixed-sort conjunction detection at `sugar-ir-compiler-smt-lib/src/lib.rs:109-123` and implementation at `123-209`;
- refusal of unreduced `substitute`/`apply` and `divergence-between` nodes at `sugar-ir-compiler-smt-lib/src/lib.rs:211-240`.

Those are target-admissibility checks, not transport decoding.

### Phase 3: Make registry and verifier pass typed input

Files:

- Registry compile method: `sugar-ir-compiler/src/registry.rs:47-58`.
- Verifier plan input source: `sugar-verifier/src/solvers/plan.rs:40-49`.
- `run_plan_with_compilers`: `sugar-verifier/src/solvers/plan.rs:69-81`.
- Solver input compilation: `sugar-verifier/src/solvers/plan.rs:404-432`.

Target effect:

```rust
pub fn run_plan_with_compilers(
    plan: &SolverPlan,
    registry: &Registry,
    compilers: &CompilerRegistry,
    formula: &CompilerInput,
) -> (ObligationVerdict, String, Vec<SolverInvocation>)
```

or, if only formulas should reach this verifier path:

```rust
formula: &sugar_ir_types::Formula
```

The important property is that `formula: &Json` at `sugar-verifier/src/solvers/plan.rs:73` is retired or isolated behind a frontend adapter.

### Phase 4: Keep JSON-RPC as a transport frontend, not backend contract

Files:

- Client request shape: `sugar-ir-compiler/src/subprocess.rs:235-243`.
- Server method handling: `sugar-ir-compiler/src/server.rs:69-89`.

There are two acceptable migration routes:

1. Keep JSON-RPC method `sugar.ir.compile` with `ir_json` for protocol compatibility, but decode `ir_json` into `CompilerInput` in the RPC server before invoking the compiler backend.
2. Add a versioned method, e.g. `sugar.ir.compileTyped`, that carries an explicit tagged compiler input envelope.

The first route is the least disruptive. The important invariant is that `JsonRpcCompiler` may remain JSON-RPC transport glue, but the in-process backend trait must not remain JSON-shaped.

If the RPC server becomes the JSON frontend, frontend decode failures must not collapse into `Failed(String)`-shaped folklore. Add a typed frontend failure payload and map it to JSON-RPC error `data`:

```rust
pub enum FrontendErrorKind {
    MalformedTransport,
    UnknownInputKind,
    InvalidTypedIr,
    UnsupportedLegacyVariant,
}

pub struct FrontendErrorPayload {
    pub kind: FrontendErrorKind,
    pub frontend: String,
    pub input_format: String,
    pub path: Option<String>,
    pub detail: String,
    pub retirement: Option<String>,
}
```

Route 1 is therefore allowed only as a declared compatibility hatch:

- **Owner:** `sugar-ir-compiler` RPC/frontend adapter.
- **Input:** JSON-RPC `params.ir_json` transport.
- **Output:** `CompilerInput` or typed `FrontendErrorPayload` in JSON-RPC error `data`.
- **Addressing:** `path` points at the offending transport/typed-IR position when available.
- **Failure type:** `FrontendErrorKind`, not only an error string.
- **Replay inputs:** original request payload plus frontend name/version.
- **Retirement:** switch callers to a typed compile envelope once the compatibility wire method can be retired.

### Phase 5: Add binary frontend without touching backends

Add a binary frontend only after the typed boundary exists.

Expected implementation shape:

```rust
pub struct BinaryProofIrFrontend;

impl BinaryProofIrFrontend {
    pub fn decode(bytes: &[u8]) -> Result<CompilerInput, FrontendError> {
        // decode canonical binary representation into typed variants
    }
}
```

Acceptance test:

1. Decode a JSON fixture into `CompilerInput`.
2. Decode the equivalent binary fixture into `CompilerInput`.
3. Assert typed equality or canonical equivalence.
4. Compile both through the same backend.
5. Assert `CompiledFormula` equality except for fields admitted by `FrontendProvenancePolicy`.

`FrontendProvenancePolicy` is owned by `sugar-ir-compiler`, not by comments in individual tests. It should be a typed manifest/config row consumed by the equality instrument, for example:

```rust
pub struct FrontendProvenancePolicy {
    pub owner: String,
    pub allowed_fields: Vec<CompiledFormulaFieldPath>,
    pub reason: String,
    pub retirement: Option<String>,
}
```

The default policy is empty: JSON and binary frontend outputs must be byte-for-byte equal after typed decode and backend compile. Any non-empty allowance is a named compatibility exception with owner and retirement path.

No SMT-LIB/Lean/Coq/Maude backend file should change in this phase.

## 8. Required instruments

This repo wants orientation in instruments, not folklore. Add these ratchets with the refactor.

### Instrument A: no transport JSON at backend ingress

Static scan over backend compiler impls should fail on:

```text
impl IrCompiler for .* {
    fn compile(&self, ir: &Json, ...)
    fn compile(&self, ir: &serde_json::Value, ...)
}
```

Current offender lines to baseline/drain:

- `sugar-ir-compiler-smt-lib/src/lib.rs:42-48`
- `sugar-ir-compiler-lean/src/lib.rs:35-41`
- `sugar-ir-compiler-coq/src/lib.rs:81-99`
- `sugar-ir-compiler-maude/src/lib.rs:134-140`
- `sugar-ir-compiler/src/subprocess.rs:186-229` for compatibility wrappers

### Instrument B: backend phase cannot call frontend decode

After migration, backend compile entrypoints should not call `serde_json::from_value` on the obligation payload. Current lines to drain:

- `sugar-ir-compiler-smt-lib/src/lib.rs:267-270`
- `sugar-ir-compiler-smt-lib/src/lib.rs:276-279`
- `sugar-ir-compiler-lean/src/lib.rs:89-114`
- `sugar-ir-compiler-coq/src/lib.rs:56-71`
- `sugar-ir-compiler-maude/src/lib.rs:162-165`

Allowlist JSON use for:

- `CompiledFormula.metadata` while it remains declared dialect metadata (`sugar-ir-compiler/src/lib.rs:42-47`);
- literal values inside typed IR where the current type is intentionally `serde_json::Value`, e.g. `IrTerm::Const.value` at `sugar-ir-types/src/lib.rs:345-349`.

### Instrument C: binary frontend zero-backend-diff test

Create a test that compares JSON frontend and binary frontend outputs through at least SMT-LIB and one non-SMT backend. The test should fail if adding the binary frontend requires backend changes, if backend output depends on source serialization, or if any output difference is not admitted by the typed `FrontendProvenancePolicy`.

## 9. Backend ownership after refactor

The refactor must preserve ownership lines:

| Layer | Owns | Does not own |
|---|---|---|
| Frontend | Decode transport, construct typed ProofIR, reject malformed transport | Target-language lowering |
| Compiler middle/backend | Type-directed normalization, target admissibility, lowering, opacity, target metadata | Source serialization format |
| Solver adapter | Run concrete tool over `CompiledFormula`, consume declared metadata when needed | ProofIR semantics |
| Verifier | Assemble obligations, choose plan, interpret verdict with compiler telemetry | Target syntax generation |

Maude proves why `metadata` remains part of the compiler product: `compile_artifact` builds `metadata.maude.moduleSource`, `queries`, and `trs` at `sugar-ir-compiler-maude/src/lib.rs:197-218`, and the solver adapter can consume that without re-parsing ProofIR. That is compiler side-table ownership, not solver semantics ownership.

## 10. Done criteria

The refactor is done when all are true:

1. The in-process backend trait accepts typed ProofIR input, not `serde_json::Value`.
2. JSON decoding lives in a frontend adapter or RPC transport adapter.
3. Binary decoding can be introduced as another frontend adapter.
4. SMT-LIB, Lean, Maude, Coq, and future TPTP/Vampire backends compile from the same typed input contract.
5. Replacing JSON frontend with binary frontend causes zero backend changes.
6. `CompiledFormula` remains richer than `script()`: opacity and metadata survive unchanged.
7. Existing solver planning still routes `CompiledFormula` to `solve_compiled`, preserving `sugar-verifier/src/solvers/plan.rs:392-400` semantics.
8. Instruments forbid new backend ingress from accepting transport JSON.

## 11. One-line law

> Types travel. Formats terminate. Backends lower typed obligations; they do not decode source transport.
