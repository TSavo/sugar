> With human teams, orientation was comparatively plentiful and generation was
> scarce. With agents, generation is cheap and parallel while reliable
> orientation is scarce. The invariant inverted; the process did not. So process
> must pin orientation in executable instruments, not in meetings, careful
> intentions, or waiting for green.

> "The past 3 years of my journey with AI can be summarized as a series of
> increasingly sophisticated arguments about why it's wrong about process."
>
> - T Savo, June 25, 2026

# Instrument Driven Development

## Manifesto: Instrument Driven Development

The sacred cows of development are familiar: do not check in broken code, do
not merge failing tests, do not cause regressions. They are not moral laws.
They are compensating controls for low observability. They survive because most
teams move slowly enough that gates feel affordable.

For human teams, the bargain was coherent. The people doing the work carried
the architecture in their heads, remembered yesterday's conversation, and were
expensive to interrupt. Orientation was relatively abundant because it lived in
the team. Generation was scarce because every change cost human hours. A gate
protected the expensive thing.

Agents invert that economy. Generation becomes cheap, parallel, and relentless.
Orientation becomes the scarce resource: the goal, the taste, the boundary, the
reason a change is good instead of merely plausible. A process built for scarce
generation will keep protecting generation after generation has stopped being
the bottleneck. It will serialize the cheap thing while letting the scarce
thing decay.

At extreme velocity, gates become the bottleneck. A review gate, a green-CI
gate, a release gate, a "wait for the full sweep" gate: each one serializes the
work. It asks every parallel shot to queue behind a single reading that cannot
exist until after the shot lands. The gate is not safety. The gate is latency
wearing a safety vest, and it spends orientation while pretending to save risk.

Instrument Driven Development is the replacement bargain. If we want to break
the sacred cows without drowning in hidden damage, we do not replace discipline
with vibes. We replace gates with instruments. The instrument is where
orientation is stored.

TDD pins behavior: given this input, prove this output. IDD pins direction:
given this codebase, measure the ways it is drifting away from the shape we
intend. It turns architectural judgment into executable telemetry.

The first invariant is temporal: every "first I'll, then I'll" is suspect.
"First I'll run the suite, then I'll commit." "First I'll make sure it
compiles, then I'll start." "First I'll launch the checks, then I'll wait."
This is gate-thinking reasserting itself as prudence. The thing named first is
the thing to relocate: last, parallel, latent, or delegated to CI. Only creating
the exact red instrument, or turning that red instrument green, gets to be
first. Consuming broad validation does not. If it is broad confidence
telemetry, launch it and keep moving. If it is final hygiene, do it at the
edge. Do not let the preflight become the work.

Most important engineering rules begin as taste. Authentication belongs at the
boundary. Storage details should not leak into handlers. Errors should stay
typed until the edge. Migrations should be reversible. Parsers should have one
owner. Background jobs should be idempotent. Secrets should never cross a log
boundary. Dead code should disappear, not collect a permission slip. These
start as "vibes" because experienced engineers can feel the shape before they
can point to every violation.

Vibes are useless at agent speed. A vibe in chat decays. A vibe in a plan goes
stale. A vibe in a comment becomes folklore. So the first act is to convert the
vibe into a vector: named axes, current `R`, observed `Delta R` between runs,
and predicted `Epsilon R` for the change about to land. The vector is not just
tracking work. It is preserving orientation against drift.

The first artifact is not a checklist. It is not a reminder. It is a red
instrument: a unit test, compiler failure, report, receipt, or static audit
that recognizes the live offender set. Its failure names the pattern, points at
the file and line, shows the illegal shape, and describes the replacement
architecture. It says: move this policy to the boundary; replace this stringly
error with a typed result; delete this dead path; put this storage concern
behind the repository; split this God function; make this migration idempotent;
stop logging this secret.

Then the agent can do what agents are good at: chase green. The context is no
longer a fragile paragraph in chat; it is executable gravity. As long as red
remains, drift is visible. When silence arrives at stable zero, the vibe has
become law. The abundant resource is allowed to run; the scarce resource is
pinned.

## Sacred cows: massive parallelism is moving fast and breaking things — loudly

Three commandments are carved over every engineering door: **don't check in broken code. don't merge failing tests. don't cause regressions.** They are not superstition — they are the scar tissue of every team that drowned in its own hidden breakage. But each one is a gate, and to fan out we are going to break all three. We have no choice: a gate is where parallelism goes to die. What follows is the argument that breaking these rules is survivable, and the price that buys the survival — paid in full, up front.

