# Retirement partition for #6964's 93 PRESENCE-ONLY sites

Source: `git show ff9732e29` removed asserts (pre-repair presence teeth).
Parsed **93** sites. Instrument residual after #6964: R_presence=0, R_synth=1.

## Counts

| Bucket | N | Meaning |
|---|---:|---|
| **(a)** mr_brown constructor kills | **23** | `exception_type_coordinate` presence — unconstructible once `RaiseEffect` requires `Term` |
| **(b)** missing object, not yet built | **70** | occurrence/MRO nouns |
| **(c)** open domain membrane | **0** | permanent auditor |
| **Total** | **93** | |

## (a) mr_brown — delete with the climb, do not re-repair

**Object (building now):** `RaiseEffect(exception_type_coordinate: Term)` + `UndeterminedRaiseEffect` + `RaiseEffect.for_builtin` one door. Refuses `None` at construction.

**Shell deleted when climb lands:** any tooth that only proved coordinate *presence*. #6964 already replaced these with `== _identity(...)` value pins — those value pins still pin *which* type and should stay until Eq on sealed faces is the only comparison path. What brown kills is the *need for a presence-only axis* on this field, and any residual `is not None` on coordinate.

**Sites (23):**
- `implementations/python/sugar-lift-py-tests/tests/test_binop_method_caller.py` — `halted.effect.exception_type_coordinate`
- `implementations/python/sugar-lift-py-tests/tests/test_bool_op_operand_sequence.py` — `exits.exits[0].effect.exception_type_coordinate`
- `implementations/python/sugar-lift-py-tests/tests/test_compare_if_method_caller.py` — `halted.effect.exception_type_coordinate`
- `implementations/python/sugar-lift-py-tests/tests/test_contains_method_caller.py` — `halted.effect.exception_type_coordinate`
- `implementations/python/sugar-lift-py-tests/tests/test_function_formal_native_operation_binding.py` — `halted.effect.exception_type_coordinate`
- `implementations/python/sugar-lift-py-tests/tests/test_mutable_global_value.py` — `halted.effect.exception_type_coordinate`
- `implementations/python/sugar-lift-py-tests/tests/test_pandas_subscript_caller_gap.py` — `halted.effect.exception_type_coordinate`
- `implementations/python/sugar-lift-py-tests/tests/test_setattr_method_caller.py` — `halted.effect.exception_type_coordinate`
- `implementations/python/sugar-lift-py-tests/tests/test_setattr_named_formal_caller.py` — `halted.effect.exception_type_coordinate`
- `implementations/python/sugar-lift-py-tests/tests/test_setattr_named_formal_caller.py` — `halted.effect.exception_type_coordinate`
- `implementations/python/sugar-lift-py-tests/tests/test_setattr_named_formal_caller.py` — `halted.effect.exception_type_coordinate`
- `implementations/python/sugar-lift-py-tests/tests/test_setattr_named_formal_caller.py` — `halted.effect.exception_type_coordinate`
- `implementations/python/sugar-lift-py-tests/tests/test_setitem_formal_caller.py` — `halted.effect.exception_type_coordinate`
- `implementations/python/sugar-lift-py-tests/tests/test_setitem_method_caller.py` — `halted.effect.exception_type_coordinate`
- `implementations/python/sugar-lift-py-tests/tests/test_unary_not_bool_law.py` — `face.effect.exception_type_coordinate`
- `implementations/python/sugar-lift-py-tests/tests/test_unary_not_bool_law.py` — `face.value.effect.exception_type_coordinate`
- `implementations/python/sugar-lift-py-tests/tests/test_unpack_sequencing_law.py` — `effect.exception_type_coordinate`
- `implementations/python/sugar-source-tree/tests/test_attribute_property_exit_construction.py` — `effect.exception_type_coordinate`
- `implementations/python/sugar-source-tree/tests/test_attribute_property_exit_construction.py` — `effect.exception_type_coordinate`
- `implementations/python/sugar-source-tree/tests/test_attribute_property_exit_construction.py` — `halted.effect.exception_type_coordinate`
- `implementations/python/sugar-source-tree/tests/test_try_exitset_law.py` — `out.effect.exception_type_coordinate`
- `implementations/python/sugar-source-tree/tests/test_try_sugar.py` — `out.effect.exception_type_coordinate`
- `implementations/python/sugar-source-tree/tests/test_try_sugar.py` — `out.effect.exception_type_coordinate`

## (b) Missing nouns — name the object, rung type/door

### RaiseEffect.occurrence required (AuthenticatedRaiseLocus); one door at ground_raise_effect / for_builtin — 61 sites

| Rung | Object |
|---|---|
| **type** | non-optional `occurrence: str` (or `AuthenticatedRaiseLocus`) on authenticated RaiseEffect |
| **one door** | `ground_raise_effect` / `for_builtin` always mint locus from site; no third path |
| **panic** | unfinished producer that cannot name locus throws — never `None` |

