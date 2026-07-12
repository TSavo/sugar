// SPDX-License-Identifier: MIT OR Apache-2.0
//
// reportMode.ts: paint sugar/reportMode ranges from sugar-lsp.
// Intelligence is the server; this host only applies decorations when
// sugar.reportMode is enabled (#4149).

import * as vscode from "vscode";

export type ReportPaint =
  | "fact"
  | "walk_open"
  | "dig_stop"
  | "minority"
  | "silent"
  | "forged"
  | "unsat";

export interface ReportModeRange {
  kind: ReportPaint;
  range: {
    start: { line: number; character: number };
    end: { line: number; character: number };
  };
  label: string;
  source?: string;
}

export interface ReportModePayload {
  uri: string;
  totals: {
    stated: number;
    accounted: number;
    silentlyUnaccounted: number;
    minorityPresent: number;
    minorityDug: number;
    minorityUnAsserted: number;
    facts: number;
    unsat: number;
  };
  ranges: ReportModeRange[];
  workspaceRanges?: Array<ReportModeRange & { uri: string }>;
  workspace?: {
    totals: ReportModePayload["totals"];
    ranges: Array<ReportModeRange & { uri: string }>;
  };
}

function dec(
  overviewRulerColor: string,
  backgroundColor: string,
  borderColor?: string
): vscode.TextEditorDecorationType {
  return vscode.window.createTextEditorDecorationType({
    isWholeLine: false,
    overviewRulerLane: vscode.OverviewRulerLane.Left,
    overviewRulerColor,
    backgroundColor,
    borderColor,
    borderWidth: borderColor ? "0 0 0 2px" : undefined,
    borderStyle: borderColor ? "solid" : undefined,
  });
}

/** Report mode palette: blue fact · green dig · red dig-stop/crime · yellow minority. */
export class ReportModePainter {
  private readonly fact = dec("rgba(30,144,255,0.9)", "rgba(30,144,255,0.12)", "rgba(30,144,255,0.8)");
  private readonly walkOpen = dec("rgba(46,160,67,0.9)", "rgba(46,160,67,0.10)", "rgba(46,160,67,0.7)");
  private readonly digStop = dec("rgba(248,81,73,0.9)", "rgba(248,81,73,0.12)", "rgba(248,81,73,0.8)");
  private readonly minority = dec("rgba(210,153,34,0.9)", "rgba(210,153,34,0.14)", "rgba(210,153,34,0.8)");
  private readonly silent = dec("rgba(248,81,73,1)", "rgba(248,81,73,0.18)", "rgba(248,81,73,1)");
  private readonly forged = dec("rgba(248,81,73,1)", "rgba(248,81,73,0.18)", "rgba(248,81,73,1)");
  // Unsat is also a diagnostic squiggle; light wash so both channels read.
  private readonly unsat = dec("rgba(248,81,73,0.7)", "rgba(248,81,73,0.08)");

  private readonly byUri = new Map<string, ReportModePayload>();
  private enabled = true;
  private status: vscode.StatusBarItem;

  constructor() {
    this.status = vscode.window.createStatusBarItem(vscode.StatusBarAlignment.Left, 50);
    this.status.command = "sugar.reportMode.toggle";
    this.refreshStatus();
    this.status.show();
  }

  dispose(): void {
    for (const d of [
      this.fact,
      this.walkOpen,
      this.digStop,
      this.minority,
      this.silent,
      this.forged,
      this.unsat,
    ]) {
      d.dispose();
    }
    this.status.dispose();
  }

  setEnabled(on: boolean): void {
    this.enabled = on;
    this.refreshStatus();
    this.repaintAll();
  }

  isEnabled(): boolean {
    return this.enabled;
  }

  toggle(): void {
    this.setEnabled(!this.enabled);
    void vscode.workspace
      .getConfiguration("sugar")
      .update("reportMode", this.enabled, vscode.ConfigurationTarget.Global);
  }

  onPayload(payload: ReportModePayload): void {
    this.byUri.set(payload.uri, payload);
    // The server already grouped and counted workspace ranges. The host only
    // projects each ready range list into the matching visible document.
    for (const wr of payload.workspace?.ranges ?? []) {
      const existing = this.byUri.get(wr.uri);
      this.byUri.set(wr.uri, {
        uri: wr.uri,
        totals: payload.workspace!.totals,
        ranges: [...(existing?.ranges ?? []).filter((r) => r.kind !== wr.kind || r.label !== wr.label), wr],
        workspace: payload.workspace,
      });
      this.paintUri(wr.uri);
    }
    this.paintUri(payload.uri);
    this.refreshStatus();
  }

