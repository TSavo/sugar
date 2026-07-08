// SPDX-License-Identifier: MIT OR Apache-2.0
//
// rust-prove-e2e.test.js: the IDE PROVE-path receipt for a RUST consumer
// (#3774 "the LSP with pandas and rust kit").
//
// It drives the SAME module the VS Code extension runs -- `proveClient` --
// over the REAL fixture (examples/rust-serde-federation: a real serde_json
// 1.0.150 vendor row + a rust consumer crate, NO annotations) and asserts the
// rust parity of the python flip:
//
//   consumer-bad  -> a RED diagnostic anchored at the `assert_eq!` line in the
//                    CONSUMER's OWN tests/consumer_test.rs, carrying the
//                    `unsatisfied` reason (the vendor's sworn fact and the
//                    consumer's lie are contradictory).
//   consumer-good -> no diagnostic (the vendor's sworn fact and the consumer's
//                    fact agree; the current discharge law refuses -- not
//                    green-discharges -- singleton stated/stated corroboration,
//                    same law examples/serde-json-showcase's own good/ suite
//                    documents).
//   flip the literal "true" <-> "false" -> the diagnostic appears / clears.
//
// No VS Code host is needed: the diagnostics the editor would paint are
// exactly the array `proveProject` returns; `extension.ts` calls the same
// function (once kitId === "rust" is no longer gated out), so this
// LSP-diagnostic-level test IS the receipt for the editor behavior on a rust
// consumer.
//
// Env (set by run-rust-prove-e2e.sh):
//   SUGAR_BIN           resolved `sugar` binary (via bin/sugarbin)
//   SUGAR_EXAMPLE_DIR   examples/rust-serde-federation

const assert = require("assert");
const os = require("os");
const path = require("path");
const fs = require("fs");
const cp = require("child_process");

const { proveProject, formatDetail } = require("../out/proveClient.js");

const BIN = process.env.SUGAR_BIN;
const EXAMPLE_DIR = process.env.SUGAR_EXAMPLE_DIR;
assert(BIN && fs.existsSync(BIN), `SUGAR_BIN must point at a sugar binary (got ${BIN})`);
assert(EXAMPLE_DIR && fs.existsSync(EXAMPLE_DIR), `SUGAR_EXAMPLE_DIR must exist (got ${EXAMPLE_DIR})`);

let failures = 0;
function check(name, cond, detail) {
  if (cond) {
    console.log(`ok   - ${name}`);
  } else {
    failures++;
    console.log(`FAIL - ${name}${detail ? ` :: ${detail}` : ""}`);
  }
}

function run(binArgs, cwd, env) {
  return cp.spawnSync(BIN, binArgs, { cwd, env: { ...process.env, ...env }, encoding: "utf8" });
}

function mint(dir, env) {
  // Matches the editor's on-save step (proveClient.mintProject): clean the
  // dir's OWN prior proofs (staged vendor imports under .sugar/imports/ are
  // deliberately untouched), drop .sugar/runs, re-mint.
  for (const n of fs.readdirSync(dir)) {
    if (/^blake3-512_.*\.proof$/.test(n)) {
      fs.rmSync(path.join(dir, n), { force: true });
    }
  }
  fs.rmSync(path.join(dir, ".sugar", "runs"), { recursive: true, force: true });
  const r = run(["mint", "--out", ".", "--quiet"], dir, env);
  assert.strictEqual(r.status, 0, `mint failed in ${dir}: ${r.stderr || r.stdout}`);
}

// The rust prove pre-flight needs a `components/` registry claiming the
// "rust-test-assertions" / "rust-cargo-test-witness" / "rust-walk" surfaces
// by their REAL sugarbin-resolved binaries -- the repo's OWN top-level
// `.sugar/components/` (discovered exe-relative, see component_plan.rs)
// ships dev/debug-profile paths that this release-profile receipt would not
// find, and a LATER-discovered root by the same component NAME wins. Writing
// our own hermetic registry under `SUGAR_COMPONENT_PATH` (a later root than
// exe-relative, see component_plan.rs::component_roots) overrides it.
function writeComponentRegistry(work, binDir) {
  const dir = path.join(work, "components");
  const entries = {
    "rust-walk": [path.join(binDir, "sugar-walk-rpc"), "--rpc"],
    "rust-test-assertions": [path.join(binDir, "rust_test_assertions_rpc")],
    "rust-cargo-test-witness": [path.join(binDir, "witness_rpc")],
    "ir-compiler-smt-lib": [path.join(binDir, "sugar-ir-smt-lib")],
  };
  for (const [name, command] of Object.entries(entries)) {
    const compDir = path.join(dir, name);
    fs.mkdirSync(compDir, { recursive: true });
    const arr = command.map((t) => `"${t}"`).join(", ");
    fs.writeFileSync(
      path.join(compDir, "manifest.toml"),
      `name = "${name}"\nversion = "0.1.0"\nprotocol_version = "sugar-component/1"\ncommand = [${arr}]\n`
    );
  }
  return dir;
}

