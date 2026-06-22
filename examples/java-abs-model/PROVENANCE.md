# java-abs-model: z3.model derive showcase

## What this is

This showcase exercises the second solver primitive: **model extraction** (`get-value`).

Where `sugar prove`/`sugar verify` ask z3 a yes/no question (is this contract
discharged?), `sugar derive` asks: **given this universe definition and a concrete
input, what does z3 COMPUTE?**

The mechanism:

```
(set-logic QF_BV)
(declare-const a (_ BitVec 32))
(declare-const r (_ BitVec 32))
(assert (= r (ite (bvslt a #x00000000) (bvneg a) a)))   ; the walked Math.abs body
(assert (= a #x80000000))                                ; query input: MIN_VALUE
(check-sat)
(get-value (r))                                          ; => ((r #x80000000)) = -2147483648
```

z3 returns `sat` then `((r #x80000000))`. Interpreting the 32-bit pattern as a
signed two's complement i32: `-2147483648`. That is `abs(Integer.MIN_VALUE)`,
**derived from the definition, not executed.**

## The punchline

- The JDK's own AbsTests.java (merged flagship: `examples/java-abs-flagship`) at
  line 110 SWEARS: `abs(MIN_VALUE) == MIN_VALUE` ("// Strange but true").
- z3.model **independently derives** the same -2147483648 from the walked body.
- Two unrelated witnesses. Same strange truth. No execution. No hardcoded value.

The industry believes `abs(x) >= 0`. Both witnesses refute it for MIN_VALUE.

## The chain is closed (no-vendor axiom)

The lift is the source of truth. The bv_tree is NEVER hardcoded in the CLI or in
run.sh. The showcase closes the chain end to end:

1. **mint** — `sugar mint` walks `good/vendor/jdk21/java/lang/Math.java` and emits
   the `int32.eq-bv-expr` universe atom into a `blake3-512_*.proof`.
2. **extract** — `sugar dump --json` surfaces the minted proof; run.sh pulls the
   universe atom's `args[1]` (the bv_tree) straight out of the dumped artifact.
   The extracted tree carries the lifter's own `"sort": {"kind":"primitive",...}`
   annotations — proof it came from the lift, not a literal typed by hand.
3. **derive** — `sugar derive --bv-expr <extracted>` (or `--from-proof <path>`,
   which reads the atom out of the proof itself) emits the QF_BV query and asks
   z3 `(get-value (r))`.

`sugar derive` has **no built-in abs formula**. It only ever takes the bv_tree
from the lifted universe (`--from-proof` or an extracted `--bv-expr`).

### The guard that proves the chain is real

If the universe atom is deleted from the proof, `sugar derive --from-proof` has
nothing to derive from and **REFUSES** (exit 2) — it does NOT fall back to a
built-in. run.sh exercises exactly this: it flips the atom name in a proof copy
and asserts the verb refuses. That refusal is the proof there is no hollow
shortcut.

Every operator in the bv_tree traces to a tree node in
`vendor/jdk21/java/lang/Math.java` (LiteralTree, BinaryTree, UnaryTree,
ConditionalExpressionTree). No arithmetic is hand-authored in the kit.

## Vendored source

`good/vendor/jdk21/java/lang/Math.java`: jdk-21+35, sha256 `1264b299cbffe5611764dc9a626f9beb2a02728a1651f3f3fee1e0b767924151`.

Source: https://github.com/openjdk/jdk, tag `jdk-21+35`.
Upstream path: `src/java.base/share/classes/java/lang/Math.java`
License: GNU General Public License, version 2, with the Classpath Exception.

JUnit5 assertion vocabulary under `good/vendor/junit5/` (see its PROVENANCE.md).

## Additive

This showcase uses the NEW `sugar derive` verb. The existing discharge path
(`sugar prove` / `sugar verify`) is NOT modified. All existing tests remain
byte-identical green.
