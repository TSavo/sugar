# Authenticated Raise Rewrite Casualty Receipt

## Snapshots and measured counts

- Mechanical introducer: `bf847eb9363fd050b326ffd16543275b231d783e`.
- Introducer parent: `9f8675d24` (the exact parent used by the AST delta).
- Introducer population: 115 changed Python files.
- Introduced unbound loads: 187 `AuthenticatedRaiseLocus` loads in 71 offender
  files within that 115-file population.
- Current survivor snapshot after production PR #7147: `3cdc88c01269140c8b88d45b47d5ee38ec272163`.
- Current survivor population: 20 unbound loads in 14 test files.
- Exact current line ancestry: 1 load from `bf847eb93`, 18 loads from `8a3ceb2c0`, and 1 load from `1eeb80bb3`.
- Exact test-repair snapshot: `0ef212b9a8d4e59da9d754483ff6f04be8a6c4e7`.
- Local binding instruments on that snapshot: 0 files with an unbound `AuthenticatedRaiseLocus`; 0 of the five bounded `_identity` files remain unbound.

These are file/load measurements. They are not suite-failure counts.

## First-terminal chains

### BoolOp legacy probe

- Exact baseline SHA: `b02b333d871c97df33821c9d3918ddadccbed971`.
- Input and coordinate: `test_bool_op_operand_sequence.py::test_left_operand_is_evaluated_and_truth_tested_exactly_once`, BoolOp construction at baseline line 164.
- First observed terminal: `TypeError: BoolOpSugar.values requires ConstructedTermSugar, got _ProbeSugar`.
- Entrance: `BoolOpSugar.__post_init__`.
- After repair snapshot `0ef212b9a8d4e59da9d754483ff6f04be8a6c4e7`: the probe is a genuine `ConstructedTermSugar`; the exact file constructs through all 12 tests, `12 passed`.

### BoolOp synthetic halted operand

- Exact baseline SHA: `b02b333d871c97df33821c9d3918ddadccbed971`.
- Input and coordinate: `test_bool_op_operand_sequence.py:225`, synthetic `LeftTruthError`.
- First observed terminal: unbound `AuthenticatedRaiseLocus` at the test construction entrance.
- Entrance: direct test `RaiseEffect` construction.
- After binding the name: the next terminal was `TypeError` because the narrowed constructor required `exception_type_coordinate`.
- After repair snapshot `0ef212b9a8d4e59da9d754483ff6f04be8a6c4e7`: the synthetic non-builtin carries an explicit test coordinate and the halt constructs.

### Native exceptional projection

- Exact baseline SHA: `b02b333d871c97df33821c9d3918ddadccbed971`.
- Input and coordinate: BoolOp formal-truth discharge with `_ExceptionalTruth()`; source coordinate `boolop_caller.py:2:11-2:25`.
- First observed terminal: `NameError: AuthenticatedRaiseLocus is not defined`.
- Entrance: `NativeOperationResolutionV1.project` at `caller_parameter_contract.py:153`.
- After production SHA `3cdc88c01269140c8b88d45b47d5ee38ec272163`: projection constructs one `Halted` face with the requested type coordinate and authenticated operation occurrence.
- Next test terminal: unbound `_identity` in the assertion; after repair snapshot `0ef212b9a8d4e59da9d754483ff6f04be8a6c4e7`, the complete BoolOp file is `12 passed`.

### Generator manager first-resume refusal

- Exact baseline SHA: `b02b333d871c97df33821c9d3918ddadccbed971`.
- Inputs and coordinates: premature return at `test_generator_context_manager_construction.py:76`; never-yield at line 102.
- First terminal at the production entrance: the unbound `AuthenticatedRaiseLocus` in `GeneratorWithSugar._entry_refusal_exit`.
- Entrance: `generator_with_sugar.py:128`.
- After binding the name: the next observed terminal was `TypeError: RaiseEffect.__init__() missing exception_type_coordinate`.
- After production SHA `3cdc88c01269140c8b88d45b47d5ee38ec272163`: the observed builtin refusal routes through `RaiseEffect.for_builtin`; both focused twins pass, `2 passed`.

### Function-formal identity assertion

- Exact current-main SHA: `3cdc88c01269140c8b88d45b47d5ee38ec272163`.
- Input and coordinate: `test_function_formal_native_operation_binding.py::test_positional_actuals_discharge_through_python_binder`, `helper(None, 2)`.
- First terminal before the test repair: unbound `_identity` at line 60.
- Entrance: `_assert_named_halt`.
- After repair snapshot `0ef212b9a8d4e59da9d754483ff6f04be8a6c4e7`: the identity assertion passes; the next terminal is the separate occurrence-shape assertion at line 61. This receipt does not claim that later drift is fixed.

### Unary identity assertion

