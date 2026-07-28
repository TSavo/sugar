# Binary-operation exceptional-floor design

## Scope

Repair only the Python BinOp producer.  Assertion boundaries consume the
resulting `ExitSet`; they never inspect expression syntax.  This change does not
touch assertion-With, Compare, UnaryOp, Subscript, Attribute, `outcome/`,
`exit_set.py`, or generator construction.

## Producer law

A binary operation may publish an exceptional exit only when its operands and
native source-visible operation authenticate that exit.  Existing ground floor
arms retain their cited `RaiseEffect` exits for overflow, type, and division
failures.  An operation with an operand whose runtime type is undecidable cannot
select `__op__`, `__rop__`, or an exception identity.  That is a third value:
the BinOp producer raises a named construction gap instead of returning a
completed symbolic value or manufacturing an effect.

The general undecided-binary door owns this refusal.  Direct symbolic and
call-result binary helpers must route through that same door so no side path can
launder undecided dispatch into `Complete(SymbolicValue(...))`.  Guarded
operations continue to distribute through their existing floor law; each arm
then either constructs, emits its authenticated ground exit, or refuses.

## Authentication and tests

The real reproducer is pandas 3.0.3
`tests/series/test_logical_ops.py`, manager beginning at line 95, body
`s_0123 & np.nan`.  Tests run through #6462's authenticated launcher and pull
#6464's content-addressed demand table.  They authenticate manifest CID
`sha256:a223a4499d0909f22190748b4aca9144e35a58fec31e84cb924e2c25fd3c03d0`.
The truthful runtime shape raises; the lying `s_0123 & 0` shape completes at
runtime, but both remain source-undecidable to the producer and therefore both
must take the same named refusal rather than inventing `TypeError`.

Focused floor laws additionally prove that a decided ground exceptional face
still carries its authenticated exception, an undecided operand refuses, and a
guarded operation retains per-arm behavior.

## Verification

Run the focused tests for every touched Python package.  Prove the regression
test's teeth with a clean / mutated / bites / reverted / clean transaction.
Use the shared shelf only; an absent source-stamped binary is reported as a
blocker and is never worked around by rebuilding the demand table.
