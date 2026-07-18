# `source_fragment.py` side-door inventory (2026-07-18)

This inventory accompanies #5207 and the STEP 1 zero-tolerance instrument in
#5204. The promoted `classify_loop_control_scope` walker is gone. Its semantic
owner is `LoopControlScopeSugar`; raw traversal is isolated in the structural
recognition layer, and For/While/Try/comprehension Sugars consume only that
owner.

The structural gateway now lives at `sugar_lift_py_tests/source_fragment.py`;
`factory/source_fragment.py` is an AST-free compatibility import. This makes
the boundary explicit: source grammar projection is not factory behavior
construction. The gateway contains no IR/floor construction and no `.reduce`
call. Its remaining raw-AST sites are enumerated below rather than silently
treating their former factory filename as permission.

## Traversal and visitor side doors

| Kind | Function | Lines | Disposition |
|---|---|---:|---|
| `ast.walk` | `_mark_annotation_subtree` | 66 | Flag: annotation-context mutation belongs to an annotation recognizer/context pass. |
| `ast.walk` | `_annotation_roots` | 85 | Flag: annotation-shape classification belongs to the annotation Sugar family. |
| `ast.walk` | `_mark_runtime_statement` | 114, 116 | Flag: expression-context mutation belongs to a context/recognition pass. |
| `NodeVisitor` | `_mark_loop_body` | 132 | Flag: loop-control metadata mutation remains a temporal-context side door; it is not the removed semantic scope classifier. |
| `ast.walk` | `_has_source_ancestor` | 270 | Flag: source-ancestry classification belongs to the source-location/context layer. |
| `ast.walk` | `binds_name_anywhere` | 1962 | Flag: whole-subtree binding classification belongs to a binding recognizer. |
| `ast.walk` | `loaded_names` | 2032 | Flag: whole-subtree load classification belongs to a binding recognizer. |
| `ast.walk` | `stored_or_deleted_names` | 2045 | Flag: whole-subtree mutation classification belongs to a binding recognizer. |

## `isinstance(node, ast.*)` sites

The STEP 1 instrument distinguishes structural child projection from
behavior-driving classification. Structural sites are still recorded here so
future promotion work starts from an honest census.

| Function | Lines | Disposition |
|---|---:|---|
| `_is_suite` | 50 | Structural block normalization. |
| `_dotted_expr_name` | 55, 57 | Flag: qualified-name shape recognition. |
| `_is_pep613_type_alias` | 72, 76, 78 | Flag: annotation/type-alias classification. |
| `_annotation_roots` | 86, 89, 93 | Flag: annotation classification. |
| `_mark_runtime_statement` | 119 | Flag: runtime-expression context classification. |
| `from_node` | 186 | Structural fragment construction boundary. |
| `memento` | 234 | Structural node identity/cache validation. |
| `_has_source_ancestor` | 281 | Flag: source-ancestry classification. |
| `is_within_annotation` | 327, 330, 334, 338 | Flag: annotation classification. |
| `_compute_fragments` | 397, 409, 417 | Structural child projection. |
| `statements` | 427, 430 | Structural statement projection. |
| `terms` | 437 | Structural expression projection. |
| `call_is_method_call` | 501 | Flag: call-shape classification; promote with call Sugars. |
| `call_receiver` | 506 | Structural call-child projection. |
| `call_target_name` | 514, 516 | Flag: call-target classification; promote with call Sugars. |
| `initializer_call_site` | 614 | Flag: initializer-call classification. |
| `subscript_index` | 710 | Structural subscript-child projection. |
| `named_expr_target_name` | 753 | Flag: binding-target classification. |
| `assign_target_name` | 859 | Flag: assignment-target classification. |
| `assign_target_attribute_receiver_name` | 877, 878 | Flag: assignment-target classification. |
| `assign_target_attribute_name` | 887 | Flag: assignment-target classification. |
| `assign_target_dotted_attribute_path` | 895 | Flag: assignment-target classification. |
| `except_handler_type_names` | 994 | Flag: exception-handler classification. |
| `stmt_node` | 1169 | Structural statement projection. |
| `is_statement_site` | 1265 | Structural role projection. |
| `assert_with_test` | 1341 | Structural assertion reconstruction. |
| `boolop_op_kind` | 1366 | Flag: operator classification; promote with Boolean-op Sugar. |
| `joined_str_static_text` | 1442 | Flag: format/static-value classification. |
| `annassign_target_id` | 1587 | Flag: annotated-binding classification. |
| `literal_pytest_parametrize_rows` | 1669 | Flag: literal/pytest-call classification. |
| `with_optional_vars_name` | 1801 | Flag: With binding-target classification. |
| `for_target_name` | 1849 | Flag: For binding-target classification. |
| `for_flat_tuple_target_names` | 1862, 1864 | Flag: For destructuring classification. |
| `for_nested_tuple_target_paths` | 1874 | Flag: For destructuring classification. |
| nested `visit` in `for_nested_tuple_target_paths` | 1881, 1884 | Flag: For destructuring classification. |
| `binds_name_anywhere` | 1964, 1972, 1973, 1977 | Flag: whole-subtree binding classification. |
| `loaded_names` | 2033 | Flag: whole-subtree load classification. |
| `stored_or_deleted_names` | 2046 | Flag: whole-subtree mutation classification. |

## Counts

- `isinstance(node, ast.*)`: 56 sites
- `ast.walk`: 8 sites
- `NodeVisitor`: 1 site
- IR/floor construction: 0 sites
- `.reduce`: 0 sites
- Total enumerated raw-AST/construction/reduction sites: 65

The merged #5204 zero-tolerance factory instrument moves from 110 to 45
offenses for this lane. All 65 former `factory/source_fragment.py` loci leave
the factory census; `factory/source_fragment.py` is green at zero. The global
stable-zero test remains honestly red on 45 unrelated factory loci, chiefly
`factory/sugar_constructors.py`; this lane does not suppress or allowlist them.