function firstProof(dir) {
  const f = fs.readdirSync(dir).find((n) => /^blake3-512_.*\.proof$/.test(n));
  return f ? path.join(dir, f) : undefined;
}

// The `assert_eq!(s, ...)` line, computed from source (not a brittle constant).
function assertLine(file) {
  const lines = fs.readFileSync(file, "utf8").split("\n");
  return lines.findIndex((l) => l.includes("assert_eq!(s,")) + 1;
}

// Copy a directory recursively (small fixtures only -- no need for a library).
function copyDir(src, dst) {
  fs.mkdirSync(dst, { recursive: true });
  for (const entry of fs.readdirSync(src, { withFileTypes: true })) {
    const s = path.join(src, entry.name);
    const d = path.join(dst, entry.name);
    if (entry.isDirectory()) {
      if (entry.name === "target") continue; // never copy build output
      copyDir(s, d);
    } else {
      fs.copyFileSync(s, d);
    }
  }
}

// Substitute @BIN_DIR@ in the rust lift plugin manifest templates with the
// REAL sugarbin-resolved bin dir -- mirrors examples/*/run.sh's `sed` step.
function templateManifests(dir, binDir) {
  for (const surface of ["rust-test-assertions", "rust-cargo-test-witness"]) {
    const src = path.join(dir, ".sugar", "lift", surface, "manifest.toml.in");
    const dst = path.join(dir, ".sugar", "lift", surface, "manifest.toml");
    const text = fs.readFileSync(src, "utf8").replace(/@BIN_DIR@/g, binDir);
    fs.writeFileSync(dst, text);
  }
}

// Build a hermetic copy of the fixture so we can flip literals without
// touching the committed fixtures; mint the vendor + one consumer, stage the
// .proof. Mirrors prove-e2e.test.js's python `stage()`.
function stage(work, twin, binDir, componentPath) {
  const src = EXAMPLE_DIR;
  const vendorDir = path.join(work, "vendor");
  const consumerDir = path.join(work, `consumer-${twin}`);
  copyDir(path.join(src, "vendor"), vendorDir);
  copyDir(path.join(src, `consumer-${twin}`), consumerDir);
  templateManifests(vendorDir, binDir);
  templateManifests(consumerDir, binDir);
  fs.mkdirSync(path.join(consumerDir, ".sugar", "imports"), { recursive: true });

  const env = { SUGAR_COMPONENT_PATH: componentPath };
  mint(vendorDir, env);
  const vproof = firstProof(vendorDir);
  assert(vproof, "vendor produced no .proof");
  fs.copyFileSync(vproof, path.join(consumerDir, ".sugar", "imports", path.basename(vproof)));
  // Mint the consumer AFTER its vendor import is staged, so the consumer's own
  // assertion contract exists alongside the vendor's in the pool a
  // directory-prove will read.
  mint(consumerDir, env);
  return { consumerDir, vendorDir, env };
}

function proveConsumer(consumerDir, env) {
  return proveProject({ binaryPath: BIN, projectDir: consumerDir, env });
}

