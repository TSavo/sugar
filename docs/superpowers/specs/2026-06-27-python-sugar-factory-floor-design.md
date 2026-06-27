# Python Sugar/Factory/Floor Design

## Purpose

The Rust kit has made the old Python direction look suspect in the right way.
The problem is not that Python lacks useful logic. It has a lot of it: source
mementos, exact-or-refuse source oracle behavior, implication RPC, package
accounting, source audits, unit-test facts, and many hard-won recognizers.

The problem is ownership. The current Python lifter lets large ordered
classifier cascades act as factory, sugar, floor policy, accounting, and report
source at once. That is too much semantic authority in one place. The Rust
breakthrough was not merely "split the code into files"; it was making the
semantic boundary executable.

This design moves Python toward the same model without cargo-culting Rust's
exact floor set.

## Final Ownership Invariant

The Python kit is written in Python. The Rust CLI is written in Rust. The Rust
CLI must not learn Pythonisms.

Rust owns rendezvous, proof envelopes, canonical ProofIR transport, solver
plans, witness recomputation, and z3 verification. Python owns Python syntax,
Python builtins, Python platform behavior, Python package source shapes, Python
source/body discovery, and Python-to-ProofIR emission. If a behavior requires
knowing what `pandas`, `numpy`, `len`, `range`, descriptors, decorators,
vectorized broadcasting, truthiness, or Python exceptions mean, that behavior
belongs in a Python sugar or Python floor.

The Python kit is not done when the toy examples lift. It is done when a user
literally runs `sugar lift` on numpy and pandas projects with no config or
manifest, component discovery selects Python, constraints are shape-discovered
by Python sugars, facts trigger the right source/body digs, universes are
emitted with source warrants, and the Rust CLI remains language-blind while z3
proves the resulting ProofIR.

## Core Judgment

Rewrite the kit around the factory/sugar/floor law. Reuse old code only when it
earns the move.

The first executable artifact is the new factory. Everything goes through that
factory immediately. At the start it has no sugar, so every source shape it sees
panics with `write more Sugar for this AST` and a precise requested role,
observed AST, blame locus, and suggested sugar module. Then a sugar may claim the
shape and expose the next gap: no lawful floor species, floor reader, or
floor-owned visitor exists yet, so construction panics with `write more Floor for
this AST` or `write more Floor for this construction`. That is the intended red
instrument, not a failure of design. Each migration step teaches the factory one
more dumb sugar or one more floor visitor until the screaming set shrinks to
stable zero.

The old Python tests and cascades are not compatibility obligations. They are
source material. Copy a helper, fixture, or expected predicate only when it fits
the new construction law: shape-owned sugar, typed child bodies, completed floor
or real effect, source memento, factory audit, and ProofIR emission. Otherwise
delete or rewrite it. The source oracle and implication machinery are capabilities
to carry forward, not old files to keep alive unchanged.

## Pythonic Shape

The Python kit should feel like Python, not a transliteration of Rust.

The shape is many small, well organized type hierarchies with dumb classes.
Each class mostly names one concept, carries typed fields, and exposes one tiny
operation such as `reduce`, `accept_*`, `to_json`, or `emit`. Policy is visible
at the package boundary through recognizers, claims, visitors, and emitters, not
hidden in clever base classes or bucket modules.

- Sugars are small `@dataclass(frozen=True, slots=True)` values or simple dumb
  classes with clear fields and a `reduce(ctx)` method.
- Recognizers read like Python AST code: `match`/`case`, `isinstance` only for
  the immediate source shape, and tiny helpers such as `name_of(node)` where
  Python's AST representation needs one.
- Claims are module-level constants exported by the sugar module that owns the
  source shape.
- Context is an explicit object, not a bag of globals.
- Floors use `Protocol` visitors and `accept_*` methods for operation-specific
  double dispatch.
- Gaps are normal Python exceptions with structured `.info`, but the message is
  intentionally loud and stable enough for tests and reports.
- Tests are pytest fixtures around real Python source snippets and, for proof
  obligations, the literal `sugar lift` command path.