- Exact current-main SHA: `3cdc88c01269140c8b88d45b47d5ee38ec272163`.
- Input and coordinate: `test_unary_not_bool_law.py::test_halted_truth_is_not_negated`.
- First observed terminal: `TypeError: UnaryOpSugar.operand requires ConstructedTermSugar, got _ValueSugar`.
- Entrance: `UnaryOpSugar.__post_init__`.
- After binding `_identity`: the same earlier terminal remains, so the identity load is not yet executable. This receipt does not claim the separate unary fixture drift is fixed.

### Try identity assertions

- Exact current-main SHA: `3cdc88c01269140c8b88d45b47d5ee38ec272163`.
- Inputs and coordinates: `test_bare_reraise_reemits_the_exact_inflight_raise` and `test_finally_raise_supersedes_break_instead_of_fabricating_loop_exit`.
- First observed terminal: the tests receive `ExitSet` where their older assertions require `Incomplete`.
- Entrance: the assertion immediately after `function.sugar().desugar()`.
- After replacing the unbound helper with typed-source identity derivation: the same earlier outcome-shape terminal remains. This receipt does not claim that separate outcome drift is fixed.

### Local processes without a terminal receipt

- Exact repair snapshot: `0ef212b9a8d4e59da9d754483ff6f04be8a6c4e7`.
- Inputs: the focused pandas-subscript and source-setattr identity tests.
- Observation: the local pytest processes exited 143 with no pytest terminal output.
- Claim boundary: exit 143 is not counted as a product terminal, pass, failure, or timeout.

## Rewrite mechanism callability

- `bf847eb93` changed 115 Python files and added no script, codemod, workflow, or agent instruction.
- `8a3ceb2c0` likewise contains the mechanical call-site rewrite but no callable rewrite artifact.
- `1eeb80bb3` changed 50 Python tests plus `docs/presence-only-retirement-partition.md`; it added no callable tool.
- A current search of `.claude`, `.briefs`, `docs`, `bin`, and `scripts` finds the symbol only in the retirement document, not in a source-rewrite mechanism.

Repository evidence therefore finds no rewrite mechanism that remains callable. The evidence is consistent with a one-time mechanical agent or hand pass whose edits were committed without its generator. It does not prove that no external or uncommitted prompt/tool ever existed.

## Raw 187 introducer coordinates

