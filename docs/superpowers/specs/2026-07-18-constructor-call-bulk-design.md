# ConstructorCallSugar Bulk Initializer Construction Design

## Scope

The #5134 recensus named 23 `ConstructorCallSugar` files. The
`ArrowPeriodType` explicit-base initializer belongs to #5126 and is excluded.
The #5094 `IndexType` locus is already retired. Replaying the remaining 22
files on current main `a865598ff` confirms 22 live
`owner=ConstructorCallSugar` terminals.

This slice constructs local source initializers whose ordinary statement
sequence is already supported by the contextualized initializer reducer:

- assertions;
- assignments to locals or `self` fields;
- `if` statements whose reduced path outcome is decidable;
- exact zero-argument `super().__init__(...)` tails;
- explicit raises and exceptional exits produced by those reduced paths.

## Chosen construction

Keep the existing field-only fast path. Expand
`_source_initializer_needs_statement_door` only for statement shapes owned by
the ordinary reducer:

1. `Assert`, local assignments, and annotated `self` assignments continue to
   require the statement door.
2. `If` and `Raise` now require the statement door so selection is made from
   their reduced semantic outcomes.
3. The already-authenticated zero-argument `super()` receiver calling
   `__init__(...)` now requires the statement door even when no local
   assignment precedes it. Its initializer arguments may be positional or
   keyword and are constructed by the ordinary call reducer.
4. Existing statically constructed class fields are carried through the
   source-body strategy and use the same descriptor refusal as the field-only
   strategy.
5. Arbitrary expression calls, explicit-base `Base.__init__` calls, imports,
   pass-only bodies, and unsupported statements remain outside the door and
   retain the named `ConstructorCallSugar` panic.

The statement router does not decide a branch or exception from AST syntax.
It only chooses the existing reducer. That reducer consumes the actual reduced
outcomes and either constructs exact object state / an exact exceptional exit,
or remains loud.

## Rejected approaches

- A bespoke constructor interpreter would duplicate the ordinary statement
  reducer and repeat its path-selection and binding laws.
- Routing every initializer statement would collide with #5126 and could make
  unimplemented imports or arbitrary calls look constructed.
- A RuntimeEffect or empty-success fallback would relabel missing machinery
  instead of constructing evidence and is forbidden.

## Loud boundary

Runtime-dependent or unsupported initializer logic does not receive a ground
value. This change adds no effect constructor. Any effect already produced by
the ordinary reducer remains subject to the sealed RuntimeOperand door; an
unimplemented shape continues to panic.

## Verification

- RED/GREEN discrimination for a concrete `if` initializer and a
  `self`-assignment plus `super().__init__` initializer.
- RED/GREEN discrimination that source-body construction preserves exact
  class fields without bypassing descriptor refusal.
- Bad twins for arbitrary expression calls and explicit-base initializers stay
  at `owner=ConstructorCallSugar`.
- A file-backed truthful/lying witness proves SAT/UNSAT without printing
  raise/error source twins.
- Replaying the 22 named representatives records completed, advanced-loud, and
  unchanged-loud mass with silent movement exactly zero.
- Direct claim-mass tripwires remain green, with loud re-pinning in this PR
  only if a pinned fixture genuinely moves.