- One file per class. A sugar class, floor class, effect class, visitor class,
  or substantial proof/report class gets its own module. Package `__init__.py`
  files may re-export names, and tiny value enums/constants may live with their
  sole owner, but semantic classes do not share bucket files.

The code should be boring to a Python maintainer: readable dataclasses,
pattern-matching recognizers, named protocols, explicit imports, and no clever
metaprogramming just to imitate Rust's type system.

## Rust Lessons To Carry Forward

### Rust Kit Audit To Mirror

The Rust kit's design is concrete and should be copied at the level of roles,
not at the level of Rust filenames:

- `docs/sugar-invariants.md` states the construction law: recognize source
  shape, construct typed children, reduce recursively, delegate floor work, then
  return only `Complete` or `Incomplete(actual Effect)`. Every non-effect gap
  panics.
- `sugar/claim.rs` makes each sugar module export a `SugarClaim`: name, role,
  ordering edges, and a recognizer function. The claim lives with the sugar that
  owns the source shape.
- `sugar/catalog.rs` is only the broker: collect candidates for the requested
  role, order them by `comes_before`, select, create the audit seed, and wrap
  the selected node in accounting.
- `sugar/factory.rs` owns typed `SugarBody<Floor>` construction, build-time
  context, role builders, and factory audit rows. It is not the semantic owner
  of every source shape.
- dedicated builtin sugars such as `write_macro` claim known compiler/std
  shapes before broad fallbacks. The generic macro fallback is correct to panic
  when no visible `macro_rules!` source exists.

Python should therefore grow `claim`, `catalog`, `factory`, `floor`, `sugar/*`,
`factory_audit`, `proofir_emit`, and kit-RPC modules. Do not name the new
architecture after the old Python transport file. The Rust lesson is not "put
more logic in an RPC loop"; it is "make many dumb sugars volunteer through a
factory that records the walk."

### Source Oracle Shape

Rust source mementos do not carry source text or serialized AST. They carry a
replayable pointer:

- `kind: source-memento`
- source surface/role when applicable
- file
- function/source name
- span: start/end line and column
- parameter names
- `source_cid`
- `template_cid`

The source oracle materializes source only when asked by report/replay. It
re-reads the authoritative source, recomputes the CIDs, and either resolves the
fragment or returns a typed refusal. The report path routes those requests from
the plan; absent source is a graceful degrade that still displays the pinned
file/span/CIDs. Python must use the same pattern: proof data gets mementos, not
body text side doors.

### ProofIR Emission Shape

Completed Python floors emit ProofIR declarations in the existing contract
shape:

```json
{
  "kind": "contract",
  "name": "module.symbol::universe",
  "outBinding": "out",
  "pre": {"kind": "atomic", "name": "...", "args": []},
  "post": {"kind": "atomic", "name": "...", "args": []},
  "inv": {"kind": "atomic", "name": "...", "args": []},
  "sourceWarrants": [
    {
      "kind": "source-memento",
      "role": "python.body-universe",
      "file": "pkg/module.py",
      "source_function_name": "symbol",
      "span": {"start_line": 1, "start_col": 0, "end_line": 5, "end_col": 0},
      "param_names": ["x"],
      "source_cid": "blake3-512:...",
      "template_cid": "blake3-512:..."
    }
  ]
}
```

At least one of `pre`, `post`, or `inv` must be present. `sourceWarrants` are
input to proof-envelope minting; they are not an excuse to embed source text in
the contract.

### Floors Are Typed Consumption Contracts

A floor is not a status such as `warranted`, `refused`, or `support`.

A floor is the semantic type a parent sugar is allowed to consume. Rust's key
lesson is that a parent does not rummage through child syntax and hope. It asks
the factory for a child in a role, reduces that child, and consumes the completed
value through the expected floor. If the child completed as the wrong species,
that is an internal bug, not a graceful report condition.

Examples from Rust:

- a term consumer requires a term floor;
- a sequence adaptor requires a finite sequence floor;
- tuple decomposition requires tuple components;
- format lowering consumes typed format-template and format-value floors;
- float operations consume an IEEE float floor, not generic term syntax.

