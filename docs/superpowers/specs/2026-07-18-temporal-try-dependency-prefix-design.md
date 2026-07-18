# TemporalContext module Try dependency-prefix design

## Validated frontier

All five TemporalContext representatives from #5121 remain live on current
main after #5188:

- `pandas/tests/plotting/test_boxplot_method.py`: `verts`
- `numpy/f2py/tests/util.py`: `_imp`
- `pandas/tests/series/methods/test_astype.py`: `_imp`
- `numpy/f2py/crackfortran.py`: `show`
- `pandas/tests/arrays/sparse/test_dtype.py`: `tups`

This slice owns the two `_imp` files.

## Root cause

Install-source function construction calls
`_ctx_with_module_global_binds` to replay only the earlier module declarations
needed by the function body. The reverse selector correctly recognizes a
module-level `Try` as owning names joined by its continuing paths. When that
Try is selected, however, dependency expansion only follows `Assign` and
`AnnAssign` right-hand sides.

For `importlib.__init__`, the selected Try binds `_bootstrap` but loads the
earlier `_imp` and `sys` imports. Those loaded names are not added to the
reverse worklist, so forward replay reduces the existing `TrySugar` without
the real execution prefix and panics at `_imp`.

## Construction

Extend the reverse dependency selector, not TrySugar and not the AST:

- when a selected module-level `Try` is admitted by
  `_module_declaration_bound_names`, add the names reported by the existing
  `SourceFragment` loaded-name traversal to the worklist;
- replay the selected declarations forward through the existing
  SequentialDigBody/statement catalog exactly as today.

No inline `ast.*` or bespoke `_is_` predicate is added. The recognizers remain
`_module_declaration_bound_names` for module ownership and the ordinary
statement catalog (`TrySugar`) for construction.

## Execution-order floor

Reverse selection is single-pass in execution order. If the dependency is
declared after the Try, the selector has already passed it before discovering
the Try's loaded name. It therefore remains absent and `TemporalContext`
panics. No later declaration backfills an earlier use.

## Evidence

- Red/green discrimination: earlier `seed` used inside a selected Try resolves;
  the same `seed` declared after the Try stays loud.
- Named representatives: both `_imp` terminals retire, with their next loud
  terminal owner and observed value reported.
- Fresh truthful/lying witness: module Try dependency-prefix source is SAT;
  wrong value twin is UNSAT.
- Conservation reports completed, next-loud, remaining TemporalContext, and
  silent counts. No RuntimeEffect constructor or empty-success arm is added.
