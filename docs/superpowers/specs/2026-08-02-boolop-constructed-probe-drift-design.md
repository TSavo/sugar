# BoolOp Constructed Probe Drift Design

## Problem

Commit `df07b3f88` deliberately closed `BoolOpSugar.values` to
`ConstructedTermSugar` and added construction-time admission that rejects an
arbitrary `Sugar`. `test_bool_op_operand_sequence.py` still supplies
`_ProbeSugar(Sugar)`, so BoolOp rejects the fixture before the 12 semantic tests
can exercise operand selection.

The measured stale surface is one test file, seven `BoolOpSugar` construction
sites, and fourteen `_ProbeSugar` operands. These are site counts, not fourteen
independent test failures.

## Authority

The product door is authoritative. The same commit added the hierarchy-based
admission rule and a bad twin proving that arbitrary `Sugar` must remain
inadmissible. Changing `BoolOpSugar.values` back to `Sugar` would undo that
correctness boundary.

## Considered Repairs

1. Promote the test probe to `ConstructedTermSugar` and give it canonical test
   testimony. This preserves its observable evaluation behavior and satisfies
   the same contract as every nested term. This is the selected repair.
2. Replace the probe with production literal sugars. Those construct real
   terms, but cannot return the arbitrary floor values and symbolic formal used
   by these operand-selection tests without losing the behavior under test.
3. Loosen the product door. This would make the old fixture pass by reopening
   the deliberately forbidden arbitrary-Sugar path, so it is rejected.

## Change

Only `test_bool_op_operand_sequence.py` changes. `_ProbeSugar` subclasses
`ConstructedTermSugar` and implements `to_term` as canonical test testimony
from its fixed label. Its `desugar` behavior, evaluation log, returned floor
value, and every product type remain unchanged.

## Proof

Before the repair, the file collects 12 tests and the first test fails at
`BoolOpSugar.values requires ConstructedTermSugar, got _ProbeSugar`. After the
repair, all 12 must execute and pass. The existing closed-door bad twin in
`test_constructed_term_sugar.py` must also remain green, proving arbitrary
`Sugar` is still rejected.

## Bounded Follow-up Audit

After the focused repair, inspect only the `df07b3f88` diff for narrowed type
annotations, removed parameters, and new runtime admission checks. For each
door, report whether repository callers use the current contract or retain the
old shape. Do not repair other doors in this lane.
