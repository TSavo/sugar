# Pandas Wall Baseline, July 5 2026

Part of #3503.

This is the August-seat scouting baseline for full pandas source plus its test
corpus using the current Python audit machinery. The original measurement found
the `MapSugar receiver` crash; the first refresh routed that case to a typed
effect, then found the same propagation bug in `AddSugar`. This revision
records the current-main receipt after the Sugar-ABC propagation base and the
prior-assignment typed effect both landed. The wall no longer stops at
`MapSugar`, `AddSugar`, builtin `slice(...)`, or categorical prior-assignment
folding. It now reaches a later propagation escape: `BitwiseOpSugar` still
forces an incomplete `notna()` receiver-method effect as a completed value.
This remains a frontier receipt rather than a completed wall baseline.

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
| current first-render receipt repo head | `a4d123eec0583db0296dc30b506c84e674891e90` |
| current first-render receipt sugar binary | `sugar-darwin-x86_64-release-blake3-512_4d21d292546eac518053f5a08406d9913fe0ffa0520cc0e9812f2bf6fc6d6e448610a7a750e4baf818e06cc9ec2cebf8b1f286f4679eaf22d7072f0e994119d0` |
| current first-render cached audit workspace | `/Users/tsavo/.cache/sugar/python-panic-audit-workspaces/26c47b548a870f226b60b172082e310c508f8da25351d03cf6719d572cac6085/pandas` |
| current first-render audit workspace cache key | `26c47b548a870f226b60b172082e310c508f8da25351d03cf6719d572cac6085` |

The audit workspace was materialized through
`sugar_lift_py_tests.idd.collect_panic_audit._cached_audit_workspace`, the same
cache path used by the numpy/pandas panic audit.

The release binaries were resolved by `bin/sugarbin`; the current receipt used
the clean current-main binary above. `file` identified it as a Mach-O 64-bit
`x86_64` executable.

## Render Result

The pandas wall does not currently render. The current JSON and visual receipts
both ran to real exit code `2`, emitted no stdout, and aborted before emitting
`sourceLedger` or `sourceAudits`. Both modes reached the same first blocker:
`BitwiseOpSugar left` reads the incomplete typed effect for
`call-method:notna` as a completed value.

| command | exit | stdout bytes | stderr bytes | elapsed |
|---|---:|---:|---:|---:|
| `sugar lift --report --json <cached-pandas-audit-workspace>` (ABC AddSugar-moved receipt) | 2 | 0 | 8110 | 16.19s |
| `sugar lift --report --json <cached-pandas-audit-workspace>` (bounded rerun receipt) | timeout | 0 | 1942 | 120.02s |
| `sugar lift --report --json <cached-pandas-audit-workspace>` (final-source rerun) | 130 | 0 | 6816 | >11m, interrupted |
| `sugar lift --report --json <cached-pandas-audit-workspace>` (current first-render receipt) | 2 | 0 | 9487 | 8m59s |
| `sugar lift --report --visual <cached-pandas-audit-workspace>` (current first-render receipt) | 2 | 0 | 9487 | 9m17s |

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
| `/tmp/pandas-wall-first-render-a4d/pandas-report.json` (current first-render receipt) | `e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855` |
| `/tmp/pandas-wall-first-render-a4d/pandas-report.json.stderr` (current first-render receipt) | `60128e8d59bf2c90c7929d34d46e83b97df1627d3b00a6bdd266066f9538ee92` |
| `/tmp/pandas-wall-first-render-a4d/pandas-report.visual` (current first-render receipt) | `e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855` |
| `/tmp/pandas-wall-first-render-a4d/pandas-report.visual.stderr` (current first-render receipt) | `1439f2d0aaca86c3704b205cf0aad27d72a1a5b1a925795c55f081ccfeb89dff` |

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

## Current Blocker

The current main receipt reaches this later blocker in pandas' own corpus:

```text
tests/test_sorting.py:300:20
BitwiseOpSugar left cannot read completed value from incomplete effect:
write more Sugar for this AST:
owner=python.factory
observed=call-method:notna
requested=term
fix=add receiver-dispatched method sugar for `notna`, resolve a local body, link an imported .proof, or emit a real effect
```

Source shape:

```python
jmask = {
    "left": out["left"].notna(),
    "right": out["right"].notna(),
    "inner": out["left"].notna() & out["right"].notna(),
    "outer": np.ones(len(out), dtype="bool"),
}
mask = jmask[how]
assert mask.all() ^ mask.any() or how == "outer"
```

Call path:

```text
_lift_callsite_assertion
_assertion_factory_ctx
BoolOpAssertionSugar._build
TruthyAssertionSugar._build
BitwiseOpSugar._build
complete_value(BitwiseOpSugar left)
```

The old `MapSugar receiver`, `AddSugar receiver`, builtin `slice(...)`, and
prior-assignment `mode()` blockers are no longer the first aborts in this
receipt. The wall gets to `pandas/tests/test_sorting.py` and stops when
`BitwiseOpSugar` forces an incomplete typed effect for `notna()` as a completed
value. This is a Sugar-ABC escapee in the bitwise operand path, not a new
factory/floor recognizer to guess.

Minimal repro:

```python
def test_repro(out, how):
    jmask = {
        "left": out["left"].notna(),
        "right": out["right"].notna(),
        "inner": out["left"].notna() & out["right"].notna(),
    }
    mask = jmask[how]
    assert mask.all() ^ mask.any() or how == "outer"
```

Focused receipt:

```text
PYTHONPATH=implementations/python/sugar-lift-py-tests/src python3 - <<'PY'
from sugar_lift_py_tests.factory.literal_call_report import build_literal_call_report
...
build_literal_call_report(source=src, filename="pandas-bitwise-notna-repro.py", memento_file="pandas-bitwise-notna-repro.py")
PY
RuntimeError: BitwiseOpSugar left cannot read completed value from incomplete effect:
write more Sugar for this AST: owner=python.factory blame=pandas-bitwise-notna-repro.py:4:16
observed=call-method:notna requested=term
```

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
| 1 | 1 | `BitwiseOpSugar` forces incomplete `call-method:notna` effect before report rows are emitted | `pandas/tests/test_sorting.py:300:20` |

## Transfer Notes

| mechanism from numpy work | pandas status |
|---|---|
| content-addressed audit workspace cache | Transfers. The pandas workspace is keyed by vendor source plus kit source. |
| re-export bridges / set-module-style aliasing | Not reached. The wall aborts before bridge/call-edge counts render. |
| guard shapes | Not reached. The corpus contains guard-heavy tests, but the current blocker still aborts before frequency counts render. |
| decorators | Not reached. The pandas package and tests are present, but decorator frequency cannot be measured until render survives. |
| local alias plus higher-order map | Drained for the first pandas hit. The minimal repro now returns a typed `factory-gap` row with `call-local:typ` grounds. |
| builtin `slice(...)` inside arithmetic receiver | No longer the first blocker. The base `Sugar` template propagates the typed `call-builtin:slice` effect before `AddSugar._build` can force it. |
| receiver method `mode()` in prior assignment folding | No longer the first blocker after the prior-assignment typed effect landed. |
| bitwise `notna()` composition | Current first blocker. `BitwiseOpSugar._build` forces the `call-method:notna` effect as a completed value. |

## August Work-List Seed

1. Make `BitwiseOpSugar` propagate typed effects from either operand instead of
   forcing `Complete`.
2. Re-run this exact baseline and require `bare-red count = 0`.
3. Only after the wall renders, classify the real top-10 reason templates by
   frequency.
