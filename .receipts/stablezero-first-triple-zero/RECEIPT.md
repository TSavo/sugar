# `pandas/core/series.py` — the first true `stableZero`

Every number here is read off `series-760a65540.json` in this directory. Nothing
is inferred, and the caveat at the bottom is part of the claim, not a footnote.

## The measurement

```
implementations/python/sugar-lift-py-tests/scripts/stablezero_classify.py \
  <pandas>/core/series.py --out series-760a65540.json --deadline 60
```

Commit `760a65540`. pandas 3.0.3. Isolated — the file is copied ALONE into an
empty temp directory, so each function's verdict depends on nothing but that
function. Mac, load ~15; battleaxe was holding the authoritative corpus
baseline and nothing heavy went near it.

`stablezero_classify.py` exits 0 **only** on `stableZero`. This run exited 0,
and that exit code is the claim — not a line of output someone read off a tail.

## The board

| term | value |
| --- | --- |
| `completed_denominator` | 179 |
| `R(timeout)` | **0** |
| `R(construction_panics)` | **0** |
| `R(unnamed_exceptions)` | **0** |
| `R(factoring_gaps)` | **0** |
| `R(factoring_gaps_remaining_work)` | **0** |
| `stableZero` | **true** |

```
statuses = {clean: 174, SugarNotWritten: 5}
```

## Why this one is worth a receipt

It is the first file the board can call *done by the full definition* rather
than by one axis. Every other file measured in the same sweep carries at least
one residual, and for most of the session the interesting question was which
axis was hiding the others — a timeout absorbing panics (#6324), a panic
absorbing an unnamed exception (#6352), a scalar `factoring_gaps` absorbing the
difference between remaining work and correct output (#6356).

Four terms at zero simultaneously, on 179 functions, is the shape those splits
were built to make visible.

## THE CAVEAT, stated because a receipt that omits it is a lie

**174 of 179 functions reached the floor. Five did not.**

`SugarNotWritten: 5` is the TREE door refusing — a recognition gap, counted on
its own name and deliberately not folded into the Floor terms this rig gates
on. Those five functions never exercised the floor at all, so `stableZero` here
means *"every function the floor saw, it handled, and none of the four gated
terms fired"* — it does not mean 179/179 fully lifted.

`stableZero` is a statement about the four terms over the completed
denominator. Reading it as "this file is finished" would be exactly the
misclassification the `R(unnamed_exceptions)` term was added to prevent, one
level up.
