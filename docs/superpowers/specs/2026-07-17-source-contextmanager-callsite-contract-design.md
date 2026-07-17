# Source Contextmanager Callsite Contract Design

## Live frontier

Current main `b241a1626` has two verified `SequentialDigBody` terminals in
#4921. The decidable representative is
`pandas/tests/reshape/merge/test_merge_asof.py`: a `with option_context(...)`
statement forces the generator producer body as though it needed a returned
manager floor, then panics at the generator's `try/yield/finally`.

The source oracle already proves that exact `@contextmanager` definition has
one yield and a finally body that cannot override exceptional exit. That is
concrete evidence that `__exit__` never suppresses.

## Construction

Carry the existing source-derived `ExitSuppressionContract` on the
`FunctionCallable` created from the installed definition, and copy it to each
callsite. When a `with` statement has no `as` target, that exact contract is
all the raising path needs; do not dig the unrelated generator producer result.
If an entered value is requested, or if the source recognizer cannot prove a
contract, retain the existing exact manager-result demand and panic.

This adds no RuntimeEffect constructor. Conditional handlers, returns after
yield, and every unrecognized decorator/body shape retain `None` and therefore
remain loud.

## Evidence

- source-recognized try/yield/finally callable carries non-suppression;
- conditional-handler bad twin carries no contract;
- exact contract avoids an intentionally panicking producer dig, while the
  missing-contract twin still panics;
- source-contextmanager witness is truthful SAT and wrong-result UNSAT;
- representative conservation is `SequentialDigBody 1 -> 0`,
  `FunctionCallable 0 -> 1`, silent `0`.

