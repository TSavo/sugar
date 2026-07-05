# Pandas Wall Baseline, July 5 2026

Part of #3503.

This is the August-seat scouting baseline for full pandas source plus its test
corpus using the current Python audit machinery. The original measurement found
the `MapSugar receiver` crash; this revision refreshes the wall after routing
that case to a typed effect.

## Corpus

| field | value |
|---|---:|
| pandas version | 3.0.3 |
| installed package | `/usr/local/lib/python3.14/site-packages/pandas` |
| cached audit workspace | `/Users/tsavo/.cache/sugar/python-panic-audit-workspaces/e17a7b3da98c63ba59bef1a18a4f040503e5fb8ba0e16d9b967701438674c1ba/pandas` |
| audit workspace cache key | `e17a7b3da98c63ba59bef1a18a4f040503e5fb8ba0e16d9b967701438674c1ba` |
| Python files | 1421 |
| pandas test Python files | 1122 |
| repo head | `6fa7d8743b52f732406ce2e7adad4dd1fc9b905f` |
| sugar binary stamp | `6fa7d8743b52f732406ce2e7adad4dd1fc9b905f-dirty-491789b70f9bf49d` |

The audit workspace was materialized through
`sugar_lift_py_tests.idd.collect_panic_audit._cached_audit_workspace`, the same
cache path used by the numpy/pandas panic audit.

The release binary was resolved by `bin/sugarbin` for
`6fa7d8743b52f732406ce2e7adad4dd1fc9b905f` plus this PR's dirty-tree
`MapSugar` incomplete-effect propagation change.

## Render Result

The pandas wall does not currently render. Both requested report modes abort
before emitting `sourceLedger`, `sourceAudits`, or visual rows.

| command | exit | stdout bytes | stderr bytes | elapsed |
|---|---:|---:|---:|---:|
| `sugar lift --report --json <cached-pandas-audit-workspace>` | 2 | 0 | 7932 | 298.58s |
| `sugar lift --report --visual <cached-pandas-audit-workspace>` | 2 | 0 | 7932 | 307.61s |

Raw receipt hashes:

| receipt | sha256 |
|---|---|
| `/tmp/mapsugar-effect-honesty-pandas-final2/pandas-report.json.stderr` | `0281eeb0af1825f24f7f6f0e254179fec1f129ac2326c45ea6e0538da391fbff` |
| `/tmp/mapsugar-effect-honesty-pandas-final2/pandas-report.visual.stderr` | `d263b0122bf930b69fb6b59049fd29d62d15b0764bf844fd938b6377e603e389` |
| `/tmp/mapsugar-effect-honesty-after.json` | `5aebb5634ef8ff05c6e51cc8b0075313c20dbc8112f3de6cbb90aa008149d8dc` |
| `/tmp/mapsugar-effect-honesty-after.stderr` | `232774b53f6d619c371621aea0f1e7a2fdba2e01bb83747352b5b44f83d8e62a` |

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

## First Blocker

The current first blocker is in pandas' own test corpus:

```text
pandas/tests/internals/test_internals.py:1179:29
AddSugar receiver cannot read completed value from incomplete effect:
write more Sugar for this AST:
owner=python.factory
observed=call-builtin:slice
requested=term
fix=add builtin call sugar for `slice`, resolve a local body, link an imported .proof, or emit a real effect
```

Source shape:

```python
bpl = BlockPlacement(slice(0, 5))
assert bpl.add(1).as_slice == slice(1, 6, 1)
assert bpl.add(np.arange(5)).as_slice == slice(0, 10, 2)
assert list(bpl.add(np.arange(5, 0, -1))) == [5, 5, 5, 5, 5]
```

Call path:

```text
_lift_callsite_assertion
_literal_floor_via_factory
AddSugar.desugar
complete_value(AddSugar receiver)
```

The old `MapSugar receiver` blocker is no longer the first abort. The wall now
gets to `pandas/tests/internals/test_internals.py` and stops when `AddSugar`
forces the incomplete typed effect for `slice(0, 5)` as a completed term.

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
| 1 | 1 | AddSugar receiver forces incomplete `call-builtin:slice` effect before report rows are emitted | `pandas/tests/internals/test_internals.py:1179:29` |

## Transfer Notes

| mechanism from numpy work | pandas status |
|---|---|
| content-addressed audit workspace cache | Transfers. The pandas workspace is keyed by vendor source plus kit source. |
| re-export bridges / set-module-style aliasing | Not reached. The wall aborts before bridge/call-edge counts render. |
| guard shapes | Not reached. The corpus contains guard-heavy tests, but the current blocker still aborts before frequency counts render. |
| decorators | Not reached. The pandas package and tests are present, but decorator frequency cannot be measured until render survives. |
| local alias plus higher-order map | Drained for the first pandas hit. The minimal repro now returns a typed `factory-gap` row with `call-local:typ` grounds. |
| builtin `slice(...)` inside arithmetic receiver | New first blocker. `AddSugar` forces the `call-builtin:slice` effect as a completed receiver. |

## August Work-List Seed

1. Make the `call-builtin:slice` effect remain typed through `AddSugar` instead
   of forcing `Complete`.
2. Re-run this exact baseline and require `bare-red count = 0`.
3. Only after the wall renders, classify the real top-10 reason templates by
   frequency.
