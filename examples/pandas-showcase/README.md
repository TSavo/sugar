# pandas showcase

The next library up the ladder from numpy is **pandas**, and standing it up is
not a research project: it is **not even a new package**. The Python factory
lift RPC handles both the plain pytest surface and the pandas testing surface;
`.sugar/vocab-exceptions/pandas.testing.json` carries the structurally opaque
pandas helper exceptions. This example differs from
[`numpy-showcase`](../numpy-showcase) only by that exception file and pointing
the witness venv at pandas.

```sh
./run.sh
```

## The claim, two ways

Drop sugar on a pandas project and prove its correctness with zero code
changes. The project contains real pandas tests plus one deliberately buggy
(self-contradictory) one, so the showcase proves the **correct** pandas code and
**catches** the contradiction, both ways:

| axis | mechanism | good code | the bug (`test_pandas_sum_bad.py`) |
|---|---|---|---|
| **consistency** | z3 over the lifted assertions | `Series.sum() == 6` is mutually consistent → **discharged** | `== 6` AND `== 7` → **UNSAT → refused** |
| **witness** | pytest re-runs under real pandas | the test reproduces → **discharged** | the run is `failed` → **refused** |

That is the whole correctness claim, on the real library: *the spec is
consistent, AND the witness matches the spec.*

## The cast

- `test_pandas_sum.py` — a scalar assertion (`df["a"].sum() == 6`) on a real
  pandas op. The plain pytest **consistency** seat lifts the scalar (where z3's
  teeth are); the **witness** seat re-runs it under pandas.
- `test_pandas_frame.py` — `assert_frame_equal(..., check_exact=True)`, lifted by
  the pandas.testing seat. An **un-pinned** `assert_frame_equal` would be loudly
  **refused**: pandas compares floats with a tolerance by default, so lifting it
  as exact equality would claim an exactness pandas never checked.
- `test_pandas_sum_bad.py` — the degenerate: two contradictory scalar assertions
  about the same result, refused both ways.

## Why pandas keeps both axes (and why TensorFlow would not)

The witness axis is framework-blind: pytest-witness just runs `python -m pytest`,
so it works on any pytest package. The consistency axis needs an *algebraic*
proposition, which comes from **scalar** assertions. pandas keeps both because
its tests assert scalars (`.sum() == 6`) alongside frame equality. A package
whose tests only assert `assert_allclose` over giant tensors (TensorFlow,
Transformers) would get the witness axis but a near-vacuous consistency axis —
which is exactly why pandas, not fame, is the right next rung.

## Scope

This example demonstrates lift + **prove** (consistency + witness by recompute).
The stricter signed-receipt **`verify`** also passes: it re-resolves each witness
by recompute — the good witnesses re-run and reproduce their pinned CID, and the
contradictory one is refused as a failed run, the same verdict `prove` gives.
`run.sh` self-checks the `prove` verdict and exits non-zero if sugar does not
produce exactly it.

## Environment

The witness lifter runs pandas's tests, so it needs `pandas` + the kit deps in a
venv (PEP 668: never `--break-system-packages`). `run.sh` provisions
`/tmp/pandas-witness-venv` and the lift manifests point their interpreter there.
