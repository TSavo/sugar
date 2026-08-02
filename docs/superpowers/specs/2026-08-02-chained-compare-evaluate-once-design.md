# Chained Compare Evaluate-Once Design

## Goal

Make Python chained comparisons preserve source evaluation semantics: in
`a < b < c`, evaluate `b` exactly once, reuse that reduced value as the right
operand of the first leg and the left operand of the second leg, and evaluate
`c` only when the first comparison continues.

## Proven defect

At `84b104f06`, `Compare._construct_sugar` constructs adjacent comparison
sugars and wraps them in `BoolOpSugar("And", ...)`. Each comparison desugars
both of its operands independently, so the shared middle sugar is desugared
twice. A focused probe measured `middle_desugar_count=2` while the overall
outcome was `Complete`. This is a silent correctness defect, not a missing
construct.

## Architecture

`Compare._construct_sugar` remains the only source-construction door. A
single-operator `Compare` continues to return its existing
`EqualityOpSugar` or `ComparisonOpSugar`. A multi-operator `Compare` returns
`ChainedCompareSugar`, holding the same ordered per-leg sugars and exact
per-leg source occurrences already constructed today.

`ChainedCompareSugar.desugar` evaluates the first operand once, then evaluates
each next operand once only when that leg is reached. It passes the reduced
right value forward as the next leg's reduced left value. Each existing leg
owner gains a narrow `apply_reduced(left, right, ctx)` entry so chaining reuses
its equality, ordering, membership, identity, exceptional-exit, and refinement
law without redispatching on operator kind.

The non-final comparison result is routed through the same operand-selecting
truth helper as `BoolOpSugar("And", ...)`. A stopping face returns that exact
comparison result; only a continuing face evaluates the next operand. The
final comparison result is returned without truth coercion, matching Python's
`and`-equivalent result rule.

Canonical construction testimony remains compatible with the existing
BoolOp-of-leg-pairs term. The change corrects reduction order and does not add
a new taxonomy, result category, label, cache, or fabricated binding.

## Rejected alternatives

- Global `Sugar.desugar` caching would change evaluation semantics for every
  sugar to repair one source construct.
- A synthesized temporary binding would invent source identity absent from the
  authenticated Python source.
- Teaching `BoolOpSugar` to recognize comparison species would make a caller
  interrogate operand kinds and move Compare ownership into the wrong door.

## Teeth

The regression test uses the production `Compare` construction door and
replaces the shared middle child with a falsifiable probe.

1. Exact-count tooth: `middle_desugar_count == 1`. Removing the carry-forward
   behavior makes this fail with `2` even though the outcome remains Complete.
2. Left-to-right tooth: the complete evaluation trace is exactly
   `left, middle, right`, with no duplicated or reordered operand.
3. Short-circuit tooth: a false first leg evaluates `left, middle` and never
   evaluates the later right operand.
4. Per-leg ownership tooth: mixed chains retain their ordered
   `ComparisonOpSugar` and `EqualityOpSugar` owners.
5. Semantic-effect tooth: the middle probe returns `1` on its first evaluation
   and `2` on its second. `0 < middle() < 2` must be true. The broken double
   evaluation makes the second leg `2 < 2` and produces false.

Existing focused BoolOp and chained-Compare tests remain the discrimination
floor for short-circuiting, exact selected operands, per-leg occurrences,
mixed comparison laws, and authenticated exceptional exits.
