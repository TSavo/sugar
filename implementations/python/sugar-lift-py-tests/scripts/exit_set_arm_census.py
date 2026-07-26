"""Arm census for the four ExitSet composition sites (#6309, halted face).

Method-patching instrument only: it wraps ``ExitSet.sequence``,
``ExitSet.and_finally``, ``ExitSet.and_exit`` and
``ExitSet.and_exit_truthiness`` (plus ``ExitSet.normalize``, to capture the
pre-normalize arm list) and restores every original on exit. **No production
file changes, so the source stamp does not move.**

Why the row shape is what it is
-------------------------------

Each site emits arms from a double loop over ``self.exits`` x the other
operand's exits.  The reviewed question is whether the **halted** face grows
as a product, so every row records the input cardinalities separately and
then RECONSTRUCTS the emitted arm counts from them in closed form.  The
reconstruction is checked against what the site actually appended
(``reconciles``); a row that does not reconcile is an instrument bug, not a
finding.

That is deliberately stronger than a remainder bucket.  ``halted_from_exit``
and ``halted_from_incoming`` are not measured by subtracting one from the
total -- they are each predicted from the inputs, and their sum is required
to equal the observed halted count.  A residual can absorb an instrument
error silently; two independent predictions plus an equality cannot.

Per-site closed forms, read off the source at ``a4eade69a`` (the halted-product
baseline; ``exit_set.py`` is byte-identical on this branch).  ``S`` is
``self.exits``, ``O`` the other operand's exits, ``c``/``h`` the completed and
halted counts of a set.

``sequence`` (:363-376) -- the CONTROL.  The halted bypass at :367-369
appends one arm per halted incoming and ``continue``s, so halted incomings
never enter the inner loop::

    halted_from_incoming = h(S)                      # exact, by the bypass
    iterations           = pre_len - h(S)            # one append per iteration

The inner arm count is driven by ``step()`` and is not a function of the
inputs, so ``sequence`` reports iterations and faces but claims no product.
That is the point of a control: it should show the halted face FLAT while the
other three show it growing.

``and_finally`` (:405-418) -- one append per iteration.  A completed cleanup
re-emits the incoming only when ``restores(clean.value)`` (:411-416); the
``else`` at :417-418 is terminal cleanup completion (return-in-finally), which
CONVERTS a halted incoming into a completion.  So the completed cleanups split
into restoring (``c_r``) and terminal (``c_t``) and must be counted apart::

    iterations           = |S| * |O|
    halted_from_exit     = |S| * h(O)
    halted_from_incoming = h(S) * c_r                # NOT h(S) * c(O)
    completed_out        = c(S) * c_r + |S| * c_t

With the default predicate (``cleanup_restores=None`` -> always True) ``c_t``
is 0 and the two spellings coincide, which is exactly why a plain
``completed(O)`` column would pass unnoticed until someone models
return-in-finally.

``and_exit`` (:454-487) -- ``exit_disposition_effect(disposition, incoming)``
reads ``incoming`` ONLY; ``ex`` never reaches it.  So the verdict is a
function of the incoming exit alone and the completed exit face contributes
only a multiplicity ``c(O)``.  The halted term is therefore still a product --
a verdict-weighted left factor times ``c(O)`` -- rather than a per-pair
unknown, and probing costs ``|S|`` calls, not ``|S| * |O|``.  The
``RetainedObligation`` branch (:466-483) emits TWO arms per pair, each
independently completed or halted according to whether ``held`` / ``failed``
is None, so a single undecidable predicate contributes 0, 1 or 2 halted arms::

    iterations           = |S| * |O|
    halted_from_exit     = |S| * h(O)
    halted_from_incoming = c(O) * (n_effect + n_ro_held_halts + n_ro_failed_halts)
    completed_out        = c(O) * (n_none + 2*n_ro - n_ro_held_halts - n_ro_failed_halts)
    pre_len              = |S|*h(O) + c(O)*(n_none + n_effect + 2*n_ro)

Note ``n_effect`` counts COMPLETED incomings that halt as well as halted ones
that stay halted -- an assertion boundary halts a body that never raised, so a
(completed, completed) pair yields a halted arm.  Neither a
``|S| x halted(O)`` term nor a ``halted(S) x completed(O)`` term covers that,
which is why the verdict shapes are first-class row inputs.

``and_exit_truthiness`` (:502-529) -- a completed incoming with a completed
``ex`` emits one arm and ``continue``s (:508-510); a HALTED incoming with a
completed ``ex`` emits two (:522-529), one on each truth face.  Here the four
cardinalities are sufficient::

    iterations           = |S| * |O|
    halted_from_exit     = |S| * h(O)
    halted_from_incoming = h(S) * c(O)
    completed_out        = |S| * c(O)
    pre_len              = |S|*h(O) + c(S)*c(O) + 2*h(S)*c(O)

Conservation, on every row and at every site::

    completed_out + halted_from_exit + halted_from_incoming == pre_len

with no remainder bucket.  ``post_len`` (after ``normalize``) is recorded
beside ``pre_len`` but is NOT part of the conservation identity: normalize
merges arms, so post-normalize length under-reports the work done.  Per the
same argument, ``iterations`` is the load-bearing column -- an arm born dead
under ``_and_guards`` returning ``false_guard()`` still cost a loop turn and
still shows up in ``iterations`` even when it never reaches ``pre_len``'s
survivors.

Usage::

    from exit_set_arm_census import arm_census

    with arm_census() as rows:
        ...  # exercise the construction under test
    for row in rows:
        print(row.site, row.iterations, row.halted_out)
"""

