// SPDX-License-Identifier: MIT OR Apache-2.0
//
// linkerdClient.ts: a dependency-free (no `vscode` import) client for the
// sugar-linkerd daemon wire protocol, so the exact same code path is exercised
// by the editor extension AND the headless end-to-end receipt.
//
// Wire protocol (spec #126 §3, as exercised by
// implementations/rust/sugar-linkerd/tests/conformance.rs):
//   - Newline-delimited JSON-RPC 2.0 over a Unix domain socket.
//   - One request line in, one response line out; the daemon also serves
//     concurrent connections, so we open a fresh connection per request.
//   - parseFile { kitId, file, source } -> { diagnostics: LinkerDiagnostic[] }
//   - projectStatus {} / shutdown {} are used for readiness / teardown.

import * as net from "net";
import * as fs from "fs";
import * as cp from "child_process";

/** One diagnostic as returned by sugar-linkerd's `parseFile`. */
export interface LinkerDiagnostic {
  kind: string;
  errorKind: string;
  targetSymbol: string;
  sourceContractCid: string;
  reason: string;
  file: string | null;
  callSiteLocus: {
    file?: string;
    line?: number | null;
    column?: number | null;
  } | null;
}

/** Map a source file extension to the kitId sugar-linkerd dispatches on. */
export function kitIdForFile(file: string): string | undefined {
  const dot = file.lastIndexOf(".");
  const ext = dot >= 0 ? file.slice(dot + 1).toLowerCase() : "";
  const table: Record<string, string> = {
    rs: "rust",
    py: "python",
    go: "go",
    cs: "csharp",
    rb: "ruby",
    zig: "zig",
    java: "java",
    swift: "swift",
    cpp: "cpp",
    cc: "cpp",
    c: "c",
    php: "php",
    scala: "scala",
  };
  return table[ext];
}

/** A live handle to a sugar-linkerd daemon reachable at a Unix socket. */
export class LinkerdClient {
  private nextId = 1;
  private child: cp.ChildProcess | undefined;

  constructor(private readonly socketPath: string) {}

  /**
   * Ensure a daemon is reachable at `socketPath`. If it is not and a
   * `binaryPath` is supplied, spawn one and wait for the socket to answer.
   */
  async ensureDaemon(
    binaryPath: string | undefined,
    snapshotPath: string,
    idleTimeoutMs = 600_000
  ): Promise<void> {
    if (await this.isLive()) {
      return;
    }
    if (!binaryPath) {
      throw new Error(
        `no sugar-linkerd at ${this.socketPath} and no binaryPath configured ` +
          `(resolve one with: bin/sugarbin --bin sugar-linkerd)`
      );
    }
    try {
      fs.unlinkSync(this.socketPath);
    } catch {
      /* socket absent: fine */
    }
    this.child = cp.spawn(
      binaryPath,
      [
        "--socket",
        this.socketPath,
        "--snapshot",
        snapshotPath,
        "--idle-timeout-ms",
        String(idleTimeoutMs),
      ],
      { stdio: "ignore" }
    );
    this.child.unref();
    await this.waitForSocket(10_000);
  }

  private async isLive(): Promise<boolean> {
    if (!fs.existsSync(this.socketPath)) {
      return false;
    }
    try {
      await this.rpc("projectStatus", {});
      return true;
    } catch {
      return false;
    }
  }

  private async waitForSocket(timeoutMs: number): Promise<void> {
    const start = Date.now();
    while (Date.now() - start < timeoutMs) {
      if (fs.existsSync(this.socketPath)) {
        try {
          await this.rpc("projectStatus", {});
          return;
        } catch {
          /* not ready yet */
        }
      }
      await delay(50);
    }
    throw new Error(`sugar-linkerd socket ${this.socketPath} never became ready`);
  }

  /** Send a `parseFile` and return the diagnostics for this file. */
  async parseFile(
    kitId: string,
    file: string,
    source: string
  ): Promise<LinkerDiagnostic[]> {
    const res = await this.rpc("parseFile", { kitId, file, source });
    if (res.error) {
      throw new LinkerdRpcError(res.error.code, res.error.message);
    }
    const diags = res.result?.diagnostics;
    return Array.isArray(diags) ? (diags as LinkerDiagnostic[]) : [];
  }

  /** Best-effort daemon shutdown (used by tests). */
  async shutdown(): Promise<void> {
    try {
      await this.rpc("shutdown", {});
    } catch {
      /* daemon may already be gone */
    }
    if (this.child && !this.child.killed) {
      this.child.kill();
    }
  }

  /** One request line in, one response line out, fresh connection. */
  private rpc(method: string, params: unknown): Promise<any> {
    const id = this.nextId++;
    const req = { jsonrpc: "2.0", id, method, params };
    return new Promise((resolve, reject) => {
      const conn = net.connect(this.socketPath);
      let buf = "";
      let settled = false;
      const done = (fn: () => void) => {
        if (settled) {
          return;
        }
        settled = true;
        conn.end();
        fn();
      };
      conn.on("connect", () => conn.write(JSON.stringify(req) + "\n"));
      conn.on("data", (chunk) => {
        buf += chunk.toString();
        const nl = buf.indexOf("\n");
        if (nl >= 0) {
          const line = buf.slice(0, nl);
          done(() => {
            try {
              resolve(JSON.parse(line));
            } catch (e) {
              reject(e);
            }
          });
        }
      });
      conn.on("error", (e) => done(() => reject(e)));
    });
  }
}

export class LinkerdRpcError extends Error {
  constructor(public readonly code: number, message: string) {
    super(message);
    this.name = "LinkerdRpcError";
  }
}

function delay(ms: number): Promise<void> {
  return new Promise((r) => setTimeout(r, ms));
}
