# Install-source body dig (CallSugar)

## Shipped
1. **`install_source_dig.py`** — resolve same-module / from_import / `module.attr`
2. **CallSugar** attaches `body` when resolve + `build_bridge_body` succeed
3. **parameters** = formals when arity matches (dig requires len match)
4. **audit_lift_file** seeds `name_resolver` for same-module defs
5. **module global binds** modernized (BoundVar scope thread; `bind_temporal` blame)
6. Re-export resolve helpers for `test_module_global_name_bind`

## Law
- body=None still lawful (coordinate only)
- resolve fail → opaque dig, never invent
- nested_external_bridge default False unchanged

## Tests
`test_install_source_body_dig` + `test_module_global_name_bind` → 9 passed