Python needs this invariant more than it needs Rust's exact floor names.

### Floors Delegate By Double Dispatch

Every floor operation goes through a floor-owned delegation interface. A sugar
or report/compiler pass does not crack open a floor by `isinstance` chains,
private dict keys, ctor names, or ad hoc shape tests. The caller provides a
narrow operation visitor; the floor accepts it and calls the method for its own
species.

The Rust floors are operation-specific traits, not one global visitor:

- `SequenceFloorVisitor` plus `accept_sequence_floor`;
- `SequenceElementVisitor` plus `accept_sequence`;
- `TermFloorVisitor`, `BoolFloorVisitor`, `ScalarFloorVisitor`, and
  `MonadicFloorVisitor` over term floors;
- `DesugaredFloorVisitor` plus `accept_desugared_floor` for term/term-seq/tuple
  component projection;
- `IeeeFloatVisitor`, `LiteralCStrVisitor`, and `NumericLiteralVisitor` for
  domain floors.

Python should mirror that shape with small `Protocol`s and explicit `accept_*`
methods:

```python
class DesugaredFloorVisitor(Protocol[T]):
    def visit_term(self, floor: TermFloor) -> T: ...
    def visit_tuple_components(self, floor: TupleComponentsFloor) -> T: ...
    def visit_passthrough(self, floor: FloorValue) -> T: ...

result = completed_floor.accept_desugared_floor(visitor)
```

That is double dispatch: the consumer chooses the operation, the floor chooses
the species-specific branch. If no visitor method exists for the species, that
is `write more Floor for this construction`, not a sugar-side fallback. Each
new floor visitor is an intentional door through the floor. It exists so callers
do not cut side doors through floor internals.

### Outcome Is Total

Every lawful sugar reduction has exactly two non-panicking terminal outcomes:

- `Complete(FloorValue)`
- `Incomplete(Effect)`

There is no terminal `None`, no silent skip, and no "best effort" fallthrough.
`None` may exist inside a recognizer as "I do not claim this source site." Once
a sugar claims a site, construction leaves by exactly one of three paths:

- `Complete(FloorValue)`: all required sugar and floor work was done.
- `Incomplete(Effect)`: the source contains an actual effect boundary.
- panic: construction is missing a sugar or floor; stop immediately and name
  the owner, blame site, observed shape, and concrete fix.

The type shape must make bad construction unrepresentable. `Complete` cannot
carry an effect. `Incomplete` cannot carry a construction gap. A construction
gap cannot be returned as a value that later code might ignore.
In Python, gap helpers should be typed `NoReturn` and raise directly. In Rust
or protocol-core code, construction gaps must not become enum variants in the
lawful outcome type.

### Effects Must Be Earned

An effect is a real source property that destroys the timeless value relation:
runtime dispatch, mutation, IO, nondeterminism, environment reads, dynamic
attribute lookup, dynamic imports, path-sensitive exception flow, or similar.

Pure but untranslated syntax is not an effect. It is a construction gap that
panics and names the missing sugar or floor. This is the inverse-sin guardrail:
refusing a pure shape just because we have not written the sugar is a fake
refuse.

### The Factory Is The Denominator

The factory is not a recognizer implementation. It is the broker and auditor.
For each requested source site and role, it records:

- source locus and AST kind;
- source memento when the site has one;
- requested role;
- all matching candidates;
- selected sugar;
- completed output floor;
- disposition;
- emitted formula/proof fragment when a completed floor emits one;
- effect/refusal reason when applicable.

This is the denominator for progress. Factory construction gaps are work, not
ambience, and they are allowed to exist only as loud stop-the-world failures
with fix text.

### Same Syntax Can Serve Multiple Roles

A Python `ast.Call` is not one thing. Depending on requested role, it may be:

- a term;
- an assertion subject;
- a callsite fact source;
- a body-universe delegation;
- a precondition target;
- an effect site;
- inert support.

The role belongs in the factory request. It should not be inferred globally by
one ordered cascade.

### Raw AST Is Not A Semantic Side Door

