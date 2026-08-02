# Construction → consumer codomain law (fifth hierarchy-lie class)

**Instrument:** `implementations/python/sugar-lift-py-tests/scripts/construction_consumer_codomain_law.py`  
**CI enrollment:** `tools/run_static_sole_construction_floors.sh` (and `run_sole_construction_floors.sh`)  
**Axes:** `R_construction_consumer_codomain discrimination` + `R_construction_consumer_codomain = 0`

## Question

Which types can construction produce that a consuming slot cannot accept?

## The class (brown, 2026-08-02)

Construction extended the live graph — new ConstructedTerm leaves, non-binding
unpack, GuardedBinding faces, If branch slots — while **consuming doors** still
assumed the pre-extension closed set. Produce the new inhabitant, leave the
match/door on the old codomain → **TypeError aborts the file and erases the
roster**. Four instances, 159 files. Walking backwards from broken files found
them; this instrument finds them **forwards**, in seconds, with no corpus.

## Method (static AST)

1. **Produced:** inheritance-proven `ConstructedTermSugar` descendants + binding-state species  
2. **Closed doors:** `isinstance` / `require_constructed_term_sugar` arms that also raise `TypeError` or `SugarNotWritten`  
3. **Gap (sibling):** produced sibling absent from a door that totalizes that family  
4. **Gap (dynamic-discharge proxy):** `Expression` / `*StateV1` / `*Place*` `_construct_sugar` returns a `*Sugar` that is **not** a `ConstructedTermSugar` descendant → axis `R_expression_construct_not_term`

### Axis 4 — why it exists (fifth lie, sealed board)

Sealed board found:
`AttributeSugar.receiver requires ConstructedTermSugar, got ConstructedObjectPlaceSugar`
on `tests/frame/test_arithmetic.py`. Pure isinstance-sibling scan reported
`R_total=0` because `require_constructed_term_sugar` accepts the **base**
`ConstructedTermSugar` (all descendants covered) — it cannot see a mint that
lives **outside** the term hierarchy entirely. That mint is dynamic discharge
currency: `ObjectPlaceStateV1(Expression)._construct_sugar` → nested slot.

Static proxy enrolled: scan Expression-ish `_construct_sugar` Call returns;
flag Sugar-not-CTS. **Do not** union every `*Sugar` mint into the term set —
that lie hid ObjectPlace pre-promote.

### Reach honesty (what static still cannot follow)

- `getattr` / variable factories / runtime type mutations
- mints outside enrolled roots

Those remain **runtime-only**: `require_constructed_term_sugar` TypeError at
the slot + sealed-board / discharge twins. Do not force a static answer.

## Bankable zero language (load-bearing)

**ZERO IS BANKABLE EVIDENCE, NOT ABSENCE OF AN INSTRUMENT.**

That sentence is the difference between a measured zero and silence-as-a-clean-floor.
It is the distinction this campaign exists to defend.

### Caveat (must stay prominent — proven load-bearing by ObjectPlace)

Zero is **under this instrument's reach**: static AST on enrolled doors, mint
packages, and Expression `_construct_sugar` mint→term proxy. **Do not read
`R_total=0` as "the class is closed forever".** It means: at this tip, every
produced sibling is accepted by every closed door we can see statically, and
every Expression-ish construct mint we can name is a ConstructedTermSugar.
Remaining gaps may still be dynamic-only (getattr factories, etc.).

## CI law (enrollment is existence)

Without enrollment this is a report someone ran once. With enrollment in the
static sole-construction floor job it is a **per-commit guarantee**: the fifth
lie is red the moment someone extends the hierarchy without extending the door
— not a month later when a file roster silently vanishes.

Run locally:

```bash
python3 implementations/python/sugar-lift-py-tests/scripts/construction_consumer_codomain_law.py --self-test
python3 implementations/python/sugar-lift-py-tests/scripts/construction_consumer_codomain_law.py
```

## Tip measurement (example)

| metric | value |
| --- | ---: |
| R_total | 0 |
| R_construction_consumer_codomain_gap | 0 |
| R_kind_dispatch_codomain_gap | 0 |
| R_expression_construct_not_term | 0 |

Closed doors / mints (typical tip surface):

- `require_constructed_term_sugar` — base `ConstructedTermSugar`
- `binding_state_read_node` — `Node | UnboundBinding | GuardedBinding | LoopProjectedBinding`
- `_projection_term` — ConstructedTermSugar + projection faces
- `ObjectPlaceStateV1._construct_sugar` → `ConstructedObjectPlaceSugar` (promoted to CTS)

After #7099 / #7101 / #7103 hierarchy fixes + ObjectPlace promote, static closed
doors and Expression mint→term proxy accept every inhabitant this instrument
can see. Proven zero remains bankable under the caveat above.

## Fix judgment (ObjectPlace fifth lie)

**Promote** `ConstructedObjectPlaceSugar` → `ConstructedTermSugar` + `to_term`.
Do **not** widen `AttributeSugar.receiver`. An object place projects
authenticated construction testimony of an object — same ontology as
`ConstructedReceiverRefSugar`. The slot was truthful; the mint understated.
