# Sealed frontier closing account

Source receipt SHA-256: `cedb430388de1bd85b8bddcdc4d547a8dfcba3954e00e8930d8419bc936274b4`

Measured commit: `1b3ac2dd9675b00507ea438a7580306dd95015f7`

The closing account is derived from all 477 `constructionPanics` rows by the
selectors and exact `file:start` manifests in `closing-account.jq`. The
generated `closing-account.json` carries every original row identity and its
single assigned class.

| Class | Rows | Meaning at the measured first terminal |
|---|---:|---|
| deliberate membrane | 301 | 290 pytest-distribution and 11 stdlib targets explicitly outside the enrolled pandas population |
| boundary exposure terminating early | 70 | The row terminates before the population predicate; authenticated counterfactual ownership is outside enrolled pandas |
| landed defect | 95 | pandas was falsely off-population through path-derived roster seeding; fixed after this receipt by `25d1dc7d02e75275117d2b958721c299f0d50062` (#7227) |
| existing construct behind wrong entrance | 5 | Two `parser.read_csv` receiver-method rows and three same-module `FunctionDef` rows whose construction exists but is unreachable through the current entrance |
| entrance defect | 3 | Same-module class manager enrollment lacks the callsite body for `TextFileReader`, `HDFStore`, and `StataReader` |
| engine invariant | 3 | Construction recursion escapes at one `Module` and two `FunctionDef` roots |
| **Total** | **477** | Exact row-identity union |

Validation: 477 accounted, zero uncovered, zero multiply classified, and zero
duplicate stable row identities. The generated JSON SHA-256 is recorded by the
handoff report.

The five existing-construct rows are two distinct entrance surfaces, not one:

- `tests/io/parser/common/test_chunksize.py:53` and
  `tests/io/parser/common/test_iterator.py:42` use a fixture/formal
  receiver-method entrance to pandas `TextFileReader`, which already owns
  `__enter__`/`__exit__`.
- `io/formats/format.py:1044`, `io/sql.py:354`, and `io/common.py:405` use a
  missing same-module `FunctionDef` entrance. Existing import-backed
  `FunctionDef` construction machinery is present. The `urlopen` row may expose
  a stdlib boundary next; that descendant is currently masked and unmeasured.

Caveats:

- 477 is a **FIRST-TERMINAL LOWER BOUND**.
- Descendants behind each first terminal remain masked.
- 944/1421 is attendance testimony, not completion.
- Files-unblocked means the current first terminal **MOVES**; it does not mean
  the file completes or remaining work falls by that count.
