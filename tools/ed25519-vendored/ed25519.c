/* SPDX-License-Identifier: MIT OR Apache-2.0 */
/*
 * Ed25519 thin wrapper: OpenSSL EVP_PKEY_ED25519 backend.
 *
 * The C kit uses OpenSSL libcrypto for the same reason the C++ kit does:
 * byte-identical signatures without vendoring ~1500 LOC of field arithmetic.
 * Both kits link -lcrypto; the C++ kit's sign_ed25519.cpp is the reference.
 *
 * Compile: cc -std=c11 -I<openssl-include> ed25519.c -lcrypto
 */

#include "ed25519.h"

#include <openssl/evp.h>
#include <string.h>

int pk_ed25519_pubkey_from_seed(const uint8_t seed[32], uint8_t pk_out[32]) {
    EVP_PKEY *pkey = EVP_PKEY_new_raw_private_key(EVP_PKEY_ED25519, NULL, seed, 32);
    if (!pkey) return -1;
    size_t pklen = 32;
    int rc = EVP_PKEY_get_raw_public_key(pkey, pk_out, &pklen);
    EVP_PKEY_free(pkey);
    return (rc == 1 && pklen == 32) ? 0 : -1;
}

int pk_ed25519_sign(const uint8_t *msg, size_t msg_len,
                    const uint8_t seed[32],
                    uint8_t sig_out[64]) {
    EVP_PKEY *pkey = EVP_PKEY_new_raw_private_key(EVP_PKEY_ED25519, NULL, seed, 32);
    if (!pkey) return -1;
    EVP_MD_CTX *ctx = EVP_MD_CTX_new();
    if (!ctx) { EVP_PKEY_free(pkey); return -1; }
    int ok = 0;
    if (EVP_DigestSignInit(ctx, NULL, NULL, NULL, pkey) == 1) {
        size_t siglen = 64;
        if (EVP_DigestSign(ctx, sig_out, &siglen, msg, msg_len) == 1 && siglen == 64)
            ok = 1;
    }
    EVP_MD_CTX_free(ctx);
    EVP_PKEY_free(pkey);
    return ok ? 0 : -1;
}

int pk_ed25519_verify(const uint8_t *msg, size_t msg_len,
                      const uint8_t sig[64],
                      const uint8_t pk[32]) {
    EVP_PKEY *pkey = EVP_PKEY_new_raw_public_key(EVP_PKEY_ED25519, NULL, pk, 32);
    if (!pkey) return 0;
    EVP_MD_CTX *ctx = EVP_MD_CTX_new();
    if (!ctx) { EVP_PKEY_free(pkey); return 0; }
    int ok = 0;
    if (EVP_DigestVerifyInit(ctx, NULL, NULL, NULL, pkey) == 1) {
        ok = (EVP_DigestVerify(ctx, sig, 64, msg, msg_len) == 1) ? 1 : 0;
    }
    EVP_MD_CTX_free(ctx);
    EVP_PKEY_free(pkey);
    return ok;
}
