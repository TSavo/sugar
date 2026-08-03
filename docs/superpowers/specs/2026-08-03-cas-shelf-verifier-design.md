# CAS Shelf Verification Design

## Problem

The filesystem shelf addresses binary cells by the BLAKE3-512 digest of the
decompressed payload, but reuses the strict local-build manifest verifier when
reading those cells. That verifier includes the complete `cargo -Vv` and
`rustc -Vv` strings. A cell built on Ubuntu 24.4 and consumed in the managed
Debian 12 image therefore reports corruption even when the Cargo commit,
source stamp, payload address, and payload SHA-256 all match.

Recovery then attempts to evict the cell through a deliberately read-only
Docker bind and reports the surviving path as root-owned/unevictable. The host
cell is actually peer-readable and peer-evictable. Both terminals name the
wrong cause.

## Why content addressing did not finish the migration

#6982 moved binary bytes from a source-stamp path to `cas/h(payload)`, but kept
one build-environment-specific artifact manifest inside that payload cell. The
address became content-derived while verification still treated diagnostic
build-environment strings as membership. Identical payloads produced under two
host OS strings still collide in one CAS cell and one manifest. The migration
split the address but not the two meanings carried by the manifest.

## Design

Keep `verify_artifact_manifest` strict for local targets, build outputs, and
the mutable local cache. Add one filesystem-CAS verifier for shelf reads. It
authenticates:

- BLAKE3-512 of decompressed bytes equals the cell content key;
- SHA-256 equals the manifest;
- schema, binary, package, source stamp, build identity, platform, target
  triple, profile, features, built, and executed fields match;
- diagnostic `rustc` and `cargo` strings are present but do not define CAS
  membership.

Manifest parse failure and stable-field mismatch receive named terminals.
Payload-address mismatch remains the existing CAS crime. No failure is called
byte corruption unless payload bytes fail a byte-integrity check.

The battleaxe transport also declares when the shelf bind is read-only.
Recovery checks that declaration before attempting eviction and reports a
read-only recovery refusal. A writable shelf that genuinely cannot remove a
cell retains the peer-ownership/mode refusal.

## Discrimination

An end-to-end temporary shelf contract proves four arms:

1. Same source/platform/target/profile and identical payload, with only the
   `cargo -Vv` OS line changed, resolves from the CAS shelf without rebuilding.
2. A planted wrong source stamp refuses by the manifest-identity field name.
3. A planted payload under the wrong CAS address refuses by the address/payload
   crime.
4. A planted manifest mismatch under a declared read-only shelf refuses as
   read-only recovery; a writable private cell remains the ownership/mode arm.

The test also proves that the strict local verifier still rejects Cargo
identity drift. No existing shelf cell is deleted, chmodded, or rewritten.