Sugars may retain raw AST for provenance, source mementos, token keys, fast
literal paths, and report spans. But a parent should not rebuild semantic
children by crawling raw child AST later. Semantic children are factory-built
floor values.

### Factory Construction Is Post-Order

The factory reads the AST tree backwards in the construction sense: the deepest
or last-needed child sugar is made first, then the parent sugar is constructed
with typed child bodies already inside it. A parent is not born holding raw AST
and a promise to ask the factory later.

This is the Rust `SugarBody<T>` lesson. Recognition descends through the source
shape and captures typed child bodies during construction. Reduction/desugar
then walks the already-built chain inside-out. That is why bad construction is
impossible to ignore: if the child floor does not exist, parent construction
does not complete.

### Python Builtins Are Sugars

Every Python builtin that contributes semantics is a sugar. There is no
separate "builtin magic" lane in the factory, floors, report renderer, source
oracle, or ProofIR compiler.

Examples include builtin functions, builtin constants, builtin exception
shapes, and builtin protocols that the lifter chooses to model. A modeled
builtin must have a `SugarClaim`, emit typed floors or real effects, appear in
factory audit rows, and carry the same proof obligations as any other sugar.
An unmodeled builtin is a sugar construction gap, not an implicit uninterpreted
function and not a generic runtime effect.

### Constraints Are Shape Sugars

Constraints are source-shaped facts discovered by the Python kit. They are not
global annotations, framework adapters, or Rust-side knowledge.

The Rust pattern to copy is `constraint.rs`: the catalog asks for the
`Constraint` role, and individual sugar modules claim source shapes such as
relation macros, `assert!`, boolean expressions, `cfg!`, bounded literal
macros, and if-panic forms. Each recognizer starts from syntax, builds typed
child floors during construction, and only then emits a warranted constraint or
effect.

Python must work the same way. Do not start from `lift_pydantic_model`-style
framework adapters that inspect a model object and directly synthesize
preconditions. If pandas or numpy contributes a fact, the owner is a
source-shape sugar:

- `assert expr` is an assertion-surface/constraint sugar;
- `Field(..., ge=1)` is a call-with-keyword shape sugar, after Python name
  resolution says the callee is the relevant `Field`;
- `Annotated[T, ...]` is a subscript/metadata shape sugar;
- `df[col].notna().all()` is a call-chain shape sugar;
- `arr.shape[0] == n` is an attribute/index/relation shape sugar.

Package identity may refine a shape after recognition, but package identity is
not the factory. The factory sees a source site and a requested role; Python
sugars volunteer for that shape.

The intended pipeline is:

1. A vendor unit-test sugar recognizes a callsite assertion shape and emits a
   `CallsiteFactFloor`: this exact source line says this exact call produced
   this exact fact.
2. The callsite fact triggers a dig request for the callee, method, object, or
   package source whose universe can explain the fact.
3. The Python source oracle resolves the target source by memento.
4. The Python body walker reads that AST out loud: for each atom/statement in
   source order, the factory asks shape-owned sugars whether they own the
   requested role.
5. The factory constructs post-order: the deepest child sugar is built first,
   then its parent with that typed body, and so on until the outer callsite
   universe sugar is complete.
6. `desugar` reduces the already-built chain inside-out.
7. The chain slams to exactly `Complete(FloorValue)`, `Incomplete(Effect)`, or
   a loud construction-gap panic that names the missing sugar/floor.
8. Completed floors emit language-agnostic ProofIR atoms/declarations. The
   Python kit owns this lowering because it owns the source semantics.
9. `BodyUniverseFloor` predicates, `PreconditionFloor`s, effects, and emitted
   ProofIR are reported next to the source lines that warranted them.
10. Implication lifting connects the callsite fact to downstream preconditions
   and postconditions.

This is the forensics loop: here is the fact, here is the source line that
warranted it, here is the dig it authorized, here is the body universe it
exposed, here are the predicates/effects and ProofIR emitted, and here is what
z3 proved.