- `implementations/python/sugar-lift-py-tests/src/sugar_lift_py_tests/caller_parameter_contract.py:153` — `AuthenticatedRaiseLocus`
- `implementations/python/sugar-lift-py-tests/src/sugar_lift_py_tests/sugar/comparison_op_sugar.py:281` — `AuthenticatedRaiseLocus`
- `implementations/python/sugar-lift-py-tests/src/sugar_lift_py_tests/sugar/generator_with_sugar.py:128` — `AuthenticatedRaiseLocus`
- `implementations/python/sugar-lift-py-tests/src/sugar_lift_py_tests/sugar/raise_sugar.py:92` — `AuthenticatedRaiseLocus`
- `implementations/python/sugar-lift-py-tests/tests/test_assertion_boundary_exitset_consumer.py:232` — `AuthenticatedRaiseLocus`
- `implementations/python/sugar-lift-py-tests/tests/test_assertion_boundary_exitset_consumer.py:256` — `AuthenticatedRaiseLocus`
- `implementations/python/sugar-lift-py-tests/tests/test_assertion_boundary_exitset_consumer.py:259` — `AuthenticatedRaiseLocus`
- `implementations/python/sugar-lift-py-tests/tests/test_assertion_boundary_exitset_consumer.py:613` — `AuthenticatedRaiseLocus`
- `implementations/python/sugar-lift-py-tests/tests/test_assertion_boundary_exitset_consumer.py:642` — `AuthenticatedRaiseLocus`
- `implementations/python/sugar-lift-py-tests/tests/test_assertion_boundary_exitset_consumer.py:680` — `AuthenticatedRaiseLocus`
- `implementations/python/sugar-lift-py-tests/tests/test_assertion_boundary_exitset_consumer.py:712` — `AuthenticatedRaiseLocus`
- `implementations/python/sugar-lift-py-tests/tests/test_assertion_boundary_exitset_consumer.py:64` — `AuthenticatedRaiseLocus`
- `implementations/python/sugar-lift-py-tests/tests/test_attribute_store_desugar.py:177` — `AuthenticatedRaiseLocus`
- `implementations/python/sugar-lift-py-tests/tests/test_block_value_hard_incomplete_follow.py:10` — `AuthenticatedRaiseLocus`
- `implementations/python/sugar-lift-py-tests/tests/test_block_value_hard_incomplete_follow.py:19` — `AuthenticatedRaiseLocus`
- `implementations/python/sugar-lift-py-tests/tests/test_bool_op_operand_sequence.py:221` — `AuthenticatedRaiseLocus`
- `implementations/python/sugar-lift-py-tests/tests/test_callsite_positional_actual_exitset.py:87` — `AuthenticatedRaiseLocus`
- `implementations/python/sugar-lift-py-tests/tests/test_callsite_positional_actual_exitset.py:94` — `AuthenticatedRaiseLocus`
- `implementations/python/sugar-lift-py-tests/tests/test_comprehension_value_length.py:116` — `AuthenticatedRaiseLocus`
- `implementations/python/sugar-lift-py-tests/tests/test_delete_state_joins.py:390` — `AuthenticatedRaiseLocus`
- `implementations/python/sugar-lift-py-tests/tests/test_desugar_axis_twins.py:52` — `AuthenticatedRaiseLocus`
- `implementations/python/sugar-lift-py-tests/tests/test_effect_boundary_observation_conserves_demands.py:101` — `AuthenticatedRaiseLocus`
- `implementations/python/sugar-lift-py-tests/tests/test_effect_router.py:33` — `AuthenticatedRaiseLocus`
- `implementations/python/sugar-lift-py-tests/tests/test_effect_slot_binding_testimony.py:101` — `AuthenticatedRaiseLocus`
- `implementations/python/sugar-lift-py-tests/tests/test_effect_slot_binding_testimony.py:102` — `AuthenticatedRaiseLocus`
- `implementations/python/sugar-lift-py-tests/tests/test_effect_slot_binding_testimony.py:135` — `AuthenticatedRaiseLocus`
- `implementations/python/sugar-lift-py-tests/tests/test_effect_slot_binding_testimony.py:136` — `AuthenticatedRaiseLocus`
- `implementations/python/sugar-lift-py-tests/tests/test_effect_slot_binding_testimony.py:137` — `AuthenticatedRaiseLocus`
- `implementations/python/sugar-lift-py-tests/tests/test_effect_slot_binding_testimony.py:183` — `AuthenticatedRaiseLocus`
- `implementations/python/sugar-lift-py-tests/tests/test_effect_slot_binding_testimony.py:50` — `AuthenticatedRaiseLocus`
- `implementations/python/sugar-lift-py-tests/tests/test_effect_slot_binding_testimony.py:81` — `AuthenticatedRaiseLocus`
- `implementations/python/sugar-lift-py-tests/tests/test_exception_context_reraise.py:197` — `AuthenticatedRaiseLocus`
- `implementations/python/sugar-lift-py-tests/tests/test_exit_disposition_exit_suppression_contract.py:31` — `AuthenticatedRaiseLocus`
- `implementations/python/sugar-lift-py-tests/tests/test_exit_disposition_exit_suppression_contract.py:63` — `AuthenticatedRaiseLocus`
- `implementations/python/sugar-lift-py-tests/tests/test_exit_disposition_suppresses_coordinate.py:31` — `AuthenticatedRaiseLocus`
- `implementations/python/sugar-lift-py-tests/tests/test_exit_disposition_suppresses_coordinate.py:75` — `AuthenticatedRaiseLocus`
- `implementations/python/sugar-lift-py-tests/tests/test_exit_disposition_suppresses_coordinate.py:84` — `AuthenticatedRaiseLocus`
- `implementations/python/sugar-lift-py-tests/tests/test_exit_set.py:29` — `AuthenticatedRaiseLocus`
- `implementations/python/sugar-lift-py-tests/tests/test_exit_set.py:36` — `AuthenticatedRaiseLocus`
- `implementations/python/sugar-lift-py-tests/tests/test_exit_set.py:64` — `AuthenticatedRaiseLocus`
- `implementations/python/sugar-lift-py-tests/tests/test_exit_set.py:77` — `AuthenticatedRaiseLocus`
- `implementations/python/sugar-lift-py-tests/tests/test_exit_set.py:99` — `AuthenticatedRaiseLocus`
- `implementations/python/sugar-lift-py-tests/tests/test_exit_set.py:106` — `AuthenticatedRaiseLocus`
- `implementations/python/sugar-lift-py-tests/tests/test_exit_set.py:107` — `AuthenticatedRaiseLocus`
- `implementations/python/sugar-lift-py-tests/tests/test_exit_set.py:114` — `AuthenticatedRaiseLocus`
- `implementations/python/sugar-lift-py-tests/tests/test_exit_set.py:131` — `AuthenticatedRaiseLocus`
- `implementations/python/sugar-lift-py-tests/tests/test_exit_set.py:158` — `AuthenticatedRaiseLocus`
- `implementations/python/sugar-lift-py-tests/tests/test_exit_set.py:165` — `AuthenticatedRaiseLocus`
- `implementations/python/sugar-lift-py-tests/tests/test_exit_set.py:166` — `AuthenticatedRaiseLocus`
- `implementations/python/sugar-lift-py-tests/tests/test_exit_set.py:173` — `AuthenticatedRaiseLocus`
- `implementations/python/sugar-lift-py-tests/tests/test_exit_set.py:183` — `AuthenticatedRaiseLocus`
- `implementations/python/sugar-lift-py-tests/tests/test_exit_set.py:193` — `AuthenticatedRaiseLocus`
- `implementations/python/sugar-lift-py-tests/tests/test_exit_set.py:204` — `AuthenticatedRaiseLocus`
- `implementations/python/sugar-lift-py-tests/tests/test_exit_set.py:217` — `AuthenticatedRaiseLocus`
- `implementations/python/sugar-lift-py-tests/tests/test_exit_set.py:230` — `AuthenticatedRaiseLocus`
- `implementations/python/sugar-lift-py-tests/tests/test_exit_set_arm_census.py:49` — `AuthenticatedRaiseLocus`
- `implementations/python/sugar-lift-py-tests/tests/test_exit_set_normalize_identity.py:72` — `AuthenticatedRaiseLocus`
- `implementations/python/sugar-lift-py-tests/tests/test_factored_boundary_nested_exit_faces.py:150` — `AuthenticatedRaiseLocus`
- `implementations/python/sugar-lift-py-tests/tests/test_factored_boundary_source_resource_stack.py:259` — `AuthenticatedRaiseLocus`
- `implementations/python/sugar-lift-py-tests/tests/test_factored_boundary_try_finally.py:130` — `AuthenticatedRaiseLocus`
- `implementations/python/sugar-lift-py-tests/tests/test_fixture_supplied_resource_obligation.py:231` — `AuthenticatedRaiseLocus`
- `implementations/python/sugar-lift-py-tests/tests/test_generator_construction_v1.py:49` — `AuthenticatedRaiseLocus`
- `implementations/python/sugar-lift-py-tests/tests/test_generator_construction_v1.py:107` — `AuthenticatedRaiseLocus`
- `implementations/python/sugar-lift-py-tests/tests/test_generator_guard_context_binding.py:436` — `AuthenticatedRaiseLocus`
- `implementations/python/sugar-lift-py-tests/tests/test_generator_if_guard_outcome_sequencing.py:111` — `AuthenticatedRaiseLocus`
- `implementations/python/sugar-lift-py-tests/tests/test_generator_if_guard_outcome_sequencing.py:228` — `AuthenticatedRaiseLocus`
- `implementations/python/sugar-lift-py-tests/tests/test_generator_if_step.py:212` — `AuthenticatedRaiseLocus`
- `implementations/python/sugar-lift-py-tests/tests/test_generator_value_exitset_sequencing.py:324` — `AuthenticatedRaiseLocus`
- `implementations/python/sugar-lift-py-tests/tests/test_generator_value_exitset_sequencing.py:122` — `AuthenticatedRaiseLocus`
- `implementations/python/sugar-lift-py-tests/tests/test_generator_value_exitset_sequencing.py:135` — `AuthenticatedRaiseLocus`
- `implementations/python/sugar-lift-py-tests/tests/test_generator_value_exitset_sequencing.py:279` — `AuthenticatedRaiseLocus`
- `implementations/python/sugar-lift-py-tests/tests/test_generator_value_exitset_sequencing.py:286` — `AuthenticatedRaiseLocus`
- `implementations/python/sugar-lift-py-tests/tests/test_generator_value_exitset_sequencing.py:408` — `AuthenticatedRaiseLocus`
- `implementations/python/sugar-lift-py-tests/tests/test_grouped_raise_effect.py:23` — `AuthenticatedRaiseLocus`
- `implementations/python/sugar-lift-py-tests/tests/test_grouped_raise_effect.py:118` — `AuthenticatedRaiseLocus`
- `implementations/python/sugar-lift-py-tests/tests/test_loop_stop_iteration_coordinate.py:30` — `AuthenticatedRaiseLocus`
- `implementations/python/sugar-lift-py-tests/tests/test_loop_stop_iteration_coordinate.py:36` — `AuthenticatedRaiseLocus`
- `implementations/python/sugar-lift-py-tests/tests/test_loop_stop_iteration_coordinate.py:52` — `AuthenticatedRaiseLocus`
- `implementations/python/sugar-lift-py-tests/tests/test_match_guard_binding_rollback.py:284` — `AuthenticatedRaiseLocus`
- `implementations/python/sugar-lift-py-tests/tests/test_method_raise_transport.py:392` — `AuthenticatedRaiseLocus`
- `implementations/python/sugar-lift-py-tests/tests/test_native_operation_exit_carrier.py:709` — `AuthenticatedRaiseLocus`
- `implementations/python/sugar-lift-py-tests/tests/test_native_operation_prefix_carrier.py:92` — `AuthenticatedRaiseLocus`
- `implementations/python/sugar-lift-py-tests/tests/test_no_call_body_attribution.py:42` — `AuthenticatedRaiseLocus`
- `implementations/python/sugar-lift-py-tests/tests/test_no_call_body_attribution.py:48` — `AuthenticatedRaiseLocus`
- `implementations/python/sugar-lift-py-tests/tests/test_no_call_body_attribution.py:54` — `AuthenticatedRaiseLocus`
- `implementations/python/sugar-lift-py-tests/tests/test_partition_arm_growth.py:163` — `AuthenticatedRaiseLocus`
- `implementations/python/sugar-lift-py-tests/tests/test_partition_arm_growth.py:83` — `AuthenticatedRaiseLocus`
- `implementations/python/sugar-lift-py-tests/tests/test_partition_demand_conservation.py:83` — `AuthenticatedRaiseLocus`
- `implementations/python/sugar-lift-py-tests/tests/test_pending_contract_partition_arm.py:310` — `AuthenticatedRaiseLocus`
- `implementations/python/sugar-lift-py-tests/tests/test_pending_contract_partition_arm.py:524` — `AuthenticatedRaiseLocus`
- `implementations/python/sugar-lift-py-tests/tests/test_pending_contract_partition_arm.py:545` — `AuthenticatedRaiseLocus`
- `implementations/python/sugar-lift-py-tests/tests/test_pending_contract_partition_arm.py:84` — `AuthenticatedRaiseLocus`
- `implementations/python/sugar-lift-py-tests/tests/test_pending_contract_partition_arm.py:106` — `AuthenticatedRaiseLocus`
- `implementations/python/sugar-lift-py-tests/tests/test_pending_contract_partition_arm.py:184` — `AuthenticatedRaiseLocus`
- `implementations/python/sugar-lift-py-tests/tests/test_pending_contract_partition_arm.py:484` — `AuthenticatedRaiseLocus`
- `implementations/python/sugar-lift-py-tests/tests/test_pending_contract_partition_arm.py:504` — `AuthenticatedRaiseLocus`
- `implementations/python/sugar-lift-py-tests/tests/test_pending_contract_partition_arm.py:208` — `AuthenticatedRaiseLocus`
- `implementations/python/sugar-lift-py-tests/tests/test_pending_contract_partition_arm.py:437` — `AuthenticatedRaiseLocus`
- `implementations/python/sugar-lift-py-tests/tests/test_promote_terminal_raise_halts.py:18` — `AuthenticatedRaiseLocus`
- `implementations/python/sugar-lift-py-tests/tests/test_promote_terminal_raise_halts.py:39` — `AuthenticatedRaiseLocus`
- `implementations/python/sugar-lift-py-tests/tests/test_raise_from_try_composition.py:248` — `AuthenticatedRaiseLocus`
- `implementations/python/sugar-lift-py-tests/tests/test_raise_matcher_subject_is_a_value.py:74` — `AuthenticatedRaiseLocus`
- `implementations/python/sugar-lift-py-tests/tests/test_raise_matcher_subject_is_a_value.py:159` — `AuthenticatedRaiseLocus`
- `implementations/python/sugar-lift-py-tests/tests/test_raise_matcher_subject_is_a_value.py:174` — `AuthenticatedRaiseLocus`
- `implementations/python/sugar-lift-py-tests/tests/test_raise_matcher_subject_is_a_value.py:192` — `AuthenticatedRaiseLocus`
- `implementations/python/sugar-lift-py-tests/tests/test_raise_matcher_subject_is_a_value.py:212` — `AuthenticatedRaiseLocus`
- `implementations/python/sugar-lift-py-tests/tests/test_reduce_body_stateful_halt.py:10` — `AuthenticatedRaiseLocus`
- `implementations/python/sugar-lift-py-tests/tests/test_reduce_body_stateful_halt.py:26` — `AuthenticatedRaiseLocus`
- `implementations/python/sugar-lift-py-tests/tests/test_render_edge_exceptional_exit_citation.py:80` — `AuthenticatedRaiseLocus`
- `implementations/python/sugar-lift-py-tests/tests/test_render_edge_exceptional_exit_citation.py:95` — `AuthenticatedRaiseLocus`
- `implementations/python/sugar-lift-py-tests/tests/test_render_edge_exceptional_exit_citation.py:305` — `AuthenticatedRaiseLocus`
- `implementations/python/sugar-lift-py-tests/tests/test_render_edge_exceptional_exit_citation.py:327` — `AuthenticatedRaiseLocus`
- `implementations/python/sugar-lift-py-tests/tests/test_render_edge_exceptional_exit_citation.py:340` — `AuthenticatedRaiseLocus`
- `implementations/python/sugar-lift-py-tests/tests/test_render_edge_exceptional_exit_citation.py:353` — `AuthenticatedRaiseLocus`
- `implementations/python/sugar-lift-py-tests/tests/test_render_edge_exceptional_exit_citation.py:371` — `AuthenticatedRaiseLocus`
- `implementations/python/sugar-lift-py-tests/tests/test_render_edge_exceptional_exit_citation.py:388` — `AuthenticatedRaiseLocus`
- `implementations/python/sugar-lift-py-tests/tests/test_render_edge_exceptional_exit_citation.py:397` — `AuthenticatedRaiseLocus`
- `implementations/python/sugar-lift-py-tests/tests/test_render_edge_exceptional_exit_citation.py:321` — `AuthenticatedRaiseLocus`
- `implementations/python/sugar-lift-py-tests/tests/test_slice_subscript_store_formal_caller.py:163` — `AuthenticatedRaiseLocus`
- `implementations/python/sugar-lift-py-tests/tests/test_source_constructed_exit_truthiness.py:9` — `AuthenticatedRaiseLocus`
- `implementations/python/sugar-lift-py-tests/tests/test_source_constructed_exit_truthiness.py:25` — `AuthenticatedRaiseLocus`
- `implementations/python/sugar-lift-py-tests/tests/test_source_raise_transport.py:399` — `AuthenticatedRaiseLocus`
- `implementations/python/sugar-lift-py-tests/tests/test_source_return_operation_generalization.py:135` — `AuthenticatedRaiseLocus`
- `implementations/python/sugar-lift-py-tests/tests/test_source_return_operation_generalization.py:138` — `AuthenticatedRaiseLocus`
- `implementations/python/sugar-lift-py-tests/tests/test_source_return_operation_generalization.py:140` — `AuthenticatedRaiseLocus`
- `implementations/python/sugar-lift-py-tests/tests/test_spread_exit_factoring.py:72` — `AuthenticatedRaiseLocus`
- `implementations/python/sugar-lift-py-tests/tests/test_state_survival_matrix.py:354` — `AuthenticatedRaiseLocus`
- `implementations/python/sugar-lift-py-tests/tests/test_subscript_refusal_preservation.py:68` — `AuthenticatedRaiseLocus`
- `implementations/python/sugar-lift-py-tests/tests/test_subscript_refusal_preservation.py:92` — `AuthenticatedRaiseLocus`
- `implementations/python/sugar-lift-py-tests/tests/test_subscript_store_desugar.py:187` — `AuthenticatedRaiseLocus`
- `implementations/python/sugar-lift-py-tests/tests/test_subscript_store_desugar.py:221` — `AuthenticatedRaiseLocus`
- `implementations/python/sugar-lift-py-tests/tests/test_trystar_subgroup_routing.py:573` — `AuthenticatedRaiseLocus`
- `implementations/python/sugar-lift-py-tests/tests/test_trystar_subgroup_routing.py:574` — `AuthenticatedRaiseLocus`
- `implementations/python/sugar-lift-py-tests/tests/test_trystar_subgroup_routing.py:798` — `AuthenticatedRaiseLocus`
- `implementations/python/sugar-lift-py-tests/tests/test_trystar_subgroup_routing.py:893` — `AuthenticatedRaiseLocus`
- `implementations/python/sugar-lift-py-tests/tests/test_trystar_subgroup_routing.py:621` — `AuthenticatedRaiseLocus`
- `implementations/python/sugar-lift-py-tests/tests/test_trystar_subgroup_routing.py:618` — `AuthenticatedRaiseLocus`
- `implementations/python/sugar-lift-py-tests/tests/test_trystar_subgroup_routing.py:831` — `AuthenticatedRaiseLocus`
- `implementations/python/sugar-lift-py-tests/tests/test_trystar_subgroup_routing.py:915` — `AuthenticatedRaiseLocus`
- `implementations/python/sugar-lift-py-tests/tests/test_trystar_subgroup_routing.py:920` — `AuthenticatedRaiseLocus`
- `implementations/python/sugar-lift-py-tests/tests/test_with_effect_boundary_warning.py:270` — `AuthenticatedRaiseLocus`
- `implementations/python/sugar-lift-py-tests/tests/test_with_effect_boundary_warning.py:447` — `AuthenticatedRaiseLocus`
- `implementations/python/sugar-lift-py-tests/tests/test_with_resource_sugar.py:194` — `AuthenticatedRaiseLocus`
- `implementations/python/sugar-lift-py-tests/tests/test_with_resource_sugar.py:218` — `AuthenticatedRaiseLocus`
- `implementations/python/sugar-lift-py-tests/tests/test_with_resource_sugar.py:303` — `AuthenticatedRaiseLocus`
- `implementations/python/sugar-lift-py-tests/tests/test_with_resource_sugar.py:339` — `AuthenticatedRaiseLocus`
- `implementations/python/sugar-lift-py-tests/tests/test_with_resource_sugar.py:366` — `AuthenticatedRaiseLocus`
- `implementations/python/sugar-lift-py-tests/tests/test_with_resource_sugar.py:383` — `AuthenticatedRaiseLocus`
- `implementations/python/sugar-lift-py-tests/tests/test_with_resource_sugar.py:394` — `AuthenticatedRaiseLocus`
- `implementations/python/sugar-lift-py-tests/tests/test_with_resource_sugar.py:413` — `AuthenticatedRaiseLocus`
- `implementations/python/sugar-lift-py-tests/tests/test_with_resource_sugar.py:685` — `AuthenticatedRaiseLocus`
- `implementations/python/sugar-lift-py-tests/tests/test_with_resource_sugar.py:662` — `AuthenticatedRaiseLocus`
- `implementations/python/sugar-lift-py-tests/tests/test_with_resource_sugar.py:292` — `AuthenticatedRaiseLocus`
- `implementations/python/sugar-lift-py-tests/tests/test_with_resource_sugar.py:634` — `AuthenticatedRaiseLocus`
- `implementations/python/sugar-lift-py-tests/tests/test_with_resource_sugar.py:96` — `AuthenticatedRaiseLocus`
- `implementations/python/sugar-lift-py-tests/tests/test_with_source_resource_sugar.py:170` — `AuthenticatedRaiseLocus`
- `implementations/python/sugar-lift-py-tests/tests/test_with_source_resource_sugar.py:183` — `AuthenticatedRaiseLocus`
- `implementations/python/sugar-lift-py-tests/tests/test_with_source_resource_sugar.py:197` — `AuthenticatedRaiseLocus`
- `implementations/python/sugar-lift-py-tests/tests/test_with_source_resource_sugar.py:248` — `AuthenticatedRaiseLocus`
- `implementations/python/sugar-lift-py-tests/tests/test_with_source_resource_sugar.py:147` — `AuthenticatedRaiseLocus`
- `implementations/python/sugar-lift-python-source/src/sugar_lift_python_source/manager_protocol_construction.py:663` — `AuthenticatedRaiseLocus`
- `implementations/python/sugar-lift-python-source/tests/test_generator_lifecycle_performance.py:134` — `AuthenticatedRaiseLocus`
- `implementations/python/sugar-lift-python-source/tests/test_generator_manager_renamed_lifecycle.py:268` — `AuthenticatedRaiseLocus`
- `implementations/python/sugar-lift-python-source/tests/test_generator_nested_managers.py:184` — `AuthenticatedRaiseLocus`
- `implementations/python/sugar-lift-python-source/tests/test_match_argument_shapes.py:743` — `AuthenticatedRaiseLocus`
- `implementations/python/sugar-lift-python-source/tests/test_metaclass_block_publication.py:65` — `AuthenticatedRaiseLocus`
- `implementations/python/sugar-lift-python-source/tests/test_metaclass_block_publication.py:91` — `AuthenticatedRaiseLocus`
- `implementations/python/sugar-lift-python-source/tests/test_returned_resource_with_construction.py:889` — `AuthenticatedRaiseLocus`
- `implementations/python/sugar-lift-python-source/tests/test_returned_resource_with_construction.py:924` — `AuthenticatedRaiseLocus`
- `implementations/python/sugar-lift-python-source/tests/test_sole_path_manager_construction.py:1915` — `AuthenticatedRaiseLocus`
- `implementations/python/sugar-lift-python-source/tests/test_source_resource_nested_exit_faces.py:146` — `AuthenticatedRaiseLocus`
- `implementations/python/sugar-lift-python-source/tests/test_source_resource_nested_exit_faces.py:294` — `AuthenticatedRaiseLocus`
- `implementations/python/sugar-lift-python-source/tests/test_source_resource_nested_exit_faces.py:324` — `AuthenticatedRaiseLocus`
- `implementations/python/sugar-lift-python-source/tests/test_source_resource_nested_exit_faces.py:325` — `AuthenticatedRaiseLocus`
- `implementations/python/sugar-source-tree/tests/test_nested_assertion_manager_composition.py:440` — `AuthenticatedRaiseLocus`
- `implementations/python/sugar-source-tree/tests/test_nested_assertion_manager_composition.py:590` — `AuthenticatedRaiseLocus`
- `implementations/python/sugar-source-tree/tests/test_parameter_contract_demand_set.py:275` — `AuthenticatedRaiseLocus`
- `implementations/python/sugar-source-tree/tests/test_parameter_contract_demand_set.py:385` — `AuthenticatedRaiseLocus`
- `implementations/python/sugar-source-tree/tests/test_parameter_contract_demand_set.py:441` — `AuthenticatedRaiseLocus`
- `implementations/python/sugar-source-tree/tests/test_parameter_contract_demand_set.py:476` — `AuthenticatedRaiseLocus`
- `implementations/python/sugar-source-tree/tests/test_parameter_contract_demand_set.py:358` — `AuthenticatedRaiseLocus`
- `implementations/python/sugar-source-tree/tests/test_store_target_effect.py:205` — `AuthenticatedRaiseLocus`
- `implementations/python/sugar-source-tree/tests/test_with_multiple_managers.py:365` — `AuthenticatedRaiseLocus`
- `implementations/python/sugar-source-tree/tests/test_with_multiple_managers.py:421` — `AuthenticatedRaiseLocus`
- `implementations/python/sugar-source-tree/tests/test_with_multiple_managers.py:435` — `AuthenticatedRaiseLocus`
- `implementations/python/sugar-source-tree/tests/test_with_multiple_managers.py:383` — `AuthenticatedRaiseLocus`
- `implementations/python/sugar-source-tree/tests/test_with_partition_shared_algebra.py:737` — `AuthenticatedRaiseLocus`

