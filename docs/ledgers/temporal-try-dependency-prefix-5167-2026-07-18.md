# TemporalContext module-Try dependency prefix — #5167

Measured on `origin/main` at
`cd9a1ff5353e328148759a88bc03b6fb5b912457` with the Python 3.14 editable kit
and the full installed NumPy 2.5.1 / pandas 3.0.3 files.

## Construction

The existing `_ctx_with_module_global_binds` statement-catalog selector already
recognizes a module-level `Try` as the declaration that owns a continuing-path
binding. When that selected `Try` loads another module name, the reverse
dependency worklist now consumes `_names_in_fragment(prior)` testimony before
the selected statements are replayed forward through the ordinary catalog and
`TrySugar`.

This is execution-order preserving. The reverse selector is a single pass, so a
declaration after the `Try` has already been passed when the `Try` adds its
dependency and cannot be selected retroactively. No AST shape predicate,
RuntimeEffect, or empty-success arm was added.

## Named representative replay

| Representative | Before | After | Disposition |
|---|---|---|---|
| `numpy/f2py/tests/util.py` | `TemporalContext(_imp)` from `importlib` | `TemporalContext(__file__)` in `importlib/__init__.py:26` | advanced to distinct loud front |
| `pandas/tests/series/methods/test_astype.py` | `TemporalContext(_imp)` from `importlib` | `TemporalContext(__file__)` in `importlib/__init__.py:26` | advanced to distinct loud front |
| `pandas/tests/arrays/sparse/test_dtype.py` | `TemporalContext(tups)` | no recovered panic | completed |
| `numpy/f2py/crackfortran.py` | `TemporalContext(show)` | `TemporalContext(show)` | unchanged loud |
| `pandas/tests/plotting/test_boxplot_method.py` | `TemporalContext(verts)` | `TemporalContext(verts)` | unchanged loud |

### Conservation

| Mass | Files |
|---|---:|
| starting named TemporalContext terminals | 5 |
| completed | 1 |
| advanced to a distinct loud named terminal | 2 |
| remained at the same loud named terminal | 2 |
| silently lost | 0 |
| ending named TemporalContext terminals | 4 |

The two `_imp` loci prove the constructed earlier-definition path. Their next
`__file__` terminal is not an earlier source declaration and is intentionally
not fabricated by this slice.

## Discrimination and witness

- Earlier `seed = 7`, then a module `Try` loading `seed`, then `def f()`:
  dependency prefix constructs and `alias` is bound.
- The same `seed = 7` after the `Try`: remains a loud
  `TemporalContext(seed)` `FactoryPanic`.
- Fresh imported-module witness:
  `module_try_dependency_prefix` truthful twin is SAT; the lying twin is UNSAT.

## Focused verification

```text
pytest test_module_global_name_bind.py test_try_sugar.py
30 passed in 58.91s

pytest test_claim_mass_tripwires.py
5 passed in 67.41s

black 26.5.1
3 focused Python files clean
```