The Rust CLI sees only language-agnostic artifacts: plan atoms/mementos,
ProofIR emitted by the Python kit, source/witness oracle responses, and solver
results. It must never special-case pandas, numpy, Python builtins, or Python
AST classes.

## Python Floor Set

This is the first proposed Python floor set. The names should evolve only when
a real consumer needs the distinction.

### `TermFloor`

A timeless ProofIR term. Used for literal values, stable names, pure operators,
constructor terms, field reads that have a closed shape, and call-result terms
when the call is represented as an uninterpreted but stable subject.

### `PredicateFloor`

A boolean formula suitable for assertions, guards, and pre/post conditions.
This is distinct from `TermFloor` so Python truthiness does not leak into FOL
by accident.

### `AssertionFactFloor`

A unit-test warranted fact with a source warrant. The floor carries the formula,
the test/callsite identity, and the memento rope to the test source.

### `CallsiteFactFloor`

A fact about one observed callsite. This is the place where unit-test evidence
and body universes meet. It must carry enough subject identity to support
implications and downstream precondition reporting.

### `BodyUniverseFloor`

Predicates warranted by walking a function body. Examples include translate,
rstrip/lstrip, delegation, regex membership, guard/raise, return literal, and
constructor field universes. The floor carries predicates plus the source
memento for the body that warranted them.

### `PreconditionFloor`

A function-entry or partial-function precondition, including guard-then-raise
patterns and built-in partial operations. This should be separate from
`BodyUniverseFloor` so downstream callsite obligations can be reported as
preconditions, not as generic predicates.

### `LiteralValueFloor`

An exact CPython literal value. This is for closed, finite data that can be
inspected without invoking runtime behavior.

### `SequenceFloor`

A finite iterable sequence. Consumers such as tuple/list projection,
enumeration, and finite loop expansion may consume this floor. Runtime
iterables do not complete here.

### `TupleComponentsFloor`

Fixed destructurable components. This exists because tuple-producing operations
and tuple destructuring need component identity, not a generic sequence blob.

### `ClassShapeFloor`

Closed/open class and attribute shape information with explicit assumptions.
This floor is Python-specific and should own `__init__`, slots, class attributes,
late mutation, dynamic setattr/delattr, MRO ambiguity, and monkey-patch
boundaries.

### `SupportFloor`

Inert metadata that accounts for source without emitting predicates: imports,
definitions, annotations, decorators, docstrings, overload stubs, and other
scaffolding.

### `EffectFloor`

A named red boundary. A red function emits no predicates. It shows green source
until the effect boundary, then the effect and the source memento for the
boundary.

## Loud Gap Discipline

The Python spine should start intentionally small. Incompleteness is allowed
only when it is loud, typed, and names the extension point that closes it.

There are two first-class gap families:

- Sugar gap: source syntax has no lawful sugar owner yet. Panic with
  `write more Sugar for this AST`, name the AST kind, requested role, and
  concrete sugar module to add.
- Floor gap: source syntax was recognized, but the system has no lawful floor
  operation or floor value species for the required construction. Panic with
  `write more Floor for this AST` when the gap is AST-warranted, or
  `write more Floor for this construction` when it is a lower-level floor
  operation, and name the floor/value operation to add.

Neither gap is an effect. Neither may silently fall through to an old
classifier, generic dict, or side-door report path. The error text is part of
the instrument: name the missing owner, blame the source or construction that
exposed it, and spell the next implementation move.

Normal lift mode panics on the first construction gap. Audit-only mode catches
construction-gap panics, records their owner/blame/fix metadata, and continues
walking so the report can show all missing sugar and floor work in one pass.
Audit-only mode must never turn those gaps into `Complete` or `Incomplete`
results; it is inventory, not semantics.

## Per-Sugar Proof Obligations

Every sugar, including builtin sugars and any sugar that copied logic from an
old helper, must ship with a SAT and UNSAT fixture pair:

- the fixture source is exact Python that `sugar lift` reads through the normal
  source-oracle path;
- the visual report shows that exact Python next to the lifted fact,
  predicate, or effect;
