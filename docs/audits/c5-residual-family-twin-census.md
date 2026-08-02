# C5 residual-family twin census (code inventory)

**Criterion 5:** every residual family must be proven by BOTH a truthful twin and a lying twin.
**Method:** closed production vocabularies (`WithConstructionGapKind` 42 members, `SugarNotWritten` hierarchy, `GapKind`, `ConstructionPanic`, recensus board categories) + static scan of focused test trees for family wire/class tokens and truthful/lying **markers**.
**Not a recensus measure.** No battleaxe. Black seal untouched.

## Why C5 exists (the membrane example)

`call-target-off-population` is the population membrane — the residual that stops rebuild of CPython off-pin. A **truthful** twin only proves we recognise the residual when present. Without a **lying** twin we cannot prove we would notice its **absence**. If the membrane silently stopped citing and went back to rebuilding, nothing would catch it: the walk would only get slower, and we would hunt for a cause — exactly the failure mode of tonight's hours of contention hunting. That is the whole C5 criterion in one family: a detector nobody has fooled is a detector nobody has tested.

## Summary (verified re-scan after rank-1)

| metric | pre-rank1 | **verified post-rank1** |
| --- | ---: | ---: |
| residual families inventoried | 65 | **66** |
| both twins (heuristic marker) | 37 | **43** |
| **missing lying twin** | **25** | **20** |
| missing truthful twin | 26 | 22 |

**Predict-then-verify:** rank-1 predicted 25 → ~21. Re-scan on tip with `test_c5_residual_lying_twins_rank1.py` present reports **missing_lying=20**. All four rank-1 wires credit as `both` against that file:

| family | census credit path |
| --- | --- |
| `call-target-off-population` | both ← rank-1 file |
| `exit-missing` | both ← rank-1 file |
| `unresolved-symbol` | both ← rank-1 file |
| `ConstructedValueTestimonyNotWritten` | both ← rank-1 file |

Delta is not exactly −4: inventory cardinality moved 65→66 (`UNRECOGNIZED_RESOLUTION_KIND` enrolled), and heuristic co-credit on other files moved a few rows. The four planted twins **are** visible to the census — the number 25 was not a blind orientation figure; the re-scan can see the new markers.

A family with **no lying twin marker** is a family we cannot even *claim* to detect under this inventory.

### Caveats — read before treating R as proof

**`R_missing_lying_twin=20` is not “46 families proven.”** It is “20 families still lack a lying **marker** under a static inventory.” The dual:

1. **Marker ≠ proof the detector fires.** The census looks for wire/class tokens co-located with `truthful` / `lying` / `*_twin_*` spelling. It does **not** execute the twin, does **not** assert the detector product, and does **not** prove the lying face exercises the real residual path. A family can score `both` by marker and still be unproven if the lying twin never makes the detector fire (or only renames a sibling kind). Treat `both` as *candidate enrollment*, not as C5 discharge.
2. **Heuristic over-credit:** a multi-kind test file with twin markers can mark several kinds `both` when only one kind is twinned in that file.
3. **Heuristic under-credit:** twins that never spell the wire string (type-only assert) can show as `neither`.
4. **Separate domain:** Sugar/ProofIR family C5 lives in `scripts/semantic_family_twin_inventory_law.py` (factory `witnesses()` / NotVerdictBearing opt-outs). That is not this residual table. Do not read 66 residual families as the full semantic family set.
5. **Static only:** no corpus, no seal remeasure, no battleaxe. Residual gap products, not sugar-catalog C5.

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

## Missing lying twin — ranked (seal / floor load-bearing)

A truthful twin proves recognition when the residual is present. A **lying** twin
proves we would notice its **absence** (or refuse a misclassification). Rank is
by whether tonight's seal / floors depend on that detector:

