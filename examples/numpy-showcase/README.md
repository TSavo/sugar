# numpy showcase showdown

All the verbs over **one** operation, `numpy.rot90` — the full sugar+contract
lifecycle, kit-side, with the `.proof` as the transport and rust proof-blind.

```sh
./run.sh
```

## The cast

- `.sugar/imports/*.proof` — the **numpy sugar `.proof`** (the transport),
  sugar-lifted by `run.sh` from the **installed numpy source**. Lean
  `SourceMemento` mode: it carries CIDs + spans, NOT inline bodies; the body is
  resolved on demand from the installed numpy by the Source Oracle. The binding's
  symbol is the **public** name `numpy.rot90` (derived from numpy's `__init__`
  re-exports), while the memento points at the real source location
  (`lib/_function_base_impl.py`). `numpy.add` is a C ufunc with no python body, so
  it never lifts; `rot90` is real python, which is why it does.
- `test_numpy_rot90.py` — numpy's **own** testing vocabulary (`numpy.testing`).
  Two lifters read it: the **consistency** seat (numpy.testing) and the
  **witness** seat (pytest-witness, which *runs* it).
- `app.py` — production `np.rot90` (aliased) callsite, lifted with the project.

## The showdown

| verb | what it does | result |
|---|---|---|
| **sugar-lift** | numpy's installed source → a lean sugar `.proof` for `numpy.rot90` | one `.proof` in `imports/` |
| **prove** | the good contract discharges **two ways** | **consistent** (z3) AND **witnessed** (recompute) |

## The degenerate case (contracts contradict)

The same rotated element asserted `== 2` **and** `== 9` is refused **both** ways:
- **consistency**: the spec contradicts itself → z3 UNSAT → refused.
- **witness**: when actually run, `np.rot90([[1,2],[3,4]])[0][0]` is `2`, so the
  `== 9` assertion *fails* → witness outcome `failed` → refused by recompute.

That is the whole correctness claim, on a real library operation: *the spec is
consistent, AND the witness matches the spec.*

## Environment

The witness lifter **runs numpy's test** and the numpy.testing lifter
**introspects numpy.testing** for its vocabulary, so both need `numpy` in a venv
(PEP 668: never `--break-system-packages`). `run.sh` provisions
`/tmp/numpy-witness-venv` and points the lift manifests at it.