"Move fast and break things" is half a sentence. Breaking things is fine; breakage that *hides* is what kills you — it accumulates into a swamp no one can see the bottom of. So teams do the obvious thing and add a gate: review-then-merge, prove-then-ship, green-CI-before-anything. The gate feels like the price of speed without chaos.

But a gate is a serialization point, and serialization is the death of parallelism. Every shot queues behind the gate and waits for green; fire a hundred agents and all hundred stall at the same checkpoint — the gate, not the work, is the bottleneck. You cannot fan out through a gate. And the green it waits for is *always late*: every measurement worth having is taken after the shot lands, never before. A gate orders the shot to wait on a signal that does not exist yet — and cannot, until the shot is fired. That is why it serializes; it has inverted cause and effect. It is also guarding the old scarce resource: generation. While it waits, the new scarce resource — orientation — leaks away.

So we ask the inverted question. Not "how do we go fast safely," but "what would make breaking things safe enough that the gate becomes unnecessary?" There are exactly two answers, and everything here is built on them.

**Make every break loud.** A failure that must never happen does not earn a counter we promise to lower someday — it earns a `panic`. It stops the program. A break that stops the program cannot hide and cannot accumulate; it is fixed on contact. (It is why you never find a type error sitting in a shipped binary — not because they never arise, but because the compiler refuses to emit one while a single type is unaccounted; the hole halts the build, so it dies before it has a name.) Loud breakage is breakage you can afford to cause.

**Measure every gap.** This is delta-epsilon testing, and it is indifferent to what we build. Every goal is a vector of named remaining-work counts, `R`. At each check-in the instrument reports current `R`. `Delta R` is what you read by comparing that run with the previous run — what actually moved. Separately, every change carries `Epsilon R` — the change we predict when that work lands. We are done only at a *stable* zero: `R`, eyeballed `Delta`, and predicted `Epsilon` all zero, every floor intact. We never guess where we stand; we read it. And we read it late, on purpose: the measurement lands after the shot, never before — `Epsilon R` exists precisely because the observed signal has not arrived yet. Latency is not a defect to engineer away; it is the shape of telemetry itself. The gate's whole error was to demand the reading before the shot. We take the same reading after, and fix forward. The point is not merely to count work; it is to keep orientation alive between shot and signal.

A checklist is not measurement. A threshold is not measurement. Both freeze what one agent happened to notice, then ask every later agent to trust that stale map. The instrument is automated recognition of the live work: a test, compiler error, or report that turns red for every remaining offender and says what must replace it. When the goal is removal, the failure output is part of the design: it names the current illegal shape and the replacement architecture that makes it disappear. We do not fly by promises, comments, pinned plans, or hand-maintained counts. We fly by the red compiler, the red test, and the measured `R` they expose.

Those two are the gate's entire job — keep silent ruin from shipping — done without ever stopping the line. And they are one loop, not two tools: automated instrumentation reports current `R`, humans read `Delta R` from one run to the next, each change states predicted `Epsilon R`, and the system stays red until all three are zero. Red is red. There is no softer red for "known debt," no green because the count improved, and no threshold that turns remaining work into success. **That silence is the proof the zero is real, and it is load-bearing forward: once delta-epsilon is zero you know the instrument cannot fire again, so red after that is, by definition, a regression** — the stable zero, broken by new work, announcing itself the one way that cannot be ignored.

Here is the payoff, and it is the whole reason the discipline exists: **once breakage is loud and state is measured, there is nothing left to coordinate for safety.** Agents still divide the work so their shots do not collide — parallelism is not the absence of a plan — but no agent waits on another for *permission*. A broken shot screams and is fixed forward. The ledger keeps everyone honest about what remains. So you fire every shot you have, in parallel, the moment it is ready — and massive parallelism is not a technique you bolt on, it is what *falls out* of moving fast and breaking things loudly. The gates were the only thing stopping you; the instruments made them unnecessary. They let the cheap resource run while the scarce resource stays pinned.