| rank | family | why load-bearing | verified status |
| ---: | --- | --- | --- |
| **1** | `call-target-off-population` | Population membrane; silent stop → rebuild CPython / slower walk with no alarm | **both** (rank-1 file; marker credit verified) |
| **2** | `exit-missing` | Closed CM protocol residual on seal vocabulary | **both** (rank-1; discriminates vs enter-missing) |
| **3** | `unresolved-symbol` | Default With loud residual without a contract ref | **both** (rank-1; bare return is not unresolved-symbol) |
| **4** | `ConstructedValueTestimonyNotWritten` / category gap | False-green construction class | **both** (rank-1; tuple ok / list loud) |
| … | remaining vocabulary / panic / board rows | see still-missing list | **missing lying marker** |

### Still missing lying twin marker (verified R=20)

- `WithConstructionGapKind.AMBIGUOUS_SYMBOL` (`ambiguous-symbol`)
- `WithConstructionGapKind.WRONG_CONTRACT_KIND` (`wrong-contract-kind`)
- `WithConstructionGapKind.SIGNATURE_MISMATCH` (`signature-mismatch`)
- `WithConstructionGapKind.UNAUTHENTICATED_MEMBER` (`unauthenticated-member`)
- `WithConstructionGapKind.PAYLOAD_CID_MISMATCH` (`payload-cid-mismatch`)
- `WithConstructionGapKind.STALE_DERIVED_CONTRACT` (`stale-derived-contract`)
- `WithConstructionGapKind.UNSUPPORTED_CONTEXT_MANAGER_SEMANTICS` (`unsupported-context-manager-semantics`)
- `WithConstructionGapKind.UNSUPPORTED_WITH_BINDING_TARGET` (`unsupported-with-binding-target`)
- `WithConstructionGapKind.ASYNC_CONTEXT_MANAGER_UNSUPPORTED` (`async-context-manager-unsupported`)
- `WithConstructionGapKind.UNSUPPORTED_STATEMENT` (`unsupported-statement`)
- `WithConstructionGapKind.MALFORMED_IMPORT_BINDING` (`malformed-import-binding`)
- `WithConstructionGapKind.ARTIFACT_MODULE_ABSENT` (`artifact-module-absent`)
- `WithConstructionGapKind.TARGET_OUTSIDE_BINDING` (`target-outside-binding`)
- `WithConstructionGapKind.OPAQUE_SOURCE` (`opaque-source`)
- `WithConstructionGapKind.INCOMPLETE_CALL_ACTUALS` (`incomplete-call-actuals`)
- `WithConstructionGapKind.ARTIFACT_MISMATCH` (`artifact-mismatch`)
- `WithConstructionGapKind.UNRECOGNIZED_RESOLUTION_KIND` (`unrecognized-resolution-kind`) — new vs pre-rank1 n=65
- `panic.AsyncContextManagerUnsupported` (`AsyncContextManagerUnsupported`)
- `panic.SubstituteNotWritten` (`SubstituteNotWritten`)
- `recensus.category.instrument-defect-unresolvable-dispatch` (`instrument-defect-unresolvable-dispatch`)

**Verified R:** missing lying = **20** (was 25 pre-rank1; predicted ~21; actual 20). Marker credit only — see caveats.

## Group inventory sources

- **WithConstructionGapKind** (42): `implementations/python/sugar-source-tree/src/sugar_source_tree/panic.py`
- **panic.* residual classes**: SNW subclasses + VocabularyMissing/BackendDefect/SubstituteNotWritten in same file
- **ConstructionPanic**: `sugar_lift_py_tests/gap/panic.py` (single product class; GapKind is orthogonal)
- **GapKind** (6): `sugar_lift_py_tests/gap/info.py` — construction-gap locus labels, not CM residual kinds
- **recensus categories** (4): `recensus_enumerate_consumer.py` board categories

*Static inventory only (`tools/c5_residual_family_twin_census.py` approach). Summary metrics and still-missing list re-verified post-rank1; the large status table above is the pre-rank1 snapshot and is superseded by the verified summary for R. Marker credit is not detector proof — see caveats. No corpus measurement.*
