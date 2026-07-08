# Plugin Extension Protocol (`pep/1.7.0`)

**Status:** v1.0.0 normative draft. Listed in the protocol catalog under property key `plugin-protocol` (catalog entry to be appended in a follow-up CI mint; this spec MUST NOT edit `2026-04-30-protocol-catalog.json` directly). CID is computed from the bytes of this file (raw-bytes BLAKE3-512).
**Date:** 2026-05-12
**Author:** T Savo
**Related:**
- `2026-04-30-canonicalization-grammar.md` (JCS canonicalization, normative)
- `2026-04-30-ir-formal-grammar.md` (IrFormula shape used by `sugar` plugins)
- `2026-04-30-protocol-versioning.md` (version token grammar)
- `2026-04-30-agent-plugin-protocol.md` (kind-specific predecessor; legacy protocol identifier `sugar-agent/1`, see §0.4)
- `2026-04-30-lift-plugin-protocol.md` (kind-specific predecessor; legacy protocol identifier `sugar-lift/1`, see §0.4)
- `2026-04-30-ir-extension-protocol.md` and `2026-05-06-extension-protocols.md` (extension surfaces this protocol unifies)
- `2026-05-03-substrate-layers-envelope-header-body.md` (envelope/header/metadata layering reused)
- `2026-05-03-contract-cid-vs-attestation-cid.md` (CID semantics for the declared-behavior vs delivery split, §6)
- `2026-05-09-pattern-predicate-protocol.md` (precedent for content-addressed editorial extensions registered at runtime)
- `2026-05-12-plugin-protocol.md` consumers in this PR: `2026-05-12-sugar-dict-memento.md`, `2026-05-12-loss-function-memento.md`
- `2026-05-14-transport-gap-and-partial-morphism-protocol.md` §1.3 (`loss-record` schema consumed by `loss-function` plugins)
- `2026-05-15-concept-hub-abstraction-layer.md` (loss-record dimensions also normative here)

## §0. Purpose

Sugar is a substrate, not a program. Every semantic decision the substrate makes (how a canonical clause is rendered into a target language, how loss is scored, which discharge backend handles which obligation, which lifter handles which file extension, which realizer fires for which clause shape) MUST be externalized as a content-addressed memento. The runtime binary is the engine; the plugins ARE the algebra (per `project_sugar_substrate_trinity` and the `algebra-is-the-portable-thing` thesis at `docs/papers/16-after-portability-the-universal-address-space.md`).

This spec defines the universal seam through which any such memento is loaded, addressed, version-negotiated, and registered. Three principles are non-negotiable:

1. **No hard coding.** A built-in default is still a memento at a fixed declared CID. The runtime MUST be able to enumerate, replace, and discharge every built-in along the same surface a third-party plugin uses.
2. **Trichotomy across plugin boundaries.** Plugin loading itself MUST emit `exact`, `loudly-bounded-lossy`, or `refuse` per `project_sugar_first_principle.md`. No silent fallback. A refusal to load a plugin is a precise extension request, not a hidden error.
3. **Federation by CID.** A plugin's identity is its declared-behavior CID. Delivery (JSON file, JSON-RPC server, statically-linked symbol) is a transport detail; CID stability is the federation guarantee (§6.2).

### §0.1 Relation to the substrate trinity

A plugin manipulates {terms, contracts, implications}. Sugar dicts render `contracts`; loss functions score divergences over `implications`; lifters mint `terms`; realizers discharge `contracts -> implications`. The plugin protocol is the registration mechanism for any of these algebraic operations, not just the four named in this PR.

### §0.2 What is NOT in scope for v1.0.0

- Discovery beyond CLI flags (no central registry; federation by reference is left to the consumer mementos themselves).
- Hot-reload of plugins mid-run (a `PluginRegistryMemento` is sealed at run start, §9).
- Sandboxing of plugin RPC processes (the host environment's process model is out of scope; plugins run with the runtime's privileges).
- Cross-runtime plugin portability (a Rust runtime and a TypeScript runtime MAY each implement this protocol; byte-identical CIDs across runtimes are required by §6.2, but the runtime binaries themselves are not portable).

### §0.3 Trichotomy mapping

| Outcome                    | Meaning                                                                                       |
|----------------------------|-----------------------------------------------------------------------------------------------|
| `exact`                    | Every requested plugin loaded; every declared CID validated; registry sealed without warning. |
| `loudly-bounded-lossy`     | One or more NON-CRITICAL plugins failed to load; each failure recorded as a `PluginLoadFailureMemento` (§8); registry sealed with the explicit failure-set in `PluginRegistryMemento.failures`. The run proceeds; downstream consumers MAY refuse to compose through the failure-set. |
| `refuse`                   | A plugin flagged `critical: true` failed to load, OR a duplicate-CID collision occurred at the same `(kind, cid)` slot (§9.2), OR protocol-version negotiation failed (§5). The runtime MUST exit non-zero with the failure list. |

### §0.4 Relation to the existing kind-specific plugin specs

`pep/1.7.0` is THE protocol going forward. Having three parallel protocol-version tokens (`sugar-agent/1`, `sugar-lift/1`, `pep/1.7.0`) permanently embeds an M*N protocol-space tax: every new kind must decide which surface to follow, every runtime must implement and maintain multiple dispatch paths, and every verifier must understand the union. Per Supra omnia, rectum, that is incorrect. The protocol that exists to eliminate M*N complexity MUST itself be the singular seam.

**Legacy protocol identifiers.** `sugar-agent/1` and `sugar-lift/1` are now defined as legacy protocol identifiers. The kinds `agent` and `lift` are two of the first entries in `pep/1.7.0`'s open `kind` enum (§2.1). The kind-specific predecessor specs (`2026-04-30-agent-plugin-protocol.md`, `2026-04-30-lift-plugin-protocol.md`) remain readable as the authoritative definitions of the `content` payload shapes for those two kinds; they do NOT define a separate ongoing protocol surface.

