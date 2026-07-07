// SPDX-License-Identifier: MIT OR Apache-2.0
//
// extension.ts: the VS Code side of slice A (#3774).
//
// It is a plain LSP-style client (no language-server framework): on every
// open / edit of a supported document it asks sugar-linkerd to re-lift and
// re-link that file, then paints the returned per-file diagnostics as red
// squiggles. The adjudication is the PRODUCTION construction (`link()` inside
// the daemon), so the editor shows exactly what the proofchain says because it
// asks it. There is no shadow verifier here.
//
// Today's daemon discharges obligations structurally (JCS-canonical implication
// / vacuous discharge); the solver-backed semantic adjudication that turns a
// literal test assertion UNSAT is slice B/C (see README).

import * as fs from "fs";
import * as os from "os";
import * as path from "path";
import * as crypto from "crypto";
import * as vscode from "vscode";
import {
  LinkerdClient,
  kitIdForFile,
  LinkerDiagnostic,
  LinkerdRpcError,
  ERR_METHOD_NOT_FOUND,
  ERR_PROVE_CONTEXT_UNAVAILABLE,
  ProveRow as DaemonProveRow,
} from "./linkerdClient";
import {
  proveProject,
  mintProject,
  ProveDiagnostic,
  formatDetail,
  diagnosticsFromRows,
  ProveRow as ProveClientRow,
} from "./proveClient";
import { TimingLogger } from "./timing";

let client: LinkerdClient | undefined;
let diagnostics: vscode.DiagnosticCollection;
let proveDiagnostics: vscode.DiagnosticCollection;
let proveBinaryPath = "";
let proveOnSave = true;
let timing: TimingLogger | undefined;
const timers = new Map<string, NodeJS.Timeout>();

export async function activate(context: vscode.ExtensionContext): Promise<void> {
  diagnostics = vscode.languages.createDiagnosticCollection("sugar");
  context.subscriptions.push(diagnostics);
  proveDiagnostics = vscode.languages.createDiagnosticCollection("sugar-prove");
  context.subscriptions.push(proveDiagnostics);

  const cfg = vscode.workspace.getConfiguration("sugar");
  proveBinaryPath = cfg.get<string>("prove.binaryPath") || "";
  proveOnSave = cfg.get<boolean>("prove.onSave") ?? true;

  // Timing log for the LSP prove path. Default: `<workspace>/.sugar/
  // lsp-timing.jsonl` (durable, greppable) mirrored to the "Sugar Timing"
  // OutputChannel (live). Override the path with `sugar.prove.timingLog`.
  const wsRoot = vscode.workspace.workspaceFolders?.[0]?.uri.fsPath ?? os.tmpdir();
  const timingPath =
    cfg.get<string>("prove.timingLog") || path.join(wsRoot, ".sugar", "lsp-timing.jsonl");
  const timingChannel = vscode.window.createOutputChannel("Sugar Timing");
  context.subscriptions.push(timingChannel);
  timing = new TimingLogger(timingPath, timingChannel);
  timingChannel.appendLine(`sugar: LSP timing -> ${timingPath}`);
  const socketPath = resolveSocketPath(cfg.get<string>("linkerd.socketPath") || "");
  const binaryPath = cfg.get<string>("linkerd.binaryPath") || undefined;
  const snapshotPath = socketPath + ".snapshot";

  // The link() path (bridge obligations) needs the linkerd daemon. The PROVE
  // path (native assertion vs a vendor .proof) does NOT — it shells `sugar
  // prove` and is fully independent. A linkerd failure must therefore NOT kill
  // the prove path: it is the actual red/green flip. Register linkerd's
  // listeners only if the daemon comes up; register prove unconditionally.
  const debounceMs = cfg.get<number>("debounceMs") ?? 250;
  client = new LinkerdClient(socketPath);
  let linkerdUp = false;
  try {
    // The daemon's resident prove context (vendor pool, lift overlay) is
    // per-project: pass the workspace root explicitly so proveConsistency
    // serves THIS project rather than whatever cwd the extension host had.
    // 24h idle timeout: the editor session owns this daemon; a 10-minute
    // idle-suicide meant every post-coffee save silently paid the ~34s cold
    // shell prove (the daemon died, the client threw, the fallback ate it).
    await client.ensureDaemon(binaryPath, snapshotPath, 86_400_000, [
      "--project-root",
      wsRoot,
    ]);
    linkerdUp = true;
  } catch (e) {
    // Keep the client: the prove path heals (respawns the daemon) per save.
    // Nulling it here doomed the whole session to the cold path.
    console.error(`sugar: linkerd unavailable at activation (will heal on save): ${(e as Error).message}`);
  }

  if (linkerdUp) {
    context.subscriptions.push(
      vscode.workspace.onDidOpenTextDocument((doc) => scheduleLink(doc, 0)),
      vscode.workspace.onDidChangeTextDocument((e) => scheduleLink(e.document, debounceMs)),
      vscode.workspace.onDidCloseTextDocument((doc) => diagnostics.delete(doc.uri))
    );
  }

  // The PROVE path (native assertion vs vendor .proof). A directory prove mints
  // + solves, so it runs on OPEN and on SAVE (or on keystroke debounce only if
  // the user opts out of on-save), never per-keystroke. This is the operation
  // that flips a NATIVE `assert` red/green against a loaded vendor universe --
  // distinct from link() above.
  if (proveBinaryPath) {
    context.subscriptions.push(
      vscode.languages.registerCodeActionsProvider(
        { language: "python", scheme: "file" },
        new SugarProveFixProvider(),
        { providedCodeActionKinds: SugarProveFixProvider.kinds }
      ),
      vscode.workspace.onDidSaveTextDocument((doc) => void runProve(doc)),
      vscode.workspace.onDidOpenTextDocument((doc) => void runProve(doc)),
      vscode.workspace.onDidChangeTextDocument((e) => {
        if (!proveOnSave) {
          void runProve(e.document);
        }
      })
    );
  }

  // Prime any already-open documents.
  for (const doc of vscode.workspace.textDocuments) {
    if (linkerdUp) {
      scheduleLink(doc, 0);
    }
    if (proveBinaryPath) {
      void runProve(doc);
    }
  }
}

