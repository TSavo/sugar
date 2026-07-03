# Writing a lift adapter, step 2: walk the AST

Each lift adapter walks the source library's AST. This step is language-specific because each language exposes its AST differently. The general shape is consistent: parse, recognize, extract.

## Where the AST comes from

Three options, in increasing fidelity:

### 1. Reflection / runtime introspection

The adapter inspects loaded program metadata at runtime. Examples:

- Java reflection (`Class.getAnnotations()`) for Bean Validation, JML annotations represented as runtime annotations.
- .NET reflection (`MemberInfo.GetCustomAttributes()`) for DataAnnotations.
- Pydantic's runtime model class metadata.
- Ruby's runtime class metadata for `validates :field, ...` introspection.

Pros: simple. The metadata is already there. No parser to write.
Cons: requires loading the program. May miss compile-time-only information. May see processed/transformed annotations rather than as-written.

### 2. Compile-time AST walking via the language's compiler

The adapter is a compiler plugin or a tool that consumes the compiler's AST. Examples:

- Rust procedural macros for `#[contracts::ensures]`.
- TypeScript Compiler API (`typescript`) for walking `zod.object` schemas.
- Python's `ast` module for walking decorators.
- JavaParser for `//@ requires` JML comments.

Pros: highest fidelity. Sees as-written annotations. Has access to types and identifiers.
Cons: more setup. Couples to a specific compiler version.

### 3. Source-level parsing

The adapter parses source files directly with a regex or hand-written tokenizer. Examples:

- The Java JML adapter uses a hand-written tokenizer + recursive-descent parser for `//@ requires` comments.
- The Zig adapter walks `//sugar:contract` comment blocks with a custom parser.

Pros: works without the language's compiler infrastructure.
Cons: hand-rolled parsers are easy to get wrong. Locating annotations precisely (line, column, scope) is harder.

For most adapters, option 2 (compile-time AST) is the best fit. Reflection is acceptable for runtime annotation libraries. Source-level parsing is a fallback for languages where the compiler API is awkward.

## Structural patterns

Three patterns recur across adapters:

### Pattern A: decorator on a class field

```python
class User(BaseModel):
    email: str = Field(..., pattern=r"^[^@]+@[^@]+\.[^@]+$")
```

Walk: locate `BaseModel` subclasses, iterate fields, inspect each field's `Field(...)` call (or default value). Extract constraint args.

This is the shape of `pydantic`, `class-validator` (TypeScript), `DataAnnotations` (C#), `active_model` (Ruby).

### Pattern B: attribute on a function or method

```rust
#[contracts::requires(x >= 0)]
#[contracts::ensures(ret => ret >= x)]
fn add_one(x: i32) -> i32 { x + 1 }
```

Walk: locate functions with the relevant attributes, parse the attribute argument expression, extract pre/post predicates.

This is the shape of `contracts` (Rust), native `#[requires]` / `#[ensures]`, and JML `//@ requires` after parsing.

### Pattern C: chain-style schema

```typescript
const UserSchema = z.object({
  email: z.string().email(),
  age: z.number().int().min(0).max(150),
});
```

Walk: locate top-level `z.object` calls, recursively walk each field's schema chain (`z.string().email()`), accumulate constraints into a single canonical predicate per field.

This is the shape of `zod`, `valibot`, `io-ts`, `runtypes`, the `fast-check` property combinators.

## What you extract

For each annotation you recognize, extract:

1. **The annotation kind** (the structural identifier: `@Min`, `z.string().email()`, `prop_assert!`).
2. **The arguments** (the constants and references the annotation parameterizes over).
3. **The annotated location** (the field, function, parameter, or call site this annotation applies to).
4. **The bound symbol's signature** (the type information the bridge will need: parameter sorts, return sort).
5. **A source location** (file, line, column) for diagnostics. This is metadata; not signed.

These five pieces are enough to construct a canonical IR formula plus a binding to the call site.

## Call-edge emission

Under the Bridge Linkage Protocol ([`protocol/specs/2026-05-03-bridge-linkage-protocol.md`](../../../protocol/specs/2026-05-03-bridge-linkage-protocol.md) §1 R1), a lift adapter emits two streams per compilation unit:

1. **Contract mementos** (`kind: "contract"`): the canonical IR formulas for recognized annotations (step 3).
2. **Call-edge mementos** (`kind: "call-edge"`): one per call site within the lifted code.

A call edge captures the caller-callee relationship: `sourceContractCid` (the calling function's contract), `targetContractCid` or `targetSymbol` (the callee), `callSiteLocus`, and an `evidenceTerm` encoding the satisfaction obligation `post_callee ⊃ pre_caller`. When the target contract is not yet known (cross-kit calls), set `targetContractCid: null` and populate `targetSymbol` for linker resolution.

The two streams are emitted in the same response envelope. The linker (`sugar prove`) derives bridge mementos mechanically from the union of contracts and call edges across all kits. The adapter must NOT emit `kind: "bridge"` mementos directly; bridges are linker-derived.

Walk the AST for call sites the same way you walk for annotations: parse, recognize the call graph, extract caller-callee pairs and locus information. This data flows alongside the canonical IR formulas produced in step 3.

## Type information matters

The bridge's `boundCallSiteSorts` and `boundReturnSort` come from the type system. If your adapter cannot recover the type information from the AST, it cannot construct a full bridge.

For statically-typed languages (Rust, Java, C#, TypeScript with strict mode, Go, C++, Swift), this is straightforward.

For dynamically-typed languages (Python, Ruby, JavaScript), this requires inference from runtime annotations or type hints. Pydantic's adapter uses Pydantic's own type information; the Ruby adapter falls back to `Sort.Any` where types are unrecoverable.

## What to do when you don't recognize something

Three valid behaviors, in order of severity:

1. **Ignore silently.** The annotation is unrecognized but probably harmless. Log at debug level. The codebase still compiles and runs; your adapter just didn't lift this one annotation.
2. **Warn.** The annotation looks like one your adapter should handle but you don't yet. Log at warn level with the file:line. Useful when an adapter is at coverage Tier B and a user hits an unsupported annotation.
3. **Error.** The annotation is structurally malformed (e.g., `@Min` with no argument). The source library would reject this too; your adapter forwards the rejection.

Never invent. If you can't canonicalize an annotation correctly, do not lift it. Lifting it incorrectly puts a wrong contract into the lattice, and lattice errors are much harder to detect than missing entries.

## Test as you walk

Write tests for the walker before you write the canonicalizer (step 3). The walker's input is a known AST; the walker's output is a structured intermediate representation (your adapter's, not the protocol's). Test that walking the AST recovers the structured intermediate correctly. Then test that canonicalizing the intermediate produces the canonical IR bytes.

This separates two concerns:

- "Did I correctly understand the source library's annotation?" (walker test)
- "Did I correctly canonicalize the understood annotation?" (canonicalizer test)

When something breaks, you know which layer to fix.

## Read next

- [03-emit-canonical-IR.md](03-emit-canonical-IR.md): mapping recognized annotations to canonical IR formulas.
- [docs/reference/ir/grammar.md](../../reference/ir/grammar.md) (when written): IR grammar reference.