**Migration semantics.** Any existing `sugar-agent/1` or `sugar-lift/1` memento MUST be re-mintable into a `pep/1.7.0` memento with byte-stable content payload. The `content` field of the plugin memento carries the same kind-specific bytes the predecessor memento carried; the only field that changes is `protocol_versions` (which MUST be `["pep/1.7.0"]` in the re-minted form). CID identity MUST be verified over the full `pep/1.7.0` header, not the legacy header; the two headers have different shapes and WILL produce different CIDs. This is correct: a `pep/1.7.0` `agent`-kind memento and the legacy `sugar-agent/1` memento it was re-minted from are different content-addressed objects.

**Deprecation timeline.** The migration window spans one sugar binary minor version:

- **Acceptance (read side).** The CURRENT minor version of the sugar binary (the version that ships with this spec) MUST accept both legacy protocol-version tokens (`sugar-agent/1`, `sugar-lift/1`) and `pep/1.7.0` as valid `protocol_versions` values. When a legacy token is accepted, the binary MUST emit a `PluginLoadFailureMemento` with `reason_kind = "deprecated-protocol-identifier"` and `critical = false`, recording the legacy token and the `pep/1.7.0` equivalent. The run proceeds; the failure is a loud deprecation notice, not a refusal.
- **Emission (write side).** The CURRENT minor version of the sugar binary, and EVERY in-tree plugin implementation that emits a `protocol_version` field (manifest TOML, JSON-RPC `describe` response, embedded self-contract literal), MUST emit the single canonical token `pep/1.7.0`. Concretely: emit `"protocol_version": "pep/1.7.0"` for legacy single-token fields, and `"protocol_versions": ["pep/1.7.0"]` for the §1.1 plugin-memento array form. Emitting a legacy token from an in-tree implementation under this spec is a producer-side defect. This keeps the byte-stability invariant (§14) crisp: the single-element array is what consumers content-address against.
- The NEXT minor version of the sugar binary MUST refuse to load any plugin whose `protocol_versions` array does not contain `pep/1.7.0`. Legacy tokens MUST NOT be accepted. Refusal MUST emit `reason_kind = "refused-legacy-protocol-identifier"`. Producers MUST re-mint mementos against `pep/1.7.0` before the next minor version ships.

Version-bump mechanics for the protocol catalog entry follow `2026-04-30-protocol-versioning.md`.

## §1. The plugin memento

A plugin memento is a content-addressed record of a plugin's DECLARED BEHAVIOR. Delivery is separate (§3, §4). Two plugins with byte-identical content payloads MUST produce byte-identical CIDs even if one is a JSON file and the other is a JSON-RPC server (§6.2).

### §1.1 Wire shape (CDDL)

```cddl
; Shared scalar types:
;   hash, cid, signature, pubkey, iso8601, json-value
;
; Locked JCS key order: alphabetical within each object.
; The CDDL display order below is illustrative; JCS enforces alphabetical
; key order on the wire (per 2026-04-30-canonicalization-grammar.md).

; Open enum of plugin kinds. Validators MUST accept unknown kinds at
; shape level (§5.3 of the consumer specs decides whether to refuse).
; The canonical labels (v1.0.0) are listed in §2.1.
plugin-kind = tstr

; Protocol-version token; MUST conform to the grammar of
; 2026-04-30-protocol-versioning.md.
protocol-version = tstr

; Semver string; MUST conform to https://semver.org/spec/v2.0.0.html.
semver = tstr

; Locked JCS key order: cid, content, critical, kind, protocol_versions,
; provenance_cid, schemaVersion, version
plugin-memento = {
  envelope: {
    declaredAt: iso8601,
    signature:  signature,            ; over JCS(header ++ metadata)
    signer:     pubkey
  },
  header: {
    cid:                 cid,         ; DERIVED -- see §6
    content:             json-value,  ; kind-specific payload; CDDL'd by the consumer spec
    critical:            bool,        ; if true, load failure refuses the whole run (§8)
    kind:                plugin-kind,
    protocol_versions:   [+ protocol-version],
    provenance_cid:      cid,         ; CID of the ProvenanceMemento for this plugin
    schemaVersion:       "1",
    version:             semver
  },
  metadata: {
    ? note: tstr,
    ? source_url: tstr,
    ? maintainer: tstr
  }
}
```

### §1.2 Field semantics

| Layer    | Field                | Required | Meaning |
|----------|----------------------|----------|---------|
| envelope | `declaredAt`         | yes      | ISO-8601 UTC minting timestamp. |
| envelope | `signature`          | yes (swarm) | Ed25519 over `JCS(header ++ metadata)`. |
| envelope | `signer`             | yes      | `ed25519:<base64>` minter public key. |
| header   | `cid`                | yes      | Content CID; DERIVED per §6.1. |
| header   | `content`            | yes      | The kind-specific payload. Its CDDL is defined by the consumer spec for `kind` (e.g., `2026-05-12-sugar-dict-memento.md` §2 for `kind = "sugar"`). Validators of this protocol MUST NOT validate the inner shape; consumer specs MUST. |
| header   | `critical`           | yes      | If `true`, a failure to load this plugin (§8) MUST refuse the run. If `false`, the failure is recorded as a `PluginLoadFailureMemento` and the run proceeds. Default if elided is `false`; producers MUST emit the field explicitly to keep CIDs byte-stable. |
| header   | `kind`               | yes      | One of the canonical labels (§2.1) or an open-extension label. Unknown labels MUST NOT be rejected at shape level. |
| header   | `protocol_versions`  | yes      | The protocol-version tokens this plugin SPEAKS. The runtime MUST refuse to load a plugin whose `protocol_versions` does not contain a token the runtime accepts (§5). |
| header   | `provenance_cid`     | yes      | CID of a `ProvenanceMemento` (per `2026-05-06-provenance-memento.md`) recording the build chain that produced this plugin's declared content. |
| header   | `schemaVersion`      | yes      | MUST be `"1"` for v1.0.0 of this protocol. |
| header   | `version`            | yes      | Semver of the plugin's own version line. Producers SHOULD bump on every content-payload change; consumers MUST compare CIDs, not semver, for identity. |
| metadata | `note`               | no       | Human-readable. OMITTED when absent. |
| metadata | `source_url`         | no       | Where the plugin's source lives. OMITTED when absent. |
| metadata | `maintainer`         | no       | Free-form maintainer string. OMITTED when absent. |

