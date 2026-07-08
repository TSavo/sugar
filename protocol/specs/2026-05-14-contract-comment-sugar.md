# Contract-Comment Sugar (`pep/1.7.0`, liftable pre/post/invariant comments)

**Status: RETIRED (2026-07-07, #3809 / #3816).** The comment-pragma authoring
surface described here (`//sugar:contract`, JSDoc/doc-comment pre/post/invariant
tags) is retired along with the entire annotation family. The only lift path is
native source: contracts come from real assertions and function bodies, never
from a bespoke comment DSL. This document is kept for protocol history only and
is no longer normative.

**Status (historical):** v1.0.0 normative draft.
**Date:** 2026-05-14
**Author:** T Savo
**Related:**
- `2026-05-12-sugar-dict-memento.md` (`kind = "sugar"`, selection and loss scoring)
- `2026-05-13-bind-ir-lift-result.md` (`bind-contract-witness-entry`)
- `2026-05-13-compound-contract-memento.md` (`EvidenceMemento`, `CompoundContractMemento`)
- `2026-05-13-body-template-memento.md` (sibling: executable body cells)
- `2026-05-13-observation-wrapper-memento.md` (observation wrappers; this spec carries contract clauses)
- `2026-05-14-transport-gap-and-partial-morphism-protocol.md` §1.3 (`loss-record`)
- `2026-05-12-loss-function-memento.md` (loss-function plugin used at selection time)
- `2026-04-30-canonicalization-grammar.md` (JCS + BLAKE3-512)
- `2026-04-30-ir-formal-grammar.md` (`IrFormula`)

## §0. Purpose

The universal comment floor in `2026-05-12-sugar-dict-memento.md` can always
emit human-readable prose, but prose alone is not a substrate fact. It is
useful documentation with loss. A round trip needs a stricter surface:

1. the realizer emits a source-language comment that carries a canonical
   contract payload;
2. a human or tool can inspect the payload as an audit trail;
3. the lifter can recover the payload as structured `bind-contract-witness-entry`
   evidence on the next lift; and
4. the recovered witness cites the same contract/formula CIDs, or it refuses.

This spec defines that liftable comment surface. It is a sugar surface, not a
new memento family. A conforming implementation still mints/consumes
`EvidenceMemento`, `CompoundContractMemento`, `SugarDictMemento`, and the
existing bind witness shape. The comment is the carrier. The CID is the name.

### §0.1 Prose floor vs contract-comment sugar

| Surface | Liftable | Loss expectation | Purpose |
|---|---:|---|---|
| prose comment floor | no | non-empty `machine_uncheckable_prose` or equivalent | Human breadcrumb when no rigorous surface is selected. |
| contract-comment sugar | yes | empty only when the canonical formula payload relifts byte-identically | Machine-readable contract evidence embedded in host comments. |

A realizer MUST NOT claim the prose floor is exact. A contract-comment payload
MAY be exact only when its CIDs and canonical formula bytes validate per §4.

### §0.2 CID authority

Human-readable fields (`fol_text`, `concept_name`, `note`, `human_name`) are
diagnostic and editable. They do not identify the substrate object. The
authoritative pointers are CIDs:

- `concept_site_cid` points to the concept site being annotated.
- `contract_cid` points to the contract or compound contract being cited.
- `local_contract_cid` points to the local compound contract when it differs
  from the public contract being cited.
- `ir_formula_jcs_cid` points to the canonical formula bytes.
- `loss_record_cid`, `sugar_dict_cid`, and `policy_cid` point to the selection
  and loss facts that explain why this surface exists.

If a CID field and a human-readable field disagree, the CID wins. If the CID
cannot be resolved or recomputed, the lifter MUST fail closed (§5).

## §1. Wire shape

The embedded payload is a JCS-canonical JSON object. Hosts MAY wrap it in any
language-idiomatic comment syntax (§3), but the payload bytes inside the wrapper
MUST be recoverable as UTF-8 JSON.

```cddl
; Imports:
;   cid        ; "blake3-512:" 128HEXDIG
;   ir-formula ; from 2026-04-30-ir-formal-grammar.md
;   loss-record ; from 2026-05-14-transport-gap-and-partial-morphism-protocol.md §1.3

contract-comment-role = "pre" / "post" / "invariant" / "throws" / "observation"

; Locked JCS key order: artifact_kind, concept_site_cid, contract_cid,
; emitted_by, fol_text, ir_formula_jcs, ir_formula_jcs_cid,
; local_contract_cid, loss_record_cid, policy_cid, role,
; schema_version, sugar_dict_cid
contract-comment-payload = {
  artifact_kind:       "sugar-contract-comment-sugar",
  concept_site_cid:    cid,
  contract_cid:        cid,
  emitted_by:          emitted-by,
  fol_text:            tstr,
  ? ir_formula_jcs:    ir-formula,
  ir_formula_jcs_cid:  cid,
  ? local_contract_cid: cid,
  loss_record_cid:     cid,
  policy_cid:          cid,
  role:                contract-comment-role,
  schema_version:      "1",
  sugar_dict_cid:      cid
}

; Locked JCS key order: kit_cid, kit_kind, target_language
emitted-by = {
  kit_cid:          cid,
  kit_kind:         "realize" / "lift" / "sugar" / tstr,
  target_language:  tstr
}
```

### §1.1 Field semantics

| Field | Required | Meaning |
|---|---:|---|
| `artifact_kind` | yes | MUST be `"sugar-contract-comment-sugar"`. |
| `schema_version` | yes | MUST be `"1"`. Unknown versions MUST fail closed. |
| `concept_site_cid` | yes | The concept site the contract evidence is attached to. |
| `contract_cid` | yes | The public contract or compound contract CID being cited. |
| `local_contract_cid` | no | The local compound contract CID when different from `contract_cid`; omitted when absent. |
| `role` | yes | Clause role. `pre`, `post`, and `invariant` map directly to bind witness roles. `throws` and `observation` are admitted extensions with the same fail-closed validation rules. |
| `fol_text` | yes | Human-readable FOL text. Diagnostic only; never authoritative over `ir_formula_jcs` / `ir_formula_jcs_cid`. |
| `ir_formula_jcs` | no | Canonical `IrFormula` payload. When present, the lifter recomputes `ir_formula_jcs_cid` over its JCS bytes. A policy MAY omit it and expose only the CID; then relift can recover only if the formula is resolvable from the local/federated catalog. |
| `ir_formula_jcs_cid` | yes | CID of the canonical `IrFormula` bytes. Required even when `ir_formula_jcs` is omitted. |
| `loss_record_cid` | yes | CID of the loss record for this sugar emission. Empty-loss records still have a CID. |
| `sugar_dict_cid` | yes | CID of the sugar dict selected to emit this comment payload. |
| `policy_cid` | yes | CID of the policy that allowed or required tag/comment emission. |
| `emitted_by` | yes | Kit identity and target language that emitted the surface. Participates in the payload CID. |

### §1.2 Payload CID

The contract-comment payload's CID is:

```text
payload_cid = blake3-512(JCS(contract-comment-payload))
```

The payload CID MAY be emitted next to the payload as a host-language comment
field (for example `sugar-contract-payload-cid`). If present, the lifter MUST
recompute and compare it. If absent, the lifter computes it and records it in
`extension_fields.payload_cid`.

### §1.3 Exactness condition

A contract-comment witness is exact with respect to formula recovery only when
all of the following hold:

1. `schema_version == "1"`;
2. every required CID field is well formed;
3. `ir_formula_jcs` is present or resolvable by `ir_formula_jcs_cid`;
4. `blake3-512(JCS(ir_formula_jcs)) == ir_formula_jcs_cid`;
5. the parsed formula is accepted as an `IrFormula`;
6. the payload CID, when emitted, recomputes byte-identically; and
7. the lifter maps the payload into `bind-contract-witness-entry` without
   falling back to raw JSON strings.

If any condition fails, the lifter MUST NOT emit trusted contract evidence from
the comment.

## §2. Realizer behavior

A realizer emits contract-comment sugar when the active sugar/policy selection
chooses this surface for a canonical contract clause. The realizer MUST:

1. select the sugar entry through the normal sugar selection algorithm in
   `2026-05-12-sugar-dict-memento.md` §4;
2. compute the loss record observed by this surface;
3. compute `loss_record_cid`;
4. compute `ir_formula_jcs_cid` from the canonical formula;
5. populate the payload in §1;
6. optionally include `ir_formula_jcs` when policy permits source-visible
   canonical payloads; and
7. place the payload at the host-language surface declared by the sugar entry's
   `surface_locator`.

The selection policy decides whether this comment appears alone, alongside
stricter surfaces, or not at all. In inclusive mode, a realizer MAY emit Bean
Validation annotations, JUnit assertions, and contract-comment sugar for the
same clause. Each emitted surface carries its own loss record.

### §2.1 Recommended sugar entry shape

A language-specific sugar dict SHOULD represent liftable contract comments as a
normal `sugar-entry` with a precise `surface_locator`, for example:

```json
{
  "emission_template": {
    "kind": "computed",
    "surface_locator": "comment:above-method",
    "template": "sugar-contract:<computed-payload>"
  },
  "loss_record_contribution": {
    "form": "literal",
    "value": {}
  },
  "predicate_pattern": {
    "args": [],
    "kind": "atomic",
    "name": "${any_formula}"
  }
}
```

`computed` is intentionally named here even though `sugar-dict-memento`
v1.0.0 wires only `verbatim`. A kit that cannot compute the JSON payload from
the matched formula MUST refuse this entry rather than emit stale placeholders.

### §2.2 Policy-visible options

Emission policy MAY independently choose:

- whether to emit contract comments;
- whether to include `ir_formula_jcs` or only `ir_formula_jcs_cid`;
- whether comments are required, optional, or forbidden;
- whether malformed or missing comments are a relift refusal or a clustering
  fallback; and
- whether a prose comment floor is allowed when contract-comment sugar refuses.

Those choices are policy facts cited by `policy_cid`, not hidden kit defaults.

## §3. Host-language embedding

The host embedding must preserve the JSON payload bytes after unescaping. A
language MAY split long payloads across adjacent comment lines only when the
lifter's recombination rule is deterministic and specified by that language
adapter.

### §3.1 Java

Java implementations SHOULD use adjacent line comments above a method or inside
an observation wrapper body:

```java
// sugar-contract: {"artifact_kind":"sugar-contract-comment-sugar",...}
// sugar-contract-payload-cid: blake3-512:...
```

Javadoc MAY carry the same fields, but a Java lifter MUST treat the line-comment
and Javadoc surfaces as the same payload after extraction. Annotations are a
different sugar surface and are not defined by this spec.

### §3.2 Python

Python implementations MAY use line comments, function docstrings, decorators
that hold string literals, or native contract libraries. For the comment
surface, the recommended embedding is:

```python
# sugar-contract: {"artifact_kind":"sugar-contract-comment-sugar",...}
# sugar-contract-payload-cid: blake3-512:...
```

Docstring payloads MUST be parsed only from lines beginning with
`sugar-contract:` after indentation normalization. Free prose in the same
docstring is not contract-comment sugar.

### §3.3 Rust

Rust implementations SHOULD use ordinary or doc comments:

```rust
// sugar-contract: {"artifact_kind":"sugar-contract-comment-sugar",...}
// sugar-contract-payload-cid: blake3-512:...
```

`#[...]` attributes are native Rust sugar and are outside this comment-sugar
surface unless their value is exactly the payload defined in §1.

### §3.4 C

C implementations MAY use line comments or block comments. When block comments
are used, the payload MUST be the only machine-readable content in the block:

```c
/* sugar-contract: {"artifact_kind":"sugar-contract-comment-sugar",...} */
/* sugar-contract-payload-cid: blake3-512:... */
```

Preprocessor macros that expand to comments are not visible to all lifters and
MUST NOT be the only carrier of required contract-comment sugar.

### §3.5 TypeScript

TypeScript implementations SHOULD use line comments or JSDoc tags:

```ts
// sugar-contract: {"artifact_kind":"sugar-contract-comment-sugar",...}
// sugar-contract-payload-cid: blake3-512:...
```

JSDoc payloads MUST be extracted only from explicit `@sugar-contract` tags.
Other JSDoc prose remains docstring evidence at best, not exact comment sugar.

## §4. Lifter behavior

A lift kit that supports this spec scans the host-language surfaces in §3 and
converts each valid payload into a `bind-contract-witness-entry`:

```cddl
bind-contract-witness-entry = {
  col:                     uint / null,
  confidence_basis_points: 10000,
  extension_fields:        contract-comment-extension-fields,
  line:                    uint / null,
  predicate:               ir-formula,
  predicate_text:          tstr,
  role:                    "pre" / "post" / "inv" / "throws" / "observation",
  source_kind:             "native-surface"
}

; Locked JCS key order: concept_site_cid, contract_cid, ir_formula_jcs_cid,
; local_contract_cid, loss_record_cid, payload_cid, policy_cid,
; sugar_dict_cid, surface
contract-comment-extension-fields = {
  concept_site_cid:     cid,
  contract_cid:         cid,
  ir_formula_jcs_cid:   cid,
  ? local_contract_cid: cid,
  loss_record_cid:      cid,
  payload_cid:          cid,
  policy_cid:           cid,
  sugar_dict_cid:       cid,
  surface:              "contract-comment-sugar"
}
```

### §4.1 Role mapping

| Payload role | Bind witness role |
|---|---|
| `pre` | `pre` |
| `post` | `post` |
| `invariant` | `inv` |
| `throws` | `throws` |
| `observation` | `observation` |

Unknown roles MUST fail closed. They MUST NOT be mapped to `native-surface`
evidence with a free-form role.

### §4.2 Predicate text

`predicate` is authoritative. `predicate_text` SHOULD be `fol_text` when it is
present and non-empty; otherwise the lifter MAY render a deterministic debug
string from `predicate`. The lifter MUST NOT set `predicate_text` to raw payload
JSON or raw `IrFormula` JSON.

### §4.3 Evidence memento minting

Downstream bind consumers mint `EvidenceMemento` from the witness using the
existing evidence source-kind vocabulary. The source kind is `native-surface`
because the comment is a source-native surface recognized by a language kit.

The evidence's `extension_fields` MUST preserve the payload CIDs listed in §4.
This lets a verifier reconstruct the audit path:

```text
EvidenceMemento
  -> contract-comment payload CID
  -> formula CID
  -> sugar dict CID
  -> policy CID
  -> loss record CID
```

## §5. Fail-closed rules

A lifter MUST reject the payload as trusted contract-comment sugar when any of
the following holds:

- malformed JSON or invalid UTF-8 after host comment unwrapping;
- `artifact_kind` is not `"sugar-contract-comment-sugar"`;
- `schema_version` is unknown;
- a required field is missing;
- any CID field is malformed;
- emitted `payload_cid` does not match `blake3-512(JCS(payload))`;
- `ir_formula_jcs` is present but does not hash to `ir_formula_jcs_cid`;
- `ir_formula_jcs` is absent and `ir_formula_jcs_cid` cannot be resolved;
- formula parse/shape validation fails;
- role is unknown;
- `loss_record_cid`, `sugar_dict_cid`, or `policy_cid` is unknown under a policy
  that requires local resolvability; or
- the payload is attached to a syntactic region whose target function/callsite
  cannot be determined.

Failing closed means no trusted `bind-contract-witness-entry` is emitted for
that payload. A kit MAY emit a diagnostic. It MAY also emit low-confidence
docstring/prose evidence through another source-kind when policy allows, but
that evidence MUST NOT reuse the contract-comment payload's exactness claim.

## §6. Worked example

### §6.1 Source-side payload

Suppose a concept site has:

```text
concept_site_cid = blake3-512:1111...
contract_cid     = blake3-512:2222...
policy_cid       = blake3-512:3333...
sugar_dict_cid   = blake3-512:4444...
loss_record_cid  = blake3-512:5555...
formula          = eq(var("out"), var("x"))
formula_cid      = blake3-512:6666...
```

The Java realizer may emit:

```java
// sugar-contract: {"artifact_kind":"sugar-contract-comment-sugar","concept_site_cid":"blake3-512:1111...","contract_cid":"blake3-512:2222...","emitted_by":{"kit_cid":"blake3-512:9999...","kit_kind":"realize","target_language":"java"},"fol_text":"out == x","ir_formula_jcs":{"args":[{"kind":"var","name":"out"},{"kind":"var","name":"x"}],"kind":"atomic","name":"eq"},"ir_formula_jcs_cid":"blake3-512:6666...","loss_record_cid":"blake3-512:5555...","policy_cid":"blake3-512:3333...","role":"post","schema_version":"1","sugar_dict_cid":"blake3-512:4444..."}
// sugar-contract-payload-cid: blake3-512:aaaa...
public static long identity(long x) {
    return x;
}
```

The `...` abbreviations above are explanatory only. Real emitted payloads MUST
use full `blake3-512:` CIDs and valid JSON.

### §6.2 Relift

The Java lifter:

1. extracts the JSON payload;
2. recomputes the payload CID;
3. recomputes `ir_formula_jcs_cid`;
4. validates role and schema;
5. attaches the witness to `identity`; and
6. emits:

```json
{
  "col": 0,
  "confidence_basis_points": 10000,
  "extension_fields": {
    "concept_site_cid": "blake3-512:1111...",
    "contract_cid": "blake3-512:2222...",
    "ir_formula_jcs_cid": "blake3-512:6666...",
    "loss_record_cid": "blake3-512:5555...",
    "payload_cid": "blake3-512:aaaa...",
    "policy_cid": "blake3-512:3333...",
    "sugar_dict_cid": "blake3-512:4444...",
    "surface": "contract-comment-sugar"
  },
  "line": 1,
  "predicate": {
    "args": [
      { "kind": "var", "name": "out" },
      { "kind": "var", "name": "x" }
    ],
    "kind": "atomic",
    "name": "eq"
  },
  "predicate_text": "out == x",
  "role": "post",
  "source_kind": "native-surface"
}
```

The bind consumer then mints an `EvidenceMemento` from that witness and composes
it into the function's `CompoundContractMemento` through the existing bind
pipeline.

### §6.3 Cross-language travel

When this contract is realized into Python, the Python kit may choose a Pythonic
surface:

```python
# sugar-contract: {"artifact_kind":"sugar-contract-comment-sugar",...}
def identity(x: int) -> int:
    return x
```

The host syntax changed. The payload semantics did not. If the payload relifts
to the same `contract_cid` and `ir_formula_jcs_cid`, the contract identity has
survived the language hop.

## §7. Relationship to concept tags and observation tags

This spec carries contract clauses. It composes with, but does not replace:

- concept tags (`// concept: identity`, concept site anchors);
- observation tags (`sugar-observation:*`) from
  `concept:contract-observation(callsite_cid, contract_cid, mode)`;
- body-template citations such as `concept:log-emit`; and
- native library sugars such as Bean Validation, JUnit, pydantic, Zod, JML, or
  Cofoja.

A policy may emit all of these surfaces in a smoke build. A production policy
may omit some, demote gates to monitors, or require comments only when no native
surface can carry the clause. The policy decision is cited by `policy_cid`.

## §8. Non-goals

- Do not invent a `ContractCommentMemento`; the payload is a source-visible
  sugar surface over existing mementos.
- Do not make comments the preferred surface over stricter native surfaces.
- Do not treat human-readable prose as exact contract evidence.
- Do not require every target language to use the same comment delimiters.
- Do not require source-visible canonical formulas when policy forbids exposing
  them; `ir_formula_jcs_cid` plus a resolvable catalog entry is sufficient.

## §9. Implementation checklist

A conforming implementation PR should include:

- a sugar dict entry whose emission computes the §1 payload;
- realizer tests for pre and post payloads containing `contract_cid` and
  `ir_formula_jcs_cid`;
- lifter tests for successful recovery into `bind-contract-witness-entry`;
- fail-closed tests for malformed JSON, CID mismatch, unknown role, unknown
  schema version, and formula mismatch;
- an integration test proving realize -> lift preserves `contract_cid`; and
- a loss assertion showing prose comments are lossy while canonical
  contract-comment payloads are exact only when formula bytes relift
  byte-identically.