And now those three commandments read differently. "Don't check in broken code" was never the real law — it was a cheap stand-in for *measure your breakage and make it loud.* A failing test you refuse to merge is only an assertion you blocked at a gate instead of instrumenting; a regression you forbid is a count you declined to track. The old rules were a poor team's telemetry, the best you can manage when you cannot see your own state. They made sense when people were the continuity mechanism and generation was expensive. They stop making sense when agents generate faster than they can stay oriented. So the instruments are not free and they are not optional — they are the price of killing the rules, and you pay it up front: the loud-break machinery and the latent measurement are built *before* the parallelism they buy. Remove a gate and the only thing between you and the swamp is the measurement you invested in. Kill the rule, buy the instrument.

In practice: we do not gate. We instrument, fire, measure impact, and fire again. The merge is not a prize awarded after a slow compile, test, and sweep — it is the measurement boundary for the next shot. Do not spend scarce orientation waiting on abundant generation.

## The enforcement ladder: every instrument wants to become the compiler

Instruments are not all equal. They form a ladder, and each rung up, the red
arrives earlier and costs less to keep:

**prose < review < auditor < test < panic < type checker.**

Prose decays. Review is a gate. An auditor fires at check-in. A test fires at
run-time. A panic fires on contact. But the type checker fires *before the
program exists* — an illegal state you cannot construct never needs detection,
never needs a frontier, never needs a drain. It is the only instrument with
zero latency and zero maintenance, and the one place a gate is fine, because
the compiler is a gate that takes milliseconds and serializes nothing.

This is not a new idea, and it is not ours. It is what the Gang of Four saw,
built from objects because their type systems were too weak to say it
directly. Every pattern in that book is a machine for deleting a bug *class*
by making its precondition inexpressible:

- **Composite**: the client cannot write the one-vs-many bug, because the
  distinction does not exist at the interface. There is no code path where you
  forgot to handle the collection case. Correct by design.
- **Visitor / double dispatch**: the "what is the receiver" bug is unwritable,
  because dispatch *is* the design — and with abstract methods, adding a
  variant makes every visitor that does not handle it refuse to compile. The
  new case cannot be silently dropped; the compiler hands you the todo list.
- **Factory**: invalid construction is unwritable because construction has one
  door. You do not audit for objects built wrong; wrongness has no
  constructor.
- **State**: the "illegal transition" bug is unwritable when each state object
  only offers the transitions that exist. You do not check the state machine;
  you *are* the state machine.

The patterns survived thirty years because they are compile-time instruments
wearing runtime clothes. When we say "route it through the floor," "one door
for construction," "make the missing arm a compile error" — that is Composite,
Factory, Visitor, applied to proofs instead of widgets. Same law, older book.

So the prime directive one level above "instrument first": **every instrument
should be trying to climb the ladder and retire itself.** An auditor is a
confession that the type system cannot yet say the thing. Some confessions are
permanent (a non-exhaustive upstream enum forbids the compiler from enforcing
totality — so a frontier auditor holds that line forever). But most are not:
an `Option` that a required field outgrew becomes a plain field, and the
fail-open path stops parsing. A pub decoder becomes pub(crate), and the bypass
becomes a visibility error. A "callers must not reuse this" comment becomes a
move, and the reuse becomes a borrow error. A stringly status becomes an enum,
and the unhandled case becomes a missing match arm. In each case a whole R
axis does not go to zero — it goes to *unrepresentable*, the auditor that
watched it is deleted, and the only red left is the residue the type system
structurally cannot reach.

When you design a new instrument, ask in order: can the type system forbid
this outright? Can construction be given one door that refuses? Can the
failure be wired to a panic at contact? Only then, if the answer is no three
times, write the auditor — and leave a note in it naming what language or
design change would let it retire.

Name the first-then inversions out loud, because they often arrive disguised as
responsibility:

- "I'll run the entire test suite, then commit and PR." This is the old gate in
  its church clothes. The full suite is background telemetry. Commit, PR, merge,
  then run the sweep where its latency cannot serialize the next shot.
- "I'll just make sure everything is still compiling, then get to work." This
  asks permission from a signal that should be either the instrument itself or
  a background sweep. If compile is the instrument, make it speak. If it is
  broad confidence telemetry, launch it and keep moving.
- "I'll run the unit test before I make any changes." If the unit test already
  pins the target and is red, turn it green. If the target is not pinned, write
  the red instrument first. Do not run tests first to admire the starting state.
  The point is to create executable gravity or follow it home.
- "I'll spawn the tests in parallel, then start once they finish." Parallelism
  that you wait on is just a slower gate with better fan noise. Kick off the
  process proactively, then stop waiting to write code. Background signals are
  impact telemetry for the next shot, not permission for this one.

