# Sequential Dig Continuing Block State Design

## Problem

Two current pandas representatives dig `date_range` through a reduced body
that contains exact guarded exceptional exits and nested scope testimony before
an unguarded return. `BlockSugar` has already reduced the nested control flow
into a continuing `BlockValue` and threaded its exact definite bindings, but
`SequentialDigBody` treats the remaining scope records as a competing return
value and panics.

## Construction

`SequentialDigBody` will recognize a continuing `BlockValue` whose
non-exit contribution contains only `ScopeRebind`, `GuardedScopeRebind`, and
reduced support testimony. These entries are implementation state already
owned and threaded by `BlockValue.extend_scope`; guarded returns and raises
remain the result-bearing contribution and continue through the existing
source-order selection fold.

The authority is the reduced outcome, never the source AST. A custom outcome,
a halted block, an opaque entry, an incomplete reduction, or a later use of a
merely conditional binding remains a typed `FactoryPanic`. No RuntimeEffect or
empty-success arm is introduced.

## Alternatives Rejected

- Inspecting pandas AST branches would repeat the syntactic trust error and
  would not generalize.
- Ignoring arbitrary mixed state would suppress unconstructed control flow.
- Relabeling the shape as runtime dependence would be dishonest: perfect
  machinery can decide the reduced continuing-path record.

## Evidence

- A continuing reduced block with a guarded raise and exact threaded state
  reaches its unguarded return selection.
- The equivalent custom mixed outcome and a halted-block twin remain loud.
- A real truthful witness is satisfiable and its lying twin is unsatisfiable.
- Both named pandas representatives leave `SequentialDigBody`, with all mass
  either completed or moved to a distinct loud owner and `silent=0`.
