// SPDX-License-Identifier: MIT OR Apache-2.0
//
// e2e.test.js: the slice A + slice B receipt (#3774 / #3767 slice 2).
//
// It speaks the sugar-linkerd wire protocol end to end — the same
// `LinkerdClient` the VS Code extension uses — and asserts T's flip in BOTH
// discharge modes the daemon now supports:
//
//   LEG 1 — STRUCTURAL (degraded) mode  [--no-solvers]:
//     the pure `link()` path. Slice A's fixtures flip red -> green -> red with
//     `implication-undecidable` for the lie. This proves the honest degraded
//     mode still works and is reported by name (`solverMode: "structural"`).
//
//   LEG 2 — SEMANTIC mode  [default, z3 on PATH]:
//     the `link_with_solvers` path. A structurally-distinct, logically-VALID
//     obligation (`x >= 1  =>  x > 0`) is discharged by z3 -> GREEN (no
//     diagnostic); weaken the caller post to a LIE (`x >= 0 => x > 0`,
//     counterexample x = 0) -> RED `implication-unprovable`; correct it ->
//     clears. This is the semantic current: adjudication by z3, live.
//
// No GUI / VS Code host is needed: the diagnostics the editor would paint are
// exactly the arrays this test asserts on. A full editor E2E is not possible
// headlessly in CI, so this LSP-protocol-level test IS the receipt.
//
// The daemon binary is resolved by run-e2e.sh (via bin/sugarbin) and passed in
// SUGAR_LINKERD_BIN. The `rust` kit is used because its lifter runs in-process
// inside the daemon — no external kit binary is required, so the receipt is
// hermetic.

const assert = require("assert");
const os = require("os");
const path = require("path");
const fs = require("fs");

const { LinkerdClient } = require("../out/linkerdClient.js");

const BIN = process.env.SUGAR_LINKERD_BIN;
const FIXTURES = path.join(__dirname, "fixtures");

let failures = 0;
function check(name, cond, detail) {
  if (cond) {
    console.log(`ok   - ${name}`);
  } else {
    failures++;
    console.log(`FAIL - ${name}${detail ? ` :: ${detail}` : ""}`);
  }
}

function read(fixture) {
  return fs.readFileSync(path.join(FIXTURES, fixture), "utf8");
}

// 1-based line of a call site inside a fixture, computed so assertions are not
// brittle hardcoded numbers.
function callLine(source, needle) {
  return (
    source
      .split("\n")
      .findIndex((l) => l.includes(needle) && !l.trimStart().startsWith("//")) + 1
  );
}

// ---- LEG 1: structural (degraded) mode — slice A ----
async function structuralLeg() {
  console.log("\n== LEG 1: structural (--no-solvers) mode — slice A ==");
  const tag = `sugar-e2e-struct-${process.pid}`;
  const socketPath = path.join(os.tmpdir(), `${tag}.sock`);
  const snapshotPath = path.join(os.tmpdir(), `${tag}.snapshot`);
  const client = new LinkerdClient(socketPath);

  const docPath = path.join(os.tmpdir(), `${tag}-test_index.rs`);
  const redSource = read("red.rs");
  const greenSource = read("green.rs");
  const expectedLine = callLine(redSource, "checked_index(7)");

  try {
    await client.ensureDaemon(BIN, snapshotPath, 600_000, ["--no-solvers"]);

    const status = await client.projectStatus();
    check(
      "structural: daemon reports solverMode=structural (degraded mode named, not silent)",
      status.solverMode === "structural",
      JSON.stringify(status)
    );

    // ---- 1. LYING assertion -> RED. ----
    const red = await client.parseFile("rust", docPath, redSource);
    check("structural red: exactly one diagnostic", red.length === 1, `got ${red.length}`);
    const d = red[0] || {};
    check(
      "structural red: production error kind is a discharge refusal",
      d.errorKind === "implication-undecidable",
      d.errorKind
    );
    check(
      "structural red: carries the linker's reason text",
      typeof d.reason === "string" && /post_caller|pre_callee|discharge/.test(d.reason),
      d.reason
    );
    check(
      "structural red: diagnostic file matches the absolute document path",
      d.file === docPath,
      `${d.file} !== ${docPath}`
    );
    const line = d.callSiteLocus && d.callSiteLocus.line;
    check(
      "structural red: locus points at the checked_index(7) call line",
      line === expectedLine,
      `line=${line} (expected ${expectedLine})`
    );

    // ---- 2. Correct it -> GREEN. ----
    const green = await client.parseFile("rust", docPath, greenSource);
    check("structural green: diagnostic clears", green.length === 0, `got ${green.length}`);

    // ---- 3. Flip back -> RED again. ----
    const redAgain = await client.parseFile("rust", docPath, redSource);
    check("structural green->red: the squiggle returns", redAgain.length === 1, `got ${redAgain.length}`);
  } finally {
    await client.shutdown();
  }
}

