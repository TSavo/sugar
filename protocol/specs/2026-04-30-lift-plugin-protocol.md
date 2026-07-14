# Lift Plugin Protocol (`sugar-lift/1`)

**LEGACY-RETAINED.** The protocol identifier `sugar-lift/1` is SUPERSEDED by `pep/1.7.0` per `protocol/specs/2026-05-12-plugin-protocol.md` §0.4 (the Plugin Extension Protocol rename). This spec's `content`-payload normative shape REMAINS authoritative for `kind = "lift"` mementos under `pep/1.7.0`; the kind-specific message shapes (JSON-RPC method set, `package-inspection-document` identity result, identify-only lift layer, error model) defined in the sections below are unchanged and continue to govern the `content` field of any `pep/1.7.0` memento with `kind = "lift"`. ONLY the protocol-version token at the wire layer changes: producers MUST emit `protocol_version = "pep/1.7.0"` (single-token wire field) or `protocol_versions = ["pep/1.7.0"]` (plugin-memento array form). Runtimes accept legacy `sugar-lift/1` for one migration minor version per the plugin-protocol spec §0.4; that acceptance window ends with the next minor bump.

Status: v1.6.3 normative update over the v1.2.0 lift-plugin protocol for `content`-payload shape under `kind = "lift"`. Wire protocol-version token renamed under `pep/1.7.0` (see above). The v1.6.3 update formalizes the already-deployed `identify-only` lift layer and the package-inspection identity result. Listed in the protocol catalog under property key `lift-plugin-protocol`. CID is computed from the bytes of this file (raw-bytes BLAKE3-512); see the catalog at `protocol/specs/2026-04-30-protocol-catalog.json` for the value.

## Why

Sugar is the composition of two protocols (canonical IR + content addressing). Lift adapters are decoration: they consume host-language source and emit canonical IR mementos that the protocol then signs, hashes, bundles. Today the Rust CLI bundles Rust-only lift adapters as Rust crates (proptest, contracts, kani, prusti, creusot, flux, quickcheck, verus, rust-tests, .invariant.rs orchestrator). The C++, Go, TypeScript, and Python lifters live in their own per-language tooling and are invoked separately.

`sugar prove` should be one command that produces a `.proof` for any of the four peer impls just by changing directory. The lift plugin protocol is the seam that makes this possible: the Rust CLI subprocess-dispatches to per-language lift plugins via JSON-RPC over stdio (LSP shape; same shape MCP, nvim plugins, and the language-server ecosystem use). The plugin produces canonical IR; the Rust CLI signs/bundles/writes the `.proof`.

This spec defines:

1. The plugin manifest format.
2. The JSON-RPC method shapes.
3. Capability negotiation.
4. The error model.
5. The configuration surface in `.sugar/config.toml`.

## Plugin discovery

Plugins live at:

```
~/.config/sugar/lift/<name>/manifest.toml
```

Or, project-local:

```
.sugar/lift/<name>/manifest.toml
```

Project-local plugins shadow user-global plugins of the same name. Both are searched; project-local wins.

Manifest schema:

```toml
name = "go-self-contracts"
version = "1.0.0"
protocol_version = "sugar-lift/1"
command = ["go", "run", "./cmd/mint-go-self-contracts", "--rpc"]
working_dir = "implementations/go/sugar-self-contracts"

[capabilities]
authoring_surfaces = ["go-tests", "go-self-contracts"]
ir_version = "v1.1.0"
emits_signed_mementos = true
```

`command` is the argv used to spawn the plugin. The plugin SHOULD support a `--rpc` (or equivalent) flag indicating it should speak JSON-RPC on stdio rather than its default human-readable output.

`working_dir` is optional; if present, the Rust CLI sets the plugin's CWD to this path resolved relative to the workspace root.

## Transport

JSON-RPC 2.0 over stdio. One JSON object per line (NDJSON). The Rust CLI is the client; the plugin is the server. The plugin reads requests from stdin and writes responses to stdout. The plugin MAY write progress messages and diagnostics to stderr; the Rust CLI captures stderr and surfaces it to the user but does not parse it.

