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

/**
 * The three conjoined facts, rendered as human-readable FOL by the SAME renderer
 * `sugar lift --report --visual` uses (`proofir_formula_to_fol_with_instances`).
 * The verifier stamps these onto an `unsatisfied` consistency row's
 * `verification`; they are what the IDE squiggle shows. Any field is absent when
 * its ProofIR was not reachable at prove-emission (fail-open; never faked).
 */
export interface ConjoinedFactsFol {
  /** The vendor's proved universe, e.g. `⊢ str.eq-bv-blocks(out, base64.blocks(...))`. */
  vendorUniverseFol?: string;
  /** The consumer's OWN sworn fact, e.g. `⊢ call:encodeBase64("xyz") = "AAAA"`. */
  clientFactFol?: string;
  /** The vendor's OWN sworn vector, when reachable on the row. */
  vendorFactFol?: string;
}

/** One prove receipt row (the subset the editor path reads). */
export interface ProveRow {
  property: string;
  status: string;
  reason: string;
  file: string | null;
  line: number | null;
  column: number | null;
  dischargeMethod?: string | null;
  /** The row's verification detail, carrying the three FOL strings. */
  verification?: ConjoinedFactsFol | null;
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
  /** The vendor's proved universe, rendered as FOL (when reachable). */
  vendorUniverseFol?: string;
  /** The consumer's own sworn fact, rendered as FOL (when reachable). */
  clientFactFol?: string;
  /** The vendor's own sworn vector, rendered as FOL (when reachable). */
  vendorFactFol?: string;
}

/**
 * Build the IDE hover/diagnostic message for a prove diagnostic as the three
 * conjoined facts in human-readable FOL -- the SAME rendering
 * `sugar lift --report --visual` produces -- under VENDOR FACT / VENDOR UNIVERSE
 * / YOUR FACT headings, followed by the z3 verdict. Facts whose ProofIR was not
 * reachable at prove-emission are simply omitted (fail-open). YOUR FACT is
 * listed last as the most familiar line (the same equality the source asserts).
 */
/**
 * Pretty-print one FOL formula for the hover: break top-level conjuncts onto
 * their own lines and, when a call's argument list is long, put each argument
 * on its own indented line (recursively). NOTHING is truncated -- this is
 * layout only; every byte of the formula survives. Quoted strings are opaque
 * (never split, never counted for bracket depth).
 */
export function prettyFol(fol: string, indent = "    "): string {
  const splitTop = (s: string, sep: string): string[] => {
    const parts: string[] = [];
    let depth = 0;
    let inStr = false;
    let start = 0;
    for (let i = 0; i < s.length; i++) {
      const ch = s[i];
      if (inStr) {
        if (ch === '"' && s[i - 1] !== "\\") inStr = false;
        continue;
      }
      if (ch === '"') inStr = true;
      else if (ch === "(" || ch === "[") depth++;
      else if (ch === ")" || ch === "]") depth--;
      else if (depth === 0 && s.startsWith(sep, i)) {
        parts.push(s.slice(start, i));
        start = i + sep.length;
        i += sep.length - 1;
      }
    }
    parts.push(s.slice(start));
    return parts;
  };
  const hasTopComma = (s: string): boolean => {
    let depth = 0;
    let inStr = false;
    for (let i = 0; i < s.length; i++) {
      const ch = s[i];
      if (inStr) {
        if (ch === '"' && s[i - 1] !== "\\") inStr = false;
        continue;
      }
      if (ch === '"') inStr = true;
      else if (ch === "(" || ch === "[") depth++;
      else if (ch === ")" || ch === "]") depth--;
      else if (ch === "," ) return true;
    }
    return false;
  };
  const breakCall = (s: string, pad: string): string => {
    s = s.trim();
    // STRUCTURAL RULE (T): every comma becomes a line break + indent --
    // deterministic layout, not width-triggered. Only comma-free spans stay
    // on one line.
    if (!hasTopComma(s)) return pad + s;
    // find the outermost call's opening paren/bracket
    let inStr = false;
    for (let i = 0; i < s.length; i++) {
      const ch = s[i];
      if (inStr) {
        if (ch === '"' && s[i - 1] !== "\\") inStr = false;
        continue;
      }
      if (ch === '"') inStr = true;
      else if (ch === "(" || ch === "[") {
        const close = ch === "(" ? ")" : "]";
        // find matching close
        let depth = 1;
        let j = i + 1;
        let instr2 = false;
        for (; j < s.length; j++) {
          const c2 = s[j];
          if (instr2) {
            if (c2 === '"' && s[j - 1] !== "\\") instr2 = false;
            continue;
          }
          if (c2 === '"') instr2 = true;
          else if (c2 === "(" || c2 === "[") depth++;
          else if (c2 === ")" || c2 === "]") {
            depth--;
            if (depth === 0) break;
          }
        }
        const head = s.slice(0, i + 1);
        const body = s.slice(i + 1, j);
        const tail = s.slice(j); // starts with close
        const args = splitTop(body, ", ");
        if (args.length < 2) {
          // No comma at this level: descend, but GLUE -- the wrapper paren
          // stays on the same line as what it wraps (never a lone "(" line;
          // the ∧ line carries the start of its conjunct).
          const innerOne = breakCall(body, pad);
          const innerLines = innerOne.split("\n");
          if (innerLines.length === 1) return pad + s;
          innerLines[0] = pad + head + innerLines[0].trimStart();
          innerLines[innerLines.length - 1] = innerLines[innerLines.length - 1] + tail;
          return innerLines.join("\n");
        }
        const inner = args
          .map((a) => breakCall(a, pad + indent))
          .join(",\n");
        return pad + head + "\n" + inner + "\n" + pad + tail;
      }
    }
    return pad + s;
  };
  const conjuncts = splitTop(fol, " ∧ ");
  if (conjuncts.length > 1) {
    // Every ∧ becomes a line break; the connective leads the continuation
    // line so the eye scans the conjunction vertically.
    return conjuncts
      .map((c, i) => {
        const body = breakCall(c, indent);
        if (i === 0) return body;
        return indent.slice(0, Math.max(0, indent.length - 2)) + "∧ " + body.trimStart();
      })
      .join("\n");
  }
  return breakCall(fol, indent);
}

