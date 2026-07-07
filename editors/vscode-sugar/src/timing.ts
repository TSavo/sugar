// SPDX-License-Identifier: MIT OR Apache-2.0
//
// timing.ts: a small structured timing logger for the LSP prove path. Every
// step of a `runProve` pass (mint -> prove -> paint) is timed and written both
// to a JSONL file on disk (durable, greppable) and to a VS Code OutputChannel
// (live). One `TimingRun` groups the steps of a single pass under a shared
// `runId` so a pass's steps and its total can be reconstructed from the log.
//
// Wire-don't-invent: durations are `Date.now()` deltas measured at the actual
// await boundaries in `runProve`; nothing is estimated. The prove step's
// duration is the `sugar prove` subprocess wall time (the binary does not yet
// emit per-phase lift/solve timings; when it does they nest under this run).

import * as fs from "fs";
import * as path from "path";

/** One timed step within a run: a name and its wall-clock duration in ms. */
export interface TimingStep {
  step: string;
  ms: number;
  /** Optional structured context (row counts, file, exit code, ...). */
  extra?: Record<string, unknown>;
}

/** A sink the logger writes each line to (the OutputChannel, in practice). */
export interface TimingChannel {
  appendLine(line: string): void;
}

/**
 * A durable + live timing logger. `run()` opens a pass; `.step()` records a
 * step; `.end()` writes the per-step lines and a summary total. Failures to
 * write to disk are swallowed (timing must never break the editor path).
 */
export class TimingLogger {
  private seq = 0;

  constructor(
    private readonly filePath: string,
    private readonly channel?: TimingChannel
  ) {}

  /** Begin a timed pass labeled by `label` (e.g. the project dir or file). */
  run(label: string): TimingRun {
    this.seq += 1;
    // A monotonic per-session run id (seq) avoids Date.now()-based ids while
    // still ordering passes; the ISO timestamp gives wall-clock placement.
    const runId = `r${this.seq}`;
    return new TimingRun(runId, label, (line) => this.write(line));
  }

  private write(record: Record<string, unknown>): void {
    const line = JSON.stringify(record);
    if (this.channel) {
      // Human-friendly mirror for the OutputChannel.
      if (record.event === "step") {
        this.channel.appendLine(
          `  ${String(record.step).padEnd(8)} ${String(record.ms).padStart(6)} ms` +
            (record.extra ? `  ${JSON.stringify(record.extra)}` : "")
        );
      } else if (record.event === "run-end") {
        this.channel.appendLine(
          `[${record.runId}] ${record.label} — total ${record.totalMs} ms ` +
            `(${JSON.stringify(record.breakdown)})`
        );
      } else if (record.event === "run-begin") {
        this.channel.appendLine(`[${record.runId}] ${record.label} — begin`);
      }
    }
    try {
      fs.mkdirSync(path.dirname(this.filePath), { recursive: true });
      fs.appendFileSync(this.filePath, line + "\n");
    } catch {
      /* timing must never break the editor path */
    }
  }
}

/** A single in-progress timed pass. */
export class TimingRun {
  private readonly steps: TimingStep[] = [];
  private readonly startedMs = Date.now();

  constructor(
    readonly runId: string,
    private readonly label: string,
    private readonly emit: (record: Record<string, unknown>) => void
  ) {
    this.emit({ event: "run-begin", runId, label, ts: nowIso() });
  }

  /** Record `step` as having taken `ms` (measured by the caller). */
  step(step: string, ms: number, extra?: Record<string, unknown>): void {
    this.steps.push({ step, ms, extra });
    this.emit({ event: "step", runId: this.runId, step, ms, extra, ts: nowIso() });
  }

  /**
   * Time an awaited operation, record it as `step`, and return its result.
   * The single place a step's duration is measured, so every step is timed the
   * same way.
   */
  async time<T>(step: string, op: () => Promise<T>, extra?: (r: T) => Record<string, unknown>): Promise<T> {
    const t0 = Date.now();
    const r = await op();
    this.step(step, Date.now() - t0, extra ? extra(r) : undefined);
    return r;
  }

  /** Close the pass: emit the total and a per-step breakdown. */
  end(extra?: Record<string, unknown>): void {
    const totalMs = Date.now() - this.startedMs;
    const breakdown: Record<string, number> = {};
    for (const s of this.steps) {
      breakdown[s.step] = (breakdown[s.step] ?? 0) + s.ms;
    }
    this.emit({
      event: "run-end",
      runId: this.runId,
      label: this.label,
      totalMs,
      breakdown,
      extra,
      ts: nowIso(),
    });
  }
}

/** ISO timestamp; isolated so the one clock read is easy to find. */
function nowIso(): string {
  return new Date().toISOString();
}