export function deactivate(): void {
  for (const t of timers.values()) {
    clearTimeout(t);
  }
  timers.clear();
  void client?.shutdown();
}

function scheduleLink(doc: vscode.TextDocument, delayMs: number): void {
  if (doc.uri.scheme !== "file") {
    return;
  }
  const kitId = kitIdForFile(doc.fileName);
  if (!kitId) {
    return;
  }
  const key = doc.uri.toString();
  const existing = timers.get(key);
  if (existing) {
    clearTimeout(existing);
  }
  timers.set(
    key,
    setTimeout(() => {
      timers.delete(key);
      void linkDocument(doc, kitId);
    }, delayMs)
  );
}

async function linkDocument(doc: vscode.TextDocument, kitId: string): Promise<void> {
  if (!client) {
    return;
  }
  try {
    const diags = await client.parseFile(kitId, doc.fileName, doc.getText());
    diagnostics.set(doc.uri, diags.map((d) => toVsDiagnostic(doc, d)));
  } catch (e) {
    // A lifter-unavailable / kit-not-in-manifest error is not a proof failure;
    // surface it as an information diagnostic-free notice rather than a squiggle.
    console.error(`sugar: parseFile failed for ${doc.fileName}: ${(e as Error).message}`);
  }
  // Warm consistency prove now runs as part of `runProve` (see below): the
  // resident daemon's `proveConsistency` is tried first there, on the actual
  // editor prove path (mint-on-save + project-local diagnostics), instead of
  // as an unpainted side-channel here.
}

/**
 * Run `sugar prove --json` on the consumer PROJECT containing `doc` and paint
 * its `unsatisfied` rows as red squiggles at each row's source locus. Groups
 * diagnostics by the file the row points at (a project prove can implicate any
 * file in the project, not only the saved one). Cheap and side-effect-free
 * except for the diagnostic collection.
 */
