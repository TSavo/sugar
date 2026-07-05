# Pandas Wall Baseline, July 5 2026

Part of #3503.

This is the August-seat scouting baseline for full pandas source plus its test
corpus using the current Python audit machinery. The original measurement found
the `MapSugar receiver` crash; the first refresh routed that case to a typed
effect, then found the same propagation bug in `AddSugar`. This revision
records the ABC-lane receipt after centralizing effect propagation in the
`Sugar` base template method: the wall moves past the `AddSugar` receiver force
and reaches a later non-Sugar prior-assignment force. A final-source rerun was
interrupted after more than 11 minutes with no stdout, so this remains a
frontier receipt rather than a completed wall baseline.

## Corpus

| field | value |
|---|---:|
| pandas version | 3.0.3 |
| installed package | `/usr/local/lib/python3.14/site-packages/pandas` |
| cached audit workspace used for AddSugar-moved receipt | `/Users/tsavo/.cache/sugar/python-panic-audit-workspaces/4126d0eb89dc27c129a8ddb83b8625a334c08457d093da344471f20000d51640/pandas` |
| audit workspace cache key used for AddSugar-moved receipt | `4126d0eb89dc27c129a8ddb83b8625a334c08457d093da344471f20000d51640` |
| Python files | 1421 |
| pandas test Python files | 1122 |
| ABC AddSugar-moved receipt repo head | `e0468e87f95330f7b771fa7966541ec510449f21` |
| ABC AddSugar-moved receipt sugar binary stamp | `e0468e87f95330f7b771fa7966541ec510449f21-dirty-e2480ea63ea65feb` |
| bounded rerun receipt repo head | `f38b5a4c023d33d5ec6bffcde36bfe61b3eee2e3` |
| bounded rerun receipt sugar binary stamp | `f38b5a4c023d33d5ec6bffcde36bfe61b3eee2e3-dirty-4ca340e5fcc1d8a4` |

The audit workspace was materialized through
`sugar_lift_py_tests.idd.collect_panic_audit._cached_audit_workspace`, the same
cache path used by the numpy/pandas panic audit.

The release binaries were resolved by `bin/sugarbin`; the bounded rerun receipt
used the branch-stamped binary for `f38b5a4c023d33d5ec6bffcde36bfe61b3eee2e3`
plus this PR's dirty-tree `Sugar` ABC effect-propagation change.

## Render Result

The pandas wall does not currently render. The ABC-lane JSON receipt below
aborts before emitting `sourceLedger` or `sourceAudits`, after moving past the
previous `AddSugar` blocker. A bounded JSON rerun timed out after
120s with only transport checkpoint output, so it did not produce a newer
structured blocker and did not re-expose the `AddSugar` crash. A longer
final-source JSON rerun and the visual rerun were both interrupted after more
than 11 minutes with no stdout and no structured blocker beyond the interrupt
trace.

| command | exit | stdout bytes | stderr bytes | elapsed |
|---|---:|---:|---:|---:|
| `sugar lift --report --json <cached-pandas-audit-workspace>` (ABC AddSugar-moved receipt) | 2 | 0 | 8110 | 16.19s |
| `sugar lift --report --json <cached-pandas-audit-workspace>` (bounded rerun receipt) | timeout | 0 | 1942 | 120.02s |
| `sugar lift --report --json <cached-pandas-audit-workspace>` (final-source rerun) | 130 | 0 | 6816 | >11m, interrupted |

Raw receipt hashes:

| receipt | sha256 |
|---|---|
| `/tmp/mapsugar-effect-honesty-pandas-final2/pandas-report.json.stderr` | `0281eeb0af1825f24f7f6f0e254179fec1f129ac2326c45ea6e0538da391fbff` |
| `/tmp/mapsugar-effect-honesty-pandas-final2/pandas-report.visual.stderr` (historical, pre-ABC refresh) | `d263b0122bf930b69fb6b59049fd29d62d15b0764bf844fd938b6377e603e389` |
| `/tmp/mapsugar-effect-honesty-after.json` | `5aebb5634ef8ff05c6e51cc8b0075313c20dbc8112f3de6cbb90aa008149d8dc` |
| `/tmp/mapsugar-effect-honesty-after.stderr` | `232774b53f6d619c371621aea0f1e7a2fdba2e01bb83747352b5b44f83d8e62a` |
| `/tmp/sugar-abc-pandas-report.stderr` (ABC AddSugar-moved receipt, overwritten by final rerun) | `e94116e42cb920323dc316535114537b623c9e2b90ffc3c44bc47908a276bebe` |
| `/tmp/sugar-abc-current-pandas-report.json` (bounded rerun receipt) | `e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855` |
| `/tmp/sugar-abc-current-pandas-report.stderr` (bounded rerun receipt) | `3e84549275760ed777836f516e3e30daa7697866dca7a0efd11ca30d8bda39b1` |
| `/tmp/sugar-abc-pandas-report.stderr` (final-source interrupted rerun) | `69e2a94e8b0e641e84928d67e7732fd2941cf1a9afc2d51fe03557f938c0c525` |