  private refreshStatus(): void {
    if (!this.enabled) {
      this.status.text = "Sugar report: off";
      this.status.tooltip = "Click to enable report mode";
      return;
    }
    // Aggregate last payload for active editor if any.
    const ed = vscode.window.activeTextEditor;
    const key = ed?.document.uri.toString();
    const p = key ? this.byUri.get(key) : undefined;
    if (!p) {
      this.status.text = "Sugar report";
      this.status.tooltip = "Report mode on — awaiting sugar/reportMode";
      return;
    }
    const t = p.workspace?.totals ?? p.totals;
    const digStop = (this.byUri.get(key!)?.ranges ?? []).filter((r) => r.kind === "dig_stop").length;
    const digOpen = (this.byUri.get(key!)?.ranges ?? []).filter((r) => r.kind === "walk_open").length;
    const minorityRanges = (this.byUri.get(key!)?.ranges ?? []).filter((r) => r.kind === "minority").length;
    // Dual-axis one-liner: same census as CLI `sugar lift --report` (#4149).
    // stated/accounted/silent | minority — dig/facts/unsat stay in tooltip.
    this.status.text = `Sugar ${t.stated}/${t.accounted}/${t.silentlyUnaccounted} | min=${t.minorityUnAsserted}`;
    this.status.tooltip = [
      `stated=${t.stated} accounted=${t.accounted} silently_unaccounted=${t.silentlyUnaccounted} | minority un_asserted=${t.minorityUnAsserted}`,
      `present=${t.minorityPresent} dug=${t.minorityDug} (minority paint ranges=${minorityRanges})`,
      `dig open=${digOpen} dig-stop=${digStop}  (dig-stop ≠ unsat)`,
      `facts=${t.facts} unsat=${t.unsat}`,
      "Click to toggle report mode",
    ].join("\n");
  }

  private repaintAll(): void {
    for (const uri of this.byUri.keys()) {
      this.paintUri(uri);
    }
    if (!this.enabled) {
      for (const ed of vscode.window.visibleTextEditors) {
        this.clearEditor(ed);
      }
    }
  }

  private paintUri(uriStr: string): void {
    const payload = this.byUri.get(uriStr);
    for (const ed of vscode.window.visibleTextEditors) {
      if (ed.document.uri.toString() !== uriStr) {
        continue;
      }
      if (!this.enabled || !payload) {
        this.clearEditor(ed);
        continue;
      }
      this.apply(ed, payload);
    }
  }

  private clearEditor(ed: vscode.TextEditor): void {
    ed.setDecorations(this.fact, []);
    ed.setDecorations(this.walkOpen, []);
    ed.setDecorations(this.digStop, []);
    ed.setDecorations(this.minority, []);
    ed.setDecorations(this.silent, []);
    ed.setDecorations(this.forged, []);
    ed.setDecorations(this.unsat, []);
  }

  private apply(ed: vscode.TextEditor, payload: ReportModePayload): void {
    const buckets: Record<ReportPaint, vscode.DecorationOptions[]> = {
      fact: [],
      walk_open: [],
      dig_stop: [],
      minority: [],
      silent: [],
      forged: [],
      unsat: [],
    };
    for (const r of payload.ranges) {
      const range = new vscode.Range(
        r.range.start.line,
        r.range.start.character,
        r.range.end.line,
        Math.min(r.range.end.character, 100000)
      );
      buckets[r.kind].push({
        range,
        hoverMessage: r.source
          ? new vscode.MarkdownString(`**${r.label}**\n\n\`\`\`\n${r.source}\n\`\`\``)
          : r.label,
      });
    }
    ed.setDecorations(this.fact, buckets.fact);
    ed.setDecorations(this.walkOpen, buckets.walk_open);
    ed.setDecorations(this.digStop, buckets.dig_stop);
    ed.setDecorations(this.minority, buckets.minority);
    ed.setDecorations(this.silent, buckets.silent);
    ed.setDecorations(this.forged, buckets.forged);
    ed.setDecorations(this.unsat, buckets.unsat);
  }
}
