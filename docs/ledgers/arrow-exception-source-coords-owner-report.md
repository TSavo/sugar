# Owner report: ArrowInvalid / ArrowException attribute coordinates

**Owner:** external-exception (Arrow attribute operands of `external_error_raised`)  
**Branch:** `codex/arrow-exception-source-coords`  
**Seat:** CPython 3.12.13 · corpus manifest `blake3-512:6f317…` · demand table `blake3-512:0ce7…`

## The five sites (before)

From authenticated demand family `pandas._testing.external_error_raised` (47 With-sites):

| # | File | Line | Operand | Before residual |
|---|---|---:|---|---|
| 1 | `tests/series/accessors/test_list_accessor.py` | 100 | `pa.ArrowInvalid` | `SymbolicValue.attribute` construction-panic |
| 2 | `tests/series/accessors/test_list_accessor.py` | 132 | `pa.ArrowInvalid` | same |
| 3 | `tests/series/accessors/test_list_accessor.py` | 134 | `pa.ArrowInvalid` | same |
| 4 | `tests/extension/test_arrow.py` | 1715 | `pa.ArrowInvalid` | same |
| 5 | `tests/io/test_parquet.py` | 799 | `pyarrow.ArrowException` | same |

**Before R(attribute-stage) = 5.**  
Heads were not static-import-bound: four use `pa = pytest.importorskip("pyarrow")`; one uses module-level `try: import pyarrow` / `except ImportError`. Ordinary import binding left those heads loud, so Attribute floor refused member semantics.

## Construction

1. **Provider-gated import target** (`SourceUnit.provider_gated_import_target`)  
   Lexical-only closed gates for exception-type identity:
   - `name = pytest.importorskip("mod")` with import-bound `pytest` and string-literal module
   - `try: import mod` / `except ImportError:` that does not rebind `mod`  
   Shadowed, reassigned, parameter, and non-importorskip assigns stay `None`.

2. **`imported_exception_type_identity`** falls through to the provider gate when static import binding is absent. Sealed coordinate:
   - `python:exception_type_identity(import, pyarrow.ArrowInvalid)`
   - `python:exception_type_identity(import, pyarrow.ArrowException)`  
   **MRO / ClassValue are not invented** when defining source is not in the seat (pyarrow C-extension class).

3. **`AuthenticatedExceptionTypeSugar.desugar`** projects from sealed identity (or supplied `class_value`) without forcing Attribute floors on module heads.

4. **Manager actual construction** (`manager_summary_derivation`) projects that identity on exception-type formals only (`expected_exception`, `expected`, …), so `external_error_raised(pa.ArrowInvalid)` no longer dies at `SymbolicValue.attribute` while constructing returned-manager actuals.

## After (concrete)

| # | File | Line | After residual |
|---|---|---:|---|
| 1–3 | `test_list_accessor.py` | 100,132,134 | `exit-may-halt` / `unary_operation_exception_floor:CallSiteValue not` |
| 4 | `test_arrow.py` | 1715 | same stage (identity sealed; joins peer residual) |
| 5 | `test_parquet.py` | 799 | same stage |

**After R(attribute-stage) = 0** for these five.  
They join the shared external_error exit-face residual (RaisesExc field floors), not a named attribute refusal.

### Residual of 5

| Axis | Before | After | Δ |
|---|---:|---:|---:|
| Attribute construction-panic on Arrow heads | 5 | 0 | −5 |
| Identity sealed (import coordinate) | 0 | 5 | +5 |
| MRO invented | 0 | 0 | 0 |
| Defining source absent (honest) | 5 | 5 | 0 (loud only for ancestry, not for identity) |

**Epsilon R (this PR):** −5 attribute-stage offenders.  
**Next residual (not this PR):** exit-face `RaisesExc.expected_exceptions` / matches floor shared with the other 42 external_error With-sites.

## Twins

- `test_provider_gated_exception_type_identity.py` — importorskip / try-import truthful; reassignment / parameter / handler-rebind / non-importorskip lying; live five pandas sites; identity-sealed sugar without Attribute floor.
- Nested assertion composition stress path: `pa.lib.ArrowNotImplementedError` under static import desugars via identity seal.
- Returned-manager residual pins updated: attribute panic no longer the Arrow twin.

## Validation

```bash
PYTHONPATH=implementations/python/sugar-lift-python-source/src:\
implementations/python/sugar-lift-py-tests/src:\
implementations/python/sugar-source-tree/src \
.venv-py312/bin/python -m pytest \
  implementations/python/sugar-source-tree/tests/test_provider_gated_exception_type_identity.py \
  implementations/python/sugar-source-tree/tests/test_nested_assertion_manager_composition.py::test_reverse_order_branch_constructs_both_native_boundaries \
  implementations/python/sugar-source-tree/tests/test_nested_assertion_manager_composition.py::test_reassigned_local_import_head_has_no_exception_identity \
  implementations/python/sugar-lift-python-source/tests/test_returned_assertion_manager.py::test_external_error_raised_follows_authenticated_returned_manager \
  implementations/python/sugar-lift-python-source/tests/test_returned_assertion_manager.py::test_external_error_raised_population_is_the_authenticated_47_with_sites \
  -q
# 13 passed
```
