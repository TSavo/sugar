# SPDX-License-Identifier: MIT OR Apache-2.0
#
# sugar-shim-numpy: the numpy SUGAR shim.
#
# This shim carries ONLY sugar — the body and the AST shape of each numpy
# operation, keyed by its fully-qualified symbol (`numpy.add`, ...). It carries
# NO contract and NO concept. That separation is the whole design
# (SHARED-LANGUAGE.md):
#
#   - SUGAR comes from a sugar lifter (this shim): `body_text` (what materialize
#     inserts) + `ast_walk`/`ast_template` (what recognize matches in real code,
#     resolving `import numpy as np; np.add` back to the symbol `numpy.add`).
#   - CONTRACTS come from contract lifters (pytest/hypothesis/...): numpy's own
#     test suite mints the obligation on `numpy.add`, recompute-witnessed.
#   - The CLI marries them BY SYMBOL at the linker — sugar and contract are
#     parallel `.proof` members sharing the key `numpy.add`. The symbol is the
#     wedding ring; concept was the redundant hub key and is gone.
#
# Consequence: write this once, and every numpy project on Earth gets `add`
# under contract — the recognizer's AST walk finds `numpy.add` through any
# import alias, the contract from numpy's tests rides every call site, and the
# consumer's proofchain rolls numpy's witnessed correctness up by CID. No
# per-project annotation. DefinitelyTyped's leverage, for correctness.
#
# Each binding is `@sugar.bind(library="numpy", symbol="<numpy.symbol>")` over a
# thin wrapper whose body IS the canonical numpy call. The lifter reads this
# source (it is never imported), extracts body_text + ast_template, and emits a
# `library-sugar-binding-entry` named by the symbol.

import numpy

from sugar import sugar

# =============================================================================
# Elementwise binary ufuncs — the core arithmetic surface, one shape each.
# `numpy.add` is the keystone; its siblings share the (x, y) -> ufunc shape.
# =============================================================================


@sugar.bind(library="numpy", symbol="numpy.add")
def add(x, y):
    return numpy.add(x, y)


@sugar.bind(library="numpy", symbol="numpy.subtract")
def subtract(x, y):
    return numpy.subtract(x, y)


@sugar.bind(library="numpy", symbol="numpy.multiply")
def multiply(x, y):
    return numpy.multiply(x, y)


@sugar.bind(library="numpy", symbol="numpy.divide")
def divide(x, y):
    return numpy.divide(x, y)


# =============================================================================
# Linear algebra — same sugar shape, distinct symbols. `numpy.dot` is the
# canonical contraction; the recognizer keys it the same way.
# =============================================================================


@sugar.bind(library="numpy", symbol="numpy.dot")
def dot(a, b):
    return numpy.dot(a, b)


@sugar.bind(library="numpy", symbol="numpy.matmul")
def matmul(a, b):
    return numpy.matmul(a, b)
