# C5 residual-family twin census (code inventory)

**Criterion 5:** every residual family must be proven by BOTH a truthful twin and a lying twin.
**Method:** closed production vocabularies (`WithConstructionGapKind` 42 members, `SugarNotWritten` hierarchy, `GapKind`, `ConstructionPanic`, recensus board categories) + static `rg` of `implementations/python/**/tests/**` for wire/class tokens and truthful/lying markers.
**Not a recensus measure.** No battleaxe. Black seal untouched.

## Summary

| metric | count |
| --- | ---: |
| residual families inventoried | 65 |
| both twins (heuristic) | 37 |
| truthful only | 2 |
| lying only | 3 |
| mentioned without twin markers | 8 |
| neither (no test hit) | 15 |
| **missing lying twin** | **25** |
| missing truthful twin | 26 |

A family with **no lying twin** is a family we cannot prove we detect.

### Caveats

- Heuristic over-credit: a multi-kind test file with twin markers can mark several kinds `both` when only one kind is twinned in that file.
- Under-credit: twins that never spell the wire string (type-only assert) can show as `neither`.
- Separate domain: Sugar/ProofIR family C5 lives in `scripts/semantic_family_twin_inventory_law.py` (factory `witnesses()` / NotVerdictBearing opt-outs). That is not this residual table.

## Table

