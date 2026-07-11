# Method body dig (install-source)

## Shipped
1. **Class.method resolve** — `module_sibling` indexes ClassDef methods;
   `resolve_install_source_class_method` / `resolve_method_funcdef`
2. **MethodCallSugar** attaches body when resolve + **attachable** gate
3. **audit_lift_file** seeds `Class.method` into name_resolver
4. **Attachable gate** — single `return Name|const|self.attr` only;
   complex methods (Signer.sign BinOp) stay `body=None` (coordinate)
5. **_dig_floor_or_none** soft-catches FactoryPanic → opaque (not whole-def kill)

## Law
- Complex method dig without floors → coordinate, not invent
- Simple identity methods dig body
- nested_external_bridge default False

## Tests
`test_install_source_method_body_dig` + free-function dig → 10 passed
