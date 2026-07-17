// SPDX-License-Identifier: MIT OR Apache-2.0
//
// #3855 instrument: pool single-owner for Kit ↔ enumerate.
//
// Law: Kit holds one LiftPluginKit connection; enumerate_conn clones that
// connection (method override) rather than minting LiftPluginKit::new.
// Dual transport was the residual beyond per-instance ResidentSlot: lift
// owned one resident, enumeration minted a second.
//
// R axis: kit_enumerate_mints_fresh_transport
// Green only at stable zero.
// Replacement: self.connection.clone().with_method("sugar.enumerate");
// Drop of the last connection Arc shuts the child once (no double-shutdown).

use std::fs;
use std::path::PathBuf;

#[test]
fn kit_owns_connection_and_enumerate_reuses_it() {
    let kit_rs = PathBuf::from(env!("CARGO_MANIFEST_DIR")).join("src/kit.rs");
    let text = fs::read_to_string(&kit_rs).unwrap_or_else(|e| {
        panic!("read {}: {e}", kit_rs.display());
    });

    let mut offenders = Vec::new();

    if !text.contains("connection: crate::kit_path::LiftPluginKit")
        && !text.contains("connection: LiftPluginKit")
    {
        offenders.push(
            "Kit struct missing owned `connection: LiftPluginKit` field \
             (single-owner requires the handle to hold the Drop-scoped transport)"
                .to_string(),
        );
    }

    let Some(start) = text.find("fn enumerate_conn") else {
        panic!(
            "kit.rs must define enumerate_conn; without it the tree has no \
             single-owner reuse door"
        );
    };
    // Bound the body: next top-level method on Kit after enumerate_conn.
    let rest = &text[start..];
    let end = rest
        .find("\n    /// SEAM 4")
        .or_else(|| rest.find("\n    pub fn testimony"))
        .or_else(|| rest.find("\n    #[cfg(test)]"))
        .unwrap_or(rest.len().min(1200));
    let enumerate_fn = &rest[..end];

    if enumerate_fn.contains("LiftPluginKit::new") {
        offenders.push(format!(
            "enumerate_conn mints a fresh LiftPluginKit::new (dual resident). \
             Fix: self.connection.clone().with_method(\"sugar.enumerate\"). \
             Shape:\n{enumerate_fn}"
        ));
    }
    if !enumerate_fn.contains("self.connection.clone()") {
        offenders.push(
            "enumerate_conn does not clone self.connection \
             (must reuse Kit-owned transport)"
                .to_string(),
        );
    }
    if !enumerate_fn.contains("sugar.enumerate") {
        offenders.push(
            "enumerate_conn must set method sugar.enumerate on the shared connection".to_string(),
        );
    }

    assert!(
        offenders.is_empty(),
        "Kit pool single-owner residual (#3855). Axis: \
         kit_enumerate_mints_fresh_transport. Offenders (R = {}):\n  {}\n\
         Replacement: Kit.connection is the only resident owner; enumerate \
         clones it; Drop of last Arc shuts once.",
        offenders.len(),
        offenders.join("\n  ")
    );
}

#[test]
fn rendezvous_registers_from_owned_connection_not_second_new() {
    let kit_rs = PathBuf::from(env!("CARGO_MANIFEST_DIR")).join("src/kit.rs");
    let text = fs::read_to_string(&kit_rs).unwrap_or_else(|e| {
        panic!("read {}: {e}", kit_rs.display());
    });

    // Rendezvous must build one LiftPluginKit, clone into LiftKit, keep owner.
    assert!(
        text.contains("LiftKit::from_transport"),
        "Kit::rendezvous must register via LiftKit::from_transport(connection.clone()) \
         so the path-algebra LiftKit shares the Kit-owned ResidentSlot. Minting a \
         separate LiftKit::new would reintroduce dual residents."
    );
}
