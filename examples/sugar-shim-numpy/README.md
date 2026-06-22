# sugar-shim-numpy

The numpy **sugar** shim. Symbol-keyed, concept-free, sugar-only.

## What this is

A vendored boundary namespace under the Sugar proofchain. Every claim lives
in `sugar_shim_numpy/__init__.py`. Each binding carries **only sugar** — the
`body_text` (what materialize inserts) and the `ast_template` (what recognize
matches in real code, resolving `import numpy as np; np.add` back to the symbol
`numpy.add`), keyed by the fully-qualified symbol. It carries **no contract and
no concept**.

That separation is the design (`SHARED-LANGUAGE.md`):

- **Sugar** comes from this sugar lifter.
- **Contracts** come from contract lifters — numpy's own test suite mints the
  obligation on `numpy.add`, recompute-witnessed.
- The CLI **marries them by symbol** at the linker; sugar and contract are
  parallel `.proof` members sharing the key `numpy.add`. Concept was the
  redundant hub key and is retired.

Write this once and every numpy project gets `add` under contract: the
recognizer's AST walk finds `numpy.add` through any import alias, the contract
from numpy's tests rides every call site, and the consumer's proofchain rolls
numpy's witnessed correctness up by CID.

## How to lift and mint

```sh
# From the sugar repo root, with the Rust toolchain installed:
pip install -e implementations/python/sugar-lift-python-source

cd examples/sugar-shim-numpy
cargo run --manifest-path ../../implementations/rust/Cargo.toml \
    -p sugar-cli --bin sugar -- mint --out .

cargo run --manifest-path ../../implementations/rust/Cargo.toml \
    -p sugar-cli --bin sugar -- proof inspect blake3-512_*.proof
```

`mint --out .` writes the CID-named `.proof`. Each binding lands as a
`library-sugar-binding-entry` **named by its symbol** (`numpy.add`, ...) — the
join key the linker resolves call-edges against.

## Coverage

See `sugar_shim_numpy/__init__.py`. Keystone is `numpy.add`; the elementwise
binary ufuncs (`subtract`/`multiply`/`divide`) and linear-algebra contractions
(`dot`/`matmul`) share the same sugar shape, each under its own symbol.
