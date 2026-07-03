// Minimal echo RPC server. Demonstrates substrate-honest lift→lower:
// rust source uses ONLY constructs whose ProofIR-canonical form the
// substrate's java lower vocabulary can emit today (concept:while,
// concept:if, concept:assign, concept:call, concept:return + the 9
// boundary primitives). The deleted proc-macro metadata that used to sit in
// this example is now represented by native lift configuration and contract
// annotations elsewhere; this file keeps only the Rust body shape.

// ---- Boundary primitives (filled by target shims) ------------------

pub fn stdin_read_line() -> Option<String> {
    unimplemented!("materialize-fillable boundary")
}

pub fn stdout_write_line(_line: &str) {
    unimplemented!("materialize-fillable boundary")
}

// ---- Realizations (lift to ProofIR, lower to java) ----------------

/// `concept:rpc-minimal-echo-line` — read one line from stdin, write it
/// back to stdout. The boundary contract for stdin_read_line uses
/// Option<String> in rust but the concept-hub sort is concept:String
/// (with null-=-None as the cross-language loss morphism). At java
/// emission the unwrap is implicit (you already have the String).
pub fn echo_one_line() {
    let line = stdin_read_line_required();
    stdout_write_line(&line);
}

/// Helper boundary: read a line, panicking on EOF. Java realization
/// is the same as stdin_read_line (returns String directly).
pub fn stdin_read_line_required() -> String {
    unimplemented!("materialize-fillable boundary")
}

/// `concept:rpc-minimal-three-line-echo` — read three lines, echo each.
/// No mutability, no loops, no destructuring. Just sequential calls.
pub fn three_line_echo() {
    let line1 = stdin_read_line_required();
    stdout_write_line(&line1);
    let line2 = stdin_read_line_required();
    stdout_write_line(&line2);
    let line3 = stdin_read_line_required();
    stdout_write_line(&line3);
}