- Goal vector: every long-term goal defines `R(t)`, a vector of named remaining-work counts — `failing_tests`, `compiler_warnings`, `untyped_error_paths`, `unmigrated_callers`, `dead_code_sites`, `endpoints_without_auth`, `queries_without_limits`, whatever names the gaps for this goal. Keep axes separate; do not hide distinct gaps inside one number. The vector is the orientation payload: it tells every later agent what the work means.
- Stable-zero invariant: the instrument measures `R(t)` at each check-in. `Delta R(t) = R(t) - R(t-1)` is read by comparing one run to the next. The change author names `Epsilon R(t)`, the predicted change from the work being landed or launched. The system stays red until `R(t) == 0`, eyeballed `Delta R(t) == 0`, predicted `Epsilon R(t) == 0`, and every floor invariant still holds.
- Floors: a floor is a safety invariant the instrumentation must hold — `data_loss == 0`, no secret committed to the repo, no test deleted to turn the build green. It is not a progress counter, and not an absolute you can never touch: you may change a floor only WITH GOOD REASON, stated on the record. A PR may lower `R` freely; to move a floor it must say why. The sin is never the reasoned change — it is silent drift, a floor that drops because no one decided to drop it.
- New feature: write the focused unit test first. The test names the behavior, fails or would have failed before the change, and becomes the local proof that the feature exists. Add implementation and instrumentation after the test defines the target.
- Regression: write the regression unit test first. Reproduce the failure in the smallest test that would have caught it. If the failure cannot be seen clearly, add instrumentation first, then add the regression test, then fix.
- Long-term goal: write automated instrumentation for each `R` component. The instrument scans the live offender set, prints each offender with its replacement plan, reports current `R`, and exits red until stable zero. The replacement plan should name the new owner, boundary, typed contract, deletion path, migration target, or panic condition in enough detail that the next agent knows what green means. Compare consecutive runs to read `Delta R`; the PR or follow-on note states predicted `Epsilon R`. There is no threshold to update downward and no hand-maintained count to bless the merge. Counts are measured output, not authored state.
- Panic: wire every must-never-happen failure to halt the program, and run it *alongside* the automated instrumentation, never instead of it (see the section head). The panic is impact telemetry of the good kind — it cannot be missed and is fixed on contact. A panic after `Delta R` and `Epsilon R` have reached zero is, by definition, a regression: the most valuable alarm you own.
- Shot accounting: every PR states which `R` component it intends to lower, the predicted `Epsilon R`, and which floors it preserves. After the next instrument run, compare against the previous run and report the eyeballed `Delta R`. If `R > 0` and both eyeballed `Delta R` and predicted `Epsilon R` are zero, the work is stalled, not complete. If `R == 0` but predicted `Epsilon R` is nonzero, the zero is unstable.
- Instrumentation: every change needs observability at the boundary where a future agent would otherwise have to guess. Use the repo's logging/tracing/report machinery, and include exact paths to logs, reports, receipts, or run outputs in the PR notes.
- Ship: after the focused test and local evidence are coherent, commit, open the PR, and merge immediately. Do not wait for CI, full compiles, full test suites, solver-heavy proofs, or corpus sweeps.
- Background: after the merge, start the slow compile/test/prove/sweep in `tmux`, `bcargo`, or on `battleaxe`. Report the command, host, log path, and next expected signal as `Epsilon R`.
- Fire again: once the background signal is launched, move to the next shot. If CI red, delayed logs, or long-run failures land later, treat them as measured impact for the next fix-forward PR.
- Parallel fire: launch independent work streams when they do not collide. If a merge conflict, broken main, or failed background run blocks the next shot, resolve that concrete blocker and keep moving.

## The enforcement ladder: every instrument should climb until it retires

Instruments are not all equal. They live on a ladder, and each rung up, the
red arrives earlier and costs less:

**prose < review < auditor < test < panic < compiler.**

Prose decays. Review is a gate. An auditor fires at check-time, a test at
run-time, a panic at contact — but the type checker fires *before the program
exists*. An illegal state that cannot be constructed never needs detection,
never needs a frontier, never needs a drain. The compiler is the one gate this
process permits, because it is a gate that takes milliseconds and serializes
nothing: the design itself forbids incorrect construction.