- `implementations/python/sugar-lift-py-tests/tests/test_attribute_native_operation_demand.py` — `halted.exits[0].effect.occurrence_id`
- `implementations/python/sugar-lift-py-tests/tests/test_attribute_store_desugar.py` — `halt.effect.occurrence_id`
- `implementations/python/sugar-lift-py-tests/tests/test_binop_method_caller.py` — `halted.effect.occurrence_id`
- `implementations/python/sugar-lift-py-tests/tests/test_binop_method_caller.py` — `halted.effect.occurrence_id`
- `implementations/python/sugar-lift-py-tests/tests/test_boolop_middle_leg_control.py` — `halted[0].effect.occurrence_id`
- `implementations/python/sugar-lift-py-tests/tests/test_boolop_middle_leg_control.py` — `outcome.value.effect.occurrence_id`
- `implementations/python/sugar-lift-py-tests/tests/test_boolop_mixed_compare_families.py` — `halted[0].effect.occurrence_id`
- `implementations/python/sugar-lift-py-tests/tests/test_boolop_mixed_compare_families.py` — `outcome.value.effect.occurrence_id`
- … +53 more

### Grouped-leaf RaiseEffect with required occurrence at ExceptionGroup construction — 5 sites

| Rung | Object |
|---|---|
| **type** | non-optional `occurrence: str` (or `AuthenticatedRaiseLocus`) on authenticated RaiseEffect |
| **one door** | `ground_raise_effect` / `for_builtin` always mint locus from site; no third path |
| **panic** | unfinished producer that cannot name locus throws — never `None` |

- `implementations/python/sugar-lift-py-tests/tests/test_exception_group_nesting.py` — `leaf.occurrence`
- `implementations/python/sugar-lift-py-tests/tests/test_exception_group_nesting.py` — `leaf.occurrence`
- `implementations/python/sugar-lift-py-tests/tests/test_trystar_subgroup_routing.py` — `type_errors[0].occurrence`
- `implementations/python/sugar-lift-py-tests/tests/test_trystar_subgroup_routing.py` — `value_errors[0].occurrence`
- `implementations/python/sugar-lift-py-tests/tests/test_trystar_subgroup_routing.py` — `value_errors[1].occurrence`

### Chained context/cause RaiseEffect with required occurrence at chain mint — 3 sites

| Rung | Object |
|---|---|
| **type** | non-optional `occurrence: str` (or `AuthenticatedRaiseLocus`) on authenticated RaiseEffect |
| **one door** | `ground_raise_effect` / `for_builtin` always mint locus from site; no third path |
| **panic** | unfinished producer that cannot name locus throws — never `None` |

- `implementations/python/sugar-lift-py-tests/tests/test_except_as_target_cleanup.py` — `effect.context_effect.occurrence`
- `implementations/python/sugar-lift-py-tests/tests/test_exception_context_reraise.py` — `effect.context_effect.occurrence`
- `implementations/python/sugar-lift-py-tests/tests/test_raise_from_try_composition.py` — `effect.cause_value.effect.occurrence`

### Required MRO on RaiseEffect (extend brown: non-optional mro when builtin/ground) — 1 sites

| Rung | Object |
|---|---|
| **type** | non-optional `occurrence: str` (or `AuthenticatedRaiseLocus`) on authenticated RaiseEffect |
| **one door** | `ground_raise_effect` / `for_builtin` always mint locus from site; no third path |
| **panic** | unfinished producer that cannot name locus throws — never `None` |

- `implementations/python/sugar-lift-py-tests/tests/test_mutable_global_value.py` — `halted.effect.exception_type_mro`

## (c) Open domain — permanent membrane

**None of the 93.** Kit exceptional exits are closed: if they go through SourceFile/ground mint, type identity and locus are available. Python's open *except matching* surface is a different axis (matcher completeness / non-exhaustive vendor types for *matching*), not 'RaiseEffect may omit identity'. Foreign non-builtin exception *types* still need an authenticated coordinate mint — that is unfinished producer (throw or UndeterminedRaiseEffect), not an open-domain auditor forever.

## SYNTHESIZED residual (not in the 93)

R=1 at `tests/law_of_one_auditor.py` ~518 — self-seed of `projection_calls`. Owned by **mr_white** (lane title: Law of One Auditor Self-Seeding Fix). Do not touch without confirm.
**Missing object:** evidence sets sealed to production graph only; empty observed callers is Incomplete, not filled.

## What #6964 did vs what still climbs

| Layer | Status |
|---|---|
| Presence-only form | Drained by #6964 (R_presence 93→0) |
| Coordinate constructibility | mr_brown: required Term on RaiseEffect |
| Occurrence constructibility | not built — (b) |
| Value pins which-exception | still needed after brown until Eq-only sealed faces |