## Formal message grammar

This section is normative. The grammar below uses CDDL-like notation for JSON objects. `json-value` means any JSON value accepted by RFC 8259. `cid` is a self-identifying content address string of the form defined by the catalog's active hash algorithms, normally `blake3-512:<128 lowercase hex chars>`.

```cddl
jsonrpc-version = "2.0"
jsonrpc-id = uint / text
text-nonempty = text .size (1..)
cid = text
diagnostics = [* json-value]

jsonrpc-request = initialize-request / lift-request / shutdown-request
jsonrpc-response = {
  jsonrpc: jsonrpc-version,
  id: jsonrpc-id,
  (result: json-value // error: jsonrpc-error)
}

jsonrpc-error = {
  code: int,
  message: text,
  ? data: json-value
}

initialize-request = {
  jsonrpc: jsonrpc-version,
  id: jsonrpc-id,
  method: "initialize",
  params: initialize-params
}

initialize-params = {
  client: {
    name: text-nonempty,
    version: text-nonempty
  },
  protocol_version: "sugar-lift/1",
  workspace_root: text-nonempty,
  config_path: text-nonempty
}

initialize-result = {
  name: text-nonempty,
  version: text-nonempty,
  protocol_version: "sugar-lift/1",
  capabilities: lift-capabilities
}

lift-capabilities = {
  authoring_surfaces: [+ text-nonempty],
  ir_version: text-nonempty,
  emits_signed_mementos: bool,
  ? identify_result_kinds: [* identify-result-kind]
}

lift-request = {
  jsonrpc: jsonrpc-version,
  id: jsonrpc-id,
  method: "lift",
  params: lift-params
}

lift-params = {
  surface: text-nonempty,
  source_paths: [+ text-nonempty],
  options: lift-options
}

lift-options = {
  layer: lift-layer,
  ? identifyOnly: bool,
  * text => json-value
}

lift-layer = "all" / "identify-only" / "library-bindings"

lift-result = all-layer-result / identify-only-result / library-bindings-result
all-layer-result = ir-document / signed-mementos / proof-envelope
identify-only-result = identity-document / package-inspection-document
library-bindings-result = ir-document / signed-mementos / proof-envelope
identify-result-kind = "identity-document" / "package-inspection-document"

ir-document = {
  kind: "ir-document",
  ir: [* json-value],
  ? symbolKinds: { * constructor-spelling => symbol-kind },
  ? diagnostics: diagnostics
}

symbol-kind = "coordinate" / "builtin" / "contract-target" / "method-coordinate"

`symbolKinds` is presentation testimony beside the IR. It is not a term field
and MUST NOT enter a term's canonical bytes or CID preimage. A producer emits
at most one entry per constructor spelling; consumers render from that entry
and fail loudly when an open constructor spelling has no testimony.

signed-mementos = {
  kind: "signed-mementos",
  members: { * cid => signed-memento-bytes },
  signer_cid: cid,
  ? diagnostics: diagnostics
}

signed-memento-bytes = {
  bytes_base64: text,
  kind: text-nonempty,
  * text => json-value
}

proof-envelope = {
  kind: "proof-envelope",
  filename_cid: cid,
  bytes_base64: text,
  ? diagnostics: diagnostics
}

identity-document = {
  kind: "identity-document",
  identities: [* identity-binding],
  ? diagnostics: diagnostics,
  * text => json-value
}

identity-binding = {
  kind: text-nonempty,
  * text => json-value
}

package-inspection-document = {
  kind: "package-inspection-document",
  ecosystem: text-nonempty,
  package: package-identity,
  artifact: package-artifact-identity,
  ? ci: ci-input-identity,
  ? release: release-identity,
  ? proofs: proof-artifact-identity,
  ? conventionalReceipts: { * text => receipt-state },
  ? admission: admission-hint,
  ? diagnostics: diagnostics,
  * text => json-value
}

package-identity = {
  name: text-nonempty,
  version: text-nonempty,
  * text => json-value
}

package-artifact-identity = {
  binaryCid: cid,
  ? path: text-nonempty,
  ? bytes: uint,
  * text => json-value
}

ci-input-identity = {
  inputClosureCid: cid,
  ? closure: [* text-nonempty],
  * text => json-value
}

release-identity = {
  ? contractSetCid: cid,
  ? previousContractSetCid: cid,
  ? contracts: [* text-nonempty],
  * text => json-value
}

proof-artifact-identity = {
  ? status: text-nonempty,
  ? manifestHint: cid / null,
  ? proofFileCids: [* cid],
  ? files: [* proof-file-identity],
  * text => json-value
}

proof-file-identity = {
  path: text-nonempty,
  contentCid: cid,
  ? filenameCid: cid,
  ? bytes: uint,
  ? filenameMatchesContent: bool,
  * text => json-value
}

receipt-state = "green" / "red" / "yellow" / "unknown" / text-nonempty

admission-hint = {
  status: text-nonempty,
  ? reason: text,
  * text => json-value
}

shutdown-request = {
  jsonrpc: jsonrpc-version,
  id: jsonrpc-id,
  method: "shutdown",
  ? params: json-value
}
```