- the lifted ProofIR is compiled through the z3 backend;
- the SAT case proves the modeled behavior is satisfiable;
- the UNSAT case proves the negated or bad twin is rejected by z3;
- the fixture names the sugar claim that warranted the lift.

This is not optional test garnish. A sugar is not admitted until the proof pair
shows the Python source, the lifted ProofIR, and the z3 result together.

## Python Effect Set

The effect set should be flat and earned. Initial candidates:

- `RuntimeValue`: value supplied by function parameters or opaque call results;
- `RuntimeDispatch`: callable, method, or MRO target selected at runtime;
- `Mutation`: assignment, delete, attribute/item rebinding, or mutable update;
- `DynamicAttribute`: `getattr`, `setattr`, `delattr`, dynamic field access;
- `Io`: file/socket/process/stdout/stderr side effects;
- `Environment`: platform, env var, version probe, optional import probe;
- `Nondeterminism`: time, random, UUID, unordered runtime source, external state;
- `ExceptionFlow`: path-sensitive `try`/`raise` flow without a modeled universe;
- `ContextManager`: `with`/`async with` enter/exit effects;
- `GeneratorOrCoroutine`: suspension points and runtime iteration state;
- `ImportRuntime`: import machinery used as runtime behavior, not static support;
- `OpenClassShape`: dynamic class shape, monkey patch, nonlocal base, metaclass.

Pure missing translations are construction gaps that panic, not `Effect`.

## Factory Roles

Initial roles should be coarse and driven by consumers:

- `Term`
- `Predicate`
- `AssertionSurface`
- `CallsiteFact`
- `BodyUniverse`
- `Precondition`
- `LiteralValue`
- `Sequence`
- `TupleProducer`
- `ClassShape`
- `Support`
- `EffectSite`

The same AST node may have candidates in multiple roles. Candidate ordering is
per-role. Ambiguity between candidates in the same role is a factory error until
the claims declare an ordering or a more specific sugar wins.

## New Python Spine

Create a new spine under the Python lifter package with class-per-file layout:

- `factory/build.py`: dispatch only.
- `factory/audit_row.py`: one factory audit row class.
- `factory/audit_summary.py`: audit summary class/helpers.
- `claim/sugar_claim.py`: sugar claim metadata.
- `claim/sugar_candidate.py`: candidate record.
- `claim/sugar_role.py`: role enum.
- `floor/term_floor.py`, `floor/predicate_floor.py`,
  `floor/body_universe_floor.py`, etc.: one floor class per file.
- `floor/visitors/*.py`: one operation visitor protocol/class per file.
- `effect/*.py`: one typed effect class per file, plus a small registry if
  needed.
- `kit_rpc/*.py`: JSON-RPC kit protocol, component roll call, source oracle
  routes, and report payload plumbing only.
- `proofir_emit/*.py`: Python-owned conversion from completed floors to ProofIR
  `ContractDecl`/formula values.
- `sugar/*/*.py` or `sugar/*.py`: one sugar class per file, grouped by package
  only when that improves navigation.

The RPC module is orchestration only. Its name and shape must not become the
architecture. It does not own source semantics; sugars and floors do.
Any field rendered by `sugar lift --report` may appear in an RPC response as a
transport convenience, but it must also be minted into proof/memento data or be
derivable from minted proof/memento data. Live RPC-only report sections are side
doors and must be treated as instrumentation failures.

## Wholesale Migration Strategy

Do not keep the old tests alive as a parallel contract. Migrate wholesale.

Old Python code has three possible fates:

- copied into a new sugar/floor/proof emitter because it already expresses a
  valid piece of the new law;
- used as a fixture oracle while writing a new SAT/UNSAT proof pair;
- deleted or left behind as an old semantic resident counted by the IDD audit.

A copied helper stops being old code only when it is owned by a named
`SugarClaim` or floor visitor, emits Rust-shaped factory audit rows, carries
source mementos rather than source text, and emits ProofIR through
the `proofir_emit` package. There is no compatibility sugar class and no plan
to preserve the old test suite in parallel. Tests are migrated, not kept alive.

