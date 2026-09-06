# Write the With sugar: from 0 constructed to the population

> Board of record: control-effect recensus run 33982802518, `main` = `4089c6b1d4`
> (2026-09-05, first sealed board since Aug 17). Every number below is from
> that board or the pinned pandas 3.0.3 corpus it measured.

## The axis, stated correctly

The 222 file-level construction panics are the tip. The With census on the
same board is:

```
with-items      8,057
  constructed       0      <- semantics derived from source or a published contract
  cited-opaque  5,812      <- "we know which callee; we declined to look inside"
  unconstructed 2,245      <- typed resolution gap
```

**Zero With sites have constructed semantics.** Citing is honest — it never
lies about suppression — but it decides nothing: every `pytest.raises`
harness verdict today is *unwitnessed*. "Write the sugar" means moving
`constructed` from 0 toward 8,057 with derived enter/exit semantics that the
twins can refute, and letting `cited-opaque` fall to the handful of managers
whose implementation is genuinely outside our knowledge (third-party C).

Conservation law stays: `constructed + cited-opaque + unconstructed = 8,057`
on every board.

## What the 8,057 actually are (manager head, from the corpus)

| family | sites | today | what its semantics ARE |
|---|---:|---|---|
| `pytest.raises(E, match=…)` | 5,815 (5,549 with `match=`) | cited 5,703 / gap 112 | Expects-Raise boundary: no raise → Halt(Failed "DID NOT RAISE"); raise ∈ E ∧ match → suppressed, completed; raise ∈ E ∧ ¬match → Halt(Failed); raise ∉ E → propagate |
| `tm.assert_produces_warning` | 750 | gap | Expects-Warning boundary over `warnings.catch_warnings(record=True)`; exit asserts the recorded set |
| `option_context` / `pd.option_context` / `cf.option_context` / `cf.config_prefix` | 401 | gap | pandas `@contextmanager` generators: set module-global option dicts, yield, restore in `finally`; never suppress |
| `open` / `BytesIO` / `StringIO` / `gzip` / `bz2` / `lzma` / `zipfile` / `tarfile` / `tempfile.*` / `subprocess.Popen` | ~215 | gap 163 / cited ~52 | `_io` protocol: enter → self; exit → `close()`; never suppresses. Wrappers are pure Python over `_io` |
| pandas resource classes: `ExcelFile` 55, `ExcelWriter` 32, `HDFStore` 31, `sql.SQLDatabase`/`pandasSQL_builder`/`run_transaction`/`conn.*` ~110, `StataReader`/`read_stata` 31, `TextFileReader`/`parser.read_csv` 22, `get_handle` 30, `read_json` 9 | ~320 | gap | class `__enter__: return self` / `__exit__: self.close()`; bodies bottom out on `open` and third-party drivers |
| `np.errstate` | 92 | gap (dynamic-export) | pure-Python class over a contextvar: enter sets, exit resets; never suppresses |
| `tm.raises_chained_assignment_error` 58, `tm.external_error_raised` 47, `tm.set_timezone` 9, `tm.decompress_file` 9, `com.temp_setattr` 9 | 132 | gap (source-body-gap) | in-population generators delegating to the families above |
| fixture-supplied: `monkeypatch.context` 43, `ctx` 17, `capsys.disabled`, `temp_file.open`, `cleared_fs.open` | ~70 | gap (runtime-selected) | receiver is a pytest fixture formal; `MonkeyPatch.context` is `yield self / finally: undo()` |
| `warnings.catch_warnings` 44, `contextlib.closing` 27, `suppress` 11, `ExitStack` 1 | ~83 | cited | stdlib pure Python; `suppress` IS a Suppresses-Raise boundary |
| `matplotlib.rc_context`, `IPython…provisionalcompleter`, `tables.open_file`, `fsspec.open` | 12 | gap (not installed) | unreachable under this pin behind `pytest.importorskip` |

