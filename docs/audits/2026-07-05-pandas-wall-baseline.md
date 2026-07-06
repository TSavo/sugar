# Pandas Wall Baseline, July 5 2026

Part of #3503.

This is the August-seat scouting baseline for full pandas source plus its test
corpus using the current Python audit machinery. Earlier receipts stopped at
`MapSugar`, `AddSugar`, builtin `slice(...)`, categorical prior-assignment
folding, and then a `BitwiseOpSugar` template escape. The current receipt gets
past the `BitwiseOpSugar` `notna()` escape and reaches a structured audit-only
construction-gap vector.

The wall still does not emit `sourceLedger` / `sourceAudits`, so the final wall
counts are not yet measurable. The important movement is that the previous hard
panic is gone: the renderer now returns a named frontier of 65 construction
gaps.

## Corpus

| field | value |
|---|---:|
| pandas version | 3.0.3 |
| installed package | `/usr/local/lib/python3.14/site-packages/pandas` |
| Python files | 1421 |
| pandas test Python files | 1122 |
| current receipt repo head | `372ac7bc2dd015f3905d47d1d50bd4a468aede25` plus branch changes |
| current receipt sugar source stamp | `blake3-512:4d21d292546eac518053f5a08406d9913fe0ffa0520cc0e9812f2bf6fc6d6e448610a7a750e4baf818e06cc9ec2cebf8b1f286f4679eaf22d7072f0e994119d0` |
| current receipt sugar binary | `/Users/tsavo/.cache/sugar/binaries/sugar-darwin-x86_64-release-blake3-512_4d21d292546eac518053f5a08406d9913fe0ffa0520cc0e9812f2bf6fc6d6e448610a7a750e4baf818e06cc9ec2cebf8b1f286f4679eaf22d7072f0e994119d0` |
| current receipt binary file type | Mach-O 64-bit executable x86_64 |
| current cached audit workspace | `/Users/tsavo/.cache/sugar/python-panic-audit-workspaces/25a0e6921250a1b84be8939322e97a814bf0cf60a9194f4779aba831356de696/pandas` |
| current audit workspace cache key | `25a0e6921250a1b84be8939322e97a814bf0cf60a9194f4779aba831356de696` |

The audit workspace was materialized through
`sugar_lift_py_tests.idd.collect_panic_audit._cached_audit_workspace`, the same
cache path used by the numpy/pandas panic audit.

## Render Result

The current JSON and visual receipts both ran to real exit code `2`, emitted no
stdout, and returned the same structured `audit-only construction gaps` payload.
This is no longer the `BitwiseOpSugar` crash frontier.

| command | exit | stdout bytes | stderr bytes | elapsed |
|---|---:|---:|---:|---:|
| `sugar lift --report --json <cached-pandas-audit-workspace>` | 2 | 0 | 108850 | 612.15s |
| `sugar lift --report --visual <cached-pandas-audit-workspace>` | 2 | 0 | 108850 | 727.11s |

Raw receipt hashes:

| receipt | sha256 |
|---|---|
| `/tmp/bitwise-abc-escape-pandas/pandas-report.json` | `e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855` |
| `/tmp/bitwise-abc-escape-pandas/pandas-report.json.stderr` | `693cad6f0e965a53c9308265e90e627d16579897c4a72e93ee97c1d537a0068b` |
| `/tmp/bitwise-abc-escape-pandas/pandas-report.visual` | `e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855` |
| `/tmp/bitwise-abc-escape-pandas/pandas-report.visual.stderr` | `508fab060e7b4c71ccc417bcf70f33f69452501aeea224c6d6698ecc1178d5c5` |

## Current Frontier

The renderer now reaches a structured audit-only vector:

| axis | count |
|---|---:|
| total construction gaps | 65 |
| Floor gaps | 46 |
| Sugar gaps | 17 |
| Constructor gaps | 1 |
| ProofIR gaps | 1 |
| `BitwiseOpSugar` / `notna()` entries | 0 |

Top gap shapes:

| count | owner | observed | requested |
|---:|---|---|---|
| 10 | `MembershipAssertionSugar` | `ArrayLiteral.contains(SymbolicValue)` | `contains item floor` |
| 8 | `python.factory` | `GeneratorExp` | `term` |
| 6 | `ArrayLiteralSugar` | `DictLiteralValue` | `array element floor` |
| 5 | `python.factory` | `Compare` | `term` |
| 5 | `BuiltinCallSugar` | `StringValue.__float__` | `string builtin method floor` |
| 4 | `BinOpSugar` | `StringValue*TermValue` | `binary operator operand floor` |
| 3 | `MembershipAssertionSugar` | `TupleLiteralValue` | `contains_with` |
| 3 | `StringSubscriptSugar` | `DictLiteralValue` | `subscript_with` |
| 2 | `BinOpSugar` | `SymbolicValue+StringValue` | `binary operator operand floor` |
| 2 | `AttributeSugar` | `CallSiteValue` | `attribute_with` |

Representative first gap:

```text
pandas/core/apply.py:1652:8
owner=MembershipAssertionSugar
observed=ArrayLiteral.contains(SymbolicValue)
requested=contains item floor
fix=add contains support for ArrayLiteral with SymbolicValue
```

## Counts

The requested wall counts are not yet measurable because the renderer returns
the audit-only construction-gap payload before producing report rows.

| requested count | value |
|---|---|
| contracts | unavailable |
| pre-bearing | unavailable |
| call edges | unavailable |
| resolved | unavailable |
| dangling | unavailable |
| implications | unavailable |
| green count | unavailable |
| reasoned-red count | unavailable |
| bare-red count | unavailable |

Bare-red status is therefore not proven zero in this baseline. The immediate
finding is earlier: the renderer must lower the 65 construction gaps into
reasoned rows before the final wall vector can be measured.

## Bitwise Escape Receipt

The previous blocker was:

```text
tests/test_sorting.py:300:20
BitwiseOpSugar left cannot read completed value from incomplete effect:
write more Sugar for this AST:
owner=python.factory
observed=call-method:notna
requested=term
fix=add receiver-dispatched method sugar for `notna`, resolve a local body,
link an imported .proof, or emit a real effect
```

Current focused repro result:

```text
build_literal_call_report(...)
no panic
```

Current full pandas receipt:

```text
BitwiseOpSugar: 0 audit-only gap entries
notna: 0 audit-only gap entries
pandas/tests/test_sorting.py:300: 0 audit-only gap entries
```

## August Work-List Seed

1. Lower `ArrayLiteral.contains(SymbolicValue)` membership floors or emit their
   typed effects as report rows.
2. Add honest `GeneratorExp` term sugar or keep it as a typed red row.
3. Add `DictLiteralValue` array/subscript floors where warranted.
4. Re-run this exact baseline and require `bare-red count = 0` once report rows
   render.
