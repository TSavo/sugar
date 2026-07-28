# Authenticated 1,008-body no-call attribution

This report records the authenticated native-root attribution run from Sugar
main `17fb162b3dfed706eb1df3a6b1b351f143777977`. The population predicate does
not inspect manager/vendor names and does not exclude receiver-construction
calls beneath the root producer.

## Authentication

- Interpreter: CPython 3.12.13
- NumPy: 2.5.1
- pandas: 3.0.3
- Corpus files: 1,421
- Corpus BLAKE3-512 CID: `blake3-512:6f317a5a489eb7e730064d79792f0d1656723130603309e2f2ed9cbedb604eda1c4b77a26dc90c980411292ea3994af9015da4cd850b5a307af5a4998b563530`
- Shared demand table: `blake3-512:0ce7c645a7525f1fe5189b808162b49d3fc3ba3d898bfb3d5086e0f295b8b8d263fe7f530a6aa34adb125615a21e69fdee249e0314bf199b8f43580375153ab0`
- Battleaxe task: `authenticated-no-call-body-attribution`, `network = "none"`
- Binary policy: `SUGAR_BINARY_ALLOW_BUILD=0`, `SUGAR_BINARY_PUBLISH=0`

Command:

```text
SUGAR_BINARY_ALLOW_BUILD=0 SUGAR_BINARY_PUBLISH=0 PYTHONUNBUFFERED=1 bin/sugarbin run --host bx --env SUGAR_BINARY_ALLOW_BUILD --env SUGAR_BINARY_PUBLISH --env PYTHONUNBUFFERED --task authenticated-no-call-body-attribution
```

## Per-family split

Zeros are measured values.

| Family | Enrolled | Authenticated exceptional exit | Named refusal | Construction panic |
|---|---:|---:|---:|---:|
| Subscript | 392 | 0 | 390 | 2 |
| BinOp | 367 | 0 | 27 | 340 |
| Compare | 181 | 0 | 20 | 127 |
| Attribute | 53 | 0 | 53 | 0 |
| UnaryOp | 13 | 0 | 13 | 0 |
| BoolOp | 2 | 0 | 2 | 0 |
| **Total** | **1,008** | **0** | **505** | **469** |

## Loud reconciliation result

The enrolled family rows sum to 1,008. The three outcome columns sum to 974,
so the instrument remains red and names 34 unaccounted Compare completions.
No denominator was adjusted:

```text
OUTCOME TOTAL DISCREPANCY enrolled=1008 threeOutcomeTotal=974 unaccounted=34
battleaxe_exit=1
```

The complete coordinate ledger is
[`2026-07-28-no-call-1008-attribution-details.txt`](2026-07-28-no-call-1008-attribution-details.txt).
It contains:

- all 469 construction panics with body file, line, root node, and the node
  owner that raised;
- all 505 named refusals with their named coordinates;
- all 34 unaccounted completions with file, line, and root node;
- the authenticated environment, six family rows, discrepancy, and inline
  Battleaxe exit status.

The detail ledger has zero malformed panic records and zero malformed refusal
records under those required coordinate shapes.

## Gates

- The concrete BinOp reproducer is
  `tests/series/test_logical_ops.py:96` (`s_0123 & np.nan`) in the authenticated
  corpus. The formerly supplied line 95 is not the reproducer.
- The focused attribution harness completed with 17 passing tests.
- Mutation transaction: removing `coordinate=<owner>` from named-refusal
  rendering made
  `test_report_names_every_refusal_coordinate_and_panic_node_owner` fail;
  restoring it returned the source diff to clean.
- The #6541 receiver-call twins remain present: failing-node ownership beats
  root shape when a receiver Call raises before Subscript is reached.