Two managers are 81% of the population: `pytest.raises` and
`assert_produces_warning`. Both are *assertion* managers — the directive's
"assertion-With milestone" — and both are undecidable today.

## Why constructed is 0 — the two walls

1. **The population membrane.** `_is_off_population` refuses to materialize
   anything not in `enrolled_distributions` (= `{pandas}`) and refuses
   `artifact_kind == "stdlib"` wholesale. So `pytest`, `contextlib`,
   `warnings`, `io`, `numpy` are cited at the door, and every in-population
   manager whose body touches them (`external_error_raised` → `pytest.raises`,
   `raises_chained_assignment_error` → `nullcontext`, `set_timezone` →
   `os.environ`) dies as `source-body-gap`.
2. **No language-owned semantics for the C floor.** `_io.open`, `re.search`,
   `time.tzset`, `contextvars`, `os.environ` have no Python body to derive
   from. Today they are `force-floor` / `target-outside-binding`.

Everything else (dynamic exports, fixtures, resource classes) is downstream of
those two.

## The cuts, in dependency order

Each cut is a general mechanism from a concrete corpus reproducer, gated by
the directive: reproducer, truthful twin, lying twin, focused tests, no
increase on the crash/timeout axes. Re-measure on the board only at the two
milestones and at closure.

### Cut 0 — attribution instrument (½ day)
`withResolutionRows` carry only coordinates. Add the resolution `kind`
(and `targetSymbol` when present) to each row so the 2,245 unconstructed
rows are classifiable without re-reading the corpus by hand. Not a new
census; the same rows, one more field.

