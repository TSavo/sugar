# Narrow Authenticated With Arm Design

## Scope

Implement issue #6071 step 4 on top of prerequisites 1 and 2. Admit only a synchronous `With` containing one manager item whose exact manager-expression source coordinate resolves to an authenticated `ContextManagerContractRefV1` with total `Value` enter testimony and typed `NeverSuppressesDispositionV1`. Preserve the existing independently authenticated membrane arms without allowing them to satisfy or broaden this bridge-backed arm.

## Construction boundary

`With._construct_sugar` reads only `SourceUnit.construction_context.contract_refs`. It converts the manager expression's existing source CID and line/column span into `SourceFragmentCoordinateV1`, requires the corresponding immutable resolution row, and validates the complete admission predicate before constructing any manager, enter, exit, or body Sugar child. It never calls the linker, opens source, matches manager/vendor spelling, or decodes member metadata.

A missing resolution-table row after demand enrollment raises `BackendDefect`. A typed `ContextManagerResolutionGapV1` remains a structured loud With gap carrying its original kind and coordinates. Unsupported syntax or authenticated semantics produces a closed typed With gap: multiple items, async manager, unsupported binding target, or unsupported context-manager semantics. No case silently falls through or upgrades testimony.

## Binding and product

For an optional simple `as Name`, substitution reads the same frozen typed resolution row and rewrites body uses to `ObservationRef(<manager-slot>#enter_result, ENTER_RESULT)`. This coordinate is authenticated only on completed enter faces by `EnterResultBinding`; no value is fabricated.

The admitted node constructs one `WithResourceSugar` with:

- the original manager occurrence exactly once;
- a stable `ManagerRef`-based enter call;
- one parametric exit call using the stable exit-face coordinate;
- already-constructed body Sugars;
- the exact typed `NeverSuppressesDispositionV1` carried by the ref;
- the immutable `ContextManagerContractRefV1` itself.

The Sugar exposes authenticated edge testimony derived only from `catalog_cid`, `member_cid`, `payload_cid`, `demand_cid`, and `resolution_cid`. It does not reconstruct an edge from a source spelling.

## ExitSet semantics

`WithResourceSugar.desugar` retains the existing manager-once, enter, body, and parametric-exit composition. Manager and enter halts propagate. Exit runs for every body face. Exit failure supersedes the body face. A completed exit preserves a completed body's state, and typed NeverSuppresses restores a halted body's original effect. Conditional body exits retain both guarded faces, and no suppression-created `Completed(None)` face is emitted.

## Executable discrimination

Tests establish:

1. an authenticated resolved manager constructs `WithResourceSugar`, evaluates the manager once, binds the actual enter-result slot, and carries the exact ref CIDs;
2. a body raise remains halted after completed exit, including complementary completed conditional faces and tail sequencing only on completion;
3. authenticated Suppresses or unsupported semantics stays a typed loud gap;
4. an unresolved row stays the same typed loud gap with no linker, source-oracle, or decoder access;
5. async and multi-item forms stay typed loud and emit no synchronous resource edge;
6. planted linker/source/decoder calls below construction fail the boundary floor, while positive construction succeeds with those doors patched to raise;
7. `R_no_sugar_in_desugar` remains zero.

Rust verification, if required by the final edge checker, runs only on battleaxe through `bin/sugarbin`. The branch remains stacked and is not finalized until prerequisites 1 and 2 merge.