Layer selection is part of the grammar, not an out-of-band CLI convention:

- `options.layer = "all"` selects the proof-producing lift layer. The response MUST be `ir-document`, `signed-mementos`, or `proof-envelope`.
- `options.layer = "identify-only"` selects the side-effect-free identity layer. The response MUST be `identity-document` or `package-inspection-document`.
- `options.layer = "library-bindings"` selects proof-producing host-language library-sugar binding lift. The response MUST be `ir-document`, `signed-mementos`, or `proof-envelope`; when returning `ir-document`, the relevant entries use `kind = "library-sugar-binding-entry"` per `2026-05-13-bind-ir-lift-result.md`.
- If `options.identifyOnly` is present, it MUST be `true` exactly when `options.layer = "identify-only"` and `false` exactly when `options.layer = "all"` or `"library-bindings"`. It exists only as a legacy mirror for older clients.
- A plugin that does not implement the requested layer MAY return JSON-RPC error `1006` / `UNSUPPORTED_LIFT_LAYER`. A client MUST NOT accept a proof-producing response kind as an identify-only response.
- `sugar package inspect` is a client command over this same `lift` method. It dispatches to the configured lift plugin with `options.layer = "identify-only"` and requires a `package-inspection-document`. No separate package-manager JSON-RPC protocol exists.

## Methods

### `initialize`

The first call after spawn. The Rust CLI sends:

```json
{"jsonrpc":"2.0","id":1,"method":"initialize","params":{
    "client":{"name":"sugar-cli","version":"v1.1.0"},
    "protocol_version":"sugar-lift/1",
    "workspace_root":"/abs/path/to/workspace",
    "config_path":".sugar/config.toml"
}}
```

The plugin responds with its capabilities and confirms protocol version:

```json
{"jsonrpc":"2.0","id":1,"result":{
    "name":"go-self-contracts",
    "version":"1.0.0",
    "protocol_version":"sugar-lift/1",
    "capabilities":{
        "authoring_surfaces":["go-tests","go-self-contracts"],
        "ir_version":"v1.1.0",
        "emits_signed_mementos":true
    }
}}
```

If `protocol_version` does not match, the plugin SHOULD fail the request with error code `PROTOCOL_VERSION_MISMATCH`.

### `lift`

The Rust CLI requests canonical IR mementos for a given source set:

```json
{"jsonrpc":"2.0","id":2,"method":"lift","params":{
    "surface":"go-self-contracts",
    "source_paths":["implementations/go/sugar-ir-symbolic/canonicalizer/encoder.go"],
    "options":{"layer":"all"}
}}
```

When `options.layer` is `"all"`, the plugin responds with one of three proof-producing shapes:

**(a) Canonical IR (mint pipeline runs in the Rust CLI):**

```json
{"jsonrpc":"2.0","id":2,"result":{
    "kind":"ir-document",
    "ir":[
        {"kind":"contract","name":"go_encode_jcs_is_deterministic","outBinding":"out","pre":{...}},
        ...
    ],
    "diagnostics":[]
}}
```

The `ir` field is the IR-JSON Document shape (an array of declarations) per `2026-04-30-ir-formal-grammar.md`. The Rust CLI takes this, marshals via JCS, mints each declaration as a memento under the foundation key, bundles into a `.proof`. This is the simplest plugin shape — the plugin only authors IR.

**(b) Pre-minted signed mementos (plugin owns the keypair):**

```json
{"jsonrpc":"2.0","id":2,"result":{
    "kind":"signed-mementos",
    "members":{
        "blake3-512:<cid>":{"bytes_base64":"...","kind":"contract"},
        ...
    },
    "signer_cid":"blake3-512:<signer-pubkey-cid>",
    "diagnostics":[]
}}
```

The plugin returns mementos already signed under its own key. The Rust CLI bundles them into a `.proof` envelope but does not re-sign individual members. This is the shape for plugins that need to sign with a non-foundation key (CI bot keys, reviewer keys, organization keys).

**(c) Complete `.proof` bytes (plugin owns the full pipeline):**

```json
{"jsonrpc":"2.0","id":2,"result":{
    "kind":"proof-envelope",
    "filename_cid":"blake3-512:<cid>",
    "bytes_base64":"...",
    "diagnostics":[]
}}
```

The plugin returns a complete `.proof` bundle. The Rust CLI writes the bytes to `<filename_cid>.proof`. This is the shape for plugins that already have their own mint+bundle pipeline (e.g., the existing `mint-self-contracts`, `mint-go-self-contracts`, `mint_cpp_self_contracts` binaries can be wrapped in a thin RPC layer to expose this shape).

When `options.layer` is `"identify-only"`, the plugin responds with a side-effect-free identity shape. The plugin MUST NOT mint a `.proof`, sign mementos, write generated artifacts, or otherwise perform proof-producing work in this layer.

**(d) General identity document:**

```json
{"jsonrpc":"2.0","id":2,"result":{
    "kind":"identity-document",
    "identities":[
        {"kind":"project","name":"checked-add-u8","language":"c"}
    ],
    "diagnostics":[]
}}
```

**(e) Package inspection document:**

```json
{"jsonrpc":"2.0","id":2,"result":{
    "kind":"package-inspection-document",
    "ecosystem":"npm",
    "package":{"name":"safe-json","version":"1.4.2"},
    "artifact":{
        "path":"package.tgz",
        "binaryCid":"blake3-512:<cid>",
        "bytes":4096
    },
    "ci":{
        "inputClosureCid":"blake3-512:<cid>",
        "closure":["package.json","index.js","contracts.json","package.tgz"]
    },
    "release":{
        "contractSetCid":"blake3-512:<cid>",
        "previousContractSetCid":"blake3-512:<cid>",
        "contracts":["runtime.no-env-secret-read"]
    },
    "proofs":{
        "status":"discovered",
        "proofFileCids":["blake3-512:<cid>"],
        "files":[{
            "path":"blake3-512:<cid>.proof",
            "filenameCid":"blake3-512:<cid>",
            "contentCid":"blake3-512:<cid>",
            "bytes":8192,
            "filenameMatchesContent":true
        }]
    },
    "conventionalReceipts":{
        "maintainerSignature":"green",
        "slsaStyleProvenance":"green",
        "inTotoStylePipeline":"green"
    },
    "admission":{
        "status":"not-decided",
        "reason":"package identity, provenance, and tarball hash are not contract admission"
    },
    "diagnostics":[]
}}
```

The package-inspection document is an observation over package identity, artifact bytes, optional CI input closure, optional release contract-set fields, and optional shipped `.proof` artifacts. It is not itself a proof that the package satisfies any contract. It gives package-manager tooling stable CIDs to compare against `.proof` bundles, witness proofs, policy pins, and CI receipts.