// Re-stamp the assertion's expected literal, then re-mint so the proof
// reflects it -- the editor's "on save" step.
function setLiteral(consumerDir, literal, env) {
  const f = path.join(consumerDir, "tests", "consumer_test.rs");
  const src = fs.readFileSync(f, "utf8");
  const next = src.replace(/assert_eq!\(s, "[^"]*"\);/, `assert_eq!(s, "${literal}");`);
  fs.writeFileSync(f, next);
  mint(consumerDir, env);
}

function consistencyDiag(res, consumerFile) {
  const base = path.basename(consumerFile);
  return res.diagnostics.find(
    (d) => d.property.includes("unwrap#euf") && d.property.includes("b:true") && d.file.endsWith(base)
  );
}

(async function main() {
  const work = fs.mkdtempSync(path.join(os.tmpdir(), "sugar-rust-prove-e2e-"));
  console.log(`work dir: ${work}`);
  const binDir = path.dirname(BIN);
  const componentPath = writeComponentRegistry(work, binDir);

  // ---- consumer-bad: the lie is UNSAT -> a red diagnostic at the assert line ----
  {
    const { consumerDir, env } = stage(work, "bad", binDir, componentPath);
    const file = path.join(consumerDir, "tests", "consumer_test.rs");
    const expLine = assertLine(file);
    const res = await proveConsumer(consumerDir, env);
    console.log(`  [bad] prove latency: ${res.elapsedMs}ms  exit=${res.exitCode}  rows=${res.rows.length}`);
    const d = consistencyDiag(res, file);
    check("bad: a red diagnostic is emitted", !!d, JSON.stringify(res.diagnostics));
    if (d) {
      console.log(`  [bad] diagnostic: file=${d.file} line=${d.line} column=${d.column} status=${d.status}`);
      console.log(`  [bad] reason: ${d.reason}`);
      check("bad: status is unsatisfied", d.status === "unsatisfied", d.status);
      check("bad: anchored at the assert line", d.line === expLine, `got ${d.line}, expected ${expLine}`);
      check("bad: file is the CONSUMER's own tests/consumer_test.rs", d.file.endsWith("tests/consumer_test.rs"), d.file);
      check("bad: reason names the contradiction", /contradictory/i.test(d.reason), d.reason);
      const detail = formatDetail(d);
      console.log("  [bad] squiggle message:\n" + detail.replace(/^/gm, "    "));
      check(
        "bad: VENDOR FACT renders the vendor's sworn row (true -> \"true\")",
        typeof d.vendorFactFol === "string" &&
          d.vendorFactFol.includes("serde_json::to_string") &&
          d.vendorFactFol.includes('"true"'),
        d.vendorFactFol
      );
      check(
        "bad: YOUR FACT renders the conjoined (contradictory) client claim",
        typeof d.clientFactFol === "string" &&
          d.clientFactFol.includes('"false"') &&
          d.clientFactFol.includes('"true"'),
        d.clientFactFol
      );
      check(
        "bad: the squiggle shows the labeled lines + the conjoined verdict",
        detail.includes("Vendor fact:") &&
          detail.includes('"true"') &&
          detail.includes("Your fact:") &&
          detail.includes("Conjoined:") &&
          detail.includes("∧") &&
          detail.includes("UNSAT"),
        detail
      );
    }
    check("bad: red gate exit code", res.exitCode !== 0, `exit ${res.exitCode}`);

    // ---- flip the literal to the CORRECT value -> the diagnostic clears ----
    setLiteral(consumerDir, "true", env);
    const res2 = await proveConsumer(consumerDir, env);
    console.log(`  [bad->fixed] prove latency: ${res2.elapsedMs}ms  exit=${res2.exitCode}`);
    check(
      "flip bad->correct: diagnostic clears",
      !consistencyDiag(res2, file),
      JSON.stringify(res2.diagnostics)
    );
  }

  // ---- consumer-good: correct value -> no diagnostic ----
  {
    const { consumerDir, env } = stage(work, "good", binDir, componentPath);
    const file = path.join(consumerDir, "tests", "consumer_test.rs");
    const expLine = assertLine(file);
    const res = await proveConsumer(consumerDir, env);
    console.log(`  [good] prove latency: ${res.elapsedMs}ms  exit=${res.exitCode}  rows=${res.rows.length}`);
    check("good: no red diagnostic", !consistencyDiag(res, file), JSON.stringify(res.diagnostics));

    // ---- flip the literal to a LIE -> a red diagnostic appears at the assert line ----
    setLiteral(consumerDir, "false", env);
    const res2 = await proveConsumer(consumerDir, env);
    console.log(`  [good->lie] prove latency: ${res2.elapsedMs}ms  exit=${res2.exitCode}`);
    const d = consistencyDiag(res2, file);
    check("flip correct->lie: a red diagnostic appears", !!d, JSON.stringify(res2.diagnostics));
    if (d) {
      console.log(`  [good->lie] diagnostic: file=${d.file} line=${d.line} column=${d.column} status=${d.status}`);
      check("flip: anchored at the assert line", d.line === expLine, `got ${d.line}, expected ${expLine}`);
    }
  }

  try {
    fs.rmSync(work, { recursive: true, force: true });
  } catch {
    /* best effort */
  }

  console.log("");
  if (failures > 0) {
    console.log(`==== rust-prove-e2e: FAIL (${failures}) ====`);
    process.exit(1);
  }
  console.log("==== rust-prove-e2e: PASS ====");
})().catch((e) => {
  console.error(e);
  process.exit(1);
});