async function runProve(doc: vscode.TextDocument): Promise<void> {
  if (!proveBinaryPath || doc.uri.scheme !== "file") {
    return;
  }
  const kitId = kitIdForFile(doc.fileName);
  if (kitId !== "python" && kitId !== "rust") {
    // The demo lifters (native-assertion vs vendor .proof) are python and rust
    // today; other kits fall through until their own lift/witness surfaces land.
    return;
  }
  const projectDir = resolveProjectDir(doc.uri);
  if (!projectDir) {
    return;
  }
  try {
    // The lifter needs its language env resolvable. For python that means a
    // PYTHONPATH import root. For rust, `sugar-cli` discovers component
    // manifests (rust-test-assertions / rust-cargo-test-witness lifters) by
    // walking the project root and its ancestors for `.sugar/components/`
    // (see component_plan.rs::ancestor_component_roots) -- so a consumer
    // project that ships its OWN `.sugar/components/*/manifest.toml` with
    // sugarbin-resolved absolute binary paths needs no extra env at all. The
    // optional `sugar.prove.rustBinDir` only covers the case where cargo/
    // rustc or the helper RPC binaries are not already on the ambient PATH.
    const cfg = vscode.workspace.getConfiguration("sugar");
    const binDir = cfg.get<string>("prove.pythonBinDir") || "";
    const pyPath = cfg.get<string>("prove.pythonPath") || "";
    const rustBinDir = cfg.get<string>("prove.rustBinDir") || "";
    const env: NodeJS.ProcessEnv = {};
    if (kitId === "python" && binDir) {
      env.PATH = `${binDir}:${process.env.PATH ?? ""}`;
    }
    if (kitId === "python" && pyPath) {
      env.PYTHONPATH = process.env.PYTHONPATH ? `${pyPath}:${process.env.PYTHONPATH}` : pyPath;
    }
    if (kitId === "rust" && rustBinDir) {
      env.PATH = `${rustBinDir}:${process.env.PATH ?? ""}`;
    }
    // Time each LSP step into the timing log.
    const run = timing?.run(path.basename(projectDir) + "/" + path.basename(doc.fileName));
    // DAEMON-FIRST, MINT-FREE: the daemon's lift-and-merge overlay lifts the
    // request's OWN source text (sent below), so no CLI mint is needed on the
    // warm path -- the mint runs ONLY if the daemon path falls through to the
    // cold shell fallback (which proves the on-disk .proof and therefore
    // needs the on-save re-mint).
    const mint = () => mintProject({ binaryPath: proveBinaryPath, projectDir, env });
    // DAEMON-FIRST PRODUCER (#3774 warm-daemon slice): if the resident
    // sugar-linkerd daemon is up and speaks `proveConsistency`, ask it first --
    // it amortizes the pool/plan/registry/compiler load across saves instead of
    // re-loading the whole catalog per `sugar prove` shell-out. Both producers
    // feed the SAME diagnostic mapping below (`diagnosticsFromRows` +
    // `proveToVsDiagnostic`), so there is exactly one painter regardless of
    // which producer ran. Any failure (older daemon: ERR_METHOD_NOT_FOUND;
    // daemon still loading: ERR_PROVE_CONTEXT_UNAVAILABLE; daemon down: any
    // throw) falls back to the existing mint+proveProject shell path -- never a
    // silent gap, just a slower cold path.
    const kitIdForDaemon = kitId; // narrowed to "python" above
    const daemonProve = async (): Promise<ProveDiagnostic[] | undefined> => {
      if (!client) {
        return undefined;
      }
      try {
        // The daemon's lift-and-merge overlay lifts `doc.getText()` itself
        // (source-overlay project + resident vendor pool), so the warm path
        // needs NO CLI mint. A `degraded: true` response means the daemon
        // fell back to its resident on-disk pool for this request -- treat it
        // as a MISS (return undefined) so the cold path below runs its own
        // mint+prove against fresh disk state instead of trusting stale rows.
        const { rows, degraded, degradedReason } =
          await client.proveConsistencyDetailed(
            kitIdForDaemon,
            doc.fileName,
            doc.getText()
          );
        if (degraded) {
          console.log(
            `sugar: daemon-prove degraded -> cold fallback: ${degradedReason ?? "no reason given"}`
          );
          return undefined;
        }
        return diagnosticsFromRows(rows as unknown as ProveClientRow[]);
      } catch (e) {
        // HEAL, don't just fall back: a dead daemon (idle exit, crash, stale
        // socket) is respawned once and the request retried -- otherwise every
        // save after an idle period silently pays the ~34s cold prove.
        try {
          const cfg2 = vscode.workspace.getConfiguration("sugar");
          const lbin = cfg2.get<string>("linkerd.binaryPath") || undefined;
          const sp = resolveSocketPath(cfg2.get<string>("linkerd.socketPath") || "");
          const ws = vscode.workspace.workspaceFolders?.[0]?.uri.fsPath ?? projectDir;
          await client!.ensureDaemon(lbin, sp + ".snapshot", 86_400_000, [
            "--project-root",
            ws,
          ]);
          const retry = await client!.proveConsistencyDetailed(
            kitIdForDaemon,
            doc.fileName,
            doc.getText()
          );
          if (!retry.degraded) {
            console.log("sugar: daemon healed after respawn");
            return diagnosticsFromRows(retry.rows as unknown as ProveClientRow[]);
          }
        } catch (e2) {
          console.log(`sugar: daemon respawn failed: ${(e2 as Error).message}`);
        }
        const code = e instanceof LinkerdRpcError ? e.code : undefined;
        const expected =
          code === ERR_METHOD_NOT_FOUND || code === ERR_PROVE_CONTEXT_UNAVAILABLE;
        console.log(
          `sugar: daemon-prove unavailable, falling back to cold prove ` +
            `(file=${doc.fileName} expected=${expected} error=${(e as Error).message})`
        );
        return undefined;
      }
    };
    let diagnostics = run
      ? await run.time("daemon-prove", daemonProve, (d) => ({
          usedDaemon: d !== undefined,
          diagnostics: d?.length ?? 0,
        }))
      : await daemonProve();
    let usedDaemon = diagnostics !== undefined;
    if (diagnostics === undefined) {
      // COLD FALLBACK: shell mint (the on-disk .proof must reflect the save)
      // then shell prove. This is the only path that mints now.
      if (run) {
        await run.time("mint", mint, (ok) => ({ ok }));
      } else {
        await mint();
      }
      const prove = () => proveProject({ binaryPath: proveBinaryPath, projectDir, env });
      const res = run
        ? await run.time("prove", prove, (r) => ({
            rows: r.rows.length,
            diagnostics: r.diagnostics.length,
            exitCode: r.exitCode,
            subprocessMs: r.elapsedMs,
          }))
        : await prove();
      diagnostics = res.diagnostics;
    }
    const paintStart = Date.now();
    // Rebuild the whole prove collection for this project from scratch so
    // cleared rows (green now) drop their squiggles.
    proveDiagnostics.clear();
    const byFile = new Map<string, vscode.Diagnostic[]>();
    // PROJECT-LOCAL SCOPING. A project prove can implicate any memento in the
    // pool, including a VENDOR proof's own internal assertions (e.g. the pandas
    // .proof carries 21 violations anchored at pandas' own test paths). Those
    // rows are real for the vendor but are NOT the user's code -- painting them
    // would squiggle files the user never wrote. Keep only rows whose resolved
    // file is INSIDE projectDir AND exists on disk (the consumer's own sources).
    const rootAbs = path.resolve(projectDir);
    for (const d of diagnostics) {
      const abs = path.resolve(
        path.isAbsolute(d.file) ? d.file : path.join(projectDir, d.file)
      );
      const inProject =
        abs === rootAbs || abs.startsWith(rootAbs + path.sep);
      if (!inProject || !fs.existsSync(abs)) {
        continue;
      }
      const list = byFile.get(abs) ?? [];
      list.push(proveToVsDiagnostic(d));
      byFile.set(abs, list);
    }
    for (const [file, list] of byFile) {
      proveDiagnostics.set(vscode.Uri.file(file), list);
    }
    if (run) {
      const painted = Array.from(byFile.values()).reduce((n, l) => n + l.length, 0);
      run.step("paint", Date.now() - paintStart, { files: byFile.size, painted });
      run.end({ projectDir, file: doc.fileName, usedDaemon });
    }
  } catch (e) {
    console.error(`sugar: prove failed for ${projectDir}: ${(e as Error).message}`);
  }
}