A plugin MUST implement at least one of the three `"all"` response shapes. A plugin MAY implement either identify-only shape. A plugin MAY implement all five; the Rust CLI selects the shape compatible with the invoked command and workspace config.

### `shutdown`

The Rust CLI sends:

```json
{"jsonrpc":"2.0","id":99,"method":"shutdown"}
```

The plugin completes any in-flight `lift` calls, releases resources, responds with `{"id":99,"result":null}`, then exits.

## Capability negotiation

The `initialize` response declares which authoring surfaces the plugin supports. The Rust CLI matches the workspace's `[authoring] surface = ...` against the union of all plugins' capabilities and selects the first plugin (by manifest discovery order) that claims the surface.

If two plugins claim the same surface, the project-local plugin wins. If both are project-local or both are user-global, the lexicographically-earlier `name` wins, and the Rust CLI emits a diagnostic.

If no plugin claims the requested surface, `sugar prove` exits with `LIFT_PLUGIN_NOT_FOUND` and lists the candidates.

## Error model

JSON-RPC 2.0 error codes:

| Code | Name | Meaning |
|------|------|---------|
| -32700 | `PARSE_ERROR` | Plugin emitted invalid JSON. |
| -32600 | `INVALID_REQUEST` | Method call malformed. |
| -32601 | `METHOD_NOT_FOUND` | Plugin doesn't implement the method. |
| -32602 | `INVALID_PARAMS` | Required field missing. |
| -32603 | `INTERNAL_ERROR` | Unspecified plugin failure. |
| 1001 | `PROTOCOL_VERSION_MISMATCH` | Plugin's protocol version differs from client's. |
| 1002 | `IR_VERSION_MISMATCH` | Plugin's IR version is not compatible with the requested IR version. |
| 1003 | `SURFACE_NOT_SUPPORTED` | Plugin doesn't implement the requested authoring surface. |
| 1004 | `SOURCE_NOT_FOUND` | Plugin couldn't read a source path. |
| 1005 | `LIFT_FAILED` | Plugin executed but produced no IR (compile error in source, etc.). |
| 1006 | `UNSUPPORTED_LIFT_LAYER` | Plugin supports the surface but not the requested `options.layer`. |

## Configuration

`.sugar/config.toml` extension:

```toml
[authoring]
surface = "go-self-contracts"   # selects which plugin handles `sugar prove`

[lift]
plugins_path = ["~/.config/sugar/lift", ".sugar/lift"]   # discovery order

[lift.options]
layer = "all"   # "all" for proof-producing lift; "identify-only" for side-effect-free identity/inspection
```

## Conformance

A conformant plugin:

1. Implements `initialize`, `lift`, `shutdown`.
2. Returns the protocol version `sugar-lift/1` in the `initialize` response.
3. Emits canonical IR-JSON in the v1.1.0 shape (per `2026-04-30-ir-formal-grammar.md`) for the `ir-document` response shape.
4. If returning `signed-mementos` or `proof-envelope`, produces byte-deterministic output for byte-equal inputs (same source paths, same options → same CIDs).
5. Reports any diagnostics under the `diagnostics` field of the response, never silently dropping warnings.
6. If implementing `options.layer = "identify-only"`, returns only `identity-document` or `package-inspection-document` and does not mint, sign, write, or lower proof artifacts while answering that request.

A non-conformant plugin produces a different `sugar prove` output than a conformant one for the same inputs. The Rust CLI MAY refuse to dispatch to plugins that fail capability negotiation.

## Two paths into canonical IR

The lift-plugin protocol covers two architecturally distinct authoring paths into canonical IR. Both produce the same byte shape; they differ only in where the contract text lives before it becomes IR.

