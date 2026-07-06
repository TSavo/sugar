# Pandas Implication Potential

Part of #3503. This audit records the current pandas wall implication state after the membership floor drain and the first-edge pass.

## Receipt

| item | value |
| --- | --- |
| repo head | `ea40b8b14e3a42e6a21d3f288ec2ed8d61a6185c` |
| pandas version | `3.0.3` |
| workspace | `.sugar/pandas-first-edges-gate/workspace/pandas` |
| sugar binary | `/Users/tsavo/.cache/sugar/binaries/sugar-darwin-x86_64-release-blake3-512_0faacb41d3e1b287b3831f27290f441800dc9b88f8c17ee0aca167056b39f904bcacbcc56c3bbe1ced15e852baede191abe306ddd42dee62f338e0de0b4e2158` |
| binary file receipt | `Mach-O 64-bit executable x86_64` |
| gate command | `PYTHONPATH=implementations/python/sugar-lift-py-tests/src python3 tools/pandas_wall.py --output-dir .sugar/pandas-first-edges-gate` |
| gate exit | `0` |
| report SHA-256 | `094176607b3a084df5c2cb30b807da782f2377e7c811bc6ef1242ef9fd21a6b0` |
| visual SHA-256 | `bde0a9ad4f5a6f8192f86ceb6720a0e41d9ea2390b6ab35e342a5fc3cb3a8d44` |
| summary SHA-256 | `afdde3130b82accfd937d582aba9baff8f4ad882cd2cc6954676f7a407c13fdc` |

The run exceeded 30 minutes but completed cleanly. At `2026-07-06 08:56:18 PDT`, the wrapper had been running `29:35`; visual had completed, JSON was active, and the `lift_rpc.py --rpc` child was running at about `90%` CPU. This is slow, not hung.

## Result

| metric | count |
| --- | ---: |
| contracts | `8644` |
| pre-bearing contracts | `69` |
| call edges total | `2945` |
| call edges resolved | `0` |
| call edges dangling | `2945` |
| implications | `0` |
| green rows | `7870` |
| reasoned red rows | `6314` |
| bare red rows | `0` |
| construction gaps | `0` |

The retired membership blocker is gone. `tools/pandas-wall-floors.json` now gates the completed wall with `construction_gaps.total_ceiling=0`.

## First Blocker

There is no first pandas implication line yet. The wall now renders completely, but every call edge is dangling:

```text
report sections: unit test facts=8571, body universes=8644, factory report=307046, call edges total=2945, call edges resolved=0, call edges dangling=2945, implications=0, vendor conjoins=0, source mementos=14123
```

The current blocker is identity joining, not construction. The resolver has pre-bearing contracts and call edges, but it does not have declared identity evidence connecting the emitted target keys to contract keys.

Representative mismatch examples:

| contract / public spelling | observed call-edge target | disposition |
| --- | --- | --- |
| `core.tools.times.to_time` | `call:pandas.core.tools.times.to_time` | package-prefix mismatch needing declared identity, not leaf guessing |
| `pandas.Index.get_slice_bound` | `call:get_slice_bound` | leaf-only target; unsafe to resolve without receiver/owner testimony |
| `pandas.api.extensions.ExtensionArray.view` | `call:view` | leaf-only target; unsafe to resolve without receiver/owner testimony |
| `core.arrays.datetimelike.TimelikeOps.as_unit` | `call:as_unit` | leaf-only target; unsafe to resolve without receiver/owner testimony |

## Delete Vs Convert Guidance

Fresh construction-gap vector compared to the previous `tools/pandas-wall-floors.json` ceiling:

| previous shell | disposition |
| --- | --- |
| `ArrayLiteral.contains(SymbolicValue)` membership rows | deleted by floor semantics in the membership drain |
| `StringValue + SymbolicValue` | converted to a typed runtime effect; row persists only as reasoned red if reached |
| `StringValue * SymbolicValue` | converted to a typed runtime effect; row persists only as reasoned red if reached |
| lone-surrogate string literal transport | converted to a typed runtime effect before JSON-RPC transport |

The next shell most likely to delete rows is the identity/call-edge join: adding declared identity evidence for package-prefix and owner-qualified calls can turn dangling call edges into resolved edges and mint implications. Pure runtime/transport boundaries should stay typed effects unless a cited floor gives the value real meaning.

The machine-readable companion is `docs/audits/pandas-implication-potential.json`.