## §2. Plugin kinds

### §2.1 Canonical labels (v1.0.0)

Open enum. The following labels are reserved by v1.0.0 of this protocol; their consumer specs are minted separately. A `kind` not in this list is an extension label; validators MUST accept it at shape level (§5.3 of consumer specs decides further).

| `kind`                | Consumer spec                                                                 | What it carries                                                                                  |
|-----------------------|-------------------------------------------------------------------------------|--------------------------------------------------------------------------------------------------|
| `agent`               | `2026-04-30-agent-plugin-protocol.md` (LEGACY-RETAINED content-payload shape; legacy protocol identifier `sugar-agent/1`) | Agent proposals and verification invocations; first legacy kind absorbed into this protocol. |
| `lift`                | `2026-04-30-lift-plugin-protocol.md` (LEGACY-RETAINED content-payload shape; legacy protocol identifier `sugar-lift/1`)   | Source-to-IR mint procedures via JSON-RPC over stdio. `lift` is the canonical kind name for source-to-IR plugins under `pep/1.7.0`. The name `lifter` is a DEPRECATED ALIAS retained ONLY for human-readable CLI ergonomics (per §3.1 alias `--lifter <source>` desugars to `--plugin lift:<source>`); the wire `kind` value MUST be `"lift"`. |
| `sugar`               | `2026-05-12-sugar-dict-memento.md`                                            | Canonical-clause-to-surface-syntax rendering rules; the first consumer of this protocol.         |
| `loss-function`       | `2026-05-12-loss-function-memento.md`                                         | Scoring algorithms over `loss-record` candidates; the second consumer of this protocol.          |
| `discharge-backend`   | DEFERRED to follow-up; precedent `2026-04-30-multi-solver-protocol.md`        | Z3 / cvc5 / Vampire / Maude / CeTA / others; one plugin per backend.                             |
| `realizer`            | DEFERRED; precedent `2026-05-06-obligation-realizer-protocol.md`              | Per-language contract-to-discharge-obligation lowering rule.                                     |
| `effect-signature`    | DEFERRED                                                                      | New effect-signature mints; consumed by the algebraic-effects layer.                             |
| `concept-extension`   | DEFERRED; precedent `2026-05-15-concept-hub-abstraction-layer.md`             | New `concept:*` hub op mints.                                                                    |
| `pattern-predicate`   | DEFERRED; precedent `2026-05-09-pattern-predicate-protocol.md`                | Editorial pattern -> predicate -> witness pipeline registrations (PPP).                          |
| `bundle-attestation`  | DEFERRED; precedent `2026-05-02-bundle-attestation-protocol.md`               | Signed-bundle attestations for binaries, self-contracts, and catalogs (the kind-literal path).   |
| `ir-extension`        | DEFERRED; precedent `2026-04-30-ir-extension-protocol.md`                     | IR-name extensions mounted at content-addressed extension points.                                |

The kind enum is OPEN. A `kind` not in this table is an extension label; validators MUST accept it at shape level. The DEFERRED rows reserve the canonical labels under `pep/1.7.0`; their consumer specs MAY be minted under `pep/1.7.x` patch releases (definitional clarifications only) or under `pep/1.8.0` (new normative requirements per §13).

### §2.2 Kind discipline

A `kind` label is part of the plugin memento CID (§6.1). The same content bytes registered under two different kinds produce two different CIDs. This is correct: a `sugar` plugin and a `loss-function` plugin are different things even if their `content` bytes coincide accidentally. The kind is semantic.

## §3. File interface

A plugin MAY be delivered as a JSON file containing the JCS-canonical bytes of the plugin memento's `header`. The runtime loads it as follows:

1. Read the file. Reject (refuse) on read error.
2. Parse JSON. Reject (refuse) on parse error.
3. Validate against the plugin-memento CDDL (§1.1). Validate the `content` payload against the consumer spec's CDDL for the declared `kind`.
4. Compute the CID per §6.1. If a `cid` is asserted in the parsed bytes and does not match, reject (refuse): cached-with-truth-source means the cache MUST equal truth.
5. Negotiate protocol-version per §5. Reject (refuse) on mismatch.
6. Register in the runtime registry under `(kind, cid)` per §9.

### §3.1 CLI flag form

The canonical CLI form is:

```
--plugin <kind>:<source>
```

where `<source>` is a filesystem path (absolute or relative to CWD) or an RPC endpoint descriptor. The runtime MUST distinguish file sources from RPC sources by inspecting `<source>`: a string beginning with `stdio:`, `http://`, `https://`, or `tcp://` (or matching the JSON-RPC endpoint grammar of §4) is treated as RPC; otherwise it is treated as a file path. The `stdio:` prefix is the canonical form for sidecar subprocess plugins (matching the LSP/MCP spawn shape) and MUST be recognized as a first-class RPC-source kind.

Per-kind aliases SHOULD be provided by the runtime for ergonomic reasons:

```
--sugar <source>           ≡  --plugin sugar:<source>
--loss-function <source>   ≡  --plugin loss-function:<source>
--lifter <source>          ≡  --plugin lift:<source>
```

Aliases MUST desugar to the canonical form before registry insertion; the canonical form is what appears in the `PluginRegistryMemento` (§9).

### §3.2 Multi-load and order

Repeated flags load multiple plugins of the same kind. CLI flag ORDER is preserved through to the registry's `load_order` array (§9.1) and is consulted by kind-specific tie-breaking (e.g., `2026-05-12-sugar-dict-memento.md` §4.4: later sugar dicts win ties). Order MUST be deterministic across runs given identical argv.

## §4. JSON-RPC interface

A plugin MAY be delivered as a JSON-RPC 2.0 server speaking over stdio or HTTP. The runtime connects, calls `describe` to obtain the plugin memento, validates and registers as in §3.

### §4.1 Endpoint grammar

```
<endpoint> = "stdio:" <argv-list>
           | "http://" <host> ":" <port> <path>
           | "https://" <host> ":" <port> <path>
           | "tcp://" <host> ":" <port>
```

