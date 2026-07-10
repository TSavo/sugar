# Handoff (2026-07-10, rev 10)

Main is green (per-PR battleaxe corpus receipts). The session pivoted to **the Minority Report campaign** (#4016). Everything below is that.

---

## The thesis (read first)

A correctness report has two registers. The **report** is the summary of what's governed — fact, dig, universe, implication, constraint, effect — the lawful accounting. It's what lets you sleep: everything in it is under law, resolved, past tense, safe to stop thinking about.

The **`Minority Report`** is what comes after and *stays on your screen*: the ungoverned, the silent, what **isn't** proven/asserted/governed. It can't clear (no law reaches it to close it out), so it's the residue that persists — and it's the only part that can still affect the future. **The most important line in the report is not what is correct. It is what isn't.** Green is comfort; the Minority Report is intelligence. Nobody's future gets decided by the code that already testified and held up; it gets decided by the code sitting in the dark that nobody ever put under oath.

**The whole product IS the Minority Report.** Making it a bright, named, file:line beacon on the artifact means no agent — human or AI — can unsee it. The comfortable lie that "green = verified" dies the instant that wall renders. Doctrine in memory: `project_provekit_minority_report_is_the_product`.

---

## The two crimes (what the campaign prosecutes)

Honest law = correspondence between vendor assertions and digs. Two ways to break it:

- **Crime 1 — silenced assertion** (`stated → ∅`): a vendor assertion that warrants no fact and triggers no dig. The voice we silenced. Detector: `silently_unaccounted` (#4015). Gate RED when > 0.
- **Crime 2 — forged warrant** (`dig → literal/effect, ⊥ stated`): a dig grounded in no assertion, flooring into a literal/effect no claim asked for. The warrant we forged. Detector: `forged_warrant` (#4020). Gate RED when > 0.
- **Not a crime:** a body with no vendor claim = voiceless, honestly named in the Minority Report. **Fabricating a claim for it is itself Crime 2.** Prosecute the silenced; never manufacture a confession.

---

## LANDED this session (the whole arc)

- **Solve-api series CLOSED** — capstone `delete pool_only_inputs` (#4014). Solve is one path, zero project FS, byte-identical the whole way (cuts #4/#6/#2/#8/#5/#7).
- **Implication prove-then-feed** (#4018) — discharged implications feed-fold into the pool (proven-only; seal is memoization-of-proven, never proof), gated by the counterfactual bad-twin.
- **Coverage instrument + `Minority Report`** (#4015), naming scrubbed to "the report" + one named section (#4019).
- **Both crime detectors live:** Crime 1 (#4015), Crime 2 (#4020).
- **The corpus reveal (#4023):** the claim-enumerator never descended into `if`/`try`/`for`/`with` bodies — every nested vendor assertion was silently dropped under green R=0. Fix = total recursive enumeration. numpy **~34** and pandas **~54** silenced asserts un-gagged (120-file sample); statistics 3→0, ratchet green. Full 55/55 held.
- **Gallery** (#4021/#4022/#4027) — `docs/minority-report-gallery.md`, the wall made legible; numpy/pandas now RED with named residuals.
- **Auto-mode** (kevlar): capability #4007, MVP #4010, cold-only + shipped-proof + disk-durable #4012 — the mechanism that extends the Minority Report to the whole dependency tree.

---

## IN FLIGHT (I'm driving; do not collide)

- **97152** — full-tree recount: the TRUE numpy/pandas silent-loss number (not the 120-file sample). Touches only the gallery doc + read-only measurement.
- **97154** — #4024 pandas module-level assert surface (`expr.py:258`). Teeth green (10 passed), on the 55/55 gate. **Owns `factory/literal_call_report.py`.**
- **97156** — enumerate→LSP unification: route `solve_buffer` through enumerate→fold→one-solve, delete the parallel mint-as-feed. **Owns `sugar-lsp`.**

**SERIALIZED behind the above (do NOT grab — same files):** #4025 (numpy `f2py2e.py:668` function residual — same enumeration file as #4024).

---

## INDEPENDENT QUEUE — T can grab NOW (non-colliding: measure + file, don't edit the enumeration/LSP code)

- **M. Crime 2 in the wild.** statistics had 0 dig-floors, so the forged-warrant detector (#4020) hasn't been exercised on a real vendor. Run it over vendors that DO dig-floor (numpy/pandas opaque computed ops). Read-only measurement; file an indictment issue for any `forged_warrant > 0`. Non-colliding.
- **N. New-vendor Minority Report.** Run the dual-axis instrument on a vendor NOT yet audited (`requests`, `itsdangerous`, `csv`, `datetime`, a real third-party). Report its report + `Minority Report`; file indictments for silenced claims. (Measurement + issues is non-colliding; the fix serializes behind whoever owns the enumeration file.)
- **O. Auto-mode ecosystem demo.** Point auto-mode at a real pip-installed dependency and compute ITS Minority Report — the "danger surface of a dep you didn't write, under no contract you control" story. The ecosystem-scale proof of the thesis.
- **H. PyCon narrative / README arc** — rewrite around the NEW thesis: report = what lets you sleep; Minority Report = what should keep you up at night, named precisely enough to act on. The beacon no agent can unsee.
- **F / L / J. More logos** (real-name, different bug-shape class, cross-library composition) — ongoing infinite runway, python-side, `examples/`.
- **I. Fold the logo gallery into the Minority Report gallery** — one legible wall.

---

## Process

- `watch_worker` unreliable — poll. Busy-worker dispatch drops silently. Swap fresh at ~180k; **force-swap if looping** (a worker re-ran the same LSP suite 25 min at 220k — killed + restarted clean with a "run once, don't re-run" rule).
- Every PR touching the **lift path** (enumeration) needs the FULL witness corpus 55/55 (all 3 files), pasted — it feeds every proof. Report-side/doc changes don't.
- ONE PR per doc change. **Shared-checkout hazard:** `/Users/tsavo/sugar` gets branch-switched by workers mid-flight — do handoff edits via the GitHub API off main, never that working tree.
- Prosecute the silenced by lifting the vendor's OWN claim; NEVER fabricate. The only honest path to a green ratchet is the real claim testifying.
- Fix at the FACTORY (recognizer / enumeration surface); no reducer/inline/partial-eval bypass; don't fold a module assert into a fake FunctionDef (lies about provenance).
- CI CAVEAT: fast admin-merges cancel each commit's CI; main is green by per-PR corpus receipts, not a completed CI run.
