# Receipt-seating reachability: construct managers whose bodies touch unresolved message-only value-uses

**Goal.** Make a context manager construct when an unresolved import value-use in
its `__enter__`/`__exit__`/`matches` body is only reached on a
failure-**message** path, never on the suppress/raise **decision** path. The
motivating family is `pytest.raises` (5,815 sites): constructing `RaisesExc`
force-floors `_check_match`, whose mismatch branch reads the runtime-mutated
global `_config.get_verbosity` — a genuinely unresolvable value that today
voids the whole manager.

## The invariant we must NOT break

`sugar-lift-python-source/tests/test_census_instrument_holes_are_terminals.py`
pins census honesty:

1. An unresolved import value-use must never "ride as authenticated" (must not
   be seated as a resolved value).
2. When construction actually **reaches** an unresolved value-use, it must be a
   **countable** `construction-panic` row (a `SugarNotWritten`/
   `ImportValueUseResolutionGap`), never a silent swallow and never an
   instrument-failure hole (which marks a shard `measured=False`).

Both must still hold after this change. Only their **locus** moves: from eager
whole-frame seat-time to lazy consume-time.

## Why the cheap "just don't refuse" fix is wrong

`_seat_import_value_use_receipts` (manager_construction.py:3548) walks the
ENTIRE frame span and hard-raises `ImportValueUseResolutionGap`
(manager_construction.py:3871) on any unresolved target — before
`construct_manager_behavior` (manager_construction.py:1929) force-floors the
reached exit path. Turning that raise into a bare `continue` (leave unseated)
is forbidden by the guard tooth
`test_unresolved_import_value_use_is_still_refused_never_seated`, which reads
the function source and requires the raise to be present. The guard is right:
a bare continue drops the countable terminal even for a value-use the contract
DOES reach.

## Design: defer the refusal to consume-time via a typed marker

The force-floor already reaches value-uses lazily. There are exactly two
consumers of `unit.import_value_use_resolution(span)`:

- `sugar-lift-py-tests/.../sugar/attribute_sugar.py:104`
- `sugar-source-tree/.../nodes.py:12711` (`Attribute._construct_sugar`)

Both special-case `AuthenticatedImportUseV1` and otherwise fall through to
ordinary floor law.

Change:

1. **New marker** `UnresolvedImportValueUseV1` (frozen) in
   `sugar-source-tree/.../panic.py` or a small floor module, carrying the
   fields the current raise reports: `resolution_kind`, `target_symbol`,
   `dependency_module`, and the use `coordinate`. It is neither a resolved
   object nor an authenticated receipt, so it can never "ride as authenticated".

2. **Eager seater** (manager_construction.py:3871): instead of `raise`, seat
   the marker at the span (`seat_import_value_use_resolution(span_key, marker,
   ...)`) and `continue`. The manager is no longer pre-voided. Preserve every
   existing tolerated arm (dynamic-export, static-export-absent, reexport-cycle,
   ambiguous-static-export) exactly as-is.

3. **Both consumers**: when `import_value_use_resolution(span)` returns an
   `UnresolvedImportValueUseV1`, raise the SAME
   `ImportValueUseResolutionGap` there — same wording (resolution-kind, target,
   module) — so a reached unresolved value-use is the identical countable
   construction-panic row it is today, just minted at the coordinate the
   force-floor actually reached.

Net effect: reached → identical countable panic (invariant 2 preserved);
unreached (message-only) → never consumed → manager constructs. Nothing
unresolved is ever seated as resolved (invariant 1 preserved).

## Guard-test migration (same invariant, new locus)

`test_census_instrument_holes_are_terminals.py`:

- `test_unresolved_import_value_use_seat_measures_to_a_countable_terminal`
  (`io/json/_json.py`): still asserts `terminalKind in {constructed,
  construction-panic}` — passes whether _json.py's use is reached
  (construction-panic) or not (constructed). Keep as-is; it is the end-to-end
  witness.
- `test_unresolved_import_value_use_never_names_the_untyped_seating_gap`:
  asserts the message is not an INSTRUMENT-FAILURE hole. Still holds (a reached
  gap is a construction-panic, not instrument-failure). Keep.
- `test_unresolved_import_value_use_is_still_refused_never_seated`
  (inspect.getsource of the eager seater): REWRITE to pin the new contract —
  the eager seater seats `UnresolvedImportValueUseV1` and does NOT seat the
  receipt/resolved value for a real gap; the consumers raise
  `ImportValueUseResolutionGap`. The invariant (unresolved never authenticated;
  reached-unresolved is countable) is unchanged; only where the raise lives.
- `test_import_value_use_resolution_gap_is_a_countable_census_row` (the class
  is a SugarNotWritten): keep — the class is unchanged.

## Twins (new)

- **Truthful (message-only → constructs):** a class CM whose `__exit__` reads an
  unresolvable dotted value ONLY to build a non-returned message attribute; the
  suppress/raise decision uses only resolved values → manager constructs.
- **Lying (decision-path → countable panic):** a class CM whose `__exit__`
  suppress/raise decision itself depends on the unresolvable value → still a
  countable `ImportValueUseResolutionGap` at consume-time.

## Phases

- **Phase 1:** marker + eager-seater defer + both consumers raise + guard
  migration + twins. Baseline the census-terminals + manager-construction
  neighborhoods vs clean HEAD. Merge behind CI.
- **Phase 2:** pytest-enrolled tip board. Two outcomes:
  - pytest.raises constructs → the force-floor did not reach get_verbosity;
    ship, measure the corpus yield.
  - still voids at consume → the behavior force-floor DOES explore the message
    branch on symbolic input; escalate to an explicit return/effect
    reachability slice of `_check_match` (guard the message branch). Phase 1
    remains correct and independently valuable regardless.

## Risk

Core shared path (all managers, all frames). Mitigation: the change is
behavior-preserving for every REACHED value-use (identical panic) and for every
already-tolerated arm; it only defers the unreached case. Verified by
clean-HEAD baseline equality on the manager-construction + census neighborhoods
before any board.
