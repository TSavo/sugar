# Recovered construction-audit wire fixtures (#4264)

Shared golden JSON for the Python↔Rust recovered-audit membrane.

Two closed shapes:

| Prefix | Producer | Consumer | Status vocabulary |
| --- | --- | --- | --- |
| `leaf-*` | Python kit leaf (`RecoveredAuditDto`) | Rust fold (`RecoveredAuditLeafWire`) | `clean` \| `failed` |
| `tree-*` | Rust fold (`fold_recovered_audit`) | CLI + wall consumers | `valid-empty` \| `complete` \| `failed` |

Both languages round-trip these fixtures and reject unknown fields. A writer
change the other side cannot parse fails in the PR that introduces it, not on
the next wall run. Schema generation from one shared definition is the stronger
end state; these goldens are the first ratchet.

## Files

- `leaf-clean.json` — empty recovered leaf
- `leaf-full.json` — panics + effects + suppressed descendants (all leaf fields)
- `tree-valid-empty.json` — closed empty corpus
- `tree-complete-effects.json` — complete frontier with typed effects only
- `tree-failed-full.json` — failed frontier with ownership + all three lanes
- `bad-leaf-unknown-field.json` — must be rejected by leaf readers
- `bad-tree-unknown-field.json` — must be rejected by tree readers