The factory audit may count old semantic residents as diagnostic evidence, but
that is not the goal vector. `R` for this rewrite is the construction-panic
count observed while lifting the numpy and pandas targets. Stable zero means:

```text
R_numpy_pandas =
  numpy sugar construction panics
  + numpy floor construction panics
  + pandas sugar construction panics
  + pandas floor construction panics
  + unexpected/non-canonical panics
  == 0
```

Bootstrap counters such as missing spine files, missing SAT/UNSAT fixtures, or
old semantic residents are report evidence that explains why `R` is nonzero.
They must not replace the real `R`.

The machine self-instruments. No human maintains an offender list. Audit-only
mode runs the actual numpy and pandas lift path, catches the same construction
panics normal mode would stop on, records each panic's typed metadata, groups
the observed gaps by target/role/owner/fix, and prints the measured `R`. A gap
exists because the machine encountered it, not because a plan remembered it.
Fixing a sugar or floor removes a panic only when the next lift no longer
observes that panic.

The factory audit should still show old semantic residents until they disappear:

```text
old semantic residents:
  python.translate_universe.cascade = 17
  python.package_accounting.cascade = 42
  python.layer2_assertions.cascade = 9
```

Stable zero for the migration means numpy and pandas lift through audit-only
mode with zero construction panics and through normal mode without hitting a
construction gap. Old semantic residents are unacceptable if they remain on the
path to that zero, but they are not the measured `R`.

## Reporting Model

Reports must be assembled from proof/memento data plus source-oracle resolution,
not from side-door source text.

The Rust reporting lesson is two ownership rules, both of which Python must
copy:

1. Assertion lifting owns "this source assertion warranted this observed
   callsite fact." The proof must pin the fact, its source memento, its
   callsite subject, and enough accounting to reproduce the assertion-surface
   report without asking the live RPC lifter again.
2. Body-universe lifting owns "this observed callsite fact warranted this
   universe walk." The proof must pin the universe contract, the warranting
   fact reference, source mementos, factory walk/effect mementos, emitted
   predicates, and any implication/precondition edges that the report renders.

RPC may assemble these rows for the immediate lift response, but `--report` must
be able to regenerate the same logical report from the `.proof` file alone. If a
source bundle is absent, the report asks the source oracle route pinned in the
plan, then degrades to file/span/CID text if the oracle is unavailable or
refuses. Missing source never justifies embedding body text into the proof.

For `--visual`, Python should follow the Rust report shape:

1. Plan roll call: component discovery, source oracle, witness oracle,
   assertion lifter, body universe lifter, implication lifter, ProofIR
   compiler availability.
2. Unit-test fact: the fact, its source memento, source oracle resolution, and
   the source line that warranted it.
3. Body universe: the predicates, the body source memento, full source from the
   source oracle, and predicates annotated on the source lines that warrant
   them.
4. Implications: which callsite facts warrant which body predicates and which
   downstream preconditions depend on each postcondition.
5. Effects: green until red; red emits the named effect and no predicates.
6. Factory audit: role/candidate/output accounting, construction gaps, and old
   semantic resident counts.

Missing source or witness bundles degrade gracefully. The report should say the
source is not present and show the pinned file/line/col/CID memento.

## First Instrument

Before broad migration, add one red instrument:

```text
python numpy/pandas lift panic audit:
  R:
    numpy_sugar_panics: N
    numpy_floor_panics: N
    pandas_sugar_panics: N
    pandas_floor_panics: N
    unexpected_panics: N
  diagnostics:
    sugar construction gaps without fix text: N
    floor construction gaps without fix text: N
    builtin semantics without sugar claim: N
    sugars missing SAT/UNSAT z3 fixture pair: N
    source oracle routes not derived from plan: N
    ProofIR emission shapes missing ContractDecl/sourceWarrants: N
    factory audit rows missing Rust-equivalent fields: N
    audit-only gaps without owner/blame/fix: N
    old semantic residents: N
    effect reasons without typed Effect: N
    source mementos with body_text or ast_template: N
    report sections not reproducible from proof: N
    assertion surface audit rows not pinned or proof-derivable: N
    live RPC-only report fields: N
    callsite fact/body universe links missing proof memento: N
    implication/precondition edges not proof-pool reconstructable: N
```