/** The nearest workspace folder for a document (its consumer project root). */
function resolveProjectDir(uri: vscode.Uri): string | undefined {
  const folder = vscode.workspace.getWorkspaceFolder(uri);
  if (folder) {
    return folder.uri.fsPath;
  }
  return path.dirname(uri.fsPath);
}

/** Turn one prove diagnostic into a VS Code diagnostic anchored at its locus. */
function proveToVsDiagnostic(d: ProveDiagnostic): vscode.Diagnostic {
  const line0 = Math.max(0, d.line - 1);
  const col = typeof d.column === "number" ? d.column : 0;
  // Anchor at the locus; span the rest of the line so the squiggle is visible.
  const range = new vscode.Range(line0, col, line0, Number.MAX_SAFE_INTEGER);
  const diag = new vscode.Diagnostic(
    range,
    formatDetail(d),
    vscode.DiagnosticSeverity.Error
  );
  diag.source = "sugar-prove";
  diag.code = d.status;
  // Stash the PROVEN value (the vendor's fact for this callsite) so a Quick Fix
  // can offer to replace the asserted RHS with it. Case 2 (universe): the
  // z3-derived value; case 1 (sworn vector): the vendor's own value -- both
  // arrive as the RHS of `vendorFactFol` (`... = <value>`). No extra solve here.
  const proven = provenValueOf(d.vendorFactFol);
  if (proven !== undefined) {
    (diag as unknown as { sugarFixValue: string }).sugarFixValue = proven;
  }
  return diag;
}

