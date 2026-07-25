# Hand-out: `pyproject.toml[test]` sole dependency authority

**Status:** IMPLEMENTED on `fix/pyproject-test-sole-dep-authority`.  
Class closed: instrument + six class members + same-class siblings
(`ci.yml`, walls, `examples-gate`, Makefile `test-python`).

## Crime

Six Python workflows invent their own `pip install` package lists (bare
`pytest`, ad-hoc `blake3 pynacl cbor2`, free-floating `tqdm`, separate
`numpy`/`pandas` pins). That is six *instances* of dependency authority.
The *class* is: workflow YAML is not allowed to name a test dependency that
`implementations/python/sugar-lift-py-tests/pyproject.toml` `[project.optional-dependencies].test`
(and package `dependencies` for runtime) does not already own.

Authority lives in one place:

```toml
# sugar-lift-py-tests/pyproject.toml
dependencies = [blake3, pynacl, cbor2, tqdm, ...]
[project.optional-dependencies]
test = [pytest, black, pyright, itsdangerous, ...]
```

Workflows only install packages: `-e '…/sugar-lift-py-tests[test]'` (+ sibling
editables that are *packages*, not free-floating pins). No bare `pytest`.
No re-listing blake3/pynacl/cbor2. Corpus inputs (numpy/pandas) become named
extras if they must ship with test authority, not one-off workflow lines.

## The six workflows (class members today)

| Workflow | Current sin |
|----------|-------------|
| `bare-exception-zero-tolerance.yml` | bare `pytest` + non-`[test]` install |
| `native-crash-zero-tolerance.yml` | same |
| `timeout-zero-tolerance.yml` | same |
| `factory-zero-tolerance.yml` | bare `pytest` + free-floating `tqdm` |
| `datetime-claim-twins.yml` | already uses `[test]` (keep; no drift) |
| `restored-suite-scoreboard.yml` | `[test]` + free-floating `pandas` |

Related drift outside the six (same class, fix if cheap in the same PR):

- `ci.yml` core/showcases: `blake3 pynacl cbor2 pytest` re-listed
- `examples-gate.yml`: `blake3 pynacl cbor2`
- `numpy-wall.yml` / `pandas-wall.yml`: separate corpus pip lines
- `Makefile` `test-python` package loops: ad-hoc `pytest blake3 …`

## Fix shape (closes the class)

1. **Expand authority only in pyproject** — whatever the six workflows need
   that is missing from `dependencies` / `test` lands there once (e.g. put
   corpus pins in named extras `numpy` / `pandas` / `walls` if required, not
   in YAML).
2. **Rewrite each of the six** install steps to:
   ```bash
   python -m pip install -e 'implementations/python/sugar-lift-py-tests[test]' \
     -e implementations/python/sugar-lift-python-source \
     # + other *editables* only as needed
   ```
   No bare package names except editables and documented extras.
3. **Red instrument that closes the class** — a discrimination test or
   `make check-…` that greps `.github/workflows/*.yml` (and optionally the
   Makefile python install loops) for free-floating pins of packages that
   belong in pyproject (`pytest`, `blake3`, `pynacl`, `cbor2`, `tqdm`,
   `black`, `pyright`, `itsdangerous`, …). Green only when every install is
   editable+extra shaped. One red forever if a seventh workflow re-invents
   the instance.

## DoD

- All six workflows install test deps only through `sugar-lift-py-tests[test]`
  (and declared extras).
- Class-level instrument is red if any workflow reintroduces a free-floating
  pin of an authority package.
- No semantic construction change. No census claim. No Assign/Try collision.

## Do NOT

- Vendor per-workflow requirement files
- Soften discrimination floors while rewriting installs
- Touch Try / ExitSet / Assign / census residual claims
- "Fix" one workflow and leave the class open

## Validation

```bash
# after rewrite
rg -n 'pip install.*\b(pytest|blake3|pynacl|cbor2|tqdm)\b' .github/workflows/
# should only match through [test] / documented extras, not bare lists

make check-pyproject-test-dep-authority   # or the twin you add
```
