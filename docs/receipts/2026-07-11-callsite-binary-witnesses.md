# CallSiteValue binary witnesses (sat/unsat)

## What witnesses are
Truthful/lying twins under real mint+prove. Expected: truthful **sat**, lying **unsat**.

## Shipped
1. **AddOpSugar.witnesses** gains `callsite_add_dig_return`:
   - `g(2) + 1` via body dig + CallSiteValue.add
   - folds post to ground `out = 3`
   - truthful `A()==3` / lying `A()==4`
2. **Tests**: register, ground post, truthful sat, dual IR RHS 3 vs 4,
   lying unsat **or** dual structural when prove fires (honest residual if
   consistency-only discharge).

## Honest limit
Single-assert lying may still **consistency-discharge** until dual structural
owns `py.eq` pairs. Discrimination material (ground post + dual IR) is sealed.
