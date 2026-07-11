# Residual final-2 → full suite lift

## Suite (itsdangerous 2.2.0 sdist)
| | stated | lifted | refuse | silent |
|--|--------|--------|--------|--------|
| start residual lane | 57 | 49 | 8 | 0 |
| after last-8 | 57 | 55 | 2 | 0 |
| **now** | **57** | **57** | **0** | **0** |

## Fixes
1. **BlockValue.follow_rest** — only unguarded `ReturnValue` kills tail
   (GuardedReturn from except-path return no longer drops later asserts).
2. **BlockValue.extend_scope** — chain entry extend_scope (RaisesWithValue, ScopeRebind).
3. **RaisesWithValue.contribution** — include **self** so as-binding survives
   outer `with freeze_time` (was flattened to InvValue only).

## Residual 0
Encoding/signer/serializer/timed all full lift. silent still 0.