from __future__ import annotations

import json
from contextlib import contextmanager
from dataclasses import asdict, dataclass, field


@dataclass
class CensusRow:
    """One call of one composition site."""

    site: str

    # --- inputs, counted separately so the row is reconstructible ---
    n_incoming: int = 0
    n_incoming_completed: int = 0
    n_incoming_halted: int = 0
    n_other: int = 0
    n_other_completed: int = 0
    n_other_halted: int = 0

    # and_finally only: the completed cleanups split by the restores predicate.
    n_other_completed_restoring: int | None = None
    n_other_completed_terminal: int | None = None

    # and_exit only: verdict shapes, counted over INCOMINGS (the verdict is a
    # function of the incoming exit alone), each weighted by n_other_completed.
    n_verdict_none: int | None = None
    n_verdict_effect: int | None = None
    n_verdict_retained: int | None = None
    n_retained_held_halts: int | None = None
    n_retained_failed_halts: int | None = None
    verdict_probe_error: str | None = None

    # --- observed output ---
    iterations: int = 0
    pre_len: int = 0
    post_len: int = 0
    completed_out: int = 0
    halted_out: int = 0

    # --- predicted output, reconstructed from the inputs above ---
    predicted_pre_len: int | None = None
    predicted_completed_out: int | None = None
    halted_from_exit: int | None = None
    halted_from_incoming: int | None = None

    reconciles: bool = False
    reconcile_detail: str = ""

    def check(self) -> None:
        """Reconcile prediction against observation; set ``reconciles``."""
        problems: list[str] = []
        if self.halted_from_exit is None or self.halted_from_incoming is None:
            problems.append("no halted prediction")
        else:
            predicted_halted = self.halted_from_exit + self.halted_from_incoming
            if predicted_halted != self.halted_out:
                problems.append(
                    f"halted {predicted_halted} predicted != {self.halted_out} observed"
                )
        if self.predicted_completed_out is not None:
            if self.predicted_completed_out != self.completed_out:
                problems.append(
                    f"completed {self.predicted_completed_out} predicted "
                    f"!= {self.completed_out} observed"
                )
        if self.predicted_pre_len is not None:
            if self.predicted_pre_len != self.pre_len:
                problems.append(
                    f"pre_len {self.predicted_pre_len} predicted != {self.pre_len} observed"
                )
        if self.completed_out + self.halted_out != self.pre_len:
            problems.append(
                f"faces {self.completed_out}+{self.halted_out} != pre_len {self.pre_len}"
            )
        self.reconcile_detail = "; ".join(problems)
        self.reconciles = not problems


@dataclass
class _Frame:
    """One in-flight composition call; collects its own pre-normalize set."""

    row: CensusRow
    captured: object | None = None
    _stack: list = field(default_factory=list)