## Raw current survivor coordinates

- `implementations/python/sugar-lift-py-tests/tests/test_assertion_boundary_exitset_consumer.py:64` — line introducer `8a3ceb2c09699d48f666d66552cb3a83ea9a85f9`
- `implementations/python/sugar-lift-py-tests/tests/test_bool_op_operand_sequence.py:221` — line introducer `1eeb80bb3af8e318486412a670909e6ab29623ca`
- `implementations/python/sugar-lift-py-tests/tests/test_effect_boundary_observation_conserves_demands.py:101` — line introducer `8a3ceb2c09699d48f666d66552cb3a83ea9a85f9`
- `implementations/python/sugar-lift-py-tests/tests/test_exit_disposition_exit_suppression_contract.py:31` — line introducer `8a3ceb2c09699d48f666d66552cb3a83ea9a85f9`
- `implementations/python/sugar-lift-py-tests/tests/test_exit_disposition_suppresses_coordinate.py:31` — line introducer `8a3ceb2c09699d48f666d66552cb3a83ea9a85f9`
- `implementations/python/sugar-lift-py-tests/tests/test_exit_disposition_suppresses_coordinate.py:75` — line introducer `8a3ceb2c09699d48f666d66552cb3a83ea9a85f9`
- `implementations/python/sugar-lift-py-tests/tests/test_factored_boundary_nested_exit_faces.py:150` — line introducer `8a3ceb2c09699d48f666d66552cb3a83ea9a85f9`
- `implementations/python/sugar-lift-py-tests/tests/test_factored_boundary_source_resource_stack.py:259` — line introducer `8a3ceb2c09699d48f666d66552cb3a83ea9a85f9`
- `implementations/python/sugar-lift-py-tests/tests/test_factored_boundary_try_finally.py:130` — line introducer `8a3ceb2c09699d48f666d66552cb3a83ea9a85f9`
- `implementations/python/sugar-lift-py-tests/tests/test_grouped_raise_effect.py:23` — line introducer `8a3ceb2c09699d48f666d66552cb3a83ea9a85f9`
- `implementations/python/sugar-lift-py-tests/tests/test_grouped_raise_effect.py:118` — line introducer `8a3ceb2c09699d48f666d66552cb3a83ea9a85f9`
- `implementations/python/sugar-lift-py-tests/tests/test_no_call_body_attribution.py:42` — line introducer `8a3ceb2c09699d48f666d66552cb3a83ea9a85f9`
- `implementations/python/sugar-lift-py-tests/tests/test_no_call_body_attribution.py:54` — line introducer `8a3ceb2c09699d48f666d66552cb3a83ea9a85f9`
- `implementations/python/sugar-lift-py-tests/tests/test_render_edge_exceptional_exit_citation.py:94` — line introducer `8a3ceb2c09699d48f666d66552cb3a83ea9a85f9`
- `implementations/python/sugar-lift-py-tests/tests/test_render_edge_exceptional_exit_citation.py:387` — line introducer `bf847eb9363fd050b326ffd16543275b231d783e`
- `implementations/python/sugar-lift-py-tests/tests/test_subscript_store_desugar.py:187` — line introducer `8a3ceb2c09699d48f666d66552cb3a83ea9a85f9`
- `implementations/python/sugar-lift-py-tests/tests/test_subscript_store_desugar.py:221` — line introducer `8a3ceb2c09699d48f666d66552cb3a83ea9a85f9`
- `implementations/python/sugar-lift-py-tests/tests/test_with_resource_sugar.py:96` — line introducer `8a3ceb2c09699d48f666d66552cb3a83ea9a85f9`
- `implementations/python/sugar-source-tree/tests/test_nested_assertion_manager_composition.py:440` — line introducer `8a3ceb2c09699d48f666d66552cb3a83ea9a85f9`
- `implementations/python/sugar-source-tree/tests/test_nested_assertion_manager_composition.py:590` — line introducer `8a3ceb2c09699d48f666d66552cb3a83ea9a85f9`