/**
 * Extract the proven right-hand value from a `vendorFactFol` string such as
 * `⊢ call:encodeBase64("xyz") = "eHl6"` (-> `"eHl6"`) or `... = 0` (-> `0`).
 * Returns the literal verbatim (quotes preserved for strings), or undefined.
 */
function provenValueOf(vendorFactFol?: string): string | undefined {
  if (!vendorFactFol) {
    return undefined;
  }
  const idx = vendorFactFol.lastIndexOf(" = ");
  if (idx < 0) {
    return undefined;
  }
  const rhs = vendorFactFol.slice(idx + 3).trim();
  return rhs.length > 0 ? rhs : undefined;
}

/**
 * The Quick Fix: on a red prove diagnostic that carries a proven value, offer
 * to rewrite the assertion's RHS (everything after `==`) to that value. This is
 * "replace with proven value" -- the vendor's fact the consumer contradicted.
 */
class SugarProveFixProvider implements vscode.CodeActionProvider {
  static readonly kinds = [vscode.CodeActionKind.QuickFix];

  provideCodeActions(
    document: vscode.TextDocument,
    _range: vscode.Range | vscode.Selection,
    context: vscode.CodeActionContext
  ): vscode.CodeAction[] {
    const actions: vscode.CodeAction[] = [];
    for (const diag of context.diagnostics) {
      if (diag.source !== "sugar-prove") {
        continue;
      }
      const proven = (diag as unknown as { sugarFixValue?: string }).sugarFixValue;
      if (proven === undefined) {
        continue;
      }
      const line0 = diag.range.start.line;
      const lineText = document.lineAt(line0).text;
      const eq = lineText.indexOf("==");
      if (eq < 0) {
        continue;
      }
      // Replace everything after `==` (the asserted RHS) with the proven value.
      const rhsStart = new vscode.Position(line0, eq + 2);
      const rhsEnd = new vscode.Position(line0, lineText.length);
      const fix = new vscode.CodeAction(
        `Replace with proven value: ${proven}`,
        vscode.CodeActionKind.QuickFix
      );
      fix.diagnostics = [diag];
      fix.isPreferred = true;
      fix.edit = new vscode.WorkspaceEdit();
      fix.edit.replace(document.uri, new vscode.Range(rhsStart, rhsEnd), ` ${proven}`);
      actions.push(fix);
    }
    return actions;
  }
}

/** Turn one linkerd diagnostic into a VS Code diagnostic anchored at its locus. */
function toVsDiagnostic(
  doc: vscode.TextDocument,
  d: LinkerDiagnostic
): vscode.Diagnostic {
  const range = rangeFor(doc, d);
  const message =
    `${d.errorKind}: ${d.reason}` +
    (d.targetSymbol ? `\n  target: ${d.targetSymbol}` : "");
  const diag = new vscode.Diagnostic(range, message, vscode.DiagnosticSeverity.Error);
  diag.source = "sugar-linkerd";
  diag.code = d.errorKind;
  return diag;
}

function rangeFor(doc: vscode.TextDocument, d: LinkerDiagnostic): vscode.Range {
  const locus = d.callSiteLocus;
  const line1 = locus?.line ?? undefined;
  if (typeof line1 === "number" && line1 > 0) {
    const line0 = line1 - 1;
    const col = typeof locus?.column === "number" ? locus.column : 0;
    // Prefer the word at the call site; fall back to the whole line.
    const wordRange = doc.getWordRangeAtPosition(new vscode.Position(line0, col));
    if (wordRange) {
      return wordRange;
    }
    const lineText = line0 < doc.lineCount ? doc.lineAt(line0) : undefined;
    if (lineText) {
      return lineText.range;
    }
    return new vscode.Range(line0, col, line0, col + 1);
  }
  // Locus without a line: anchor to the top of the file.
  return new vscode.Range(0, 0, 0, 1);
}

function resolveSocketPath(configured: string): string {
  if (configured) {
    return configured;
  }
  const root = vscode.workspace.workspaceFolders?.[0]?.uri.fsPath ?? os.homedir();
  const hash = crypto.createHash("sha256").update(root).digest("hex").slice(0, 16);
  return path.join(os.tmpdir(), `sugar-linkerd-${hash}.sock`);
}
