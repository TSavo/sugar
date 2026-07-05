/* SPDX-License-Identifier: MIT OR Apache-2.0 */
/*
 * Ed25519 thin wrapper over OpenSSL EVP_PKEY_ED25519 (libcrypto).
 *
 * Byte-identical to ed25519-dalek (Rust), OpenSSL EVP_PKEY_ED25519 (C++),
 * and node:crypto's ed25519 for the same (seed, message) pairs.
 *
 * Build requirement: -lcrypto (OpenSSL 1.1+ or 3.x).
 * The C kit Makefile sets LDFLAGS = -lcrypto and -I to the OpenSSL
 * headers path.
 *
 * Rationale for OpenSSL over a self-rolled impl: the C++ kit already uses
 * OpenSSL EVP_PKEY_ED25519 (see implementations/cpp/sugar/proof-envelope/
 * sign_ed25519.cpp). Using the same underlying library guarantees byte-level
 * agreement with the C++ kit without vendoring ~1500 LOC of field arithmetic.
 */

#ifndef PK_ED25519_H
#define PK_ED25519_H

#include <stddef.h>
#include <stdint.h>

#ifdef __cplusplus
extern "C" {
#endif

/*
 * Derive the 32-byte public key from a 32-byte seed.
 * pk_out must point to a 32-byte buffer.
 * Returns 0 on success, -1 on OpenSSL failure.
 */
int pk_ed25519_pubkey_from_seed(const uint8_t seed[32], uint8_t pk_out[32]);

/*
 * Sign message (msg, msg_len) with the private key derived from seed.
 * sig_out must point to a 64-byte buffer.
 * Returns 0 on success, -1 on OpenSSL failure.
 */
int pk_ed25519_sign(const uint8_t *msg, size_t msg_len,
                    const uint8_t seed[32],
                    uint8_t sig_out[64]);

/*
 * Verify signature sig (64 bytes) over message (msg, msg_len)
 * with public key pk (32 bytes).
 * Returns 1 if valid, 0 if invalid (including any OpenSSL failure).
 */
int pk_ed25519_verify(const uint8_t *msg, size_t msg_len,
                      const uint8_t sig[64],
                      const uint8_t pk[32]);

#ifdef __cplusplus
}
#endif

#endif /* PK_ED25519_H */