So the prime directive sitting above "instrument first" is: **every instrument
should be trying to climb the ladder and retire itself.** An auditor is a
confession that the type system cannot yet say the thing. Some confessions are
forced — `syn::Expr` is `#[non_exhaustive]`, so grammar totality needs a
ledger; that auditor earns its keep forever. But most are temporary scaffolds:
the moment a frontier axis can become a type, a visibility boundary, a closed
enum, or a move, promote it and delete the check. Worked examples from this
repo:

- `expected_cid: Option<String>` → `String`: the fail-open ingress became
  unwritable. No audit needed; it does not parse.
- The privatized catalog decoder: a decode bypass is a visibility error, not a
  finding.
- `ComponentPlanOutcome::{Claimed, Declined, Failed}` and
  `PlanIntent::{Lift, Prove, Verify}`: crashed-vs-absent and verb-confusion
  stopped being string-matching bugs and became match arms rustc demands.
- Closed floor visitor traits: adding a floor kind makes every operation that
  does not handle it a compile failure — totality the Python kit needs a
  runtime gap plus two auditors to approximate.
- Passing a value by move where reuse would be a bug: the "callers don't reuse
  this" claim stops being a comment and becomes a borrow error.

When you build a new instrument, state which rung it is on and why it cannot
yet stand a rung higher. When you drain a frontier, prefer the fix that
deletes the axis over the fix that greens it: a type that forbids the
offender beats a test that detects it, every time. The endgame for any red
instrument is silence at stable zero — but the *best* endgame is that the
instrument becomes unnecessary because the illegal shape became
unrepresentable. Make the illegal thing inexpressible, and correctness stops
being vigilance and becomes geometry.

The same law runs through every layer of this system: the compiler forbids
ill-typed programs, the factory forbids un-owned constructions, the proofchain
forbids unwitnessed claims. One principle, three substrates.

### Coordination density: the invariant pipeline

The highest-value work in this repo is not the isolated fix. It is the
promotion chain that turns a local failure into durable system law:

1. **Bugs do not merely get fixed; they get promoted into named laws.** A bug is
   evidence that the system permitted an illegal shape to exist. The immediate
   patch matters, but the architectural question is: what class did this bug
   reveal? Name that class. State the invariant it violated. Make the fix cite
   the law, not only the symptom. A one-off patch that leaves the class unnamed
   is still ambient risk.
2. **Named laws do not sit in docs; they become instruments.** A law preserved
   only in prose is orientation with a half-life. It helps the agent that just
   read it and fails the worker who arrives cold. The law becomes real when a
   compiler error, test, auditor, panic, report, or receipt can recognize the
   offender set without asking a human to remember the argument.
3. **Instruments do not merely measure; they create ratchets.** A measurement
   that does not define non-regression is trivia. The instrument must name the
   current `R`, make new offenders red, and distinguish declared debt from new
   drift. It is allowed to carry a baseline only if the baseline is explicit,
   owned, and shrinking. A ratchet is the difference between "we noticed this"
   and "this cannot silently get worse."
4. **Ratchets do not merely gate; they define retirement paths.** A red
   instrument that only blocks work becomes another gate. IDD instruments must
   say what green means: the owner, boundary, typed contract, replay input,
   deletion path, or migration target that retires each offender. Every finding
   should point at the future type, constructor, enum, scoped key, witness, or
   memento that will make the finding impossible.
5. **Retirement paths do not merely clean code; they move obligations from
   auditors into types.** The final state is not a quiet auditor forever. The
   final state is that the illegal path cannot be constructed: the compiler
   demands the match arm, the constructor refuses the invalid object, the typed
   key carries the scope, the proof witness is independently addressed, the
   replay memento pins the decision input. The obligation has moved out of
   review and into the substrate.

This is coordination density. It is how a small shop keeps architectural memory
without meetings and scales parallel agents without trusting any single agent's
context. The invariant is:

> **local failure -> named law -> executable instrument -> ratchet -> retirement
> path -> type-level impossibility.**

Do not break this chain. If you only fix the local failure, the system learns
nothing. If you only write the law, the law decays. If you only write the
instrument, it becomes a noisy checklist. If you only ratchet, you have built a
new gate. If you only retire code without moving the obligation into a stronger
substrate, the same class returns wearing a different name. The work is complete
only when the chain has advanced as far up the enforcement ladder as the current
language and design allow.

### The capstone law (T Savo, 2026-07-02)

