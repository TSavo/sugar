# Pandas Wall Baseline, July 5 2026

Part of #3503.

This is the first August-seat scouting baseline for full pandas source plus its
test corpus using the current Python audit machinery. It changes no lifter code.

## Corpus

| field | value |
|---|---:|
| pandas version | 3.0.3 |
| installed package | `/usr/local/lib/python3.14/site-packages/pandas` |
| cached audit workspace | `/Users/tsavo/.cache/sugar/python-panic-audit-workspaces/e6584386f67991af23cdca0e0ab3ef983b1e1645526c9aa02599d1a9a46d5238/pandas` |
| audit workspace cache key | `e6584386f67991af23cdca0e0ab3ef983b1e1645526c9aa02599d1a9a46d5238` |
| Python files | 1421 |
| pandas test Python files | 1122 |
| repo head | `1e9779fe8ab477718361ab82e0c523962e050fb7` |
| sugar binary stamp | `1e9779fe8ab477718361ab82e0c523962e050fb7-dirty-3aa553bfc26f7252` |

The audit workspace was materialized through
`sugar_lift_py_tests.idd.collect_panic_audit._cached_audit_workspace`, the same
cache path used by the numpy/pandas panic audit.

The binary stamp is dirty because the baseline fixture and this report were
staged while the current-main receipt was refreshed; the lifter code under
measurement is from `1e9779fe8ab477718361ab82e0c523962e050fb7`.

## Render Result

The pandas wall does not currently render. Both requested report modes abort
before emitting `sourceLedger`, `sourceAudits`, or visual rows.

| command | exit | stdout bytes | stderr bytes | elapsed |
|---|---:|---:|---:|---:|
| `sugar lift --report --json <cached-pandas-audit-workspace>` | 2 | 0 | 8840 | 64.23s |
| `sugar lift --report --visual <cached-pandas-audit-workspace>` | 2 | 0 | 8840 | 62.88s |

Raw receipt hashes:

| receipt | sha256 |
|---|---|
| `/tmp/pandas-wall-baseline-current/pandas-report.json.stderr` | `0d40824aeb2839f154afae2e9e598641a66969bb8da3ab3577254b89d960c522` |
| `/tmp/pandas-wall-baseline-current/pandas-report.visual.stderr` | `71dc36f4c1b8ba1bbba081a46595876a58d35ff88c407af0c4f48e408423c0e5` |
| `/tmp/pandas-wall-baseline-current/repro-report.stderr` | `0c74aa641c5e92bce497e6dfebada16d06668a8cce3cf718be70bbeab901a9eb` |

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

The first blocker is in pandas' own test corpus:

```text
pandas/tests/base/test_conversion.py:127:12
MapSugar receiver cannot read completed value from incomplete effect:
write more Sugar for this AST:
owner=python.factory
observed=call-local:typ
requested=term
fix=resolve local call `typ` to a body, link an imported .proof, add sugar, or emit a real effect
```

Source shape:

```python
typ = index_or_series
s = typ([1], dtype=dtype)
result = s.map(type)[0]
if not isinstance(rdtype, tuple):
    rdtype = (rdtype,)
assert result in rdtype
```

Call path:

```text
MembershipAssertionSugar.desugar
NameSugar.desugar
StringSubscriptSugar.desugar
MapSugar.desugar
complete_value(MapSugar receiver)
```

The bug class is not pandas-specific semantics yet. The wall aborts because an
incomplete local-call effect (`typ(...)`) is forced as a completed value by a
later map/string-subscript/membership composition.

## Minimal Repro

The same failure reproduces without the full pandas tree:

```python
def test_iterable_map(index_or_series, dtype, rdtype):
    typ = index_or_series
    s = typ([1], dtype=dtype)
    result = s.map(type)[0]
    if not isinstance(rdtype, tuple):
        rdtype = (rdtype,)
    assert result in rdtype
```

Receipt:

```text
sugar lift --report --json /tmp/pandas-wall-baseline-current/repro-audit
exit 2
MapSugar receiver cannot read completed value from incomplete effect:
... test_conversion_minimal.py:3:8 observed=call-local:typ requested=term ...
```

## Top Red Shapes

Because the full wall aborts before rows are emitted, the top-10 red reason
table is not available yet. The current top blocker is:

| rank | count | template | example |
|---:|---:|---|---|
| 1 | 1 | MapSugar receiver forces incomplete `call-local` effect from local constructor alias before report rows are emitted | `pandas/tests/base/test_conversion.py:127:12` |

## Transfer Notes

| mechanism from numpy work | pandas status |
|---|---|
| content-addressed audit workspace cache | Transfers. The pandas workspace is keyed by vendor source plus kit source. |
| re-export bridges / set-module-style aliasing | Not reached. The wall aborts before bridge/call-edge counts render. |
| guard shapes | Not reached. The corpus contains guard-heavy tests, but the first blocker is earlier. |
| decorators | Not reached. The pandas package and tests are present, but decorator frequency cannot be measured until render survives. |
| local alias plus higher-order map | First blocker. `typ = index_or_series`, `typ(...)`, `s.map(type)[0]`, and membership assertion compose into the crash. |

## August Work-List Seed

1. Make the local-call effect remain typed through `MapSugar`/subscript/membership
   composition instead of forcing `Complete`.
2. Re-run this exact baseline and require `bare-red count = 0`.
3. Only after the wall renders, classify the real top-10 reason templates by
   frequency.