| family | wire / product | truthful | path | lying | path | status |
| --- | --- | :---: | --- | :---: | --- | --- |
| `WithConstructionGapKind.RUNTIME_SELECTED` | `runtime-selected` | yes | `…mentations/python/sugar-lift-py-tests/tests/test_enumerate_rpc.py` | yes | `…mentations/python/sugar-lift-py-tests/tests/test_enumerate_rpc.py` | both |
| `WithConstructionGapKind.UNRESOLVED_SYMBOL` | `unresolved-symbol` | no | `…tations/python/sugar-source-tree/tests/with_resolution_fixture.py` | no | `…tations/python/sugar-source-tree/tests/with_resolution_fixture.py` | mentioned_no_twin_markers |
| `WithConstructionGapKind.AMBIGUOUS_SYMBOL` | `ambiguous-symbol` | no | `…thon/sugar-lift-py-tests/tests/test_context_manager_resolution.py` | no | `…thon/sugar-lift-py-tests/tests/test_context_manager_resolution.py` | mentioned_no_twin_markers |
| `WithConstructionGapKind.WRONG_CONTRACT_KIND` | `wrong-contract-kind` | no | `—` | no | `—` | neither |
| `WithConstructionGapKind.SIGNATURE_MISMATCH` | `signature-mismatch` | no | `—` | no | `—` | neither |
| `WithConstructionGapKind.UNAUTHENTICATED_MEMBER` | `unauthenticated-member` | no | `—` | no | `—` | neither |
| `WithConstructionGapKind.PAYLOAD_CID_MISMATCH` | `payload-cid-mismatch` | no | `—` | no | `—` | neither |
| `WithConstructionGapKind.UNSUPPORTED_CM_SCHEMA` | `unsupported-cm-schema` | no | `…n/sugar-source-tree/tests/test_with_authenticated_contract_ref.py` | no | `…n/sugar-source-tree/tests/test_with_authenticated_contract_ref.py` | mentioned_no_twin_markers |
| `WithConstructionGapKind.NO_DERIVED_CONTRACT` | `no-derived-contract` | yes | `…r-lift-python-source/tests/test_sole_path_manager_construction.py` | yes | `…r-lift-python-source/tests/test_sole_path_manager_construction.py` | both |
| `WithConstructionGapKind.STALE_DERIVED_CONTRACT` | `stale-derived-contract` | no | `—` | no | `—` | neither |
| `WithConstructionGapKind.UNSUPPORTED_CONTEXT_MANAGER_SEMANTICS` | `unsupported-context-manager-semantics` | no | `—` | no | `—` | neither |
| `WithConstructionGapKind.UNSUPPORTED_WITH_BINDING_TARGET` | `unsupported-with-binding-target` | no | `—` | no | `—` | neither |
| `WithConstructionGapKind.ASYNC_CONTEXT_MANAGER_UNSUPPORTED` | `async-context-manager-unsupported` | no | `—` | no | `—` | neither |
| `WithConstructionGapKind.DYNAMIC_EXPORT` | `dynamic-export` | yes | `…-python-source/tests/test_relative_submodule_member_resolution.py` | yes | `…/sugar-lift-python-source/tests/test_dependency_artifact_graph.py` | both |
| `WithConstructionGapKind.STATIC_EXPORT_ABSENT` | `static-export-absent` | yes | `…gar-lift-python-source/tests/test_reexport_alias_star_warrants.py` | yes | `…gar-lift-python-source/tests/test_reexport_alias_star_warrants.py` | both |
| `WithConstructionGapKind.UNSUPPORTED_STATEMENT` | `unsupported-statement` | no | `…python/sugar-source-tree/tests/test_with_construction_gap_kind.py` | no | `…python/sugar-source-tree/tests/test_with_construction_gap_kind.py` | mentioned_no_twin_markers |
| `WithConstructionGapKind.MALFORMED_IMPORT_BINDING` | `malformed-import-binding` | no | `—` | no | `—` | neither |
| `WithConstructionGapKind.ARTIFACT_MODULE_ABSENT` | `artifact-module-absent` | yes | `…t-python-source/tests/test_returned_resource_with_construction.py` | yes | `…t-python-source/tests/test_returned_resource_with_construction.py` | both |
| `WithConstructionGapKind.TARGET_OUTSIDE_BINDING` | `target-outside-binding` | yes | `…-python-source/tests/test_relative_submodule_member_resolution.py` | no | `—` | truthful_only |
| `WithConstructionGapKind.AMBIGUOUS_STATIC_EXPORT` | `ambiguous-static-export` | yes | `…gar-lift-python-source/tests/test_reexport_alias_star_warrants.py` | yes | `…gar-lift-python-source/tests/test_reexport_alias_star_warrants.py` | both |
| `WithConstructionGapKind.OPAQUE_SOURCE` | `opaque-source` | no | `—` | no | `—` | neither |
| `WithConstructionGapKind.REEXPORT_CYCLE` | `reexport-cycle` | yes | `…-python-source/tests/test_relative_submodule_member_resolution.py` | yes | `…gar-lift-python-source/tests/test_reexport_alias_star_warrants.py` | both |
| `WithConstructionGapKind.INCOMPLETE_CALL_ACTUALS` | `incomplete-call-actuals` | no | `—` | no | `—` | neither |
| `WithConstructionGapKind.ARTIFACT_MISMATCH` | `artifact-mismatch` | no | `…gar-lift-python-source/tests/test_resolution_session_authority.py` | no | `…gar-lift-python-source/tests/test_resolution_session_authority.py` | mentioned_no_twin_markers |
| `WithConstructionGapKind.DEFINITION_MISSING` | `definition-missing` | no | `—` | no | `—` | neither |
| `WithConstructionGapKind.NON_MANAGER_RESULT` | `non-manager-result` | yes | `…r-lift-python-source/tests/test_sole_path_manager_construction.py` | yes | `…r-lift-python-source/tests/test_sole_path_manager_construction.py` | both |
| `WithConstructionGapKind.CALL_BINDING` | `call-binding` | yes | `…ugar-lift-python-source/tests/test_source_call_preconstruction.py` | yes | `…ugar-lift-python-source/tests/test_source_call_preconstruction.py` | both |
| `WithConstructionGapKind.FORCE_FLOOR` | `force-floor` | yes | `…sugar-lift-python-source/tests/test_returned_assertion_manager.py` | yes | `…sugar-lift-python-source/tests/test_returned_assertion_manager.py` | both |
| `WithConstructionGapKind.CALL_GRAPH_CYCLE` | `call-graph-cycle` | yes | `…ift-python-source/tests/test_external_call_target_construction.py` | yes | `…ift-python-source/tests/test_external_call_target_construction.py` | both |
| `WithConstructionGapKind.VALUE_CALL_TARGET` | `value-call-target` | yes | `…sugar-lift-python-source/tests/test_call_target_gap_mechanisms.py` | yes | `…sugar-lift-python-source/tests/test_call_target_gap_mechanisms.py` | both |
| `WithConstructionGapKind.CALL_TARGET_SOURCE_ABSENT` | `call-target-source-absent` | yes | `…ift-python-source/tests/test_external_call_target_construction.py` | yes | `…ift-python-source/tests/test_external_call_target_construction.py` | both |
| `WithConstructionGapKind.CALL_TARGET_EXPORT_UNRESOLVED` | `call-target-export-unresolved` | yes | `…sugar-lift-python-source/tests/test_call_target_gap_mechanisms.py` | yes | `…sugar-lift-python-source/tests/test_call_target_gap_mechanisms.py` | both |
| `WithConstructionGapKind.CALL_TARGET_OFF_POPULATION` | `call-target-off-population` | no | `…-lift-python-source/tests/test_population_membrane_stdlib_cite.py` | no | `…-lift-python-source/tests/test_population_membrane_stdlib_cite.py` | mentioned_no_twin_markers |
| `WithConstructionGapKind.ENTER_MISSING` | `enter-missing` | yes | `…r-lift-python-source/tests/test_sole_path_manager_construction.py` | yes | `…r-lift-python-source/tests/test_sole_path_manager_construction.py` | both |
| `WithConstructionGapKind.EXIT_MISSING` | `exit-missing` | no | `—` | no | `—` | neither |
| `WithConstructionGapKind.METHOD_CONSTRUCTION` | `method-construction` | yes | `…r-lift-python-source/tests/test_sole_path_manager_construction.py` | yes | `…r-lift-python-source/tests/test_sole_path_manager_construction.py` | both |
| `WithConstructionGapKind.GENERATOR_MISSING` | `generator-missing` | no | `—` | yes | `…python-source/tests/test_generator_backed_resource_publication.py` | lying_only |
| `WithConstructionGapKind.GENERATOR_PROTOCOL` | `generator-protocol` | no | `—` | yes | `…python-source/tests/test_generator_backed_resource_publication.py` | lying_only |
| `WithConstructionGapKind.ENTER_MAY_HALT` | `enter-may-halt` | yes | `…r-lift-python-source/tests/test_sole_path_manager_construction.py` | yes | `…r-lift-python-source/tests/test_sole_path_manager_construction.py` | both |
| `WithConstructionGapKind.EXIT_MAY_HALT` | `exit-may-halt` | yes | `…sugar-lift-py-tests/tests/test_first_auth_exit_vertical_slices.py` | yes | `…sugar-lift-py-tests/tests/test_first_auth_exit_vertical_slices.py` | both |
| `WithConstructionGapKind.OPAQUE_EXIT_TRUTHINESS` | `opaque-exit-truthiness` | yes | `…r-lift-python-source/tests/test_sole_path_manager_construction.py` | yes | `…r-lift-python-source/tests/test_sole_path_manager_construction.py` | both |
| `panic.SugarNotWritten` | `SugarNotWritten` | yes | `…ugar-lift-python-source/tests/test_source_call_preconstruction.py` | yes | `…ugar-lift-python-source/tests/test_source_call_preconstruction.py` | both |
| `panic.UnattributableRefusal` | `UnattributableRefusal` | yes | `…python/sugar-lift-py-tests/tests/test_no_call_body_attribution.py` | yes | `…python/sugar-lift-py-tests/tests/test_no_call_body_attribution.py` | both |
| `panic.OpaqueSourceCallResolutionGap` | `OpaqueSourceCallResolutionGap` | yes | `…sugar-lift-python-source/tests/test_call_target_gap_mechanisms.py` | yes | `…sugar-lift-python-source/tests/test_call_target_gap_mechanisms.py` | both |
| `panic.RuntimeSelectedContextManager` | `RuntimeSelectedContextManager` | yes | `…ython/sugar-lift-py-tests/tests/test_recensus_panic_collection.py` | yes | `…ython/sugar-lift-py-tests/tests/test_recensus_panic_collection.py` | both |
| `panic.ConstructedValueTestimonyNotWritten` | `ConstructedValueTestimonyNotWritten` | yes | `…hon/sugar-source-tree/tests/test_cpython_call_handle_testimony.py` | no | `—` | truthful_only |
| `panic.WithConstructionGap` | `WithConstructionGap` | yes | `…sugar-lift-python-source/tests/test_returned_assertion_manager.py` | yes | `…sugar-lift-python-source/tests/test_returned_assertion_manager.py` | both |
| `panic.ContextManagerResolutionConstructionGap` | `ContextManagerResolutionConstructionGap` | yes | `…ython/sugar-lift-py-tests/tests/test_recensus_panic_collection.py` | yes | `…ython/sugar-lift-py-tests/tests/test_recensus_panic_collection.py` | both |
| `panic.UnsupportedContextManagerSemantics` | `UnsupportedContextManagerSemantics` | yes | `…/python/sugar-source-tree/tests/test_no_swallowed_cm_ref_panic.py` | yes | `…/python/sugar-source-tree/tests/test_no_swallowed_cm_ref_panic.py` | both |
| `panic.UnsupportedWithBindingTarget` | `UnsupportedWithBindingTarget` | yes | `…r-lift-python-source/tests/test_sole_path_manager_construction.py` | yes | `…r-lift-python-source/tests/test_sole_path_manager_construction.py` | both |
| `panic.AsyncContextManagerUnsupported` | `AsyncContextManagerUnsupported` | no | `…n/sugar-source-tree/tests/test_with_authenticated_contract_ref.py` | no | `…n/sugar-source-tree/tests/test_with_authenticated_contract_ref.py` | mentioned_no_twin_markers |
| `panic.VocabularyMissing` | `VocabularyMissing` | yes | `…mentations/python/sugar-lift-py-tests/tests/test_enumerate_rpc.py` | yes | `…mentations/python/sugar-lift-py-tests/tests/test_enumerate_rpc.py` | both |
| `panic.BackendDefect` | `BackendDefect` | yes | `…ns/python/sugar-lift-py-tests/tests/test_if_branch_result_slot.py` | yes | `…mentations/python/sugar-lift-py-tests/tests/test_enumerate_rpc.py` | both |
| `panic.SubstituteNotWritten` | `SubstituteNotWritten` | no | `…ons/python/sugar-source-tree/tests/test_substitute_int_literal.py` | no | `…ons/python/sugar-source-tree/tests/test_substitute_int_literal.py` | mentioned_no_twin_markers |
| `ConstructionPanic` | `ConstructionPanic` | yes | `…on/sugar-lift-py-tests/tests/test_sin_cluster_2_ordering_floor.py` | yes | `…on/sugar-lift-py-tests/tests/test_sin_cluster_2_ordering_floor.py` | both |
| `recensus.category.completed` | `completed` | yes | `…/sugar-source-tree/tests/test_generator_for_step_v1_instrument.py` | yes | `…/sugar-source-tree/tests/test_generator_for_step_v1_instrument.py` | both |
| `recensus.category.construction-panic` | `construction-panic` | yes | `…ython/sugar-lift-py-tests/tests/test_recensus_panic_collection.py` | yes | `…ython/sugar-lift-py-tests/tests/test_recensus_panic_collection.py` | both |
| `recensus.category.backend-defect` | `backend-defect` | yes | `…/sugar-source-tree/tests/test_span_belongs_to_its_minting_unit.py` | yes | `…/sugar-source-tree/tests/test_span_belongs_to_its_minting_unit.py` | both |
| `recensus.category.instrument-defect-unresolvable-dispatch` | `instrument-defect-unresolvable-dispatch` | no | `—` | no | `—` | neither |
| `GapKind.FLOOR` | `Floor` | yes | `…ions/python/sugar-lift-py-tests/tests/test_binop_method_caller.py` | yes | `…ions/python/sugar-lift-py-tests/tests/test_binop_method_caller.py` | both |
| `GapKind.SUGAR` | `Sugar` | yes | `…urce-tree/tests/test_imported_exception_attribute_construction.py` | yes | `…urce-tree/tests/test_imported_exception_attribute_construction.py` | both |
| `GapKind.CONSTRUCTOR` | `Constructor` | no | `—` | yes | `…/python/sugar-lift-py-tests/tests/vendor/cpython-3.11/datetime.py` | lying_only |
| `GapKind.SUGAR_ORDERING` | `Sugar ordering` | no | `—` | no | `—` | neither |
| `GapKind.OPERATION` | `Operation` | yes | `…ons/python/sugar-lift-py-tests/tests/test_delete_formal_caller.py` | yes | `…ons/python/sugar-lift-py-tests/tests/test_delete_formal_caller.py` | both |
| `GapKind.PROOFIR` | `ProofIR` | yes | `…ar-lift-py-tests/tests/test_semantic_family_twin_inventory_law.py` | yes | `…ar-lift-py-tests/tests/test_semantic_family_twin_inventory_law.py` | both |