## Counts

The requested wall counts are not yet measurable because the renderer crashes
before producing report rows.

| requested count | value |
|---|---|
| contracts | unavailable |
| pre-bearing | unavailable |
| call edges | unavailable |
| resolved | unavailable |
| dangling | unavailable |
| implications | unavailable |
| green count | unavailable |
| reasoned-red count | unavailable |
| bare-red count | unavailable |

Bare-red status is therefore not proven zero in this baseline. The immediate
finding is earlier: the renderer must survive the first typed red before the
bare-red invariant can be measured.

## ABC-Lane Blocker

The AddSugar-moved receipt reaches this later blocker in pandas' own corpus:

```text
pandas/core/arrays/categorical.py:2534:23
literal_call_report.prior_assignment_block cannot read completed value from incomplete effect:
write more Sugar for this AST:
owner=python.factory
observed=call-method:mode
requested=term
fix=add receiver-dispatched method sugar for `mode`, resolve a local body, link an imported .proof, or emit a real effect
```

Source shape:

```python
codes = self._codes
mask = self.isna()
res_codes, _ = algorithms.mode(codes, mask=mask)
```

Call path:

```text
_lift_callsite_assertion
_assertion_factory_ctx
_ctx_with_prior_assignments
complete_value(literal_call_report.prior_assignment_block)
```

The old `MapSugar receiver` blocker and the subsequent `AddSugar receiver`
blocker are no longer the first aborts in that receipt. The wall gets to
`pandas/core/arrays/categorical.py` and stops when prior-assignment folding
forces an incomplete typed effect for `mode()` as a completed value.

## MapSugar Repro

The original MapSugar failure reproducer is small enough to keep as the
regression receipt:

```python
def test_iterable_map(index_or_series, dtype, rdtype):
    typ = index_or_series
    s = typ([1], dtype=dtype)
    result = s.map(type)[0]
    if not isinstance(rdtype, tuple):
        rdtype = (rdtype,)
    assert result in rdtype
```

Post-fix receipt:

```text
sugar lift --report --json /tmp/mapsugar-effect-honesty-after-audit
exit 0
factory walk row: selected=MembershipAssertionSugar status=factory-gap
reason contains observed=call-local:typ requested=term
```

## Top Red Shapes

Because the full wall still aborts before rows are emitted, the top-10 red
reason table is not available yet. The current top blocker is:

| rank | count | template | example |
|---:|---:|---|---|
| 1 | 1 | prior-assignment folding forces incomplete `call-method:mode` effect before report rows are emitted | `pandas/core/arrays/categorical.py:2534:23` |

## Transfer Notes

| mechanism from numpy work | pandas status |
|---|---|
| content-addressed audit workspace cache | Transfers. The pandas workspace is keyed by vendor source plus kit source. |
| re-export bridges / set-module-style aliasing | Not reached. The wall aborts before bridge/call-edge counts render. |
| guard shapes | Not reached. The corpus contains guard-heavy tests, but the current blocker still aborts before frequency counts render. |
| decorators | Not reached. The pandas package and tests are present, but decorator frequency cannot be measured until render survives. |
| local alias plus higher-order map | Drained for the first pandas hit. The minimal repro now returns a typed `factory-gap` row with `call-local:typ` grounds. |
| builtin `slice(...)` inside arithmetic receiver | No longer the first blocker. The base `Sugar` template propagates the typed `call-builtin:slice` effect before `AddSugar._build` can force it. |
| receiver method `mode()` in prior assignment folding | New first blocker. `literal_call_report.prior_assignment_block` forces the `call-method:mode` effect as a completed value. |

## August Work-List Seed

1. Make prior-assignment folding propagate typed effects instead of forcing
   `Complete`.
2. Re-run this exact baseline and require `bare-red count = 0`.
3. Only after the wall renders, classify the real top-10 reason templates by
   frequency.
