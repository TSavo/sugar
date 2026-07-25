# `pyproject.toml[test]` sole dependency authority

**Status:** Class closed on main via **#6275** (`ci: make sugar-lift-py-tests[test]
the sole dependency authority`). This branch (#6268) merges residual same-class
siblings that #6275 did not touch:

- `examples-gate.yml` — install via `-e '...sugar-lift-py-tests[test]'`
- `Makefile` `test-python` loops — no free-floating pytest/blake3/numpy/pandas

## Authority

```toml
# implementations/python/sugar-lift-py-tests/pyproject.toml
dependencies = [blake3, pynacl, cbor2, tqdm, ...]
[project.optional-dependencies]
test = [pytest, black, pyright, itsdangerous, numpy, pandas]
```

Workflows install only `-e '...sugar-lift-py-tests[test]'` (+ sibling editables).

## Class instrument

`tests/test_test_extras_are_the_dependency_authority.py` (landed in #6275):

1. Every authority install is `-e ...[test]`
2. No workflow hand-lists an authority-owned package
3. Module-scope third-party imports in collected tests must be declared
4. Workflow-only pins cannot satisfy tooth 3
