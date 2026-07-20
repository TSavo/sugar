# memento CID differential harness (#5940)

Measuring instrument for the ast-membrane design in #5940. No oracle: two
(or more) backends parse the same source, each emits per-node-path memento
records, and the records are diffed. Agreement or a named divergence at an
exact `file:node_path` -- never a fuzzy score.

## Scope note (read before extending)

This harness originally set out to also answer "does host CPython 3.12.3
agree with the 3.12.13 docker image on span semantics." That comparison has
been dropped as a deliverable per direction on #5940: the design no longer
proposes freezing CPython's span conventions as the spec ("We're not
freezing anything... There's segfaults, and that's about it"). Spans will be
defined as a pure function of source text, owned by us, and every provider
-- including CPython's `ast` -- normalizes into that definition or is
uninstalled. What survives from that abandoned direction:

- the harness shape (N providers, same source, diff per-node-path CIDs) --
  this is exactly the acceptance instrument the "provider that diverges is
  uninstalled, not debugged" rule needs.
- the golden corpus of span-quirky shapes -- these are the cases OUR span
  definition has to specify and that any future provider adapter must
  reproduce byte-identically.

The docker-mount attempt for the interpreter comparison hit the
known-unreliable battleaxe docker file-mount issue (whole-worktree bind
mount came up empty inside `ghcr.io/tsavo/sugar-env:task7-direct-python-scientific`
in this session) and was not chased further once the comparison was ruled
out of scope -- reported as a fact encountered, not a finding, and not
fixed.

## Files

- `memento_walker.py` -- given one source file, walks the FULL `ast` tree
  (every node CPython's `ast` module produces, in deterministic
  field-and-index order from `node._fields`, not `ast.walk`'s BFS order)
  and emits one JSONL record per node:

  ```json
  {"file": "...", "node_path": "module.body[0].value", "kind": "Call",
   "start_line": 3, "start_col": 4, "end_line": 3, "end_col": 40,
   "cid": "<sha256 hex of the UTF-8-byte-sliced source segment>"}
  ```

  `node_path` is the deterministic address: a chain of
  `.<field>` / `.<field>[<index>]` segments from `module`, built from
  `node._fields` order -- never from object identity, dict iteration, or
  `ast.walk`'s traversal order. Two independent walks of byte-identical
  source, on any interpreter whose `ast` grammar matches, produce the same
  node_path for "the same" node.

  `cid` is **not** production's `blake3_512` memento hash
  (`source_fragment.py`'s `memento()`). It is `sha256` over the exact
  source-segment bytes, chosen only so this stdlib-only probe runs without
  a `blake3` dependency inside the docker image (which lacks it). What is
  under test is segment/span STABILITY, not which hash function production
  uses -- if segments are byte-identical, any hash function agrees or
  disagrees together. The raw span fields (`start_line`/`start_col`/
  `end_line`/`end_col`) are the primary signal; a divergence there names
  which span component moved. Columns are UTF-8 **byte** offsets (spliced
  by encoding each line to UTF-8 and cutting on `col_offset`/
  `end_col_offset`), matching CPython's own column semantics rather than
  `ast.get_source_segment`'s character-based slicing.

- `diff_mementos.py` -- loads two JSONL streams keyed by `(file,
  node_path)`, reports:
  - `STRUCTURAL-ONLY-IN <label>: file:node_path` for any node_path present
    in one backend's tree and absent from the other's (louder than a CID
    mismatch -- the backends don't even agree the node exists at that
    address).
  - `DIVERGE file:node_path` with both backends' `kind`, span, and cid for
    any node_path present in both but disagreeing.
  - Exits non-zero on any divergence.

- `run_differential.sh <docker_image> [corpus_dir]` -- runs
  `memento_walker.py` over every `corpus/*.py` file on the host interpreter
  and inside the given docker image (mounting the WHOLE worktree at
  `/work`, per the known unreliability of individual-file docker mounts on
  this host; verifies the script is visible inside the container before
  running for real), diffs each file, prints a summary, exits non-zero on
  any divergence. Generalizes trivially to N providers by adding more
  backend invocations and pairwise (or all-vs-golden) diffs -- kept to two
  for now per the current ask.

- `generate_golden.py` -- regenerates `golden_mementos.jsonl` from
  `corpus/*.py` (sorted filename order, so the artifact is stable across
  runs) using the host interpreter. Full run: **0.10s** for 4 files / 1583
  node records on battleaxe host python 3.12.3.

- `golden_mementos.jsonl` -- the committed golden corpus artifact.
  1583 records across 4 files.

- `check_node_kind.py` -- prints the ast-derived NodeKind vocabulary
  (mirroring `node_kind.py:_ast_class_names()`'s leaf-class selection:
  concrete `ast.AST` subclasses only, abstract grouping bases like
  `expr`/`stmt` excluded) for the running interpreter. On host python
  3.12.3: **118 members**. Confirms `NodeKind` (`node_kind.py:62`, via
  `vars(ast)`) is interpreter-derived, per the #5940 design note --
  a new interpreter version can silently grow/shrink the wire vocabulary
  with no membrane event.

## Corpus

`corpus/quirks.py` -- hand-built shapes from the #5940 quirk list: f-strings
(plain, expr, format-spec, conversion, nested, multiline, nested-quotes --
span semantics changed in 3.12/PEP 701), parenthesized expressions (simple,
redundant, tuple, generator, walrus), decorated functions/classes (single
and stacked decorators), multi-line calls, implicit string concatenation,
lambdas (simple and full-signature), comprehensions (list/dict/set/nested/
generator), match statements (literal/sequence/mapping/class/wildcard
patterns), walrus operator (in `while`, in `if`), star-args (call-site
`*args`/`**kwargs` unpacking, def-site, unpacking assignment). 471 node
records.

`corpus/real_node_kind.py`, `corpus/real_source_fragment.py`,
`corpus/real_source_tables.py` -- copies (pinned at commit time, not live
symlinks) of `node_kind.py`, `source_fragment.py`, and `source_tables.py`
from the current membrane, as real-corpus coverage alongside the
hand-built quirks.

## Running

```
python3 tools/memento-cid-differential/generate_golden.py
./tools/memento-cid-differential/run_differential.sh <docker_image>
python3 tools/memento-cid-differential/check_node_kind.py
```
