/*
 * SPDX-License-Identifier: MIT OR Apache-2.0
 *
 * sugar-compose.h
 *
 * C ABI to libsugar's canonical compose primitive, per the
 * Contract Composition Protocol (CCP) §6.2. Spec lives at:
 *   protocol/specs/2026-05-09-contract-composition-protocol.md
 *
 * The C lifter family (sugar-lift-c-kernel-doc,
 * sugar-lift-c-sparse, sugar-lift-c-assertions) and any other
 * native consumer links to libsugar's static or dynamic library
 * and uses this header. Marshaling is JCS-encoded JSON across the
 * boundary; libsugar owns the canonical encoding (CCP Appendix A).
 *
 * Two intentional deviations from the literal §6.2 text, both
 * documented in the implementation (libsugar/src/ffi.rs):
 *
 *   1. Each atom JSON object in atoms_jcs carries an outer
 *      `formalIdx` field alongside the canonical `memento` body.
 *      Shape: `{"memento": <canonical-body>, "formalIdx": <int>}`.
 *      The C signature itself is byte-identical to §6.2.
 *
 *   2. Effects are passed twice: embedded in each memento body and as
 *      the parallel effects_jcs array. The embedded copy is
 *      authoritative; the parallel array MUST equal-by-value or the
 *      call returns an EffectsMismatch error via the result handle.
 *
 * All inputs MUST be JCS-encoded JSON (RFC 8785). Lengths are in
 * bytes, NOT counting any trailing NUL. Strings need not be NUL
 * terminated.
 */

#ifndef SUGAR_COMPOSE_H
#define SUGAR_COMPOSE_H

#include <stddef.h>

#ifdef __cplusplus
extern "C" {
#endif

/*
 * Opaque result handle. Callers obtain one from
 * pk_compose_chain_contracts and MUST release it via
 * pk_composition_result_free exactly once. The handle is
 * non-NULL on both success and error paths; inspect the accessors
 * below to discriminate.
 */
typedef struct pk_composition_result pk_composition_result;

/*
 * Compose a chain of atomic FunctionContractMementos into a single
 * ComposedFunctionContract via the canonical CCP §2 / §9 algebra.
 *
 * Parameters:
 *   atoms_jcs    JCS-encoded JSON array of atom envelopes:
 *                  [{"memento": <canonical body>, "formalIdx": N}, ...]
 *                Atoms are ordered call-graph leaf first.
 *   effects_jcs  JCS-encoded JSON array of effect arrays, parallel to
 *                atoms_jcs. effects_jcs[i] MUST equal atoms_jcs[i].memento.effects.
 *   atoms_len    Length of atoms_jcs in bytes.
 *   effects_len  Length of effects_jcs in bytes.
 *
 * Returns: a newly allocated result handle. Never NULL under normal
 * operation. The handle's `error` accessor returns non-NULL iff the
 * call failed; on success the `cid` and `body_jcs` accessors return
 * non-NULL pointers to NUL-terminated UTF-8 strings.
 */
pk_composition_result *pk_compose_chain_contracts(
    const char *atoms_jcs,
    const char *effects_jcs,
    size_t atoms_len,
    size_t effects_len);

/*
 * On success: NUL-terminated "blake3-512:<hex>" composed CID, owned
 * by the result handle.
 * On error:   NULL.
 */
const char *pk_composition_result_cid(const pk_composition_result *r);

/*
 * On success: NUL-terminated JCS-encoded body of the composed
 * contract, owned by the result handle.
 * On error:   NULL.
 */
const char *pk_composition_result_body_jcs(const pk_composition_result *r);

/*
 * On error:   NUL-terminated diagnostic message, owned by the result
 *             handle.
 * On success: NULL.
 */
const char *pk_composition_result_error(const pk_composition_result *r);

/*
 * Release a result handle. Calling with NULL is a no-op. Calling more
 * than once on the same handle is undefined behavior.
 */
void pk_composition_result_free(pk_composition_result *r);

#ifdef __cplusplus
} /* extern "C" */
#endif

#endif /* SUGAR_COMPOSE_H */