def _faces(exits):
    """(total, completed, halted) for an exit tuple."""
    from sugar_lift_py_tests.outcome.exit_set import Completed

    completed = sum(1 for e in exits if isinstance(e, Completed))
    return len(exits), completed, len(exits) - completed


@contextmanager
def arm_census():
    """Patch the four sites; yield the list of rows collected."""
    import sugar_lift_py_tests.outcome.exit_set as exit_set_module

    ExitSet = exit_set_module.ExitSet
    rows: list[CensusRow] = []
    frames: list[_Frame] = []

    original_normalize = ExitSet.normalize
    original_sequence = ExitSet.sequence
    original_and_finally = ExitSet.and_finally
    original_and_exit = ExitSet.and_exit
    original_and_exit_truthiness = ExitSet.and_exit_truthiness

    def patched_normalize(self):
        # Route to the innermost in-flight frame, last write wins: a site's own
        # ``ExitSet(tuple(exits)).normalize()`` is the last normalize call in
        # its extent at its own level, and nested composition calls push and
        # pop their own frames before it runs.
        if frames:
            frames[-1].captured = self
        return original_normalize(self)

    def _observe(frame, result):
        row = frame.row
        pre = frame.captured
        if pre is None:  # pragma: no cover - defensive
            row.reconcile_detail = "pre-normalize set not captured"
            return
        row.pre_len, row.completed_out, row.halted_out = _faces(pre.exits)
        row.post_len = len(result.exits)

    @contextmanager
    def _frame(row):
        frame = _Frame(row)
        frames.append(frame)
        try:
            yield frame
        finally:
            frames.pop()
            rows.append(row)

    def patched_sequence(self, step):
        row = CensusRow(site="sequence")
        row.n_incoming, row.n_incoming_completed, row.n_incoming_halted = _faces(
            self.exits
        )
        with _frame(row) as frame:
            result = original_sequence(self, step)
            _observe(frame, result)
        # The bypass at :367-369 is the ONLY source of a halted arm carried
        # from an incoming, and it fires exactly once per halted incoming.
        row.halted_from_incoming = row.n_incoming_halted
        row.halted_from_exit = row.halted_out - row.n_incoming_halted
        # step() drives the inner loop, so the arm count is not a function of
        # the inputs; iterations are still exact -- one append per turn.
        row.iterations = row.pre_len - row.n_incoming_halted
        row.check()
        return result

    def patched_and_finally(self, cleanup, *, cleanup_restores=None):
        row = CensusRow(site="and_finally")
        row.n_incoming, row.n_incoming_completed, row.n_incoming_halted = _faces(
            self.exits
        )
        seen: list = []

        def recording_cleanup():
            # Forward the real callable once and keep its result; never invoke
            # cleanup() a second time.
            built = cleanup()
            seen.append(built)
            return built

        with _frame(row) as frame:
            result = original_and_finally(
                self, recording_cleanup, cleanup_restores=cleanup_restores
            )
            _observe(frame, result)

        if seen:
            from sugar_lift_py_tests.outcome.exit_set import Completed

            cleanup_exits = seen[-1].exits
            row.n_other, row.n_other_completed, row.n_other_halted = _faces(
                cleanup_exits
            )
            restores = cleanup_restores or (lambda _value: True)
            restoring = sum(
                1
                for e in cleanup_exits
                if isinstance(e, Completed) and restores(e.value)
            )
            row.n_other_completed_restoring = restoring
            row.n_other_completed_terminal = row.n_other_completed - restoring
            row.iterations = row.n_incoming * row.n_other
            row.halted_from_exit = row.n_incoming * row.n_other_halted
            row.halted_from_incoming = row.n_incoming_halted * restoring
            row.predicted_completed_out = (
                row.n_incoming_completed * restoring
                + row.n_incoming * row.n_other_completed_terminal
            )
            row.predicted_pre_len = row.iterations
        row.check()
        return result

    def patched_and_exit(self, exit_es, *, disposition):
        row = CensusRow(site="and_exit")
        row.n_incoming, row.n_incoming_completed, row.n_incoming_halted = _faces(
            self.exits
        )
        row.n_other, row.n_other_completed, row.n_other_halted = _faces(exit_es.exits)
        with _frame(row) as frame:
            result = original_and_exit(self, exit_es, disposition=disposition)
            _observe(frame, result)

        row.iterations = row.n_incoming * row.n_other
        # Probe AFTER the real call so a contract that refuses raises from the
        # site under test, not from the instrument.
        from sugar_lift_py_tests.outcome.exit_disposition import (
            RetainedObligation,
            exit_disposition_effect,
        )

        none_ = effect_ = retained = held_halts = failed_halts = 0
        try:
            for incoming in self.exits:
                verdict = exit_disposition_effect(disposition, incoming)
                if isinstance(verdict, RetainedObligation):
                    retained += 1
                    held_halts += verdict.held is not None
                    failed_halts += verdict.failed is not None
                elif verdict is None:
                    none_ += 1
                else:
                    effect_ += 1
        except BaseException as exc:  # instrument must not mask the real result
            row.verdict_probe_error = f"{type(exc).__name__}: {exc}"
            row.check()
            return result

        c_other = row.n_other_completed
        row.n_verdict_none = none_
        row.n_verdict_effect = effect_
        row.n_verdict_retained = retained
        row.n_retained_held_halts = held_halts
        row.n_retained_failed_halts = failed_halts
        row.halted_from_exit = row.n_incoming * row.n_other_halted
        row.halted_from_incoming = c_other * (effect_ + held_halts + failed_halts)
        row.predicted_completed_out = c_other * (
            none_ + 2 * retained - held_halts - failed_halts
        )
        row.predicted_pre_len = row.halted_from_exit + c_other * (
            none_ + effect_ + 2 * retained
        )
        row.check()
        return result

    def patched_and_exit_truthiness(self, exit_es, *, site):
        row = CensusRow(site="and_exit_truthiness")
        row.n_incoming, row.n_incoming_completed, row.n_incoming_halted = _faces(
            self.exits
        )
        row.n_other, row.n_other_completed, row.n_other_halted = _faces(exit_es.exits)
        with _frame(row) as frame:
            result = original_and_exit_truthiness(self, exit_es, site=site)
            _observe(frame, result)

        row.iterations = row.n_incoming * row.n_other
        row.halted_from_exit = row.n_incoming * row.n_other_halted
        row.halted_from_incoming = row.n_incoming_halted * row.n_other_completed
        row.predicted_completed_out = row.n_incoming * row.n_other_completed
        row.predicted_pre_len = (
            row.halted_from_exit
            + row.n_incoming_completed * row.n_other_completed
            + 2 * row.n_incoming_halted * row.n_other_completed
        )
        row.check()
        return result

    ExitSet.normalize = patched_normalize
    ExitSet.sequence = patched_sequence
    ExitSet.and_finally = patched_and_finally
    ExitSet.and_exit = patched_and_exit
    ExitSet.and_exit_truthiness = patched_and_exit_truthiness
    try:
        yield rows
    finally:
        ExitSet.normalize = original_normalize
        ExitSet.sequence = original_sequence
        ExitSet.and_finally = original_and_finally
        ExitSet.and_exit = original_and_exit
        ExitSet.and_exit_truthiness = original_and_exit_truthiness


SITES = ("sequence", "and_finally", "and_exit", "and_exit_truthiness")


def totals(rows):
    """Per-site sums of the load-bearing columns, for a report table."""
    out = {}
    for site in SITES:
        site_rows = [r for r in rows if r.site == site]
        out[site] = {
            "calls": len(site_rows),
            "iterations": sum(r.iterations for r in site_rows),
            "pre_len": sum(r.pre_len for r in site_rows),
            "post_len": sum(r.post_len for r in site_rows),
            "completed_out": sum(r.completed_out for r in site_rows),
            "halted_out": sum(r.halted_out for r in site_rows),
            "halted_from_exit": sum(r.halted_from_exit or 0 for r in site_rows),
            "halted_from_incoming": sum(r.halted_from_incoming or 0 for r in site_rows),
            "non_reconciling": sum(1 for r in site_rows if not r.reconciles),
        }
    return out


def dump_rows(rows, path):
    """Write every row as JSON lines -- the product claim must be recheckable."""
    with open(path, "w", encoding="utf-8") as handle:
        for row in rows:
            handle.write(json.dumps(asdict(row), sort_keys=True) + "\n")
    return path
