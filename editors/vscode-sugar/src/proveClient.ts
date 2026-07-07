// SPDX-License-Identifier: MIT OR Apache-2.0
//
// proveClient.ts: a dependency-free (no `vscode` import) client that runs the
// PROVE operation on a consumer PROJECT and turns its `unsatisfied` rows into
// editor diagnostics, so the exact same code path is exercised by the VS Code
// extension AND the headless end-to-end receipt.
//
// WHY PROVE, NOT link(). The green/red flip T's north star (#3774) wants -- a
// NATIVE assertion (`assert encodeBase64("xyz") == "AAAA"`) going UNSAT against
// a VENDOR's loaded `.proof` universe -- is the `sugar prove` / verify-consistency
// operation, NOT the daemon's `link()` (bridge post => pre). `prove --json`
// conjoins the vendor fact + vendor universe + the consumer's own fact and z3
// decides SAT/UNSAT; the consumer row comes back `status: "unsatisfied"` on the
// lie. That verdict row IS the red squiggle.
//
// THE SEAM THAT MADE THIS ANCHORABLE. The consistency verdict row now carries
// the assertion's own source locus (`file`/`line`/`column`, recovered from the
// contract memento's `file`+`span`; see sugar-verifier/src/consistency.rs).
// Before that, a directory-prove dropped the source and there was nothing to
// anchor a squiggle to. Here we simply read `row.file`/`row.line`/`row.column`.

import * as cp from "child_process";

/** One prove receipt row (the subset the editor path reads). */
export interface ProveRow {
  property: string;
  status: string;
  reason: string;
  file: string | null;
  line: number | null;
  column: number | null;
  dischargeMethod?: string | null;
}

/** A diagnostic derived from a non-discharged consistency row. */
export interface ProveDiagnostic {
  /** Source file the row is anchored to, as the receipt reported it. */
  file: string;
  /** 1-based line of the offending assertion. */
  line: number;
  /** 0-based column, when the receipt carried one. */
  column: number | null;
  /** The prove verdict: "unsatisfied" | "undecidable" | ... (never "discharged"). */
  status: string;
  /** The euf/consistency property the row decided. */
  property: string;
  /** The verifier's reason string (solver verdict, contradiction, etc.). */
  reason: string;
}

export interface ProveResult {
  /** Diagnostics for every row that did not discharge and carries a locus. */
  diagnostics: ProveDiagnostic[];
  /** Every consistency row in the receipt (for observability / tests). */
  rows: ProveRow[];
  /** Wall-clock latency of the prove invocation, milliseconds. */
  elapsedMs: number;
  /** Process exit code (non-zero when the gate is red). */
  exitCode: number | null;
}

export interface ProveOptions {
  /** Path to the `sugar` binary (resolve via bin/sugarbin). */
  binaryPath: string;
  /** The consumer PROJECT directory to prove (the `.` argument). */
  projectDir: string;
  /** Extra env (PYTHONPATH / PATH for the lifter). Merged over process.env. */
  env?: NodeJS.ProcessEnv;
  /** Extra CLI args inserted before `--json` (e.g. debug flags). */
  extraArgs?: string[];
  /** Hard timeout, ms. Default 120_000. */
  timeoutMs?: number;
}

/**
 * A `status` a consistency row can report that the editor paints as a red
 * diagnostic. `discharged` (proven) and `refused` (honestly undecided, not a
 * violation) are NOT painted -- only a decided contradiction / encoding STOP.
 */
function isRedStatus(status: string): boolean {
  return status === "unsatisfied" || status === "undecidable";
}

/**
 * Scan noisy stdout for the JSON prove receipt (the first balanced `{...}`
 * object carrying a `rows` array). The CLI interleaves human/log lines with the
 * `--json` receipt, so we cannot `JSON.parse` the whole buffer.
 */