The first target is not zero for all of Python. The first target is that the
instrument literally runs the selected numpy and pandas lifts in audit-only mode,
captures every sugar/floor panic with owner/blame/fix metadata, reports `R`, and
keeps `R > 0` until the missing sugar or floor is written.

## First Migration Slice

The first implementation slice should be small enough to prove the model:

1. Python component roll call via `sugar.component.plan`.
2. Source oracle component route for Python.
3. Proof-report memento schema for plan atoms, assertion facts, callsite facts,
   body universes, source warrants, factory walks, effects, implications, and
   compiler selection.
4. Proof-only report regression: build a tiny `.proof`/memento fixture with one
   unit-test fact, one warranted body universe, one source memento, and one
   implication/precondition edge, then assert the report renders without a live
   Python RPC lifter.
5. Minimal factory/floor kernel.
6. Route every selected Python AST site through the new factory, with no
   semantic fallback to old cascades. The expected state is all sugar screams.
7. Port one existing family as a native sugar:
   - recommended: translate/rstrip body universe plus unit-test fact pairing,
     because the source memento behavior already exists and the visual report
     can prove the full loop.
8. Add the floor species/readers/visitors that the new sugar exposes. The
   expected intermediate state is floor screams.
9. Emit factory audit rows and a report section from the new spine.
10. Add audit-only mode that reports all construction gaps at once without
   changing normal panic semantics.
11. Add the first SAT/UNSAT z3 proof pair for the migrated sugar.
12. Run a Python example without config/manifest by component discovery.

The slice is successful when the report can show:

- this Python kit claimed the `.py` project;
- this test fact came from this source line;
- this body universe came from this source body;
- these predicates attach to these source lines;
- implications connect the fact to the universe/precondition;
- the proof contains plan atoms/mementos sufficient to reproduce the report;
- the migrated sugar has SAT and UNSAT z3 proof fixtures that show the exact
  Python lifted by `sugar lift`;
- audit-only mode reports all remaining sugar/floor construction gaps with
  owner, blame, observed shape, and fix;
- if the migrated family was on the numpy/pandas path, the next audit-only lift
  shows the corresponding observed panic count moved down.

## Non-Goals

- Do not keep old tests alive as a second contract.
- Do not preserve old files merely because they work.
- Do not delete source oracle or implication capability; port it through the new
  protocol path.
- Do not widen semantic claims to make the report look better.
- Do not treat pure untranslated syntax as a refused effect.
- Do not allow source text into `.proof` members.
- Do not make config/manifests the default path; they are overrides.

## Open Design Questions

- Should `PredicateFloor` and `PreconditionFloor` share formula storage but
  differ only by consumer role, or be separate dataclasses?
- Should class shape facts live in the same body universe report or a distinct
  object/shape report?
- How much of `translate_universe.py` should be copied into native sugars before
  the first migration slice?
- Should Python use a single assertion lifter component with phases, or separate
  component manifests for source, assertions, implications, and witness?
- What is the smallest Python no-config example that exercises source oracle,
  facts, body universes, and implications without pulling in the whole pandas
  accounting surface?

## Decision

The direction is a wholesale rewrite with selective code reuse:

- new semantic spine;
- old semantic residents audited until gone;
- one family ported at a time as native sugar/floor code;
- red instrument runs the actual numpy and pandas lift targets and tracks the
  observed sugar/floor construction panic vector until it reaches zero;
- bootstrap and architecture diagnostics explain nonzero `R`, but they are not
  the goal vector;
- reports come from proof/memento/source-oracle resolution only.

The design is done only when numpy and pandas can lift with no config or
manifest, produce zero construction panics, and emit a forensic report with
component roll call, source-backed unit-test facts, source-backed body universes,
implications, effects, factory accounting, and a plan memento pinned in the
proof.

## Implementation Plan

See
[`2026-06-27-python-sugar-factory-floor-idd-plan.md`](../plans/2026-06-27-python-sugar-factory-floor-idd-plan.md).
