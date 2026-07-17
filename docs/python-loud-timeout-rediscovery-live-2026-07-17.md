# Loud-timeout live rediscovery (#4894) — post-optimization head

**When:** 2026-07-17 14:12 UTC  
**Head:** post construction optimisations (SourceOracle value door, dig body, deepcopy FunctionDef-only, claim-mass/MRO/ImportFrom ratchets, etc.)  
**Method:** 3 concurrent shards × sequential children; discovery bound **10s**; 1032 assert-bearing numpy+pandas files.

## Live terminals at 10s (conservation)

| Terminal | Files |
|---|---:|
| completed | 675 |
| factory-construction-panic | 323 |
| bare-exception | 14 |
| **timeout-or-hang** | **20** |
| **sum** | **1032** |

## Residual R (live timeout fog)

| Axis | Old (provisional recensus) | **Live now** |
|---|---:|---:|
| Timeout blob at 10s | 293 | **20** |
| By package | — | {'numpy': 5, 'pandas': 15} |

**ΔR timeout blob:** 293 → 20 (**−273**).

### Why the wait

Full rediscovery is O(assert-bearing files × wall). ~1032 candidates, each a separate process with a hard **10s** ceiling. Three shards cut wall clock ~3×; worst case still ~1 hour if many files hang. That is measurement cost, not a stuck process.

### Committed classification ledger (historical escalation of old blob)

Still useful for B-owner ranking of files that *were* timeouts; not a substitute for live 10s rediscovery after construction PRs. See summary JSON for 240 classified / 53 identity-unavailable residual against the original 293 seed.

### Next

Escalate only the **20 live** timeout files (60→120→300), not the historical 293.
