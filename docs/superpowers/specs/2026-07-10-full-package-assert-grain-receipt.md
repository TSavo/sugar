# Full-package assertion-grain receipt (numpy + pandas)

**Part of** #4016 / #4013. Measurement only — does not edit the enumerator.
**Enumerator:** main post-[#4023](https://github.com/TSavo/sugar/pull/4023) (`build_literal_call_report` + `account_lift_coverage`).
**Host:** local Mac; packages `numpy==2.5.0`, `pandas==3.0.3` (full installed trees under site-packages).

## Method

| metric | definition |
|--------|------------|
| **nested_before_approx** | On-disk `ast.Assert` nodes that are **not** direct children of a `FunctionDef`/`AsyncFunctionDef` body. Same method as the #4023 sample receipts. Under the pre-totality walk these never reached `_lift_assert` → silent under green R=0. |
| **after_*** | Dual-axis partition against the live #4023 enumerator for each `.py` file. |

Full AST pass (every file, no lift):

| package | files | stated | nested_before_approx |
|---------|------:|-------:|---------------------:|
| numpy | 407 | **3208** | **714** |
| pandas | 1421 | **17543** | **2906** |

## Lift-path results (post-#4023 totality)

| package | files ok/total | stated (ok files) | lifted | refused | **silent residual** | nested_before≈ (ok files) |
|---------|---------------:|------------------:|-------:|--------:|--------------------:|--------------------------:|
| numpy | 405/407 | 3101 | 3058 | 0 | **43** | 666 |
| pandas | 1421/1421 | 17543 | 17204 | 0 | **339** | 2906 |

### numpy partial note (honest)

Two files **FactoryGap-panicked** mid-lift and are **not** in the after-totals (assert counts on those files still exist on disk):

| file | stated on disk | error |
|------|---------------:|-------|
| `numpy/_core/tests/test_deprecations.py` | 4 | AttributeSugar constructor-bound field |
| `numpy/_core/tests/test_stringdtype.py` | 103 | BinOpSugar SymbolicValue+ArrayLiteral floor |

So full-tree **stated = 3208**; lift-path after accounting covers **3101** of them. The **43** silent residual is among the 405 completed files. Do **not** treat 43 as the only unfinished work on the whole tree — the 2 aborts are a separate red surface.

### Beacon headline (what R=0 hid)

Across the full installed packages, the pre-totality nested walk left approximately:

- **numpy: 714** nested asserts invisible under green R=0  
- **pandas: 2906** nested asserts invisible under green R=0  
- **combined ≈ 3620** vendor/test asserts the nested-blindness hid  

#4023 un-gagged the function-body nested surface. Residuals that **remain silent after totality**:

- **numpy: 43** (includes indictment `f2py2e.py:668` / #4025)  
- **pandas: 339** (includes indictment `expr.py:258` module-level / #4024, plus many more)

Library (non-`*/tests/*`) residual loci — see JSON receipt for full silent list sample.

Machine-readable: `2026-07-10-full-package-assert-grain-receipt.json`.