export function extractReceipt(stdout: string): { rows?: ProveRow[] } | undefined {
  // eslint-disable-next-line no-control-regex
  const clean = stdout.replace(/\x1b\[[0-9;]*m/g, "");
  for (let i = 0; i < clean.length; i++) {
    if (clean[i] !== "{") {
      continue;
    }
    const parsed = tryDecodeFrom(clean, i);
    if (parsed && Array.isArray((parsed as { rows?: unknown }).rows)) {
      return parsed as { rows: ProveRow[] };
    }
  }
  return undefined;
}

/** Attempt to parse a JSON value starting at `start`, returning it or undefined. */
function tryDecodeFrom(text: string, start: number): unknown {
  let depth = 0;
  let inStr = false;
  let esc = false;
  for (let j = start; j < text.length; j++) {
    const ch = text[j];
    if (inStr) {
      if (esc) {
        esc = false;
      } else if (ch === "\\") {
        esc = true;
      } else if (ch === '"') {
        inStr = false;
      }
      continue;
    }
    if (ch === '"') {
      inStr = true;
    } else if (ch === "{") {
      depth++;
    } else if (ch === "}") {
      depth--;
      if (depth === 0) {
        try {
          return JSON.parse(text.slice(start, j + 1));
        } catch {
          return undefined;
        }
      }
    }
  }
  return undefined;
}

/** Map a prove receipt's consistency rows into editor diagnostics. */
export function diagnosticsFromRows(rows: ProveRow[]): ProveDiagnostic[] {
  const out: ProveDiagnostic[] = [];
  for (const row of rows) {
    if (!row || typeof row.property !== "string") {
      continue;
    }
    // Only consistency rows carry an assertion locus; only red ones squiggle.
    if (!row.property.startsWith("consistency:")) {
      continue;
    }
    if (!isRedStatus(row.status)) {
      continue;
    }
    if (typeof row.file !== "string" || typeof row.line !== "number") {
      // No locus on this row: we refuse to guess a line (no fake anchoring).
      continue;
    }
    out.push({
      file: row.file,
      line: row.line,
      column: typeof row.column === "number" ? row.column : null,
      status: row.status,
      property: row.property,
      reason: row.reason,
    });
  }
  return out;
}

/**
 * Run `sugar prove --allow-failed-components . --json` on a consumer project and
 * return the diagnostics the editor should paint. Rejects only on spawn failure
 * or timeout; a red gate (non-zero exit) is a normal, resolved result.
 */
export function proveProject(opts: ProveOptions): Promise<ProveResult> {
  const started = Date.now();
  const args = [
    "prove",
    "--allow-failed-components",
    ".",
    ...(opts.extraArgs ?? []),
    "--json",
  ];
  return new Promise((resolve, reject) => {
    const child = cp.spawn(opts.binaryPath, args, {
      cwd: opts.projectDir,
      env: { ...process.env, ...(opts.env ?? {}) },
    });
    let stdout = "";
    let settled = false;
    const timer = setTimeout(() => {
      if (settled) {
        return;
      }
      settled = true;
      child.kill("SIGKILL");
      reject(new Error(`sugar prove timed out after ${opts.timeoutMs ?? 120_000}ms`));
    }, opts.timeoutMs ?? 120_000);

    child.stdout.on("data", (c) => (stdout += c.toString()));
    // stderr is log noise; the --json receipt lands on stdout.
    child.on("error", (e) => {
      if (settled) {
        return;
      }
      settled = true;
      clearTimeout(timer);
      reject(e);
    });
    child.on("close", (code) => {
      if (settled) {
        return;
      }
      settled = true;
      clearTimeout(timer);
      const receipt = extractReceipt(stdout);
      const rows: ProveRow[] = (receipt?.rows ?? []).filter(
        (r): r is ProveRow => !!r && typeof (r as ProveRow).property === "string"
      );
      resolve({
        diagnostics: diagnosticsFromRows(rows),
        rows,
        elapsedMs: Date.now() - started,
        exitCode: code,
      });
    });
  });
}