## Missing lying twin (action list)

- `WithConstructionGapKind.UNRESOLVED_SYMBOL` (`unresolved-symbol`)
- `WithConstructionGapKind.AMBIGUOUS_SYMBOL` (`ambiguous-symbol`)
- `WithConstructionGapKind.WRONG_CONTRACT_KIND` (`wrong-contract-kind`)
- `WithConstructionGapKind.SIGNATURE_MISMATCH` (`signature-mismatch`)
- `WithConstructionGapKind.UNAUTHENTICATED_MEMBER` (`unauthenticated-member`)
- `WithConstructionGapKind.PAYLOAD_CID_MISMATCH` (`payload-cid-mismatch`)
- `WithConstructionGapKind.UNSUPPORTED_CM_SCHEMA` (`unsupported-cm-schema`)
- `WithConstructionGapKind.STALE_DERIVED_CONTRACT` (`stale-derived-contract`)
- `WithConstructionGapKind.UNSUPPORTED_CONTEXT_MANAGER_SEMANTICS` (`unsupported-context-manager-semantics`)
- `WithConstructionGapKind.UNSUPPORTED_WITH_BINDING_TARGET` (`unsupported-with-binding-target`)
- `WithConstructionGapKind.ASYNC_CONTEXT_MANAGER_UNSUPPORTED` (`async-context-manager-unsupported`)
- `WithConstructionGapKind.UNSUPPORTED_STATEMENT` (`unsupported-statement`)
- `WithConstructionGapKind.MALFORMED_IMPORT_BINDING` (`malformed-import-binding`)
- `WithConstructionGapKind.TARGET_OUTSIDE_BINDING` (`target-outside-binding`)
- `WithConstructionGapKind.OPAQUE_SOURCE` (`opaque-source`)
- `WithConstructionGapKind.INCOMPLETE_CALL_ACTUALS` (`incomplete-call-actuals`)
- `WithConstructionGapKind.ARTIFACT_MISMATCH` (`artifact-mismatch`)
- `WithConstructionGapKind.DEFINITION_MISSING` (`definition-missing`)
- `WithConstructionGapKind.CALL_TARGET_OFF_POPULATION` (`call-target-off-population`)
- `WithConstructionGapKind.EXIT_MISSING` (`exit-missing`)
- `panic.ConstructedValueTestimonyNotWritten` (`ConstructedValueTestimonyNotWritten`)
- `panic.AsyncContextManagerUnsupported` (`AsyncContextManagerUnsupported`)
- `panic.SubstituteNotWritten` (`SubstituteNotWritten`)
- `recensus.category.instrument-defect-unresolvable-dispatch` (`instrument-defect-unresolvable-dispatch`)
- `GapKind.SUGAR_ORDERING` (`Sugar ordering`)

## Group inventory sources

- **WithConstructionGapKind** (42): `implementations/python/sugar-source-tree/src/sugar_source_tree/panic.py`
- **panic.* residual classes**: SNW subclasses + VocabularyMissing/BackendDefect/SubstituteNotWritten in same file
- **ConstructionPanic**: `sugar_lift_py_tests/gap/panic.py` (single product class; GapKind is orthogonal)
- **GapKind** (6): `sugar_lift_py_tests/gap/info.py` — construction-gap locus labels, not CM residual kinds
- **recensus categories** (4): `recensus_enumerate_consumer.py` board categories

*Generated by static inventory (`/tmp/c5_rows.txt` via tools/c5_residual_family_twin_census approach). No measurement.*
