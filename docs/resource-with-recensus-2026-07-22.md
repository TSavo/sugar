# Resource-`with` re-census (2026-07-22)

**Snapshot:** `c11e5f647` (post #6042 parametric exit / construction boundary closed)  
**Packages:** installed `numpy` + `pandas` under the local venv  
**Instrument:** `implementations/python/sugar-lift-py-tests/scripts/resource_with_recensus.py`  
**Artifacts:** `docs/resource-with-recensus.json`, `docs/resource-with-recensus-grouped.json`

No manager was enrolled. Production unauthenticated resource managers remain
`RuntimeSelectedContextManager`. `open` is **not** a special case.

## Boundary

| Axis | Count |
|------|------:|
| Python files scanned | **1,818** |
| `with` items (ast) | **11,535** |
| Shape `call_dotted` | **11,417** |
| Shape `name` (bound manager) | **104** |
| Other shapes | **14** |

Classification of manager **identity** (structural dotted call spelling as
written in source) against the committed community membrane spellings
(`pytest.raises`, `tm.assert_produces_warning`, `contextlib.suppress`):

| Bucket | Approx. mass (top-identity rollup) | Meaning |
|--------|-----------------------------------:|---------|
| **Assertion wired** | **8,189** | Membrane Expects/Suppresses already on production path |
| **Resource loud** | **~2,862+** (rest of identity mass) | Unauthenticated → RuntimeSelected residual |

Assertion mass is dominated by `pytest.raises` (6,353) and
`tm.assert_produces_warning` (1,836). Those are **not** resource-enrollment
work.

## Resource-loud groups (by manager identity)

Top unauthenticated call_dotted identities (not on the membrane):

| Count | Identity | Notes |
|------:|----------|--------|
| 348 | `tm.ensure_clean` | IO resource / temp path |
| 292 | `np.errstate` | Source-visible class; `__exit__` resets only (implicit None) |
| 273 | `open` | Builtin — **defer** to attested semantic manifest later; do not name-enroll |
| 252 | `option_context` | Pandas config CM; `__exit__` restores options, no True return |
| 194 | `warnings.catch_warnings` | Warning surface (not raise Expects) |
| 167 | `pytest.warns` | Warning Expects-shaped; not membrane-enrolled spelling |
| 148 | `assert_raises` | NumPy unittest alias — not `pytest.raises` |
| 142 | `ensure_clean_store` | HDF5 temp store |
| 135 | `pd.option_context` | Same family as `option_context` |
| 133 | `tm.assert_cow_warning` | Warning family |
| 74 | `assert_raises_regex` | Raises alias |
| 69 | `tm.raises_chained_assignment_error` | Raises-like |
| 54 | `temppath` | Temp path |
| 40 | `monkeypatch.context` | Pytest fixture CM |
| 37 | `util.switchdir` | `@contextmanager` try/yield/finally (known design representative) |
| 33 | `ExcelFile` | IO |
| 30 | `ExcelWriter` / `sql.SQLDatabase` | IO |
| 28 | `HDFStore` | IO |

## Grouping by exit-disposition **evidence** (not enrollment)

These buckets are for choosing the next **general proof rule**, not for
name-based admits:

| Evidence bucket | ~Mass | Role in next cut |
|-----------------|------:|------------------|
| **config_context_manager** (`errstate`, `option_context`, `config_prefix`, …) | **748** | Strong source-visible NeverSuppresses candidates: exit restores config and does not return True |
| **io_resource_manager** (`ensure_clean`, stores, Excel, temppath, …) | **654** | Need enter/exit construction; often suppress-never but bodies vary |
| **warning_observation_like** (`catch_warnings`, `pytest.warns`, cow warning, …) | **529** | Parallel to Expects(warning) — membrane spelling expansion, not NeverSuppresses |
| **raises_alias_not_on_manifest** (`assert_raises*`, chained assignment error) | **291** | Membrane spelling / alias expansion for Expects(raise) |
| **builtin_or_open_defer_manifest** (`open`) | **273** | **Do not** special-case by name; later attested builtin manifest |
| **source_visible_cm_candidate** (`util.switchdir`) | **37** | `@contextmanager` try/yield/finally → never-suppress (existing design) |
| **bound_name_manager** (`i`, `it`, …) | **47** | Manager is a bound name — identity is temporal, not a call spelling |
| **other_resource** | **~283** | Monkeypatch, SQL builders, get_handle, `contextlib.closing`, … |

## Source-visible `__exit__` that only returns None/False

Conservative linear-body scan found **13** methods (sample):

- `numpy/_core/_ufunc_config.py` — `errstate.__exit__` (reset only; **implicit None**)
- `numpy/lib/_npyio_impl.py`, `numpy/testing/...`
- `pandas/io/common.py`, excel, json, parsers, pytables, sas, sql, pickle tests

**Note:** `option_context.__exit__` has a simple `if` + loop and **no** `return True`,
but the conservative scanner rejected branching. The next proof rule must
allow branch-only restore bodies that never return a suppressing truth value.

`util.switchdir` is a generator CM (`try: yield finally: chdir`) — disposition
evidence is the existing try/yield/finally rule, not a class `__exit__` method.

## Recommended next proof rule (general path first)

**Name:** `source_visible_exit_returns_none_or_false`  
**Disposition issued:** `NeverSuppresses`  
**Rule (intent):**

1. Resolve the manager expression to a **source-visible** context-manager
   definition (class with `__exit__`, or `@contextmanager` generator).
2. Prove that exceptional exit **never** suppresses:
   - class `__exit__`: every return is `None` or `False` (or implicit None);
     no `return True`; branches allowed only if they share that property;
   - `@contextmanager`: `try: yield; finally: …` with no `except` that
     swallows (existing design).
3. Admit only through **`WithResourceSugar`** with constructed
   `ManagerRef` / enter / parametric exit — never a normal-path-only dissolve.
4. Leave unproved disposition as **RuntimeSelected** (explicit red).

### Explicitly not next

- Enrolling `open` by spelling.
- Guessing subclass exception matching for Suppresses.
- Treating membrane Expects/Suppresses residual mass as resource work
  (already wired for `pytest.raises` / `tm.assert_produces_warning` /
  `contextlib.suppress`; aliases like `assert_raises` are membrane spelling
  work, not NeverSuppresses).

### Suggested first general admits (after the rule exists)

Ordered by evidence + mass, **not** by name special-case:

1. **`np.errstate` / `errstate`** — class `__exit__` is restore-only; **~315** sites.
2. **`option_context` / `pd.option_context` / `cf.option_context`** — restore-only
   exit with branches; **~407** sites once branch-safe proof lands.
3. **`util.switchdir`** — try/yield/finally representative; **37** sites; already
   named in prior design docs.

IO managers (`ensure_clean`, Excel, HDFStore) and builtins (`open`) come after
the general rule is green and measured, not before.

## How to re-run

```bash
export PYTHONPATH=implementations/python/sugar-lift-py-tests/src:\
implementations/python/sugar-source-tree/src:\
implementations/python/sugar-lift-python-source/src

python implementations/python/sugar-lift-py-tests/scripts/resource_with_recensus.py \
  --packages numpy,pandas \
  --json docs/resource-with-recensus.json
```

Then re-group with the post-process in session notes / extend the script to
emit `resource-with-recensus-grouped.json` from the raw JSON + membrane spellings.