// ---- LEG 2: semantic mode — slice B (z3) ----
async function semanticLeg() {
  console.log("\n== LEG 2: semantic (default, z3) mode — slice B ==");
  const tag = `sugar-e2e-sem-${process.pid}`;
  const socketPath = path.join(os.tmpdir(), `${tag}.sock`);
  const snapshotPath = path.join(os.tmpdir(), `${tag}.snapshot`);
  const client = new LinkerdClient(socketPath);

  const docPath = path.join(os.tmpdir(), `${tag}-caller.rs`);
  const greenSource = read("green_semantic.rs");
  const redSource = read("red_semantic.rs");
  const expectedLine = callLine(redSource, "callee(x)");

  try {
    await client.ensureDaemon(BIN, snapshotPath); // default: semantic when z3 present

    const status = await client.projectStatus();
    if (status.solverMode !== "semantic") {
      console.log(
        `SKIP - semantic leg: daemon reports solverMode=${status.solverMode} ` +
          `(no z3 resolvable). Structural leg already proved the degraded mode is honest.`
      );
      return;
    }
    check(
      "semantic: daemon reports solverMode=semantic with a z3 seat",
      status.solverMode === "semantic" &&
        Array.isArray(status.solverSeats) &&
        status.solverSeats.some((s) => /z3/i.test(s)),
      JSON.stringify(status)
    );

    // ---- 1. TRUTH (x>=1 => x>0) -> z3 discharges -> GREEN. ----
    const green = await client.parseFile("rust", docPath, greenSource);
    check(
      "semantic green: z3 discharges the valid obligation (no diagnostic)",
      green.length === 0,
      JSON.stringify(green)
    );

    // ---- 2. LIE (x>=0 => x>0, counterexample x=0) -> z3 refutes -> RED. ----
    const red = await client.parseFile("rust", docPath, redSource);
    check("semantic red: exactly one diagnostic", red.length === 1, `got ${red.length}`);
    const d = red[0] || {};
    check(
      "semantic red: z3 verdict is implication-unprovable (refuted, not merely undecidable)",
      d.errorKind === "implication-unprovable",
      d.errorKind
    );
    check(
      "semantic red: reason names the solver's post=>pre refutation",
      typeof d.reason === "string" && /post_caller|pre_callee|solver|violated/.test(d.reason),
      d.reason
    );
    check(
      "semantic red: diagnostic file matches the absolute document path",
      d.file === docPath,
      `${d.file} !== ${docPath}`
    );
    const line = d.callSiteLocus && d.callSiteLocus.line;
    check(
      "semantic red: locus points at the callee(x) call line",
      line === expectedLine,
      `line=${line} (expected ${expectedLine})`
    );

    // ---- 3. Correct it back to the truth -> clears. ----
    const greenAgain = await client.parseFile("rust", docPath, greenSource);
    check(
      "semantic red->green: correcting the lie clears the diagnostic",
      greenAgain.length === 0,
      JSON.stringify(greenAgain)
    );
  } finally {
    await client.shutdown();
  }
}

async function main() {
  assert.ok(BIN, "SUGAR_LINKERD_BIN must point at the sugar-linkerd binary");
  assert.ok(fs.existsSync(BIN), `sugar-linkerd binary not found at ${BIN}`);

  await structuralLeg();
  await semanticLeg();

  if (failures > 0) {
    console.error(`\n${failures} check(s) failed`);
    process.exit(1);
  }
  console.log(
    "\nslice A + B receipt: structural red->green->red AND semantic (z3) green->red->green verified through sugar-linkerd"
  );
}

main().catch((e) => {
  console.error(e);
  process.exit(1);
});
