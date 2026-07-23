# Object Subscript Fields Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add authenticated `obj[key]` field places to the existing occurrence-keyed immutable object field map.

**Architecture:** Add an authenticated subscript key/field coordinate and version variant, then route Subscript store/read through `ObjectPlaceStateV1._with_store` and `field`. Preserve the single temporal binding map, attribute vocabulary, and every loud boundary.

**Tech Stack:** Python 3.12, frozen dataclasses, JCS/BLAKE3 CIDs, Sugar typed source tree, pytest.

## Global Constraints

- Object identity is the construction occurrence only.
- Subscript state lives only in `ObjectPlaceStateV1`'s existing versioned field map.
- No generic field-schema rewrite and no class/name/vendor gate.
- Opaque, symbolic, unhashable, custom-dispatch, and out-of-range cases remain typed-loud.
- One temporal binding model, immutable prior-linked versions, selective invalidation, no panic catch, no timeout increase.

---

### Task 1: Red coordinate and acceptance twins

**Files:**
- Modify: `implementations/python/sugar-source-tree/tests/test_object_identity_v1.py`
- Modify: `implementations/python/sugar-lift-py-tests/tests/test_object_field_flow_acceptance.py`
- Create: `implementations/python/sugar-lift-py-tests/tests/fixtures/object_field_flow/subscript_flow.py`

**Interfaces:**
- Produces: failing expectations for `SubscriptKeyCoordinateV1`, `SubscriptFieldCoordinateV1`, `SubscriptFieldVersionV1`, and supported `obj[key]` flow.

- [ ] Add truthful/lying twins for key separation, aliases, version chains, forgery, and loud residuals.
- [ ] Run the exact new tests and verify failures are caused by missing subscript coordinate/projection support.
- [ ] Commit the red acceptance twins.

### Task 2: Authenticated key and field coordinates

**Files:**
- Modify: `implementations/python/sugar-source-tree/src/sugar_source_tree/object_identity.py`
- Test: `implementations/python/sugar-source-tree/tests/test_object_identity_v1.py`

**Interfaces:**
- Produces: `SubscriptKeyCoordinateV1.mint/decode`, `SubscriptFieldCoordinateV1.mint/decode`, and `SubscriptFieldVersionV1.mint/decode`.

- [ ] Mint key coordinates only from decoded constructed-value testimony plus the constructed key term CID.
- [ ] Bind field/version CIDs to the owner object coordinate, key coordinate, store occurrence, generation, value testimony, and prior version.
- [ ] Reject stale owner, key testimony, key term, and prior-version CIDs.
- [ ] Run coordinate twins green and commit.

### Task 3: Same-map subscript store and read

**Files:**
- Modify: `implementations/python/sugar-source-tree/src/sugar_source_tree/nodes.py`
- Modify: `implementations/python/sugar-lift-py-tests/src/sugar_lift_py_tests/sugar/place_assign_sugar.py`
- Modify: `implementations/python/sugar-lift-py-tests/src/sugar_lift_py_tests/floor/place_assign_value.py`
- Test: `implementations/python/sugar-lift-py-tests/tests/test_object_field_flow_acceptance.py`

**Interfaces:**
- Consumes: subscript coordinate/version types from Task 2.
- Produces: `ObjectPlaceStateV1.with_subscript_store` and `subscript_field`, using existing selector/value/version arrays.

- [ ] Construct key testimony once and admit only supported immutable/hashable key Floor values.
- [ ] Route single Subscript assignment through `_with_store` and update every alias sharing the object coordinate.
- [ ] Project Subscript reads by rebuilding the authenticated key coordinate; preserve branch joins and selective invalidation.
- [ ] Extend place lowering with the closed `subscript` selector kind; unknown kinds stay loud.
- [ ] Run acceptance twins green and commit.

### Task 4: Loud-boundary and battleaxe verification

**Files:**
- Modify only tests if a missing discrimination twin is found.

**Interfaces:**
- Produces: final zero-side-door and focused receipts.

- [ ] Run symbolic/opaque/unhashable/custom-dispatch/out-of-range twins and verify typed loudness.
- [ ] Run construction side-door and panic-catch laws; require both `R=0` and no auditor errors.
- [ ] Run the focused object identity, binding, Assign, Call, attribute, and subscript suite on battleaxe.
- [ ] Rebase on current `origin/main`, rerun focused verification, force-push with lease, and open a ready unmerged PR.