export function formatDetail(d: ProveDiagnostic): string {
  const strip = (s: string): string => s.replace(/^⊢\s*/, "");
  const lines: string[] = [];
  const parts: string[] = [];
  const section = (label: string, fol: string) => {
    lines.push(label);
    lines.push(prettyFol("⊢ " + strip(fol)));
  };
  if (d.vendorFactFol) {
    section("Vendor fact:", d.vendorFactFol);
    parts.push(strip(d.vendorFactFol));
  }
  if (d.vendorUniverseFol) {
    section("Vendor universe:", d.vendorUniverseFol);
    parts.push(strip(d.vendorUniverseFol));
  }
  if (d.clientFactFol) {
    section("Your fact:", d.clientFactFol);
    parts.push(strip(d.clientFactFol));
  }
  const verdict = d.status === "unsatisfied" ? "UNSAT" : d.status.toUpperCase();
  if (parts.length > 0) {
    // The Conjoined section IS the parts conjoined -> the solver's verdict:
    // each conjunct pretty-printed on its own block, verdict on the last line.
    lines.push("Conjoined:");
    // ONE call: the whole conjunction goes through prettyFol so the ∧ rule
    // (line start, indented, conjunct opening on the same line) applies.
    lines.push(prettyFol(parts.map((p) => "(" + p + ")").join(" ∧ ")));
    lines.push(`  →  ${verdict}`);
    // THE FIX: the model's answer. Case 2 (universe): z3.model DERIVED the
    // value from the vendor's law; case 1: it is the vendor's sworn value.
    // Either way the proven value rides vendorFactFol -- show the edit the
    // Quick Fix (⌘.) will apply.
    const rhsOf = (fol: string): string | undefined => {
      const i = fol.lastIndexOf(" = ");
      return i >= 0 ? fol.slice(i + 3).trim() : undefined;
    };
    const vendorVal = d.vendorFactFol ? rhsOf(d.vendorFactFol) : undefined;
    if (vendorVal !== undefined && d.clientFactFol) {
      const yours = strip(d.clientFactFol)
        .split(" ∧ ")
        .map((c) => rhsOf(c.trim()))
        .find((v) => v !== undefined && v !== vendorVal);
      if (yours !== undefined) {
        lines.push("The fix (z3.model):");
        lines.push(`    replace ${yours} with ${vendorVal}   — Quick Fix (⌘.) applies it`);
      }
    }
  } else {
    lines.push(`z3: ${d.status} — ${d.reason}`);
  }
  return lines.join("\n");
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
    const v = row.verification ?? undefined;
    out.push({
      file: row.file,
      line: row.line,
      column: typeof row.column === "number" ? row.column : null,
      status: row.status,
      property: row.property,
      reason: row.reason,
      vendorUniverseFol: v?.vendorUniverseFol,
      clientFactFol: v?.clientFactFol,
      vendorFactFol: v?.vendorFactFol,
    });
  }
  return out;
}

/**
 * The editor's "on save" step: re-lift the edited source into a fresh `.proof`
 * so `prove` reflects what the user just typed, not a stale mint. Cleans the
 * project's OWN prior proofs first (staged vendor imports under `.sugar/imports/`
 * are untouched), drops `.sugar/runs`, then `sugar mint --out . --quiet`.
 * Resolves true on a clean mint, false (never throws) so prove is still attempted.
 */
export function mintProject(opts: ProveOptions): Promise<boolean> {
  const fs = require("fs") as typeof import("fs");
  const pathMod = require("path") as typeof import("path");
  try {
    for (const n of fs.readdirSync(opts.projectDir)) {
      if (/^blake3-512_.*\.proof$/.test(n)) {
        fs.rmSync(pathMod.join(opts.projectDir, n), { force: true });
      }
    }
    fs.rmSync(pathMod.join(opts.projectDir, ".sugar", "runs"), { recursive: true, force: true });
  } catch {
    /* best-effort clean */
  }
  return new Promise((resolve) => {
    const child = cp.spawn(opts.binaryPath, ["mint", "--out", ".", "--quiet"], {
      cwd: opts.projectDir,
      env: { ...process.env, ...(opts.env ?? {}) },
    });
    let settled = false;
    const timer = setTimeout(() => {
      if (settled) return;
      settled = true;
      child.kill("SIGKILL");
      resolve(false);
    }, opts.timeoutMs ?? 120_000);
    child.on("error", () => {
      if (settled) return;
      settled = true;
      clearTimeout(timer);
      resolve(false);
    });
    child.on("close", (code) => {
      if (settled) return;
      settled = true;
      clearTimeout(timer);
      resolve(code === 0);
    });
  });
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