**Kit-authored**: the contract is written using the host language's kit-authoring API (Rust `sugar-macros-rt`, C++ `sugar/ir.hpp`, Go kit primitives, TS kit primitives). The kit produces canonical IR-JSON deterministically. Self-contracts (`.invariant.rs`, `.invariant.cpp`, `slabs/*.go`, `.invariant.{json,ts}`) are all kit-authored. The protocol uses this path to express its own correctness.

**Decorator-lifted**: the contract lives in an existing host-language annotation library (Zod schema, kani harness, proptest strategy, class-validator decorator, JSDoc tag, Pydantic model, etc.). A lift adapter parses the native annotation and emits canonical IR-JSON. Lift adapters are the canonical path for host code that already has annotations.

Both paths share the same `lift` method, the same response shapes, and the same IR-JSON output. The plugin manifest declares which path(s) it implements via the `authoring_surfaces` capability list. A single plugin MAY support both — for example, a Rust plugin could expose `surface = "rust-self-contracts"` (kit-authored) AND `surface = "kani"` (decorator-lifted) under the same binary.

The protocol doesn't care which path produced the IR. Both paths hash to identical CIDs for identical propositions. The only test is byte equality.

## Reference plugins

Reference CLI plugins ship with Sugar for all language implementations:

| Surface | Plugin command | Reference | Status |
|---------|---------------|-----------|--------|
| `typescript` | `npx tsx src/lift/bin/main.ts --rpc` | `implementations/typescript/src/lift/` | ✅ Real lifter (zod, fast-check, vitest) |
| `rust-self-contracts` | `cargo run -p sugar-self-contracts --rpc` | `implementations/rust/sugar-self-contracts/` | ✅ Real lifter (invariant.rs, proptest, kani) |
| `go-self-contracts` | `go run ./cmd/mint-go-self-contracts --rpc` | `implementations/go/sugar-self-contracts/cmd/` | ✅ Real lifter (Go test extraction) |
| `cpp-self-contracts` | `./target/mint_cpp_self_contracts --rpc` | `implementations/cpp/sugar-self-contracts/` | ✅ Real lifter (C++ invariant extraction) |
| `csharp-self-contracts` | `dotnet run --project Sugar.SelfContracts --rpc` | `implementations/csharp/Sugar.SelfContracts/` | ✅ Real lifter (C# invariant extraction) |

Each implements the protocol over NDJSON-on-stdio, returning the `proof-envelope` shape (c). The dispatcher resolves these via `.sugar/lift/<surface>/manifest.toml` per peer's directory.

The apex demonstration — **one Rust CLI binary, all projects**:

```sh
$ cd implementations/typescript && sugar mint
$ cd implementations/rust        && sugar mint
$ cd implementations/go          && sugar mint
$ cd implementations/cpp         && sugar mint
$ cd implementations/csharp      && sugar mint
```

One `sugar` binary. Five `.proof` files. Configuration via `.sugar/config.toml` per directory. Same protocol catalog. Same foundation key. Different surfaces, different IR contents, byte-deterministic content-addressed output.

## Any language, any tooling

**Anyone can implement a lifter in any language.** The protocol is just JSON-RPC over stdio. Your lifter can be written in:

- Python (parse `*.py` with `ast` module)
- Java (parse `*.java` with JavaParser)
- Haskell (parse `*.hs` with `ghc-lib-parser`)
- Zig, Lua, Ruby, PHP, Kotlin, Swift, Dart, Elixir, Clojure, Scala, Julia, R, MATLAB, Fortran, COBOL... literally anything

The only requirement: read JSON from stdin, write JSON to stdout, handle three methods (`initialize`, `lift`, `shutdown`). The Rust CLI doesn't care what language your lifter is written in. It doesn't parse your language's AST. It just dispatches.

Your lifter's job:
1. Scan source files in the workspace
2. Extract properties (tests, types, contracts, assertions, schemas)
3. Convert to canonical IR-JSON
4. Bundle into a `.proof` envelope
5. Return via JSON-RPC

The Rust CLI handles: signing, hashing, CID computation, file I/O.

This is the core architectural principle: **the CLI is one thing in one language; everything else is a plugin.**
