# Issue 4208 triage tranche 1

Measured on `origin/main` at `a1d1f5536` with:

`uv run --with pytest --no-project python -m pytest` over the first fifteen
failing modules alphabetically.

Result: 94 failed, 38 passed. All fifteen modules are product regressions.
No assertions were changed and no product code was modified.

| Module | Verdict | Mechanism and locus |
|---|---|---|
| `test_alias_sugar.py` | PRODUCT REGRESSION | `factory/build.py:103` has no candidate for an `ast.alias` term, so both import-alias shapes reach the Sugar None arm. |
| `test_append_rebind.py` | PRODUCT REGRESSION | `factory/build.py:107` sees `MethodCallSugar` and `AppendCallSugar` with no dominating owner for `xs.append(...)`. |
| `test_assertion_axis.py` | PRODUCT REGRESSION | `lift_rpc.py` no longer produces the refused-loud assertion accounting pinned for held body gaps; two audit/report joins disagree. |
| `test_attribute_descriptor_dunders.py` | PRODUCT REGRESSION | live descriptor and attribute mutation sugars still dispatch through operation methods whose implementations were removed, breaking all ten protocol projections. |
| `test_aug_assign_sugar.py` | PRODUCT REGRESSION | divide-by-zero, power assignment, and subscript augmented assignment no longer reach their typed effect/fold floors. |
| `test_binary_handoff_policy.py` | PRODUCT REGRESSION | `bin/sugarbin` shelf fallback, exhaustion, and publish behavior diverge from the pinned binary handoff contract. |
| `test_binop_sugar.py` | PRODUCT REGRESSION | live binary sugars still require removed operation dispatch for effects, symbolic coordinates, and sequence repetition; twelve tests fail. |
| `test_bitwise_op_sugar.py` | PRODUCT REGRESSION | every bitwise path fails before its BV32 or concrete floor result because the operation-dispatch implementation is absent. |
| `test_boolop_sugar.py` | PRODUCT REGRESSION | boolean expression and assertion construction no longer reach the typed runtime/claim outcomes required by all three tests. |
| `test_builtin_call_sugar.py` | PRODUCT REGRESSION | `str` and `len` live builtin owners fail to preserve coordinate-carrying concrete and symbolic floor results. |
| `test_builtin_dunder_bridge.py` | PRODUCT REGRESSION | the live builtin-call partition still claims dunder-backed shapes, but 29 bridge/value-demand paths cannot dispatch to their object floors. |
| `test_call_kwargs_sugar.py` | PRODUCT REGRESSION | keyword call construction loses or refuses positional/keyword parameter coordinates, including the required loud `**kwargs` boundary. |
| `test_callsite_binary_dispatch.py` | PRODUCT REGRESSION | the Signer `sign` body cannot attach after the binary-operation gate in the installed-source resolver path. |
| `test_claim_mass_nested_dig.py` | PRODUCT REGRESSION | nested `Signer.get_signature` body attachment no longer closes systemically through the source resolver. |
| `test_claim_registry_import_validation.py` | PRODUCT REGRESSION | `default_catalog()` rejects the live registry before planted duplicate, dangling, and cycle checks can run, so all six registry invariants fail at import. |