The `stdio:<argv-list>` form spawns a subprocess (matching the LSP/MCP shape of the predecessor specs `2026-04-30-agent-plugin-protocol.md` and `2026-04-30-lift-plugin-protocol.md`).

### §4.2 Methods

#### §4.2.1 `sugar.plugin.describe`

The first call after connect. Returns the plugin's declared content memento.

Request:
```json
{
  "jsonrpc": "2.0",
  "id": 1,
  "method": "sugar.plugin.describe",
  "params": {
    "runtime_protocol_versions": ["pep/1.7.0"]
  }
}
```

Response (success):
```json
{
  "jsonrpc": "2.0",
  "id": 1,
  "result": {
    "header": { /* the plugin memento's header object, JCS-canonical */ },
    "envelope": { /* the plugin memento's envelope object */ },
    "metadata": { /* the plugin memento's metadata object */ }
  }
}
```

The runtime MUST compute the CID over the returned `header` per §6.1 and compare to the asserted `header.cid`. Mismatch is a refuse.

#### §4.2.2 `sugar.plugin.invoke`

Kind-specific. The consumer spec for each kind defines the `params` and `result` shapes for `invoke`. The protocol-level guarantee is only the JSON-RPC 2.0 envelope.

Request:
```json
{
  "jsonrpc": "2.0",
  "id": 2,
  "method": "sugar.plugin.invoke",
  "params": { /* kind-specific */ }
}
```

#### §4.2.3 `sugar.plugin.resolve_dependency_proofs`

Kit-owned package-manager proof resolution. The runtime calls this method before
verification pool assembly. The substrate MUST NOT inspect cargo metadata,
classpath entries, node_modules, sys.path, or any other platform dependency
graph directly; it passes the project root to configured kits and unions the
returned proof catalog bytes by CID.

Request:
```json
{
  "jsonrpc": "2.0",
  "id": 3,
  "method": "sugar.plugin.resolve_dependency_proofs",
  "params": {
    "project_root": "/absolute/project/root"
  }
}
```

Response (success):
```json
{
  "jsonrpc": "2.0",
  "id": 3,
  "result": {
    "proofs": [
      {
        "cid": "blake3-512:<hex>",
        "bytes_base64": "<standard-base64-proof-catalog-bytes>",
        "source": "diagnostic-kit-owned-label"
      }
    ]
  }
}
```

`proofs` entries MUST carry opaque `.proof` catalog bytes in `bytes_base64`.
`cid`, when present, MUST match the content CID of those bytes. `source` is a
diagnostic label only and MUST NOT be treated as filesystem or package-manager
authority. Implementations MAY return an empty array when the language kit has
no implementation yet, but MUST log that language-specific dependency proof
resolution is not implemented. The runtime MUST load by bytes, recompute bundle
and member CIDs, and union members. It MUST NOT extract formulas for rewriting,
follow kit-supplied `.proof` paths, or reinterpret package-manager metadata.

#### §4.2.4 `sugar.plugin.shutdown`

Graceful close. After this, an `stdio:` plugin SHOULD exit zero on stdin EOF; an HTTP plugin MAY ignore the call.

#### §4.2.5 `sugar.plugin.recognize` (RETIRED)

