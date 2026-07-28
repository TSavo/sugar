# Authenticated 1,008-body attribution after SubscriptStore construction

This background receipt was run from PR #6599 at head
`53791c34e5b3bb0812d6342e4e5235b3f99a3c11`. It does not classify store
statements; it records the independently enrolled no-call assertion-body
population after the capability commit.

## Authentication

- Battleaxe task: `authenticated-no-call-body-attribution`
- Network: `none`
- Binary policy: `SUGAR_BINARY_ALLOW_BUILD=0`, `SUGAR_BINARY_PUBLISH=0`
- Interpreter: CPython 3.12.13
- NumPy: 2.5.1
- pandas: 3.0.3
- Corpus files: 1,421
- Corpus BLAKE3-512 CID: `blake3-512:6f317a5a489eb7e730064d79792f0d1656723130603309e2f2ed9cbedb604eda1c4b77a26dc90c980411292ea3994af9015da4cd850b5a307af5a4998b563530`
- Shared demand table: `blake3-512:0ce7c645a7525f1fe5189b808162b49d3fc3ba3d898bfb3d5086e0f295b8b8d263fe7f530a6aa34adb125615a21e69fdee249e0314bf199b8f43580375153ab0`

Command:

```text
SUGAR_BINARY_ALLOW_BUILD=0 SUGAR_BINARY_PUBLISH=0 PYTHONUNBUFFERED=1 bin/sugarbin run --host bx --env SUGAR_BINARY_ALLOW_BUILD --env SUGAR_BINARY_PUBLISH --env PYTHONUNBUFFERED --task authenticated-no-call-body-attribution
```

## Three-outcome split

Zeros are measured values.

| Family | Enrolled | Named exceptional exits | Still-undischarged demands | Named refusals | Construction panics |
|---|---:|---:|---:|---:|---:|
| Subscript | 392 | 0 | 2 | 390 | 0 |
| BinOp | 367 | 0 | 340 | 27 | 0 |
| Compare | 181 | 0 | 161 | 20 | 0 |
| Attribute | 53 | 1 | 0 | 52 | 0 |
| UnaryOp | 13 | 0 | 0 | 13 | 0 |
| BoolOp | 2 | 0 | 0 | 2 | 0 |
| **Total** | **1,008** | **1** | **503** | **504** | **0** |

Conservation is exact:

```text
1008 enrolled = 1 named exceptional exit + 503 undischarged + 504 refused + 0 panicked
OUTCOME TOTAL DISCREPANCY lines=0
BATTLEAXE_EXIT_STATUS=0
```

The sole authenticated exit carries both coordinates:

```text
authenticatedExceptionalExit body=tests/test_errors.py:108:Attribute exceptionTypeCoordinate=python:exception_type_identity(import, pandas.errors.AbstractMethodError) raiseOccurrence=/usr/local/lib/python3.12/site-packages/pandas/tests/test_errors.py:95:8
```

The complete machine-rendered coordinate ledger is
[`2026-07-27-subscript-store-background-no-call-1008-attribution-details.txt`](2026-07-27-subscript-store-background-no-call-1008-attribution-details.txt).
It contains all 504 named-refusal coordinates, all 503 undischarged rows, the
one coordinate-bearing exceptional exit, all six family rows, and the inline
Battleaxe exit status. It also retains the runner's source-tree diagnostic for
`tests/frame/indexing/test_indexing.py:1003:20` rather than filtering it from
the receipt; the conserved outcome table reports zero construction panics.

