# FunctionCallable unexpected-keyword implementation plan

1. Add focused red tests for explicit unexpected-keyword construction, valid
   keyword discrimination, and symbolic `**` bad-twin loudness.
2. Add a verdict-bearing truthful/lying witness to the owning function
   definition sugar.
3. Construct the exact static `TypeError` exit in `FunctionCallable.callsite`
   while preserving the generic panic for all other failed binds.
4. Run the focused tests and witness evaluator.
5. Replay `numpy/_core/tests/test_overrides.py` and record conservation,
   including the next named terminal and `silent=0`.
6. Format, rebase onto current main, rebuild the matched binary, repeat the
   bounded receipt, commit, push, and open a non-closing PR for #4878.