RETIRED (#3811). The `recognize` and `materialize` verbs are removed from the
protocol and from every kit. Ingress into the proof pool is lift of native
source (the factory); egress is emission of native artifacts from neutral
predicates (`emit`). There is no source-rewriting verb and no tag-scanning
verb. Kits MUST NOT declare `sugar.plugin.recognize` or
`sugar.plugin.materialize` in their kit declarations; the runtime does not
dispatch them.

### §4.3 Error model on the wire

JSON-RPC errors per RFC 7065. The runtime treats any error response from `describe` as a failure to load (§8). The runtime treats any non-JSON output on stdout from an `stdio:` plugin as a refuse.

## §5. Version negotiation

### §5.1 Protocol versions the runtime accepts

The runtime declares a SET of protocol-version tokens it accepts. v1.0.0 of this spec defines `pep/1.7.0` as the canonical token. During the deprecation migration window defined in §0.4, the current minor version of the runtime MUST also accept `sugar-agent/1` and `sugar-lift/1` as legacy tokens (with a loud deprecation notice per §0.4). The NEXT minor version of the runtime MUST drop the legacy tokens and accept only `pep/1.7.0`. Future minor versions of this protocol that are wire-compatible MAY add tokens to the set; future major versions mint a new spec at a new file path.

### §5.2 Negotiation procedure

A plugin's `header.protocol_versions` MUST contain at least one token the runtime accepts. The runtime selects the FIRST token (in plugin-declared order) that it accepts and uses that for the remainder of the session.

If no token matches, the runtime refuses to load the plugin. This MUST emit a `PluginLoadFailureMemento` with `reason_kind = "protocol-version-mismatch"` (§8.1). The plugin is NOT registered.

### §5.3 No silent fallback

The runtime MUST NOT attempt an "older protocol" or "best-effort" parse on version mismatch. Per Supra omnia, rectum, a version mismatch is a refuse, not a degraded load.

## §6. Content-addressing rules

### §6.1 CID construction

The `cid` field is `"blake3-512:" ++ hex(BLAKE3-512(<cid_input>))` where `<cid_input>` is the JCS-canonical bytes of the header with `cid` elided. Concretely:

```
cid_input = JCS({
  "content":           <content>,
  "critical":          <critical>,
  "kind":              <kind>,
  "protocol_versions": <protocol_versions sorted ascending>,
  "provenance_cid":    <provenance_cid>,
  "schemaVersion":     "1",
  "version":           <version>
})
cid = "blake3-512:" ++ hex(BLAKE3-512(cid_input))
```

JCS canonicalization per `2026-04-30-canonicalization-grammar.md`. The `protocol_versions` array is sorted ascending lexicographically before JCS; the runtime MUST sort, and producers MUST emit sorted arrays.

### §6.2 Delivery does not affect CID

The CID is determined by the content payload (`content`, `kind`, `critical`, `protocol_versions`, `provenance_cid`, `schemaVersion`, `version`). Two plugins with byte-identical headers MUST produce the same CID regardless of whether they are delivered as JSON files or as JSON-RPC servers. This is the federation guarantee.

**INVARIANT (CID-delivery-independence):** For any plugin P, `CID(P-as-file) == CID(P-as-rpc)` if and only if their JCS-canonical header bytes coincide.

### §6.3 No implicit plugins

A runtime MUST NOT compile in or silently append default plugins. Plugin registration is data: config, manifests, and explicit RPC/file sources are the registry inputs. A "default" loss function or other common surface is still a normal plugin entry with a normal manifest/source and a content-addressed CID computed by §6.1. It is not a privileged runtime class.

## §7. CLI flag conventions

| Flag form                              | Effect                                                                                                  |
|----------------------------------------|---------------------------------------------------------------------------------------------------------|
| `--plugin <kind>:<source>`             | Canonical form. Loads one plugin of declared kind from the source.                                      |
| `--<kind> <source>`                    | Per-kind alias. Desugars to the canonical form. See §3.1.                                               |
| `--no-default-plugins`                 | Legacy compatibility no-op. No implicit plugins exist.                                                  |
| `--no-default-plugin <kind>`           | Legacy compatibility no-op. No implicit plugins exist.                                                  |
| `--strict-plugins`                     | Promotes EVERY plugin load failure to a refuse (overrides individual `critical = false` declarations).  |
| `--plugin-registry-out <path>`         | After the registry seals (§9), writes the `PluginRegistryMemento` to `<path>`.                          |

Flag order is preserved through to `PluginRegistryMemento.load_order` (§9.1). The runtime does not append implicit plugins, so the load order is the order of configured manifest entries and explicit user-provided sources.

## §8. Error model

### §8.1 `PluginLoadFailureMemento`

When a plugin fails to load (file not found, parse error, validation error, RPC timeout, version mismatch, signature invalid, CID mismatch), the runtime MUST mint a `PluginLoadFailureMemento`:

```cddl
; Locked JCS key order: cid, declared_source, failure_at, kind, plugin_kind,
; reason_detail, reason_kind, schemaVersion
plugin-load-failure-memento = {
  envelope: {
    declaredAt: iso8601,
    signature:  signature,
    signer:     pubkey
  },
  header: {
    cid:              cid,            ; DERIVED -- see §8.3
    declared_source:  tstr,           ; the CLI flag value verbatim, e.g. "sugar:./my-sugar.json"
    failure_at:       iso8601,        ; when the load was attempted
    kind:             "plugin-load-failure",
    plugin_kind:      plugin-kind,    ; the declared kind from the CLI flag
    reason_detail:    tstr,           ; human-readable diagnostic
    reason_kind:      failure-reason-kind,
    schemaVersion:    "1"
  },
  metadata: { ? note: tstr }
}

failure-reason-kind = "file-not-found"
                    / "parse-error"
                    / "validation-error"
                    / "rpc-timeout"
                    / "rpc-error"
                    / "protocol-version-mismatch"
                    / "signature-invalid"
                    / "cid-mismatch"
                    / "duplicate-cid-collision"
                    / "critical-load-aborted"
                    / tstr
```

### §8.2 Trichotomy of plugin loading

| Run outcome                | Condition                                                                                     | Behavior                                                                                          |
|----------------------------|-----------------------------------------------------------------------------------------------|---------------------------------------------------------------------------------------------------|
| `exact`                    | Every requested plugin loaded; no `PluginLoadFailureMemento` minted.                          | Registry sealed (§9); run proceeds.                                                               |
| `loudly-bounded-lossy`     | One or more NON-CRITICAL plugins failed; ALL failures recorded as `PluginLoadFailureMemento`s. | Registry sealed with `failures` populated; run proceeds; downstream consumers MAY refuse.        |
| `refuse`                   | ANY critical plugin failed, OR `--strict-plugins` is set and any plugin failed, OR §9.2 collision. | Runtime MUST exit non-zero. The failures are emitted to stderr AND written to the registry-out path if specified. |

### §8.3 Failure-memento CID

```
cid_input = JCS({
  "declared_source": <declared_source>,
  "failure_at":      <failure_at>,
  "kind":            "plugin-load-failure",
  "plugin_kind":     <plugin_kind>,
  "reason_detail":   <reason_detail>,
  "reason_kind":     <reason_kind>,
  "schemaVersion":   "1"
})
cid = "blake3-512:" ++ hex(BLAKE3-512(cid_input))
```

## §9. Registry semantics

### §9.1 `PluginRegistryMemento`

At run start, after all `--plugin` flags are processed and all built-ins are loaded (modulo §7 suppressions), the runtime SEALS the registry into a `PluginRegistryMemento`:

```cddl
; Locked JCS key order: built_in_count, cid, failures, kind,
; load_order, loaded, runtime_protocol_versions, schemaVersion, sealed_at
plugin-registry-memento = {
  envelope: {
    declaredAt: iso8601,
    signature:  signature,
    signer:     pubkey
  },
  header: {
    built_in_count:            uint,                         ; how many entries in load_order are built-ins
    cid:                       cid,                          ; DERIVED -- see §9.3
    failures:                  [* cid],                      ; PluginLoadFailureMemento CIDs, in load-attempt order
    kind:                      "plugin-registry",
    load_order:                [* { kind: plugin-kind, cid: cid, source: tstr } ],
    loaded:                    [* { kind: plugin-kind, cid: cid } ],   ; sorted by cid ascending
    runtime_protocol_versions: [+ protocol-version],
    schemaVersion:             "1",
    sealed_at:                 iso8601
  },
  metadata: { ? note: tstr }
}
```

`load_order` preserves CLI order plus built-ins-at-end (§7); `loaded` is the same set sorted by CID (for content-addressing). Both fields are part of the CID; reordering CLI flags changes `load_order` bytes and rolls the registry CID, which rolls every downstream consumer that cited this registry. That is correct: a different load order is a different run.

### §9.2 Duplicate-CID collision rule

Two plugins of the same `(kind, cid)` slot is a no-op (the second registration is silently dropped; the first wins). Two plugins of the same `kind` with DIFFERENT CIDs are BOTH registered; tie-breaking among them is kind-specific (consumer specs define it).

Two DIFFERENT plugin mementos asserting the same `(kind, cid)` are impossible by construction (the CID is derived from the content). If observed, this is a hash collision or a tampered memento; the runtime MUST refuse with `reason_kind = "duplicate-cid-collision"` (§8.1) on the unlikely event of CID equality with non-identical bytes.

### §9.3 Registry CID

```
cid_input = JCS({
  "built_in_count":            <built_in_count>,
  "failures":                  <failures>,
  "kind":                      "plugin-registry",
  "load_order":                <load_order>,
  "loaded":                    <loaded sorted by cid ascending>,
  "runtime_protocol_versions": <runtime_protocol_versions sorted ascending>,
  "schemaVersion":             "1",
  "sealed_at":                 <sealed_at>
})
cid = "blake3-512:" ++ hex(BLAKE3-512(cid_input))
```

### §9.4 Provenance propagation

Any pipeline-output memento produced by a run MUST cite the `PluginRegistryMemento.cid` in its provenance. Concretely, every output memento's `provenance_cid` chain MUST resolve to a `ProvenanceMemento` whose `inputs` array contains the registry CID. This is the audit trail: a verifier can re-derive any output by replaying the exact plugin set the run used.

## §10. Federation mechanics

### §10.1 No central registry required

Plugins are content-addressed. A consumer references a plugin by CID (or by the kind plus a selection predicate the consumer spec defines). No directory service is required; a `PluginRegistryMemento` published alongside a `.proof` carries enough information for any verifier to fetch and re-load every plugin the run used (modulo plugin availability at the verifier's location, which is an out-of-protocol concern handled by the same content-addressed-storage mechanisms the rest of the substrate uses).

### §10.2 Plugin dependencies

A plugin's `content` payload MAY reference OTHER plugin CIDs (e.g., a sugar dict that depends on a particular lifter producing specific term-CIDs). The reference is content-addressed; the dependency graph is auditable. v1.0.0 of this protocol does NOT define an automatic dependency-resolution mechanism; consumer specs MAY require the runtime to refuse if a referenced dependency is not present in the registry.

### §10.3 Future discovery service

A federated discovery service (e.g., a content-addressed plugin index) is anticipated but is OUT OF SCOPE for v1.0.0. The CLI flag surface (§7) is the v1.0.0 interface. A future spec MAY define a discovery protocol on top of this base.

## §12. Cross-references

- The `cid` construction follows `2026-04-30-canonicalization-grammar.md`.
- The `provenance_cid` field MUST resolve to a `ProvenanceMemento` per `2026-05-06-provenance-memento.md`.
- The `protocol_versions` token grammar MUST conform to `2026-04-30-protocol-versioning.md`.
- The kind-specific predecessor specs (`2026-04-30-agent-plugin-protocol.md`, `2026-04-30-lift-plugin-protocol.md`) remain readable as authoritative definitions of the `content` payload shapes for the `agent` and `lift` kinds; this spec SUPERSEDES them as the ongoing protocol surface per §0.4. New `agent` and `lift` plugin mementos MUST be minted against `pep/1.7.0`, not the legacy tokens.
- The first two consumer specs are minted in this PR:
  - `2026-05-12-sugar-dict-memento.md` (kind = `"sugar"`).
  - `2026-05-12-loss-function-memento.md` (kind = `"loss-function"`).
- The `loss-record` shape consumed by `loss-function` plugins is defined in `2026-05-14-transport-gap-and-partial-morphism-protocol.md` §1.3 and elaborated in `2026-05-15-concept-hub-abstraction-layer.md` §2.4.
- The substrate trinity precedent: `project_sugar_substrate_trinity` (memo); the algebra-as-portable-thing thesis: `docs/papers/16-after-portability-the-universal-address-space.md`.

## §13. Out of scope for v1.0.0

- Hot-reload of the registry mid-run.
- Cross-runtime portability beyond byte-identical CIDs.
- Sandboxing of RPC plugin processes.
- A federated discovery service.
- Consumer specs for `discharge-backend`, `realizer`, `effect-signature`, `concept-extension`, `pattern-predicate`, `bundle-attestation`, and `ir-extension` (deferred follow-ups; see §13 for the cadence under which they may be minted).
- An edit to `2026-04-30-protocol-catalog.json` registering this spec's catalog entry (CI mint follow-up).

## §13. Versioning cadence (the "until 1.8" gate)

`pep/1.7.0` is the BLESSED baseline (§14). No additional structural changes ride along with this version. The cadence under which future revisions are permitted is normative:

1. **`pep/1.7.x` patch releases (x >= 1).** Bug fixes only. NO new kinds, NO new normative requirements, NO new sections, NO changes to the wire shape, NO changes to JCS key order, NO changes to the CID construction. A patch release MAY clarify ambiguous prose, fix cross-references, correct typos, or strengthen non-normative examples. A patch release MUST NOT roll the CID of any in-spec example shown in §1.1, §8.1, §9.1, or §14.
2. **`pep/1.8.0` next minor.** New kinds (graduating any DEFERRED row of §2.1; adding new rows), new sections, new normative requirements all queue here. Consumer specs for `discharge-backend`, `realizer`, `effect-signature`, `concept-extension`, `pattern-predicate`, `bundle-attestation`, and `ir-extension` SHOULD be minted under `pep/1.8.0`. New `kind` labels MUST be added as ordinary §2.1 rows; the kind enum remains open at shape level.
3. **Backward compatibility (1.8.x reads 1.7.x).** A `pep/1.8.x` runtime MUST load any well-formed `pep/1.7.x` memento. The `pep/1.7.x` -> `pep/1.8.x` upgrade is a non-breaking minor bump.
4. **Forward compatibility (1.7.x reads 1.8.x) is NOT required.** A `pep/1.7.x` runtime MAY refuse to load a `pep/1.8.x` memento whose `protocol_versions` array does not contain a token the runtime accepts (§5). Producers SHOULD include `pep/1.7.0` in `protocol_versions` for 1.8.x mementos that do not exercise any 1.8.0-introduced field; a 1.8.x memento that exercises a 1.8.0-introduced field MUST omit `pep/1.7.0` so that 1.7.x runtimes refuse rather than silently misparse.
5. **Major version bumps (`pep/2.0.0` and later).** Mint a new spec at a new file path. CID changes at the spec level; protocol-catalog entry is a new property key, not an in-place edit of `plugin-protocol`'s entry.

This section is the explicit scope-creep gate for v1.7.0. If a substrate-wide audit discovers a missing kind or a missing surface during the 1.7.0 rename, the discovery is FLAGGED for 1.8.0; it is NOT folded into 1.7.0 unless its absence makes the 1.7.0 surface internally incoherent.

## §14. Blessing

### §14.1 The blessing claim

`pep/1.7.0` is the substrate's officially blessed protocol identifier for plugin-protocol mementos AS OF the date in the header of this spec. Blessing is itself a first-class memento per Supra omnia, rectum: a blessed protocol that is not itself a signed content-addressed declaration is just an opinion.

The blessing memento is a `ProtocolBlessingMemento` (CDDL below) signed by the substrate maintainer key (the same Ed25519 provenance key used for `2026-05-06-provenance-memento.md` envelopes; see `reference_sugar_provenance_keys` in the substrate notes for key material location).

### §14.2 `ProtocolBlessingMemento` wire shape (CDDL)

```cddl
; Locked JCS key order: blessed_at, blessed_protocol_id, blessing_authority,
; cid, kind, schemaVersion, spec_cid, supersedes
protocol-blessing-memento = {
  envelope: {
    declaredAt: iso8601,
    signature:  signature,           ; over JCS(header ++ metadata)
    signer:     pubkey               ; ed25519:<base64> of the blessing authority
  },
  header: {
    blessed_at:           iso8601,   ; when the blessing was issued
    blessed_protocol_id:  tstr,      ; the canonical protocol-version token being blessed (e.g., "pep/1.7.0")
    blessing_authority:   tstr,      ; human-readable maintainer identity (e.g., "T Savo / nefariousplan.com")
    cid:                  cid,       ; DERIVED -- see §14.3
    kind:                 "protocol-blessing",
    schemaVersion:        "1",
    spec_cid:             cid,       ; CID of the spec file this blessing applies to
    supersedes:           [* tstr]   ; legacy protocol-version tokens this blessing retires
                                      ; (e.g., ["sugar-agent/1", "sugar-lift/1"])
  },
  metadata: {
    ? note: tstr,                    ; free-form maintainer note, e.g., the cadence statement
    ? cadence_section_cid: cid       ; CID of the §13 cadence section at blessing time, OMITTED when absent
  }
}
```

### §14.3 Blessing-memento CID

```
cid_input = JCS({
  "blessed_at":          <blessed_at>,
  "blessed_protocol_id": <blessed_protocol_id>,
  "blessing_authority":  <blessing_authority>,
  "kind":                "protocol-blessing",
  "schemaVersion":       "1",
  "spec_cid":            <spec_cid>,
  "supersedes":          <supersedes sorted ascending>
})
cid = "blake3-512:" ++ hex(BLAKE3-512(cid_input))
```

### §14.4 Where the blessing memento lives

This spec defines the SHAPE of the blessing memento. The actual signed instance for `pep/1.7.0` is minted in a follow-up CI step and stored at `protocol/blessings/pep-1.7.0.json`. This spec MUST NOT pin a specific hex CID for the blessing memento; the CID is computed from the bytes of the minted instance per §14.3. Verifiers MUST:

1. Locate the blessing memento at the conventional path (`protocol/blessings/<protocol-id>.json` with `/` mapped to `-`).
2. Verify the Ed25519 signature over `JCS(header ++ metadata)`.
3. Recompute the CID per §14.3 and compare to the asserted `header.cid`.
4. Confirm `header.spec_cid` equals the CID of THIS spec file (raw-bytes BLAKE3-512 over the file contents).
5. Confirm `header.blessed_protocol_id` equals the token the verifier is being asked to bless.

A failed blessing verification is a refuse: the runtime MUST NOT proceed to load plugins under an unverified protocol identifier in strict-mode operations. Non-strict-mode operations MAY warn and proceed.

### §14.5 Blessing scope

The blessing covers the plugin-protocol identifier `pep/1.7.0` and its §13 cadence. Subsequent patch releases (`pep/1.7.x`) inherit the blessing automatically. The next minor release (`pep/1.8.0`) requires a NEW `ProtocolBlessingMemento` minted at the time `pep/1.8.0`'s spec lands; the 1.8.0 blessing memento's `supersedes` array MUST include `pep/1.7.0` (signaling the cadence promotion) but the `pep/1.7.x` mementos MUST remain loadable by 1.8.x runtimes per §13.3.

## §15. Migration trinity-convergence invariant

The 1.7.0 cut is a substrate transformation that MUST preserve convergence on THREE axes simultaneously: bytes, address-space (CIDs of content-addressed artifacts), and concept-space (concept-hub identifiers). Each axis is a separate normative invariant. The three together compose the trinity-convergence guarantee that downstream substrate (FunctionContractMementos, EvidenceMementos, SugarEntries, ConceptSiteMementos, and every other memento that references an identifier rather than carrying inline bytes) MAY depend on across the rename.

### §15.1 Byte-stability invariant (axis 1: bytes)

Across the substrate-wide rename from `sugar-{agent,lift}/1` to `pep/1.7.0` (the 1.7.0 cut), every byte of every plugin memento's `content` payload EXCEPT the protocol-identifier field is preserved exactly. Concretely, for any legacy memento M_legacy with header fields `{content, critical, kind, protocol_versions = ["sugar-agent/1"] | ["sugar-lift/1"], provenance_cid, schemaVersion, version}` and its re-mint M_pep with header fields `{content, critical, kind, protocol_versions = ["pep/1.7.0"], provenance_cid, schemaVersion, version}`:

- `M_legacy.content` is byte-identical to `M_pep.content`.
- `M_legacy.critical` is byte-identical to `M_pep.critical`.
- `M_legacy.kind` is byte-identical to `M_pep.kind` (the kind label is unchanged; the kind enum simply gained `agent` and `lift` as canonical first-class entries under `pep/1.7.0`).
- `M_legacy.provenance_cid` is byte-identical to `M_pep.provenance_cid`.
- `M_legacy.schemaVersion` is byte-identical to `M_pep.schemaVersion`.
- `M_legacy.version` is byte-identical to `M_pep.version`.

ONLY `protocol_versions` changes shape (its single element is renamed from the legacy token to `pep/1.7.0`). CID changes are the consequence of that one-field change; no other bytes shift. This is the precise content-addressable claim the rename makes.

### §15.2 Why this matters

The byte-stability invariant is what lets a verifier audit the rename mechanically. The pair `(M_legacy.cid, M_pep.cid)` can be related by a one-field substitution; an attacker cannot smuggle a different content payload through the renaming gate, because the JCS-canonical bytes of every other field are pinned by the legacy CID's content-addressing.

### §15.3 Verification procedure

For any pair `(M_legacy, M_pep)` claimed to be a rename pair:

1. Recompute `M_legacy.cid` from `M_legacy`'s JCS-canonical bytes; confirm equality with the asserted `M_legacy.cid`.
2. Recompute `M_pep.cid` from `M_pep`'s JCS-canonical bytes; confirm equality with the asserted `M_pep.cid`.
3. Confirm that the JCS-canonical bytes of `M_legacy` differ from those of `M_pep` ONLY in the `protocol_versions` value position.
4. Confirm `M_pep.protocol_versions == ["pep/1.7.0"]` exactly.
5. Confirm `M_legacy.protocol_versions` is a single-element array containing one of `{"sugar-agent/1", "sugar-lift/1"}`.

A pair that fails any check is NOT a valid rename pair; both mementos remain valid content-addresses of their respective bytes, but the "byte-stability rename" claim is REFUTED.

### §15.4 Address-space-stability invariant (axis 2: CIDs)

Across the 1.7.0 cut, all content-addressed identifiers in the substrate that are NOT plugin-protocol mementos MUST retain their existing CIDs. Concretely:

- Every memento under `menagerie/concept-shapes/` (the canonical content-addresses of concept-hub shape mementos) retains its CID. The 1.7.0 cut MUST NOT edit any file in `menagerie/concept-shapes/`.
- Every `ProvenanceMemento` CID referenced by `header.provenance_cid` is unchanged; the rename does NOT re-mint any provenance memento.
- Every `EvidenceMemento`, `FunctionContractMemento`, `SugarEntry`, `ConceptSiteMemento`, `LossFunctionMemento`, or other substrate memento outside the plugin-protocol layer retains its CID across the rename.
- The set of mementos whose CIDs are PERMITTED to change under the 1.7.0 cut is exactly the set of plugin-protocol mementos that flip their `protocol_versions` field; the magnitude of that change is governed by §15.1. No other CID in the substrate may roll as a consequence of this rename.

A verifier auditing the rename MUST be able to confirm that any CID referenced in any non-plugin-protocol memento before the PR merges resolves to byte-identical content after the PR merges.

### §15.5 Concept-space-stability invariant (axis 3: concept hub)

Across the 1.7.0 cut, all `concept:*` hub identifiers in the substrate MUST remain at their existing CIDs. Concretely:

- `concept:option`, `concept:result`, `concept:throw`, `concept:async`, `concept:result-bind`, `concept:option-bind`, and every other published `concept:*` op retain their CIDs.
- Where a memento payload REFERENCES a concept-CID (e.g., a `FunctionContractMemento.concept` field, an `EvidenceMemento` referencing a `concept:throw` hub op, a `SugarEntry.predicate_pattern` that names `concept:option`, a `ConceptSiteMemento.concept_cid` pointer), that reference's BYTES MUST be byte-identical before and after the rename. The substrate's address-space and concept-space are invariants of this rename; only the protocol-identifier field at the plugin-memento header is permitted to change.
- Implementers MUST verify, before merging the PR that performs the 1.7.0 cut, that the concept-shape mementos' CIDs are unchanged and that no concept-reference bytes have shifted anywhere in the substrate. The audit is a `git diff menagerie/concept-shapes/` returning empty, plus a substrate-wide `rg 'concept:[a-z][a-z0-9-]+' --type-not binary` whose pre-PR and post-PR outputs differ only in newly-added prose that NAMES concepts (e.g., this spec's §2.1 row for `concept-extension`) and never in concept-CID-bearing bytes inside any memento payload.

### §15.6 Trinity-convergence audit

For the 1.7.0 cut PR, the merge gate is the conjunction of all three axes:

1. **Bytes (§15.1).** Every non-protocol-identifier byte of every plugin memento's `content` payload is preserved exactly; `M_legacy.content == M_pep.content` bit-for-bit, and the same for `critical`, `kind`, `provenance_cid`, `schemaVersion`, `version`.
2. **Address-space (§15.4).** Every non-plugin-protocol CID in the substrate resolves to byte-identical content before and after the rename; the set of changed CIDs is exactly the set of re-minted plugin-protocol mementos.
3. **Concept-space (§15.5).** Every `concept:*` hub identifier and every reference-to-concept inside every memento payload is byte-identical before and after.

A PR that fails any of the three is NOT a valid 1.7.0 cut. The rename is irreversible (once mementos ship under `pep/1.7.0`, those CIDs are forever), so the audit is the gate: a failing trinity-convergence check requires the PR to be reworked before merge, not patched after.

### §15.7 Scope of the invariants

The trinity-convergence invariants apply to the v1.7.0 substrate-wide rename ONLY. Subsequent kind-payload shape changes (under `pep/1.8.0` or later) are NOT covered by these invariants; they may legitimately shift bytes of `content`, may re-mint substrate mementos, may roll concept-CIDs per their own normative procedures (and per §13). The invariants exist to bless the 1.7.0 cut precisely because the 1.7.0 cut is structurally trivial on all three axes: the only intended change is a single string-rename at the protocol-identifier field of plugin-protocol mementos.