### Cut 1 — enroll authenticated source populations (the membrane law)
**Mechanism.** The pin's `distribution` becomes an *enrollment roster*:
`{pandas, pytest, numpy-python, stdlib-python}`, each authenticated by the
environment identity (`resolved-distributions.txt`, the stdlib root CID).
`_is_off_population` refuses only what the roster does not name. C-implemented
modules (`_io`, `_sre`, `posix`, `umath`) are never "in population" — they get
Cut 2's language-owned semantics. Session memo already amortizes
materialization per source CID; the LPT prior absorbs the cost.
**Reproducer.** `pandas/_testing/contexts.py:127` (`nullcontext()` body →
`value-call-target:nullcontext`, 17 rows).
**Twins.** `with nullcontext(): x = 1` → Completed, never suppresses
(truthful); a `nullcontext` claimed to suppress a raise → refuted (lying).
**Risk.** Per-file measurement ceiling (#7415). Enroll `contextlib` first and
measure the timeout axis before `warnings`/`re`/`tempfile`/`zipfile`.

### Cut 2 — language-owned semantics for the C floor (runtime-identity keyed)
The `BuiltinSemanticCallable` value already keys operations to
`PythonRuntimeIdentity`. Extend it — never a name table — with the closed set
of C-floor laws the corpus actually needs, each carried as a term the harness
can refute:
- `_io` resource protocol: `__enter__` → self (total), `__exit__` →
  `close()`, `NeverSuppresses`. Covers `open` (150), `BytesIO`/`StringIO`
  (13), and is the floor under `gzip`/`bz2`/`lzma`/`zipfile`/`tarfile`/
  `tempfile`, `get_handle`, and every pandas reader/writer.
- `re.search(pattern, string)` as a **pure function** on concrete strings —
  a real matcher for the subset the corpus uses (literals, `re.escape`,
  `^ $ | . * + ? \d \w \s [..] (..) (?:..)`), refusing loudly on anything
  outside the subset. On a symbolic string it stays a factored predicate
  (both faces kept). This is the single decision that makes 5,549 `match=`
  sites decidable instead of unwitnessed.
- `time.tzset`, `contextvars.ContextVar.set/reset`, `os.environ` (a mutable
  mapping whose stores are `RuntimeEffect`s on module-owned state).
**Reproducer.** `with open(p) as fh: return fh` (150 sites).
**Twins.** exit never suppresses: a raise inside `with open(...)` propagates
(truthful); the same site asserted as suppressed → refuted (lying).

### Cut 2 — status 2026-09-05 (first increment landed)

The **matcher core is built and tested**, decoupled from the wiring:
- `floor/re_subset_matcher.py` — `validate_pattern` is the sole authority on
  the decidable subset (refuses look-around, back-references, named-group
  back-refs, conditional/atomic groups, possessive quantifiers, the global
  inline-flags prefix — each by name); a validated pattern is executed by the
  authenticated runtime's own `re` (`PythonRuntimeIdentity` is the key), which
  IS the definition of the answer for the subset. Returns a bounded
  `RegexMatchSpanV1` or None.
- `floor/re_match_value.py` — `ReMatchValue`: subject + spans, unconditionally
  truthy (a Match always is), `group_text(n)` decidable; None-match is
  `NoneValue` (falsy).
- `BuiltinSemanticCallable` gained `python.re.search/match/fullmatch`: concrete
  `StringValue` operands only; symbolic operands or out-of-subset patterns keep
  the call loud (`ConstructionPanic`), never a guessed (non-)match.
- Twins: `test_re_subset_matcher` (26 — every subset case agrees with the
  runtime; every refused construct refuses by name; bad pattern is loud) and
  `test_re_semantic_callable` (6 — truthful/lying search, anchored match/
  fullmatch, group recovery, symbolic + out-of-subset stay loud).

**Not yet wired (the remaining half of Cut 2):** recognizing an authenticated
import target `python:re.search` at call resolution and binding the callee to
`BuiltinSemanticCallable(operation="python.re.search")`. Today `re.search`
resolves to an `ImportMemberValue` / seated cpython frame that bottoms out at
`_sre`. The wiring must sit at the authenticated-import call door (NOT the
spelling), the same door `pytest.raises`'s `match=` flows through. BLOCKER:
the re-authentication seating path (`test_regex_search_dependency_authority`,
`test_regexflag_relative_member_seating`) has ~9 pre-existing failures; those
must go green before the C-floor recognition can hang off a trustworthy
authenticated target. `_io.open` and the other C-floor callables take the same
recognition door once it exists.

### Cut 3 — derive `pytest.raises` (5,815 sites) — *assertion-With milestone, part 1*
With pytest enrolled, `_pytest/raises.py::RaisesExc.__exit__` derives through
the existing generator/class doors into a **factored** effect boundary
(`FactoredSourceDerivedContextManagerRefV1`, consumer already admits
Expects/Suppresses Raise/Warning faces):
`{no raise → Halt(Failed)}`, `{raise ∈ E ∧ match → Completed, suppressed}`,
`{raise ∈ E ∧ ¬match → Halt(Failed)}`, `{raise ∉ E → propagate}`.
`isinstance` is already a `BuiltinSemanticCallable`; `match` is Cut 2's
`re.search`; `fail()` raises pytest's `Failed` (pure Python).
The 112 `unconstructed` spellings (`import pytest` inside the function
body, `raises` as a fixture) resolve through the same door once local
imports produce value receipts (check in Cut 0's attribution).
**Twins.** `with pytest.raises(ValueError, match="bad"): raise ValueError("bad")`
→ Completed (truthful). `with pytest.raises(ValueError): pass` → the test
must be *refuted* as Failed, never "sat" (lying). A `match` that does not
match the concrete message → refuted.
**Prize.** `cited-opaque` 5,812 → ~110; the pandas test harness verdicts stop
being unwitnessed by construction.

### Cut 4 — derive `assert_produces_warning` (750) — *assertion-With milestone, part 2*
`pandas/_testing/_warnings.py` is a `@contextmanager` over
`warnings.catch_warnings(record=True)` + `simplefilter` + post-yield
assertion. Needs `warnings` (stdlib pure Python, Cut 1) with its module-global
filter list as owned mutable state (the `MutableGlobalBindingV1` scan already
exists), and `WarningEffectKindV1` faces (consumer ready). Also covers the
44 direct `warnings.catch_warnings` sites and `pytest.warns`.
**Twins.** body warns the expected category → Completed; body silent →
refuted (`AssertionError: Did not see expected warning`).

**Milestone measurement** after Cuts 1–4: expect `constructed` ≥ 6,500.

### Cut 5 — pandas generator managers (401 + 132)
`option_context`, `config_prefix`, `temp_setattr`, `set_timezone`,
`decompress_file`, `raises_chained_assignment_error`,
`external_error_raised`: all `@contextmanager` generators over
module-global dicts / `os.environ` / Cuts 3–4. The generator-backed door
(`_publish_generator_backed_resource_contract`) exists; what fails today are
the body floors, which Cuts 1–2 remove. `raises_chained_assignment_error`
is a two-face partition (`nullcontext` | `assert_produces_warning`) — the
factored ref carries both faces; the `CHAINED_WARNING_DISABLED` module pin
decides which face is live at the pin.

### Cut 6 — diagnosis pinned 2026-09-05 (frame-door __init__ field seeding)

Localized to the exact seam. `ClassDefinitionValue.construct_receiver_state_from_block`
is handed the reduced constructor body:
- same-module path:  `BlockValue[ReceiverFieldStoreValue]` -> receiver fields `{'r'}` (correct)
- import/frame-door: `BlockValue[ObjectValue(empty)]`      -> receiver fields `{}`   (bug)

i.e. `self.r = r`'s `post_state` reduces to a fresh empty `ObjectValue` instead
of a `ReceiverFieldStoreValue` on the frame door, because the constructed-
receiver coordinate minted by `ClassDef._source_visible_body`
(`BindingCoordinateV1.mint(self.fragment.seal().cid, receiver_param.fragment,
("receiver", 0))`) is not matched when the class was materialized under the
frame-door producer reporter. Fix is in the post_state reduction's receiver-
coordinate match, and must not regress same-module manager construction.
Pinned by `test_frame_door_init_field_seeding.py` (xfail strict -> xpass when
fixed). This is what blocks `contextlib.nullcontext` and the pandas resource
classes from deriving once enrolled.

### Cut 6 — pandas resource classes (~320) — *resource-With milestone*
`ExcelFile`, `ExcelWriter`, `HDFStore`, `StataReader`, `TextFileReader`,
`IOHandles`/`get_handle`, `SQLDatabase`: class `__enter__`/`__exit__` derive
through `construct_manager_protocol` once `open` (Cut 2) is a floor and
`contextlib.closing` (Cut 1) derives. Third-party drivers (`openpyxl`,
`pyarrow`, `sqlalchemy`, `tables`) stay **cited** at their own boundary —
inside the derived `__exit__`, not at the With head — so the With constructs
with real "never suppresses" semantics and only the driver call is opaque.
`HDFStore` / `tables.open_file` / `matplotlib` / `IPython` / `fsspec`: not
installed at this pin; `pytest.importorskip` (pytest enrolled) derives to
`Halt(Skipped)`, making those bodies **unreachable under this pin** rather
than gaps. A distinct row kind, and the honest answer.

**Milestone measurement** after Cuts 5–6: expect `unconstructed` ≤ 300.

### Cut 7 — export algebra: static-first, `__all__` transitive (92 + 8)
`numpy/__init__.py` and `pandas/__init__.py` both carry module `__getattr__`,
so the export door cites everything they export as `dynamic-export` even
when the name is statically bound (`from pandas.io.pytables import HDFStore`)
or reachable through a statically evaluable `__all__` (`from ._core import
*` + `__all__.extend(_core.__all__)`). Law: resolve static bindings first;
evaluate `__all__` as a constant list algebra (literals + `extend` of other
modules' `__all__`, transitively); fall to `dynamic-export` only when the
name is bound by neither. Then `np.errstate` derives (Cut 1 numpy-python +
Cut 2 contextvars).

### Cut 8 — fixture-supplied receivers (~70)
`monkeypatch.context()` etc.: the receiver is a formal bound to an
authenticated pytest fixture (`test_fixture_supplied_resource_obligation.py`
already partitions the temp-file population by formal). Law: a method call
on a fixture formal resolves through the fixture definition's return/yield
type (`monkeypatch` → `MonkeyPatch`), then the ordinary class door.
Bare-Name heads (`ctx`) go through the existing reaching-binding projection
once their producer call resolves.

### Cut 9 — the 26 non-With rows (bugs; any time, ideally first)
Status 2026-09-05: landed with Cut 0 ("Cut 0 + Cut 9" commit).
- canonicalize `frame-is-none` (9): every in-population class constructor
  call has a resolved ClassDef and no constructor frame anywhere; the
  checker called that absence a mismatch. Absence is a lie only when the
  table seats a frame at the coordinate and the sugar dropped it. **Done.**
- canonicalize `mappings require string keys` (8): `source_call_frame_table`
  is a lookup aid keyed by coordinates, not testimony; a frozen field
  declared `metadata={"testimony": "lookup"}` is excluded from the
  ConstructedValueV2 walk. **Done.**
- `RecursionError` (6): not deep bodies — a call-graph cycle
  (`ensure_key_mapped <-> _ensure_key_mapped_multiindex`) re-entering the
  callee's universe/frame inline. Recursion is a seat: re-entry into a
  definition under construction raises at the door and the asking call
  carries the definition with a `call-graph-cycle` gap. Fixpoint
  *semantics* (an unfolding bound) is a later law; the seat is the honest
  shape today. **Done.**
- `Lambda.sugar` (1): `LambdaSugar` existed only after body substitution;
  a lambda as a default formal is asked for before that. Substitute first,
  then construct. **Done.**
- `python.super` (1): **deferred, designed.** Zero-argument `super()` reads
  `__class__` and the first formal from the temporal, and nothing seats
  `__class__` today. The law: a method universe owned by a ClassDef carries
  one class-cell coordinate (the `ConstructedReceiverRef` precedent for
  initializers), seated by the class enumeration entrance.
- `SymbolicValue.attribute` (1): `pd.array` on a dynamically exported
  `pandas` — this is Cut 7 (export algebra), not a bug.

## Order and why

```
Cut 9 (bugs) ─┐
Cut 0 (rows)  ├─> Cut 1 (populations) ─> Cut 2 (C floor) ─> Cut 3 (raises) ─> Cut 4 (warnings)  == assertion-With milestone
              │                                        └──> Cut 5 (generators) ─> Cut 6 (resources) == resource-With milestone
              └────────────────────────────────────────────> Cut 7 (exports) ─> Cut 8 (fixtures)  == closure
```

Mass follows the order: Cuts 1–4 are ~6,600 of 8,057 sites and are the
directive's first milestone; Cuts 5–6 are ~450; Cuts 7–8 ~170.

## What "not paper" means, concretely

- No name/site arms. Every cut is a door (membrane, C-floor value, export
  algebra, fixture typing) or a derivation through doors that already exist.
- Citing survives only where knowledge genuinely ends: third-party C
  drivers, and only at the driver call, never at the With head.
- Every constructed With carries semantics a lying twin can refute:
  `pytest.raises` with no raise must come out **Failed**, not unwitnessed.
- The board is the judge: `constructed` on `cmResolutions`, conservation
  intact, timeouts and crashes at 0.

## Known unknowns to measure at Cut 0

- Gap-kind distribution of the 2,245 (which `open`/`pytest.raises` spellings
  are `runtime-selected` vs `no-derived-contract`).
- Measurement-ceiling cost of enrolling `warnings`, `re`, `tempfile`,
  `zipfile` (Cut 1 risk; measure per module).
- How many `match=` patterns fall outside the Cut 2 regex subset (expect a
  handful of look-arounds; refuse loudly, count them).