**"Enrollment is existence, enforced by the type system, enumerated by the
instrument, made loud by the panic, and the fix becomes unavoidable by any
agent."**

The whole ladder in one sentence — and the last clause is the design goal.
This system is built and maintained by agents (human and AI) whose judgment
is spiky and whose context is partial. The enforcement stack exists so that
NO agent — a coordinator sixteen merges deep, a worker with no memory of why
a rule exists, a future model with different failure modes — can rationalize,
sanction-comment, or merge around an invariant. Judgment is spent exactly
once, deciding what the invariants ARE; honoring them is mechanical, because
dishonoring them is unrepresentable, uncompilable, or loudly red.

The canonical composition (the "one dumb test"): every sugar owns the source
statements that construct it (its territory — the only fact it is
authoritative about); every ProofIR node class owns the situations that make
claims of its kind SAT or UNSAT (its meaning — the only fact IT is
authoritative about); and ONE parametrized test foreach-es the catalog,
drives each sugar's truthful/lying source pair through the production RPC
pipeline (`sugar lift` → ir compiler → solver), and asserts the triple:
THAT sugar fired, THAT node was emitted, THAT verdict came back. The test
itself is deliberately dumb — every ounce of intelligence lives with an
owner, every failure mode has exactly one address, and enrollment is
existence: a sugar in the catalog testifies or reds; a sugar that cannot
testify does not compile. When reviewing or building anything in this repo,
measure it against this sentence.

## Repository Mechanics

The manifesto above is the operating model. The rest of this file is local
mechanics for applying it in this checkout.

## Project Structure & Module Organization

This repository is the Sugar workspace. Core implementations live under
`implementations/` by language (`rust/`, `python/`, `java/`, `go/`, etc.). The
Rust crates form a Cargo workspace in `implementations/rust/`. End-to-end
examples and receipts are in `examples/`; protocol and design material lives in
`protocol/`, `docs/`, and `conformance/`. Automation and helper tooling are in
`Makefile`, `bin/`, `scripts/`, and `tools/`.

## Build, Test, and Development Commands

- `make help`: list supported build and test targets.
- `make build-rust`: build the Rust workspace in release mode.
- `make test-rust`: run Rust workspace and Rust-driven RPC tests.
- `make test-python`: run Python kit tests.
- `make test-all`: run the acid test (`test-rust` plus `test-python`).
- `make test-showcases`: run checked-in end-to-end showcase receipts.
- `cd implementations/rust && cargo fmt`: format Rust code.
- `cd implementations/rust && cargo test -p sugar-cli <test-name> -- --nocapture`: run a focused Rust test.

## Coding Style & Naming Conventions

Keep changes small, explicit, and consistent with nearby code. Rust uses
`cargo fmt`, snake_case functions/modules, and crate-local unit tests when
practical. Shell scripts should be Bash/POSIX clear and executable only when
intended. Do not move generated proofs, receipts, or vendored artifacts unless
the task requires it.

## Testing Guidelines

Prefer focused regression tests before broader suites. For Sugar behavior,
assert exact reports, receipts, CIDs, or verifier outcomes rather than inferred
behavior. Start with the smallest relevant command, then widen to
`make test-rust`, `make test-python`, `make test-all`, or a specific
`examples/*/run.sh` when the blast radius warrants it.

## Commit & Pull Request Guidelines

Commit messages are short imperative summaries, often followed by PR numbers
after merge, for example `Mint toolchain run witnesses from mint path (#2297)`.
PR descriptions should state what changed, why, and the validation commands
run. Keep unrelated local work out of the branch; stage files explicitly.

## Agent-Specific Instructions

For isolated work, create repo-local worktrees under `.worktrees/` from
`origin/main`. Before editing, check `git status --short --branch`. If a
narrower `AGENTS.md` exists in a subdirectory, follow that file for work inside
its scope.

For debt, migration, and removal work, follow the IDD loop above. Do not pin
the work as a checklist or threshold. Build the automated instrument first: a
focused test, compiler check, or report that recognizes the whole live offender
set, reports current `R`, stays red while the stable-zero terms are nonzero, and
prints the replacement plan for each offender. If the goal is ownership cleanup,
the failing instrument should identify every illegal resident and describe the
boundary, abstraction, visitor, typed result, deletion, or migration that will
remove it. Fly by that red compiler/test signal until stable zero makes it
silent.
