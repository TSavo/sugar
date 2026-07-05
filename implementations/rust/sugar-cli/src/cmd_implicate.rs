// SPDX-License-Identifier: MIT OR Apache-2.0
//
// `sugar implicate <ANT-CID> <CONS-CID>`.
//
// Honest stub for v0. Minting an implication requires:
//   1. A CID -> memento resolver (not yet shipped; "TBD" per the
//      surface spec).
//   2. SMT-LIB emission for an arbitrary pair of formulas (the
//      verifier's emitter is wired for obligations from a callsite,
//      not free-standing pairs).
//   3. A signing key for the prover (out-of-scope for v0 CLI).
//
// Rather than fake a success, we surface the gap honestly.

use owo_colors::OwoColorize;

use crate::ImplicateArgs;

pub fn run(args: ImplicateArgs) -> u8 {
    eprintln!(
        "{}: `sugar implicate` is not yet implemented in v0. Planned for v1.2.0.",
        "notice".yellow().bold()
    );
    eprintln!("  antecedent : {}", args.antecedent);
    eprintln!("  consequent : {}", args.consequent);
    eprintln!(
        "  Implication minting needs a global CID-resolver + signing key wiring; \n  the verifier currently mints implications inline at handshake time. \n  See protocol/specs/2026-04-30-handshake-algorithm.md."
    );
    crate::EXIT_OK
}

#[cfg(test)]
mod tests {
    use super::*;
    use crate::OutputFlags;

    #[test]
    fn implicate_returns_ok_with_stub_message() {
        let args = ImplicateArgs {
            antecedent: "blake3-512:aa".into(),
            consequent: "blake3-512:bb".into(),
            z3: "z3".into(),
            out: OutputFlags::default(),
        };
        assert_eq!(run(args), crate::EXIT_OK);
    }
}
