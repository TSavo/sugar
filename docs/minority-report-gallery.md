# Minority Report gallery

> Campaign index for the dual-axis lift-coverage wall.
> Part of [#4016](https://github.com/TSavo/sugar/issues/4016) · Part of [#4013](https://github.com/TSavo/sugar/issues/4013).
>
> **This is the product front page** — per vendor, who testified vs who is in the
> `Minority Report`. PyCon showcase surface. Not a coverage vanity chart.

---

## Doctrine

### The report is the consensus; the Minority Report is the outlier

**The report** is the default accounting of what there is to report: assertions
partitioned into `lifted+cited` / `refused-loud` / `silently_unaccounted`. It
needs no qualifier. It is the consensus on the page — the claims that made it
into the accounting.

There is no second named report section alongside the default accounting.
[#4013](https://github.com/TSavo/sugar/issues/4013) naming correction (quoted,
with the scrubbed non-name omitted):

> **That's just the report** — the default accounting of what there is to
> report (assertions, accounted/refused-loud/silently-unaccounted). It needs
> no qualifier because it is the thing itself.
>
> **`Minority Report`** is the ONE named section, and it names what the report
> **underreports**: the bodies that fall below the reporting threshold because
> no assertion ever spoke to them.

**`Minority Report`** is the statistical outlier off the curve — the named roll
call of bodies present but never asked (`file:line`). By construction it sits
under the green and indicts the consensus: verification scope that the report
structurally cannot cover (no claim → nothing to report) is dragged onto the
page instead of vanishing. Flagging that 1% — where silence, forged warrants,
and unclaimed surface hide under everyone else's green — **is the product**.
Not "everything's fine." *Here's the one thing off the curve everyone's green
missed.*

The section header string in `sugar lift --report` is exactly `Minority Report`
([#4013](https://github.com/TSavo/sugar/issues/4013), [#4015](https://github.com/TSavo/sugar/pull/4015)).

### The two crimes (assertion ↔ dig correspondence)

The honest law is a **correspondence between vendor assertions and digs**.
There are exactly two ways to break it ([#4016](https://github.com/TSavo/sugar/issues/4016)
comment, quoted):

#### Crime 1 — a vendor assertion that warrants no fact AND no dig

> The vendor stated a claim and it produced nothing: didn't become a
> warranted+cited fact, didn't trigger a dig into the body. **The voice we
> silenced.**
>
> - Shape: `stated → ∅`.
> - Violates: *vendor tests ARE the spec* — the stated must land.
> - Measured today: `silently_unaccounted` on the assertion axis (#4013).
> - First indictment: `statistics.py:200/237/323` (#4017).

Live detector: [#4015](https://github.com/TSavo/sugar/pull/4015). Gate:
`silently_unaccounted == 0` → **RED** with `file:line` when residual > 0.

#### Crime 2 — a dig grounded in no assertion, flooring into a literal or an effect

> The substrate interrogated a body with no charge behind it and bottomed out
> by resolving to a literal or an effect that no vendor claim asked for. **The
> warrant we forged.**
>
> - Shape: `dig → literal | effect, ⊥ stated`.
> - Violates: *no fact computed outside* (ONE CONSTRUCTION) — the grounded must
>   trace back to a stated assertion; a literal/effect may be floored into ONLY
>   under an assertion's warrant.

Live detector: [#4020](https://github.com/TSavo/sugar/pull/4020). Gate:
`forged_warrant == 0` → **RED** with `file:line` when residual > 0.

#### The law

> Substrate is honest iff the two sides are in exact correspondence: every
> stated assertion lands as a fact or a dig (no Crime 1), and every dig grounds
> back to a stated assertion, flooring into a literal/effect only under a
> warrant (no Crime 2). No claim vanishes; no ground appears unstated.

#### Not a crime (do not prosecute)

> A body with no vendor claim and no dig = **voiceless**, honestly named in the
> Minority Report. Fabricating a claim for it would itself be Crime 2 (a forged
> warrant).

Voiceless (`un_asserted`) is **reported, not gated red**. Silenced
(`silently_unaccounted`) is the injustice the campaign prosecutes
([#4016](https://github.com/TSavo/sugar/issues/4016)).

### The product is the Minority Report

The deeper inversion: the whole **product** is the `Minority Report`, because
it is the only part that can affect the future.

- **Under contract is expected.** Code consistent with a vendor (numpy, etc.)
  — the parts *under contract* — is EXPECTED. Boring. Contracted code is
  deterministic and known; it cannot surprise you, therefore it cannot hurt
  you. The green wall of proofs is that comfort: reassurance that what was
  claimed held.
- **Danger lives off contract.** The danger that flaps in the night is **not**
  the parts under contract. It is the **un-contracted surface** — bodies,
  paths, usages no assertion governs. That is the only part that can actually
  affect the future (the unpredicted incident).
- **Green is comfort; the Minority Report is intelligence.** So the green wall
  of proofs is reassurance, not the product. The product **is** the
  `Minority Report` — the named danger surface at full size.
- **Campaign reframed.** Driving Crime 1 (`silently_unaccounted → 0`) and
  Crime 2 (`forged_warrant → 0`) is **not** about making green greener. It is
  about making the `Minority Report` **TRUE**, so the danger surface it names
  is the *real* one at full size — not a fake-small one hiding behind a broken
  instrument. (The nested-assert blindness made the danger surface look smaller
  than it was: silenced claims never opened digs, so un-asserted looked thinner
  than reality.)

Green is the contract room. The `Minority Report` is the only instrument that
can still change what happens next.

---

## Auto-mode: Minority Report across the dependency tree

Where does the un-contracted danger actually live? Most of all in your
**dependencies** — code you didn't write, under no contract you control,
pip-installed and trusted on faith. That is the un-contracted surface at its
largest.

**Auto-mode** is the mechanism that points the instrument at **any** lib in the
tree — no shipped proof required, no vendor cooperation:

| piece | role |
|-------|------|
| [#4007](https://github.com/TSavo/sugar/issues/4007) | The capability: LSP lifts un-instrumented vendor source on unresolved symbol; a missing `.proof` is a **cache miss**, not a black hole; vendor tests ARE the spec |
| [#4012](https://github.com/TSavo/sugar/pull/4012) | The cold-only implementation: skip warm/sealed modules; prefer vendor-shipped `*.proof`; disk-durable `.sugar/imports/auto/<source_cid>.proof` cache; mint from source only when cold |

On a cold dependency edge, auto-mode lifts the source that is already on disk
and the report's section header remains exactly `Minority Report` — naming that
dependency's danger surface: the bodies no assertion (theirs or yours) ever put
under oath.

**Auto-mode + the Minority Report = the product at ecosystem scale.** The
gallery's curated rows (six stdlib/vendors on the wall) are the **demo**.
Auto-mode is the same intelligence pointed at every lib in the tree — not just
the rows below.

No invented dependency-tree counts belong here. The wall stays measured-only;
auto-mode is the reach story, not a second fabricated table.

---

## Per-vendor wall

> **Headline — the full-tree beacon**
>
> R=0 said green. Across the **full installed packages**, the pre-totality
> nested walk hid approximately **numpy 714 + pandas 2906 ≈ 3620** asserts
> under that green. [#4023](https://github.com/TSavo/sugar/pull/4023) un-gagged
> the function-body surface. **Residuals that remain silent after totality:**
> numpy **43** · pandas **339**. Open indictments still name the first library
> loci ([#4025](https://github.com/TSavo/sugar/issues/4025) `f2py2e.py:668`,
> [#4024](https://github.com/TSavo/sugar/issues/4024) `expr.py:258` module-level)
> — they are two of many. Full measurement:
> [`2026-07-10-full-package-assert-grain-receipt.md`](superpowers/specs/2026-07-10-full-package-assert-grain-receipt.md).

Columns:

| group | fields |
|-------|--------|
| **assertions** (the report) | `stated` · `lifted+cited` · `silently_unaccounted` (Crime 1) |
| **Minority Report** | `bodies present` · `dug` · `un-asserted` / voiceless |
| **Crime 2** | `dig-floors` · `forged_warrant` |
| **status** | **RED** if Crime 1 or Crime 2 residual > 0; green when measured residual is zero |

### Hard rule on numbers

**No fabricated counts.** Assertion-grain cells are from measured receipts only.
`numpy` / `pandas` rows below are the **full installed package trees**
(`numpy==2.5.0`, `pandas==3.0.3`, every `.py` under site-packages) — not the
old 120-file sample. Body / Crime 2 columns that lack a measured receipt stay
`—` (not invented).

| vendor | stated | lifted+cited | silently_unaccounted (Crime 1) | nested before≈ (hid under R=0) | bodies present | dug | un-asserted | dig-floors | forged_warrant | status |
|--------|-------:|-------------:|-------------------------------:|-------------------------------:|---------------:|----:|------------:|-----------:|---------------:|--------|
| **statistics** | 4 | 4 | **0** | 3 | 58 | 6 | 52 | 0 | 0 | green |
| **numpy** (full tree, 407 files) | 3208† | 3058 | **43** | **714** | — | — | — | — | — | **RED** |
| **pandas** (full tree, 1421 files) | 17543 | 17204 | **339** | **2906** | — | — | — | — | — | **RED** |
| **decimal** | 0 | 0 | 0 | 0 | — | — | — | — | — | green |
| **fractions** | 0 | 0 | 0 | 0 | — | — | — | — | — | green |
| **pathlib** | 0 | 0 | 0 | 0 | — | — | — | — | — | green |

† **numpy stated** is full-tree AST (3208). Lift-path after-totals cover **405/407**
files (stated on those files = 3101 = 3058 lifted + 43 silent). Two files
FactoryGap-panicked mid-lift (107 asserts on disk not in after-accounting) —
labeled partial, not invented as silent. See receipt.

**Sources (do not mix axes):**

| axis | vendors | source |
|------|---------|--------|
| Full-tree nested-before + after residual | numpy, pandas | [full-package receipt](superpowers/specs/2026-07-10-full-package-assert-grain-receipt.md) (main post-#4023 enumerator) |
| statistics after totality + ratchet | statistics | [#4023](https://github.com/TSavo/sugar/pull/4023) |
| Minority Report bodies | **statistics only** | [#4015](https://github.com/TSavo/sugar/pull/4015) |
| Crime 2 dig-floors / forged_warrant | **statistics only** | [#4020](https://github.com/TSavo/sugar/pull/4020) |
| decimal / fractions / pathlib | those three | [#4023](https://github.com/TSavo/sugar/pull/4023) (zero asserts on disk) |

### Full-tree note (`numpy` / `pandas`)

These rows are the **complete installed package** (library + in-tree tests),
measured with the merged #4023 function-body totality enumerator. The earlier
#4023 **120-file sample** (numpy silent 1 / pandas silent 1) was a lower bound;
the full tree is the real danger surface.

| package | files | nested before≈ (hid under R=0) | after silent residual | after lifted |
|---------|------:|-------------------------------:|----------------------:|-------------:|
| numpy 2.5.0 | 407 | **714** | **43** (405 files completed lift) | 3058 |
| pandas 3.0.3 | 1421 | **2906** | **339** | 17204 |
| **combined** | | **≈ 3620** | **382** | |

`decimal` / `fractions` / `pathlib` remain single-module stdlib files with
**zero** on-disk asserts in the #4023 receipt → silent 0.

### `statistics` — first indictment closed green

| field | value | source |
|-------|------:|--------|
| stated | 4 | [#4023](https://github.com/TSavo/sugar/pull/4023) after (was 4 in [#4015](https://github.com/TSavo/sugar/pull/4015)) |
| lifted+cited | **4** | [#4023](https://github.com/TSavo/sugar/pull/4023) — was 1 under nested blindness |
| silently_unaccounted | **0** | [#4023](https://github.com/TSavo/sugar/pull/4023); ratchet green because the silenced testify ([#4017](https://github.com/TSavo/sugar/issues/4017)) |
| was silent (pre-#4023) | 3 (`:200` / `:237` / `:323` `assert not _isfinite(...)`) | [#4015](https://github.com/TSavo/sugar/pull/4015) / [#4017](https://github.com/TSavo/sugar/issues/4017) |
| bodies present | 58 | [#4015](https://github.com/TSavo/sugar/pull/4015) Minority axis |
| dug | 6 | [#4015](https://github.com/TSavo/sugar/pull/4015) |
| un_asserted | 52 | scope / voiceless — reported, not red ([#4016](https://github.com/TSavo/sugar/issues/4016)); [#4015](https://github.com/TSavo/sugar/pull/4015) |
| dig-floors | 0 | [#4020](https://github.com/TSavo/sugar/pull/4020) |
| forged_warrant | 0 | [#4020](https://github.com/TSavo/sugar/pull/4020) |
| status | **green** | Crime 1 residual 0; Crime 2 residual 0 |

```
assertions (the report) — after #4023:
  stated:                    4
  accounted (lifted+cited):  4
  silently_unaccounted:      0   ← green / silenced testify

Minority Report (bodies — still #4015):
  present:      58
  dug:           6
  un_asserted:  52   ← scope, not red

Crime 2 (still #4020):
  dig_floors:       0
  forged_warrant:   0
```

### Residuals still RED (full tree + open indictments)

| vendor | residual (full-tree measurement) | first named locus / prosecute |
|--------|----------------------------------|-------------------------------|
| **numpy** | **43** silent after totality (among 405 completed files); 2 files FactoryGap-abort (107 asserts not in after-totals) | includes `f2py2e.py:668` → [#4025](https://github.com/TSavo/sugar/issues/4025); 4 silent outside `*/tests/*` |
| **pandas** | **339** silent after totality (1421/1421 files) | includes `expr.py:258` module-level → [#4024](https://github.com/TSavo/sugar/issues/4024); 12 silent outside `*/tests/*` |

The sample residuals from #4023 were the first named library loci; the full-tree
scan shows they sit inside a **much larger** residual set. Full silent-locus
lists: [JSON receipt](superpowers/specs/2026-07-10-full-package-assert-grain-receipt.json).

---

## How to read a row

1. **Crime 1 column > 0** → vendor claims exist and were silenced. **RED.**
   Prosecute by lifting the vendor's own claim (never fabricate). Open
   campaign loci: numpy [#4025](https://github.com/TSavo/sugar/issues/4025),
   pandas [#4024](https://github.com/TSavo/sugar/issues/4024) — plus the broader
   full-tree residual counts above.
2. **Crime 2 column > 0** → digs floored into literal/effect with no warranting
   assertion. **RED.** Prosecute the forged warrant. (Only `statistics` has a
   measured Crime 2 receipt today — [#4020](https://github.com/TSavo/sugar/pull/4020).)
3. **`un_asserted` large, crimes 0** → scope is thin: the report is green on
   what was claimed, and the Minority Report names the voiceless remainder.
   Visible, honest, not red — and not "fully verified." (Body axis measured for
   `statistics` only — [#4015](https://github.com/TSavo/sugar/pull/4015).)
4. **nested before≈** → approximate count of asserts the pre-#4023 walk never
   saw (not direct `FunctionDef` body children). The size of the surface R=0 hid.
5. **`—`** → that axis has no measured receipt yet. Do not invent.

---

## Instrument map

| instrument | lives | gate |
|------------|-------|------|
| Assertion accounting + `silently_unaccounted` (Crime 1) | `sugar lift --report` / `liftCoverage` ([#4015](https://github.com/TSavo/sugar/pull/4015)) | `silently_unaccounted == 0` |
| Section header `Minority Report` | human render of `--report` ([#4013](https://github.com/TSavo/sugar/issues/4013), [#4015](https://github.com/TSavo/sugar/pull/4015)) | present verbatim when un-asserted bodies exist |
| Bodies `{present, dug, un_asserted}` | Minority axis of `liftCoverage` | reported, not gated red |
| Dig-floor warrant stamp + `forged_warrant` (Crime 2) | `liftCoverage.crime2` ([#4020](https://github.com/TSavo/sugar/pull/4020)) | `forged_warrant == 0` |

---

## Campaign links

| ref | role |
|-----|------|
| [#4016](https://github.com/TSavo/sugar/issues/4016) | EPIC — Minority Report campaign; two crimes; prosecute the silenced only |
| [#4013](https://github.com/TSavo/sugar/issues/4013) | Dual-axis harness; `Minority Report` naming; report vs named outlier section |
| [#4015](https://github.com/TSavo/sugar/pull/4015) | Crime 1 detector live on main; statistics body / pre-totality assertion seed |
| [#4020](https://github.com/TSavo/sugar/pull/4020) | Crime 2 detector live on main; statistics `forged_warrant = 0` |
| [#4017](https://github.com/TSavo/sugar/issues/4017) | First indictment — `statistics` nested silent asserts (closed green by #4023) |
| [#4023](https://github.com/TSavo/sugar/pull/4023) | Total function-body assertion enumeration (un-gagged nested surface) |
| [full-package receipt](superpowers/specs/2026-07-10-full-package-assert-grain-receipt.md) | Full-tree numpy/pandas assertion grain (beacon numbers on this wall) |
| [#4024](https://github.com/TSavo/sugar/issues/4024) | Prosecute pandas module-level assert residual (`expr.py:258`) |
| [#4025](https://github.com/TSavo/sugar/issues/4025) | Prosecute numpy function residual (`f2py2e.py:668`) |
| [#4007](https://github.com/TSavo/sugar/issues/4007) | Auto-mode capability — point the instrument at any dep (missing `.proof` = cache miss) |
| [#4012](https://github.com/TSavo/sugar/pull/4012) | Auto-mode MVP: cold-only lift, shipped-`.proof` preference, disk CID cache — ecosystem-scale `Minority Report` |

---

*Wall numbers come only from measured receipts (full-tree numpy/pandas
assertion grain; #4023 for statistics / stdlib zeros; #4015 bodies / #4020
Crime 2 for `statistics`). Never invent counts.*
