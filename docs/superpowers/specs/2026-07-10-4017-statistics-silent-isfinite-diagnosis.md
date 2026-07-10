# #4017 Diagnosis: statistics silent `assert not _isfinite(...)` (Minority Report first indictment)

**Status:** DIAGNOSIS ONLY — no fix until greenlight.  
**Branch/worktree:** `.worktrees/4017-statistics-silent-isfinite` @ `origin/main` (`04bd18ebb`, #4015)  
**Issues:** Part of #4017 / #4016 / #4013 / #3809  

## Headline (instrument)

Full stdlib `statistics.py` through `build_literal_call_report` + dual-axis coverage:

| majority | value |
|----------|-------|
| stated | 4 |
| lifted+cited | 1 |
| silently_unaccounted | **3** |

**Lifted (1):** `_coerce` — top-level body assert `assert T is not bool` → `IdentityAssertionSugar`, warranted.

**Silent (3):** vendor's own claims, never presented to the factory:

| function | parent nesting | claim |
|----------|----------------|-------|
| `_sum` | `If` → FunctionDef | `assert not _isfinite(total)` |
| `_ss` | `If` → `If` → FunctionDef | `assert not _isfinite(ssd)` |
| `_exact_ratio` | `ExceptHandler` → `Try` → FunctionDef | `assert not _isfinite(x)` |

(Line numbers vary by CPython version; battleaxe probe used 200/237/323; local 3.14 used ~1502/1544/1612. Identity is the claim + nesting, not the line.)

## WHERE dropped

**Stage:** assertion-surface **enumeration** in the Python kit lift path — **before** factory recognizer / desugar.

**File:** `implementations/python/sugar-lift-py-tests/src/sugar_lift_py_tests/factory/literal_call_report.py`  
**Function:** `build_literal_call_report`  
**Boundary (~348–350):**

```python
for fn in local_functions.values():
    for stmt in fn.function_body():   # direct children of FunctionDef only
        if stmt.observed != "Assert":
            continue
        lifted = _lift_assert(...)
```

Nested `Assert` under `If` / `Try` / `ExceptHandler` / … never enter `_lift_assert`, never hit the catalog, never appear in `sourceAudits` / factory walk → coverage `silently_unaccounted`.

**Not:** factory `owns()` miss for `Not`+Call. **Not:** desugar Incomplete. **Not:** coverage miscount (independent disk census correctly sees 4 asserts; report only speaks about 1).

## WHY — exact shape

**Hypothesis from the campaign brief was wrong for this indictment.**

| Hypothesis | Result |
|------------|--------|
| unary `not` over opaque `_isfinite` missing recognizer | **False** — shape already lifts when enumerated |
| `_isfinite` callsite opacity blocks fact | **False** — lifts as `call:_isfinite` + `py.truthy` |
| something else | **True** — **nested assert never enumerated** |

The silencing shape is structural nesting, not formula shape:

```
FunctionDef.body  ──walked──►  Assert          ✓ lifted
FunctionDef.body  ──walked──►  If.body  ──►  Assert   ✗ never visited
FunctionDef.body  ──walked──►  Try.handlers  ──► Assert  ✗ never visited
```

## Probes (instrument, not guess)

| probe source | result |
|--------------|--------|
| plain `assert not _isfinite(total)` (direct body) | **lifts** via `NotSugar` → child `CallTruthAssertionSugar`; inv `not(py.truthy(call:_isfinite(total)))`; warranted; silent=0 |
| same under `if None in partials:` | report never sees assert → silent (or empty report if sole assert) |
| same under `except (OverflowError, ValueError):` | same |
| full `statistics.py` | 1 top-level / 3 nested → silent=3 |

Existing unit coverage already proves the polarity path: `test_not_sugar.py` (`assert not checks.is_td64(1)` → NotSugar + CallTruth).

## Factory path when claim *is* presented (works today)

1. `NotSugar.owns` — `Assert` whose test is `UnaryOp`/`Not`
2. Child assert built for operand Call → `CallTruthAssertionSugar` (if `can_symbolic_term`)
3. Desugar: `not_(py.truthy(call:_isfinite(...)))` or equivalent
4. `_emit_assertion_surface_fact` → source audit warranted

No new recognizer required for the *formula* shape.

## Fix shape (proposal — not implemented)

**Not** a new `_isfinite` / `not`-call factory sugar.

**Yes:** make assertion-surface enumeration **total** over nested control-flow so each nested `Assert` still goes through existing `_lift_assert` → catalog → existing sugars. No reducer/inline/partial-eval bypass; no fabricated claims; ratchet greens only because silent loci become warranted.

Concrete change site: replace flat `fn.function_body()` Assert filter in `build_literal_call_report` with a recursive collector of all `Assert` under the function (If/Elif/Else, Try/Except/Finally, For/While, With, …), still calling `_lift_assert` per locus.

Teeth still required: truthful nested `assert not _isfinite(...)` → SAT/discharged; lying twin → UNSAT.

## Design call?

**Mild seam, not a core-factory design rewrite.**

| question | answer |
|----------|--------|
| Clean mechanical factory recognizer addition? | **No** — recognizer already exists |
| Core design decision? | **Seam = assertion-surface enumerator totality** in `build_literal_call_report` (who gets presented to the factory), not a new Sugar class |
| Alternative seams | (B) control-flow sugars emit nested assertion surfaces only when dig walks them — more invasive, dig-coupled; (A) total recursive assert collect — preferred |

Await greenlight on (A) vs other before coding.

## Generalization

**Generalizes.** Fix is “enumerate every Assert under a function,” not statistics- or `_isfinite`-specific.

Any vendor assert nested in `if` / `try` / `for` / `with` / … that today is silently unaccounted for the same reason will become a factory candidate. Shapes the catalog already owns (NotSugar, CallTruth, comparison, identity, …) will lift; shapes it doesn't will become **refused-loud** (accounted) rather than silent — still majority-gate progress.

Statistics is only the first *observed* indictment because #4015's dual-axis report first ran on it.

## DoD reminder (when greenlit)

- 3 asserts lifted+cited (not dropped, not fabricated)
- `silently_unaccounted → 0`; ratchet green because silenced testify
- bad-twin flip; do not touch ratchet to force zero
- receipts: before/after coverage, bad-twin, witness corpus 55/55
- PR: “Part of #4017” + “Part of #4016” + “Part of #3809” (never closes/fixes)
- author: `T Savo <evilgenius@nefariousplan.com>`
